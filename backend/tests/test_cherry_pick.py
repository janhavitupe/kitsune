import io

import numpy as np
from PIL import Image, ImageDraw
from scenes import FIGURE_BOX, SKY_DAY, SKY_DUSK, scene, sky_mask

from app import storage
from app.services import cherry_pick, compose
from app.services.segmentation import RawMask, save_regions

TOP_LEFT = ((20, 20, 90, 70), (250, 250, 250))
BOTTOM_RIGHT = ((420, 300, 490, 360), (240, 220, 40))


def pixels(conn, commit):
    return np.asarray(storage.load_rgb(conn, commit["blob_sha"]))


def two_patches():
    """v1's scene plus a white patch top-left and a yellow patch bottom-right."""
    img = scene(extra=TOP_LEFT)
    ImageDraw.Draw(img).rectangle(BOTTOM_RIGHT[0], fill=BOTTOM_RIGHT[1])
    return img


def pick(client, target, source, label):
    return client.post(f"/api/commits/{target['id']}/cherry-pick", json={"source_commit": source["id"], "label": label})


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
    assert v3["origin_meta"] == {"source_commit": v1["id"], "source_seq": 1, "label": "top-left area", "drawn": False, "selected": False}

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


LANTERN = ((330, 60, 350, 90), (255, 225, 150))


def test_a_later_drawing_is_never_pasted_over(client, conn, repo, upload):
    # v3 adds a lantern in the dusk sky. Bringing v1's day sky back must keep the lantern as drawn.
    v1 = upload(repo["id"], scene())
    upload(repo["id"], scene(sky=SKY_DUSK))
    v3 = upload(repo["id"], scene(sky=SKY_DUSK, extra=LANTERN))
    r = pick(client, v3, v1, "top area")
    assert r.status_code == 201, r.text
    out, old, new = pixels(conn, r.json()), pixels(conn, v1), pixels(conn, v3)
    assert np.array_equal(out[75, 340], new[75, 340])  # the lantern
    assert np.array_equal(out[60, 60], old[60, 60])  # the day sky


def test_bring_back_something_drawn_in_that_version(client, conn, repo, upload):
    # The lantern was drawn in v2 and painted over in v3; "drawn" copies exactly what v2 added.
    upload(repo["id"], scene(sky=SKY_DUSK))
    v2 = upload(repo["id"], scene(sky=SKY_DUSK, extra=LANTERN))
    v3 = upload(repo["id"], scene(sky=SKY_DAY))
    (label,) = cherry_pick.drawn_labels(conn, v2["id"])
    r = client.post(f"/api/commits/{v3['id']}/cherry-pick", json={"source_commit": v2["id"], "label": label, "drawn": True})
    assert r.status_code == 201, r.text
    assert r.json()["origin_meta"]["drawn"] is True
    out, src, new = pixels(conn, r.json()), pixels(conn, v2), pixels(conn, v3)
    assert np.array_equal(out[75, 340], src[75, 340])  # the lantern is back
    assert np.array_equal(out[60, 60], new[60, 60])  # the rest of the sky is v3's


AROUND_LANTERN = [[0.6, 0.1], [0.75, 0.1], [0.75, 0.3], [0.6, 0.3]]  # 307..384 x 38..115 on the 512x384 scene


def select(client, target, source, outline, **body):
    return client.post(
        f"/api/commits/{target['id']}/cherry-pick", json={"source_commit": source["id"], "outline": outline, **body},
    )


def test_a_hand_drawn_selection_copies_exactly_what_is_inside(client, conn, repo, upload):
    v1 = upload(repo["id"], scene(sky=SKY_DUSK, extra=LANTERN))
    v2 = upload(repo["id"], scene())
    r = select(client, v2, v1, AROUND_LANTERN, name="lantern")
    assert r.status_code == 201, r.text
    assert r.json()["message"] == "Brought back the lantern from v1" and r.json()["origin_meta"]["selected"] is True
    out, src, new = pixels(conn, r.json()), pixels(conn, v1), pixels(conn, v2)
    assert np.array_equal(out[75, 340], src[75, 340])  # inside the line: v1, sky included
    # Past the soft edge around the line, every pixel is exactly v2's.
    box = np.zeros(out.shape[:2], bool)
    box[38:116, 307:385] = True
    far = compose.alpha(box, compose.feather_radius(out.shape) * 2) == 0
    assert np.array_equal(out[far], new[far])


def test_selection_is_not_second_guessed(client, conn, repo, upload):
    # Later drawings are only protected for automatic regions. What's inside the line is what was asked for.
    v1 = upload(repo["id"], scene(sky=SKY_DUSK))
    v2 = upload(repo["id"], scene(sky=SKY_DUSK, extra=LANTERN))
    r = select(client, v2, v1, AROUND_LANTERN)
    assert r.status_code == 201 and r.json()["message"] == "Brought back the selected area from v1"
    assert np.array_equal(pixels(conn, r.json())[75, 340], pixels(conn, v1)[75, 340])


def test_bad_selections(client, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))
    assert select(client, v2, v1, [[0.1, 0.1], [0.2, 0.2]]).status_code == 400  # not a shape
    assert select(client, v2, v1, [[0.5, 0.5], [0.5, 0.5], [0.5, 0.5]]).status_code == 400  # a dot
    assert select(client, v2, v1, [[0, 0]] * 3000).status_code == 400
    assert select(client, v2, v1, AROUND_LANTERN, name="x" * 200).status_code == 422
    assert select(client, v1, v2, AROUND_LANTERN).status_code == 409  # v1 isn't the head


def test_only_the_artists_own_pixels(client, conn, repo, upload):
    # Every output pixel is the target's, the source's, or a mix of the two at the soft edge.
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK, figure=(40, 70, 140), extra=TOP_LEFT))
    out = pixels(conn, pick(client, v2, v1, "top area").json()).astype(int)
    a, b = pixels(conn, v1).astype(int), pixels(conn, v2).astype(int)
    assert (out >= np.minimum(a, b) - 1).all() and (out <= np.maximum(a, b) + 1).all()


def test_errors(client, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], two_patches())
    assert pick(client, v2, v1, "sky").status_code == 404  # no such changed region
    assert pick(client, v2, v2, "top-left area").status_code == 400
    assert pick(client, v1, v2, "top-left area").status_code == 409  # v1 isn't the head
    assert client.post("/api/commits/999/cherry-pick", json={"source_commit": 1, "label": "x"}).status_code == 404


def test_preview_saves_nothing(client, conn, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], two_patches())
    r = client.get(f"/api/commits/{v2['id']}/cherry-pick/preview?source={v1['id']}&label=top-left%20area")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(r.content)).size == (512, 384)
    assert len(client.get(f"/api/repos/{repo['id']}/commits").json()) == 2
