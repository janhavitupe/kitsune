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


def test_cannot_delete_what_history_is_built_on(client, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))
    r = client.delete(f"/api/commits/{v1['id']}")
    assert r.status_code == 409 and "later versions" in r.json()["detail"]
    client.post(f"/api/repos/{repo['id']}/branches", json={"name": "alt", "from_commit": v2["id"]})
    r = client.delete(f"/api/commits/{v2['id']}")
    assert r.status_code == 409 and "alt" in r.json()["detail"]
    assert client.delete("/api/commits/999").status_code == 404
