import numpy as np
from PIL import ImageDraw
from scenes import scene

from app import storage
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


def test_custom_prompt_uses_the_color_shifts(client, conn, repo, upload):
    v1 = upload(repo["id"], scene())
    r = explore_post(client, v1, prompt="something warm, or darker")
    assert r.status_code == 201, r.text
    assert [v["origin_meta"]["direction"] for v in r.json()] == ["something warm", "darker"]
    assert explore_post(client, v1, prompt="paint me a dragon").status_code == 400


def test_lines_and_shapes_stay_where_they_were_drawn(client, conn, repo, upload):
    img = scene()
    ImageDraw.Draw(img).line((10, 10, 400, 300), fill=(0, 0, 0), width=2)
    v1 = upload(repo["id"], img)
    base = lab_of(conn, v1)
    for v in explore_post(client, v1).json():
        out = lab_of(conn, v)
        # Same edges: the lightness gradient is only scaled, never moved.
        gb, go = np.abs(np.diff(base[..., 0], axis=1)) > 5, np.abs(np.diff(out[..., 0], axis=1)) > 3
        assert (gb & ~go).sum() < 0.02 * gb.sum()


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
