import numpy as np
from PIL import ImageDraw
from scenes import scene

from app import storage

TOP_LEFT = (20, 20, 90, 70)
BOTTOM_RIGHT = (420, 300, 490, 360)
WHITE, YELLOW, PINK = (250, 250, 250), (240, 220, 40), (230, 90, 160)


def painted(*patches):
    img = scene()
    d = ImageDraw.Draw(img)
    for box, color in patches:
        d.rectangle(box, fill=color)
    return img


def pixels(conn, commit):
    return np.asarray(storage.load_rgb(conn, commit["blob_sha"]))


def center(box):
    return (box[1] + box[3]) // 2, (box[0] + box[2]) // 2


def branch_off(client, repo, name, commit):
    r = client.post(f"/api/repos/{repo['id']}/branches", json={"name": name, "from_commit": commit["id"]})
    assert r.status_code == 201, r.text


def plan(client, repo, source, target="main"):
    return client.post(f"/api/repos/{repo['id']}/merges", json={"source": source, "target": target})


def resolve(client, merge_id, choices=None):
    return client.post(f"/api/merges/{merge_id}/resolve", json={"choices": choices or {}})


def test_changes_on_different_sides_merge_automatically(client, conn, repo, upload):
    v1 = upload(repo["id"], scene())
    branch_off(client, repo, "patch", v1)
    mine = upload(repo["id"], painted((TOP_LEFT, WHITE)))  # main: top-left
    theirs = upload(repo["id"], painted((BOTTOM_RIGHT, YELLOW)), branch="patch")  # branch: bottom-right

    p = plan(client, repo, "patch").json()
    assert p["status"] == "open" and p["base"] == v1["id"] and not p["fast_forward"]
    assert [a["label"] for a in p["auto"]] == ["bottom-right area"] and p["conflicts"] == []

    r = resolve(client, p["id"])
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["parent_id"] == mine["id"] and m["merge_parent_id"] == theirs["id"] and m["origin"] == "merge"
    assert m["branch"] == "main" and m["message"] == "Merged patch into main: took the bottom-right area"

    out = pixels(conn, m)
    assert tuple(out[center(TOP_LEFT)]) == WHITE  # main's change kept
    assert tuple(out[center(BOTTOM_RIGHT)]) == YELLOW  # branch's change taken
    assert client.get(f"/api/repos/{repo['id']}").json()["branches"][0]["head_commit_id"] == m["id"]
    assert client.get(f"/api/merges/{p['id']}").json()["status"] == "resolved"


def test_conflict_resolved_either_way(client, conn, repo, upload):
    v1 = upload(repo["id"], scene())
    branch_off(client, repo, "pink", v1)
    branch_off(client, repo, "pink-2", v1)
    upload(repo["id"], painted((TOP_LEFT, WHITE)))  # main paints the patch white
    upload(repo["id"], painted((TOP_LEFT, PINK), (BOTTOM_RIGHT, YELLOW)), branch="pink")
    upload(repo["id"], painted((TOP_LEFT, PINK), (BOTTOM_RIGHT, YELLOW)), branch="pink-2")

    p = plan(client, repo, "pink").json()
    assert [a["label"] for a in p["auto"]] == ["bottom-right area"]
    assert [(c["index"], c["label"], c["target_labels"]) for c in p["conflicts"]] == [
        (0, "top-left area", ["top-left area"])
    ]

    # Keep main's version of the conflict (the default).
    keep = pixels(conn, resolve(client, p["id"]).json())
    assert tuple(keep[center(TOP_LEFT)]) == WHITE and tuple(keep[center(BOTTOM_RIGHT)]) == YELLOW

    # Then merge the twin branch and take its side.
    p2 = plan(client, repo, "pink-2").json()
    assert p2["conflicts"]
    take = pixels(conn, resolve(client, p2["id"], {"0": "source"}).json())
    assert tuple(take[center(TOP_LEFT)]) == PINK


def test_same_change_on_both_sides_is_not_a_conflict(client, repo, upload):
    v1 = upload(repo["id"], scene())
    branch_off(client, repo, "same", v1)
    upload(repo["id"], painted((TOP_LEFT, WHITE)))
    upload(repo["id"], painted((TOP_LEFT, WHITE), (BOTTOM_RIGHT, YELLOW)), branch="same")
    p = plan(client, repo, "same").json()
    assert p["conflicts"] == [] and [a["label"] for a in p["auto"]] == ["bottom-right area"]


def test_target_unchanged_takes_the_branch_as_is(client, conn, repo, upload):
    v1 = upload(repo["id"], scene())
    branch_off(client, repo, "dusk", v1)
    d1 = upload(repo["id"], painted((BOTTOM_RIGHT, YELLOW)), branch="dusk")
    p = plan(client, repo, "dusk").json()
    assert p["fast_forward"] and [a["label"] for a in p["auto"]] == ["bottom-right area"]
    m = resolve(client, p["id"]).json()
    assert m["blob_sha"] == d1["blob_sha"] and m["parent_id"] == v1["id"] and m["merge_parent_id"] == d1["id"]


def test_nothing_to_merge(client, repo, upload):
    v1 = upload(repo["id"], scene())
    branch_off(client, repo, "idea", v1)
    upload(repo["id"], painted((TOP_LEFT, WHITE)))  # main moves on; idea has nothing new
    r = plan(client, repo, "idea")
    assert r.status_code == 400 and "already has everything" in r.json()["detail"]


def test_stale_merge_is_refused(client, repo, upload):
    v1 = upload(repo["id"], scene())
    branch_off(client, repo, "patch", v1)
    upload(repo["id"], painted((BOTTOM_RIGHT, YELLOW)), branch="patch")
    upload(repo["id"], painted((TOP_LEFT, WHITE)))
    p = plan(client, repo, "patch").json()
    upload(repo["id"], painted((TOP_LEFT, PINK)))  # main moves on after the check
    r = resolve(client, p["id"])
    assert r.status_code == 409
    assert client.get(f"/api/merges/{p['id']}").json()["status"] == "aborted"


def test_errors(client, repo, upload):
    v1 = upload(repo["id"], scene())
    branch_off(client, repo, "patch", v1)
    upload(repo["id"], painted((BOTTOM_RIGHT, YELLOW)), branch="patch")
    assert plan(client, repo, "main", "main").status_code == 400
    assert plan(client, repo, "nope").status_code == 404
    client.post(f"/api/repos/{repo['id']}/branches", json={"name": "empty-repo-branch", "from_commit": v1["id"]})

    p = plan(client, repo, "patch").json()
    assert resolve(client, p["id"], {"5": "source"}).status_code == 400  # no such conflict
    assert resolve(client, p["id"], {"0": "both"}).status_code == 422
    assert client.post(f"/api/merges/{p['id']}/abort").json()["status"] == "aborted"
    assert resolve(client, p["id"]).status_code == 409
    assert client.get("/api/merges/999").status_code == 404
