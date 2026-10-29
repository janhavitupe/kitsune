import sqlite3

import pytest
from fakes import ScriptedChat, reply
from scenes import SKY_DUSK, scene

from app import db
from app.ai import openweights, spark, wonder
from app.config import settings


def story(client, repo):
    r = client.post(f"/api/repos/{repo['id']}/story")
    assert r.status_code == 200, r.text
    return r.json()


def test_story_from_the_history_without_wonder(client, repo, upload):
    upload(repo["id"], scene(), message="First color pass")
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))
    client.post(f"/api/commits/{v2['id']}/notes", data={"kind": "client", "text": "Can the sky be dusk?"})
    s = story(client, repo)
    assert s["source"] == "template"
    md = s["markdown"]
    assert md.startswith("# forest girl: the process")
    assert "## [v1] First color pass" in md and "## [v2]" in md
    assert "> The client asked: Can the sky be dusk?" in md


def test_story_by_wonder(client, repo, upload, monkeypatch):
    upload(repo["id"], scene(), message="First color pass")
    fake = ScriptedChat(reply("# Forest girl\n\n## Starting out\nIt began with [v1]."))
    monkeypatch.setattr(wonder, "model_api", lambda: fake)
    s = story(client, repo)
    assert s["source"] == "wonder" and "[v1]" in s["markdown"]
    assert "First color pass" in fake.requests[0]["messages"][0]["content"]


def test_empty_story(client, repo):
    assert "No versions yet" in story(client, repo)["markdown"]


def test_old_databases_get_the_new_column(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "old")
    (tmp_path / "old").mkdir()
    old = sqlite3.connect(tmp_path / "old" / "kitsune.db")
    old.execute("CREATE TABLE repos (id INTEGER PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL)")
    old.execute("INSERT INTO repos (name, created_at) VALUES ('before', 'x')")
    old.commit()
    old.close()
    db.init_db()
    conn = db.connect()
    assert conn.execute("SELECT private_mode FROM repos").fetchone()[0] == 0
    conn.close()


@pytest.fixture
def private_repo(client, repo):
    r = client.patch(f"/api/repos/{repo['id']}", json={"private_mode": True})
    assert r.status_code == 200 and r.json()["private_mode"] is True
    return repo


def no_hosted_calls():
    raise AssertionError("private mode must never call the hosted model")


def test_private_mode_captions_on_open_weights_only(client, conn, private_repo, upload, monkeypatch):
    monkeypatch.setattr(spark, "model_api", no_hosted_calls)
    monkeypatch.setattr(settings, "openweights_model", "muse-spark-open")
    monkeypatch.setattr(openweights, "openweights", lambda: ScriptedChat(reply("A girl in a red coat under a dusk sky.")))
    v1 = upload(private_repo["id"], scene())
    row = conn.execute("SELECT caption, model FROM captions WHERE blob_sha = ?", (v1["blob_sha"],)).fetchone()
    assert tuple(row) == ("A girl in a red coat under a dusk sky.", "muse-spark-open")
    hits = client.get(f"/api/repos/{private_repo['id']}/search", params={"q": "red coat"}).json()["results"]
    assert [h["commit_id"] for h in hits] == [v1["id"]]


def test_private_mode_skips_instead_of_falling_back(client, conn, private_repo, upload, monkeypatch):
    monkeypatch.setattr(spark, "model_api", no_hosted_calls)  # open weights aren't configured either
    v1 = upload(private_repo["id"], scene())
    assert conn.execute("SELECT 1 FROM captions WHERE blob_sha = ?", (v1["blob_sha"],)).fetchone() is None
    r = client.get(f"/api/repos/{private_repo['id']}/search", params={"q": "before I changed the sky"}).json()
    assert r["parser"] == "rules"


def test_private_mode_reads_queries_on_open_weights(client, private_repo, upload, monkeypatch):
    monkeypatch.setattr(spark, "model_api", no_hosted_calls)
    monkeypatch.setattr(openweights, "openweights", lambda: ScriptedChat(
        reply('{"relation": "before", "anchor": "sky", "terms": ""}')
    ))
    upload(private_repo["id"], scene())
    r = client.get(f"/api/repos/{private_repo['id']}/search", params={"q": "before I changed the sky"}).json()
    assert r["parser"] == "open-weights"


def test_backfill_endpoints(client, repo, upload):
    v1 = upload(repo["id"], scene())
    missing = client.get(f"/api/repos/{repo['id']}/captions/missing").json()
    assert missing == [{"blob_sha": v1["blob_sha"], "image_url": f"/api/blobs/{v1['blob_sha']}"}]
    r = client.post(f"/api/blobs/{v1['blob_sha']}/captions", json={"caption": "A lighthouse at dawn", "model": "muse-spark-open"})
    assert r.status_code == 201
    assert client.get(f"/api/repos/{repo['id']}/captions/missing").json() == []
    hits = client.get(f"/api/repos/{repo['id']}/search", params={"q": "lighthouse"}).json()["results"]
    assert [h["commit_id"] for h in hits] == [v1["id"]]
    assert client.post(f"/api/blobs/{'0' * 64}/captions", json={"caption": "x", "model": "m"}).status_code == 404
