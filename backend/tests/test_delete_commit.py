from scenes import SKY_DUSK, scene

from app import storage


def branches(client, repo):
    return {b["name"]: b for b in client.get(f"/api/repos/{repo['id']}").json()["branches"]}


def test_delete_the_latest_version(client, conn, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))
    client.post(f"/api/commits/{v2['id']}/notes", data={"text": "dusk for the client"})
    path = storage.abs_path(storage.get_blob(conn, v2["blob_sha"])["path"])

    assert client.delete(f"/api/commits/{v2['id']}").status_code == 204
    assert client.get(f"/api/commits/{v2['id']}").status_code == 404
    assert branches(client, repo)["main"]["head_commit_id"] == v1["id"]
    assert [c["seq"] for c in client.get(f"/api/repos/{repo['id']}/commits").json()] == [1]
    assert not path.exists()  # its image is gone too
    assert client.get(f"/api/repos/{repo['id']}/search?q=dusk").json()["results"] == []
    # History goes on from v1.
    assert upload(repo["id"], scene(sky=SKY_DUSK))["parent_id"] == v1["id"]


def test_shared_pixels_stay(client, conn, repo, upload):
    upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))
    client.post(f"/api/repos/{repo['id']}/branches", json={"name": "alt", "from_commit": v2["id"]})
    v3 = upload(repo["id"], scene(sky=SKY_DUSK), branch="alt")  # same pixels as v2
    assert client.delete(f"/api/commits/{v3['id']}").status_code == 204
    assert storage.abs_path(storage.get_blob(conn, v2["blob_sha"])["path"]).exists()


def test_delete_a_version_in_the_middle(client, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))
    v3 = upload(repo["id"], scene())
    client.post(f"/api/repos/{repo['id']}/branches", json={"name": "alt", "from_commit": v2["id"]})
    a1 = upload(repo["id"], scene(sky=SKY_DUSK), branch="alt")

    assert client.delete(f"/api/commits/{v2['id']}").status_code == 204
    graph = {c["seq"]: c for c in client.get(f"/api/repos/{repo['id']}/commits").json()}
    assert sorted(graph) == [1, 3, 4]
    assert graph[3]["parent_id"] == v1["id"] and graph[4]["parent_id"] == v1["id"]
    assert branches(client, repo)["main"]["head_commit_id"] == v3["id"]
    assert branches(client, repo)["alt"]["head_commit_id"] == a1["id"]
    # The diff is worked out again against the new parent.
    assert client.get(f"/api/diff?from={v1['id']}&to={v3['id']}").status_code == 200


def test_delete_a_version_a_branch_starts_from(client, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))
    client.post(f"/api/repos/{repo['id']}/branches", json={"name": "alt", "from_commit": v2["id"]})
    assert client.delete(f"/api/commits/{v2['id']}").status_code == 204
    assert branches(client, repo)["main"]["head_commit_id"] == v1["id"]
    assert branches(client, repo)["alt"]["head_commit_id"] == v1["id"]


def test_delete_the_first_version_and_a_merged_one(client, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))
    assert client.delete(f"/api/commits/{v1['id']}").status_code == 204
    assert client.get(f"/api/commits/{v2['id']}").json()["parent_id"] is None
    assert client.delete(f"/api/commits/{v2['id']}").status_code == 204
    assert branches(client, repo)["main"]["head_commit_id"] is None
    assert client.delete("/api/commits/999").status_code == 404


def test_merge_of_a_deleted_version_merges_the_one_before(conn, repo, upload):
    from app.services import commits

    v1 = upload(repo["id"], scene())
    conn.execute("INSERT INTO branches (repo_id, name, head_commit_id, created_at) VALUES (?, 'alt', ?, '')", (repo["id"], v1["id"]))
    alt = conn.execute("SELECT id FROM branches WHERE name = 'alt'").fetchone()[0]
    a1 = upload(repo["id"], scene(sky=SKY_DUSK), branch="alt")
    a2 = upload(repo["id"], scene(), branch="alt")
    m = upload(repo["id"], scene(sky=SKY_DUSK))
    conn.execute("UPDATE commits SET merge_parent_id = ? WHERE id = ?", (a2["id"], m["id"]))
    commits.delete(conn, a2["id"])
    assert conn.execute("SELECT merge_parent_id FROM commits WHERE id = ?", (m["id"],)).fetchone()[0] == a1["id"]
    commits.delete(conn, a1["id"])  # what's left is v1, already the merge's parent
    assert conn.execute("SELECT merge_parent_id FROM commits WHERE id = ?", (m["id"],)).fetchone()[0] is None
    assert conn.execute("SELECT head_commit_id FROM branches WHERE id = ?", (alt,)).fetchone()[0] == v1["id"]
