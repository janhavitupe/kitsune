from scenes import SKY_DUSK, scene


def branches(client, repo):
    return {b["name"]: b for b in client.get(f"/api/repos/{repo['id']}").json()["branches"]}


def rebase(client, branch, to):
    return client.post(f"/api/branches/{branch['id']}/rebase", json={"to_commit": to})


def test_rebase_back_keeps_later_versions_on_a_new_branch(client, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))

    r = rebase(client, branches(client, repo)["main"], v1["id"])
    assert r.status_code == 200
    assert r.json()["branch"]["head_commit_id"] == v1["id"]
    assert r.json()["kept"] == {**r.json()["kept"], "name": "main-before-v1", "head_commit_id": v2["id"]}
    assert client.get(f"/api/commits/{v2['id']}").json()["branch"] == "main-before-v1"  # moved, not deleted
    assert upload(repo["id"], scene())["parent_id"] == v1["id"]


def test_rebase_forward_leaves_nothing_behind(client, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))
    rebase(client, branches(client, repo)["main"], v1["id"])

    r = rebase(client, branches(client, repo)["main"], v2["id"])  # back to where it was
    assert r.json()["kept"] is None and r.json()["branch"]["head_commit_id"] == v2["id"]
    assert client.get(f"/api/commits/{v2['id']}").json()["branch"] == "main-before-v1"  # stays in its lane


def test_rebase_onto_another_line(client, repo, upload):
    v1 = upload(repo["id"], scene())
    client.post(f"/api/repos/{repo['id']}/branches", json={"name": "alt", "from_commit": v1["id"]})
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))  # main's own work
    other = upload(repo["id"], scene(sky=(200, 60, 60)), branch="alt")

    r = rebase(client, branches(client, repo)["main"], other["id"])
    assert r.json()["branch"]["head_commit_id"] == other["id"]
    assert r.json()["kept"]["head_commit_id"] == v2["id"]  # main's work since v1 is kept, v1 itself isn't moved
    assert client.get(f"/api/commits/{v1['id']}").json()["branch"] == "main"


def test_rebase_refuses(client, repo, upload):
    v1 = upload(repo["id"], scene())
    main = branches(client, repo)["main"]
    assert "already the latest" in rebase(client, main, v1["id"]).json()["detail"]
    assert rebase(client, main, 999).status_code == 409
    assert client.post("/api/branches/999/rebase", json={"to_commit": v1["id"]}).status_code == 404
    assert set(branches(client, repo)) == {"main"}  # refusals leave no kept branch behind
