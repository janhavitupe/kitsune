from app.db import now
from app.services.graph import ancestors, common_ancestor


def test_linear_history(conn, repo, upload):
    v1, v2, v3 = (upload(repo["id"], (i * 40, 0, 0)) for i in range(1, 4))
    assert ancestors(conn, v3["id"]) == {v1["id"], v2["id"], v3["id"]}
    assert common_ancestor(conn, v2["id"], v3["id"]) == v2["id"]


def test_branch_common_ancestor(client, conn, repo, upload):
    v1 = upload(repo["id"], (10, 0, 0))
    v2 = upload(repo["id"], (20, 0, 0))
    client.post(f"/api/repos/{repo['id']}/branches", json={"name": "dusk", "from_commit": v1["id"]})
    d1 = upload(repo["id"], (0, 10, 0), branch="dusk")
    v3 = upload(repo["id"], (30, 0, 0))
    assert common_ancestor(conn, d1["id"], v3["id"]) == v1["id"]
    assert v2["id"] not in ancestors(conn, d1["id"])


def test_common_ancestor_after_merge(client, conn, repo, upload):
    v1 = upload(repo["id"], (10, 0, 0))
    client.post(f"/api/repos/{repo['id']}/branches", json={"name": "dusk"})
    d1 = upload(repo["id"], (0, 10, 0), branch="dusk")
    v2 = upload(repo["id"], (20, 0, 0))
    # No merge endpoint until M3, so write the merge commit directly: dusk merged into main.
    merge_id = conn.execute(
        "INSERT INTO commits (repo_id, seq, branch_id, parent_id, merge_parent_id, blob_sha, origin, created_at)"
        " VALUES (?, 99, ?, ?, ?, ?, 'merge', ?)",
        (repo["id"], v2["branch_id"], v2["id"], d1["id"], v2["blob_sha"], now()),
    ).lastrowid
    d2 = upload(repo["id"], (0, 20, 0), branch="dusk")

    assert d1["id"] in ancestors(conn, merge_id)
    # After the merge, dusk's latest shared point with main is d1, not v1.
    assert common_ancestor(conn, d2["id"], merge_id) == d1["id"]
    assert common_ancestor(conn, v1["id"], 12345) is None
