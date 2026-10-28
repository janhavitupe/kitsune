from types import SimpleNamespace

from app.ai import spark
from scenes import SKY_DUSK, scene


def search(client, repo, q):
    r = client.get(f"/api/repos/{repo['id']}/search", params={"q": q})
    assert r.status_code == 200, r.text
    return r.json()


def note(client, commit, text, kind="artist"):
    assert client.post(f"/api/commits/{commit['id']}/notes", data={"kind": kind, "text": text}).status_code == 201


def history(client, repo, upload):
    """v1 sketch → v2 dusk sky (with a note saying why) → v3 a new patch."""
    v1 = upload(repo["id"], scene(), message="First sketch")
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))
    note(client, v2, "Changed the sky to dusk because the client asked for it")
    v3 = upload(repo["id"], scene(sky=SKY_DUSK, extra=((20, 300, 90, 360), (250, 250, 250))), message="Added a rock")
    return v1, v2, v3


def test_plain_search_finds_messages_and_notes(client, repo, upload):
    v1, v2, v3 = history(client, repo, upload)
    r = search(client, repo, "sketch")
    assert [x["commit_id"] for x in r["results"]] == [v1["id"]] and "[" in r["results"][0]["snippet"]
    assert [x["commit_id"] for x in search(client, repo, "dusk client")["results"]] == [v2["id"]]
    assert search(client, repo, "rock")["results"][0]["commit_id"] == v3["id"]


def test_changed_regions_are_searchable(client, repo, upload):
    _, _, v3 = history(client, repo, upload)
    assert v3["id"] in [x["commit_id"] for x in search(client, repo, "bottom-left")["results"]]


def test_before_i_changed_the_sky(client, repo, upload):
    v1, v2, _ = history(client, repo, upload)
    r = search(client, repo, "show me the version before I changed the sky")
    assert r["relation"] == "before" and r["parser"] == "rules"
    first = r["results"][0]
    assert first["commit_id"] == v1["id"] and "just before v2" in first["reason"]


def test_after_and_when(client, repo, upload):
    _, v2, _ = history(client, repo, upload)
    assert search(client, repo, "after the sky changed")["results"][0]["commit_id"] == v2["id"]
    assert search(client, repo, "when did the sky turn dusk")["results"][0]["commit_id"] == v2["id"]


def test_client_feedback_is_findable_by_kind(client, repo, upload):
    v1 = upload(repo["id"], scene())
    note(client, v1, "Can the sky be warmer?", kind="client")
    assert [x["commit_id"] for x in search(client, repo, "client feedback")["results"]] == [v1["id"]]


def test_spark_reads_the_query_when_available(client, repo, upload, monkeypatch):
    v1, _, _ = history(client, repo, upload)
    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
        content='Sure: {"relation": "before", "anchor": "dusk", "terms": ""}'
    ))])
    monkeypatch.setattr(spark, "model_api", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: reply))
    ))
    r = search(client, repo, "the one before it went dusk")
    assert r["parser"] == "spark" and r["results"][0]["commit_id"] == v1["id"]


def test_nothing_to_search(client, repo, upload):
    history(client, repo, upload)
    assert search(client, repo, "the a of")["results"] == []
    assert search(client, repo, "unicorn")["results"] == []
    assert client.get(f"/api/repos/{repo['id']}/search", params={"q": ""}).status_code == 422
