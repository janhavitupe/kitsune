def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_new_repo_has_main(repo):
    assert [b["name"] for b in repo["branches"]] == ["main"]
    assert repo["branches"][0]["head_commit_id"] is None


def test_commits_chain_and_move_head(client, repo, upload):
    v1 = upload(repo["id"], (10, 0, 0), message="  first sketch ")
    v2 = upload(repo["id"], (20, 0, 0), message="   ")
    v3 = upload(repo["id"], (30, 0, 0))

    assert [v1["seq"], v2["seq"], v3["seq"]] == [1, 2, 3]
    assert v1["parent_id"] is None and v2["parent_id"] == v1["id"] and v3["parent_id"] == v2["id"]
    assert v1["message"] == "first sketch" and v2["message"] is None

    graph = client.get(f"/api/repos/{repo['id']}/commits").json()
    assert [c["id"] for c in graph] == [v1["id"], v2["id"], v3["id"]]
    head = client.get(f"/api/repos/{repo['id']}").json()["branches"][0]["head_commit_id"]
    assert head == v3["id"]


def test_background_analysis_finishes(client, repo, upload):
    v1 = upload(repo["id"], (10, 0, 0))
    assert v1["analysis_status"] == "pending"
    # TestClient runs background tasks before returning, so it's already finished.
    assert client.get(f"/api/commits/{v1['id']}").json()["analysis_status"] == "done"


def test_branch_from_old_version(client, repo, upload):
    v1 = upload(repo["id"], (10, 0, 0))
    upload(repo["id"], (20, 0, 0))
    r = client.post(f"/api/repos/{repo['id']}/branches", json={"name": "dusk-palette", "from_commit": v1["id"]})
    assert r.status_code == 201 and r.json()["head_commit_id"] == v1["id"]

    d1 = upload(repo["id"], (0, 0, 50), branch="dusk-palette")
    assert d1["parent_id"] == v1["id"] and d1["branch"] == "dusk-palette"


def test_branch_errors(client, repo):
    base = f"/api/repos/{repo['id']}/branches"
    assert client.post(base, json={"name": "main"}).status_code == 409
    assert client.post(base, json={"name": "bad name!"}).status_code == 422
    assert client.post(base, json={"name": "x", "from_commit": 999}).status_code == 404


def test_duplicate_upload_shares_blob(repo, upload):
    a = upload(repo["id"], (10, 0, 0))
    b = upload(repo["id"], (10, 0, 0))
    assert a["blob_sha"] == b["blob_sha"] and a["id"] != b["id"]


def test_upload_errors(client, repo):
    url = f"/api/repos/{repo['id']}/commits"
    bad = client.post(url, files={"image": ("x.png", b"nope", "image/png")})
    assert bad.status_code == 415
    missing = client.post(url, files={"image": ("x.png", b"nope", "image/png")}, data={"branch": "nope"})
    assert missing.status_code == 404
    assert client.post("/api/repos/999/commits", files={"image": ("x.png", b"", "image/png")}).status_code == 404


def test_blob_endpoints(client, repo, upload):
    v1 = upload(repo["id"], (10, 0, 0))
    img = client.get(v1["image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert "immutable" in img.headers["cache-control"]
    assert client.get(v1["thumb_url"]).headers["content-type"] == "image/webp"
    assert client.get("/api/blobs/" + "0" * 64).status_code == 404
    assert client.get("/api/blobs/not-a-sha").status_code == 422
