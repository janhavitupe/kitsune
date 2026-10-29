from types import SimpleNamespace

from scenes import scene

from app.ai import spark, voice


def add(client, commit, kind="artist", text=None, audio=None, name="note.webm"):
    data = {"kind": kind}
    if text is not None:
        data["text"] = text
    files = {"audio": (name, audio, "audio/webm")} if audio is not None else None
    return client.post(f"/api/commits/{commit['id']}/notes", data=data, files=files)


def fake_voice(text):
    return SimpleNamespace(audio=SimpleNamespace(transcriptions=SimpleNamespace(create=lambda **kw: SimpleNamespace(text=text))))


def fake_spark(text):
    reply = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: reply)))


def test_typed_note(client, repo, upload):
    v1 = upload(repo["id"], scene())
    r = add(client, v1, text="  Warmed the sky because the client wanted dusk.  ")
    assert r.status_code == 201, r.text
    note = r.json()
    assert note["transcript"] == "Warmed the sky because the client wanted dusk."
    assert note["audio_url"] is None and note["summary"] is None and note["kind"] == "artist"
    assert [n["id"] for n in client.get(f"/api/commits/{v1['id']}/notes").json()] == [note["id"]]
    assert client.get(f"/api/commits/{v1['id']}").json()["note_count"] == 1


def test_recording_is_kept_until_it_can_be_transcribed(client, repo, upload, monkeypatch):
    v1 = upload(repo["id"], scene())
    note = add(client, v1, audio=b"fake webm bytes").json()
    assert note["transcript"] is None and note["audio_url"]
    assert client.get(note["audio_url"]).content == b"fake webm bytes"
    assert client.post(f"/api/notes/{note['id']}/transcribe").status_code == 503  # no model yet

    monkeypatch.setattr(voice, "model_api", lambda: fake_voice("Changed the sky because the client wanted dusk."))
    again = client.post(f"/api/notes/{note['id']}/transcribe").json()
    assert again["transcript"] == "Changed the sky because the client wanted dusk."


def test_recording_transcribed_on_upload(client, repo, upload, monkeypatch):
    monkeypatch.setattr(voice, "model_api", lambda: fake_voice("Pushed the rim light on the left figure."))
    v1 = upload(repo["id"], scene())
    assert add(client, v1, audio=b"abc").json()["transcript"] == "Pushed the rim light on the left figure."


def test_long_client_feedback_is_summarized(client, repo, upload, monkeypatch):
    monkeypatch.setattr(spark, "model_api", lambda: fake_spark("- Make the sky dusk\n- Warm the skin"))
    v1 = upload(repo["id"], scene())
    text = "Love it overall. The sky feels too bright. Can it be dusk? Also the skin looks cold. Thanks!"
    note = add(client, v1, kind="client", text=text).json()
    assert note["kind"] == "client" and note["summary"] == "- Make the sky dusk\n- Warm the skin"
    # Short notes are left alone.
    assert add(client, v1, text="Looks great.").json()["summary"] is None


def test_errors_and_delete(client, repo, upload):
    v1 = upload(repo["id"], scene())
    assert add(client, v1, text="   ").status_code == 400
    assert add(client, v1, kind="robot", text="hi").status_code == 400
    assert add(client, v1, audio=b"x", name="note.exe").status_code == 415
    assert client.post("/api/commits/999/notes", data={"text": "hi"}).status_code == 404

    note = add(client, v1, text="keep?").json()
    assert client.delete(f"/api/notes/{note['id']}").status_code == 204
    assert client.get(f"/api/commits/{v1['id']}").json()["note_count"] == 0
    assert client.delete(f"/api/notes/{note['id']}").status_code == 404
