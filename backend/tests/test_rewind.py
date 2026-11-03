from scenes import SKY_DUSK, scene


def branches(client, repo):
    return {b["name"]: b for b in client.get(f"/api/repos/{repo['id']}").json()["branches"]}


def test_rewind_moves_later_versions_to_a_kept_branch(client, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))
    main = branches(client, repo)["main"]

    r = client.post(f"/api/branches/{main['id']}/rewind", json={"to_commit": v1["id"]})
    assert r.status_code == 200
    assert r.json()["branch"]["head_commit_id"] == v1["id"]
    assert r.json()["kept"] == {**r.json()["kept"], "name": "main-before-v1", "head_commit_id": v2["id"]}
    assert client.get(f"/api/commits/{v2['id']}").json()["branch"] == "main-before-v1"  # moved, not deleted
    assert upload(repo["id"], scene())["parent_id"] == v1["id"]


def test_rewind_refuses(client, repo, upload):
    v1 = upload(repo["id"], scene())
    client.post(f"/api/repos/{repo['id']}/branches", json={"name": "alt", "from_commit": v1["id"]})
    other = upload(repo["id"], scene(sky=SKY_DUSK), branch="alt")
    main = branches(client, repo)["main"]

    def rewind(to):
        return client.post(f"/api/branches/{main['id']}/rewind", json={"to_commit": to})

    assert "already the latest" in rewind(v1["id"]).json()["detail"]
    assert "isn't in main's history" in rewind(other["id"]).json()["detail"]
    assert rewind(999).status_code == 409
    assert client.post("/api/branches/999/rewind", json={"to_commit": v1["id"]}).status_code == 404
    assert set(branches(client, repo)) == {"main", "alt"}  # refusals leave no kept branch behind
