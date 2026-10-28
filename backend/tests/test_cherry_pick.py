import io

import numpy as np
from PIL import Image, ImageDraw

from app import storage
from app.ai import image as ai_image
from app.services import cherry_pick, compose
from app.services.segmentation import RawMask, save_regions
from scenes import FIGURE_BOX, SKY_DUSK, scene, sky_mask

TOP_LEFT = ((20, 20, 90, 70), (250, 250, 250))
BOTTOM_RIGHT = ((420, 300, 490, 360), (240, 220, 40))


def pixels(conn, commit):
    return np.asarray(storage.load_rgb(conn, commit["blob_sha"]))


def two_patches():
    """v1's scene plus a white patch top-left and a yellow patch bottom-right."""
    img = scene(extra=TOP_LEFT)
    ImageDraw.Draw(img).rectangle(BOTTOM_RIGHT[0], fill=BOTTOM_RIGHT[1])
    return img


def pick(client, target, source, label, blend="fast"):
    return client.post(
        f"/api/commits/{target['id']}/cherry-pick",
        json={"source_commit": source["id"], "label": label, "blend": blend},
    )


def test_brings_back_one_area_and_keeps_the_other(client, conn, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], two_patches())
    labels = [r["label"] for r in client.get(f"/api/diff?from={v1['id']}&to={v2['id']}").json()["regions"]]
    assert set(labels) == {"top-left area", "bottom-right area"}

    r = pick(client, v2, v1, "top-left area")
    assert r.status_code == 201, r.text
    v3 = r.json()
    assert v3["parent_id"] == v2["id"] and v3["origin"] == "cherry_pick"
    assert v3["message"] == "Brought back the top-left area from v1"
    assert v3["origin_meta"] == {"source_commit": v1["id"], "source_seq": 1, "label": "top-left area", "blend": "fast"}

    old, new, out = pixels(conn, v1), pixels(conn, v2), pixels(conn, v3)
    assert np.array_equal(out[45, 55], old[45, 55])  # inside the top-left patch: back to v1
    assert np.array_equal(out[330, 455], new[330, 455])  # bottom-right patch: still v2
    # Outside the picked area and its soft edge, every pixel is exactly v2.
    mask = np.zeros(out.shape[:2], bool)
    mask[20:71, 20:91] = True
    far = compose.alpha(mask, compose.feather_radius(out.shape) * 3) == 0
    assert np.array_equal(out[far], new[far])


def test_soft_edge_does_not_bleed_into_a_neighbouring_change(client, conn, repo, upload):
    # v2 warms the sky AND repaints the touching figure blue. Bringing back only the sky must
    # leave the figure exactly as in v2, right up to its edge.
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK, figure=(40, 70, 140)))
    r = pick(client, v2, v1, "top area")
    assert r.status_code == 201, r.text
    out, old, new = pixels(conn, r.json()), pixels(conn, v1), pixels(conn, v2)
    x0, y0, x1, y1 = FIGURE_BOX
    figure = (slice(y0 + 2, y1 - 1), slice(x0 + 2, x1 - 1))  # inside the figure, but right at its top edge
    assert np.array_equal(out[figure], new[figure])
    assert np.array_equal(out[60, 60], old[60, 60])  # the sky is back


def test_named_region_once_segmented(client, conn, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK, extra=BOTTOM_RIGHT))
    save_regions(conn, v2["blob_sha"], [RawMask("sky", sky_mask(), 0.9)], source="sam-3.1")

    r = pick(client, v2, v1, "sky")
    assert r.status_code == 201, r.text
    out, old, new = pixels(conn, r.json()), pixels(conn, v1), pixels(conn, v2)
    assert np.array_equal(out[60, 60], old[60, 60])  # sky: day again
    assert np.array_equal(out[330, 455], new[330, 455])  # the new yellow patch stays


def test_ai_blend_is_used_but_cannot_touch_outside_the_seam(client, conn, repo, upload, monkeypatch):
    calls = []

    def noisy_model(conn, crop, band):
        calls.append(crop.shape)
        return np.random.default_rng(0).integers(0, 256, crop.shape, dtype=np.uint8)

    monkeypatch.setattr(ai_image, "blend_seam", noisy_model)
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], two_patches())
    ai = pick(client, v2, v1, "top-left area", blend="ai")
    assert ai.status_code == 201, ai.text
    assert ai.json()["origin_meta"]["blend"] == "ai" and calls

    # Against the same pick blended fast, the model's noise only shows up around the picked patch.
    fast_img, _ = cherry_pick.build(conn, v1["id"], v2["id"], "top-left area", blend="fast")
    differs = np.any(fast_img != pixels(conn, ai.json()), axis=2)
    ys, xs = np.nonzero(differs)
    assert differs.any()
    assert ys.max() < 120 and xs.max() < 140  # all within the top-left patch's seam


def test_auto_blend_falls_back_without_a_key(client, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], two_patches())
    r = pick(client, v2, v1, "top-left area", blend="auto")
    assert r.status_code == 201 and r.json()["origin_meta"]["blend"] == "fast"
    assert pick(client, r.json(), v1, "bottom-right area", blend="ai").status_code == 503


def test_errors(client, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], two_patches())
    assert pick(client, v2, v1, "sky").status_code == 404  # no such changed region
    assert pick(client, v2, v2, "top-left area").status_code == 400
    assert pick(client, v1, v2, "top-left area").status_code == 409  # v1 isn't the head
    assert pick(client, v2, v1, "top-left area", blend="magic").status_code == 400
    assert client.post("/api/commits/999/cherry-pick", json={"source_commit": 1, "label": "x"}).status_code == 404


def test_preview_saves_nothing(client, conn, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], two_patches())
    r = client.get(f"/api/commits/{v2['id']}/cherry-pick/preview?source={v1['id']}&label=top-left%20area")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(r.content)).size == (512, 384)
    assert len(client.get(f"/api/repos/{repo['id']}/commits").json()) == 2
