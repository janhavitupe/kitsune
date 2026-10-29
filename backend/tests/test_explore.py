import numpy as np
from PIL import ImageDraw
from scenes import scene

from app import storage
from app.ai import image as ai_image
from app.services import explore
from app.services.pixel_diff import to_lab


def explore_post(client, commit, **body):
    return client.post(f"/api/commits/{commit['id']}/explore", json=body)


def lab_of(conn, commit):
    return to_lab(np.asarray(storage.load_rgb(conn, commit["blob_sha"])))


def test_presets_make_three_branches(client, conn, repo, upload):
    v1 = upload(repo["id"], scene())
    r = explore_post(client, v1)
    assert r.status_code == 201, r.text
    variants = r.json()
    assert [v["branch"] for v in variants] == [
        "explore/warm-golden-hour", "explore/cool-moonlit-night", "explore/muted-overcast",
    ]
    assert all(v["parent_id"] == v1["id"] and v["origin"] == "explore" for v in variants)
    assert all(v["origin_meta"]["method"] == "fast" for v in variants)
    kinds = {b["name"]: b["kind"] for b in client.get(f"/api/repos/{repo['id']}").json()["branches"]}
    assert kinds["explore/warm-golden-hour"] == "explore" and kinds["main"] == "normal"

    base, warm, moon, overcast = (lab_of(conn, c) for c in [v1, *variants])
    assert warm[..., 2].mean() > base[..., 2].mean() + 10  # warmer
    assert moon[..., 0].mean() < base[..., 0].mean() - 5  # darker
    chroma = lambda lab: np.hypot(lab[..., 1], lab[..., 2]).mean()  # noqa: E731
    assert chroma(overcast) < chroma(base) * 0.6  # more muted


def test_exploring_again_gets_new_branch_names(client, repo, upload):
    v1 = upload(repo["id"], scene())
    explore_post(client, v1)
    assert explore_post(client, v1).json()[0]["branch"] == "explore/warm-golden-hour-2"


def test_custom_prompt_and_ai_mode_need_the_models(client, repo, upload):
    v1 = upload(repo["id"], scene())
    assert explore_post(client, v1, prompt="try three palettes").status_code == 503
    assert explore_post(client, v1, mode="ai").status_code == 503
    assert explore_post(client, v1, prompt="x", mode="fast").status_code == 400
    assert explore_post(client, v1, mode="magic").status_code == 400


def test_ai_variants_keep_the_drawing(client, conn, repo, upload, monkeypatch):
    def model(conn, img, sha, direction):
        out = np.clip(img.astype(int) + [60, 20, -40], 0, 255).astype(np.uint8)
        moved = out.copy()
        moved[150:330, 300:370] = moved[150:330, 220:290]  # the model "moved" the figure
        return moved

    monkeypatch.setattr(ai_image, "recolor", model)
    v1 = upload(repo["id"], scene())
    variants = explore_post(client, v1).json()
    assert all(v["origin_meta"]["method"] == "ai" for v in variants)
    base, ai = lab_of(conn, v1), lab_of(conn, variants[0])
    # The figure stays where it was drawn: lightness detail comes from the original.
    assert abs(ai[240, 335, 0] - base[240, 335, 0]) < 8
    assert ai[..., 2].mean() > base[..., 2].mean()  # but the colors are the model's


def test_keep_composition_on_itself_is_close_to_identity():
    img = np.asarray(scene())
    ImageDraw.Draw(out := scene()).line((10, 10, 400, 300), fill=(0, 0, 0), width=2)
    line = np.asarray(out)
    assert np.abs(explore.keep_composition(img, img).astype(int) - img).mean() < 3
    # A thin line the model drew is not carried over.
    assert np.abs(explore.keep_composition(img, line).astype(int) - img).mean() < 3


def test_keep_and_discard_branches(client, repo, upload):
    v1 = upload(repo["id"], scene())
    warm, moon, _ = explore_post(client, v1).json()
    branches = {b["name"]: b for b in client.get(f"/api/repos/{repo['id']}").json()["branches"]}

    kept = client.patch(f"/api/branches/{branches[warm['branch']]['id']}", json={"name": "golden-hour", "kind": "normal"})
    assert kept.status_code == 200 and kept.json()["name"] == "golden-hour" and kept.json()["kind"] == "normal"
    gone = client.patch(f"/api/branches/{branches[moon['branch']]['id']}", json={"kind": "discarded"})
    assert gone.json()["kind"] == "discarded"
    assert client.get(f"/api/commits/{moon['id']}").status_code == 200  # hidden, not deleted

    assert client.patch(f"/api/branches/{branches['main']['id']}", json={"kind": "discarded"}).status_code == 400
    assert client.patch(f"/api/branches/{branches['main']['id']}", json={"name": "golden-hour"}).status_code == 400
    other = branches["explore/muted-overcast"]["id"]
    assert client.patch(f"/api/branches/{other}", json={"name": "golden-hour"}).status_code == 409
    assert client.patch("/api/branches/999", json={"kind": "normal"}).status_code == 404
