import json

import numpy as np
from fakes import ScriptedChat, reply
from scenes import SKY_DUSK, scene

from app import storage
from app.ai import wonder


def run(client, repo, ask="Take the sky from v1 and warm it"):
    r = client.post(f"/api/repos/{repo['id']}/assistant", json={"ask": ask})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    return [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]


def two_versions(client, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))
    label = client.get(f"/api/diff?from={v1['id']}&to={v2['id']}").json()["regions"][0]["label"]
    return v1, v2, label


def test_plan_then_tools_then_summary(client, conn, repo, upload, monkeypatch):
    v1, v2, label = two_versions(client, repo, upload)
    fake = ScriptedChat(
        reply("1. See what changed\n2. Bring back the old sky\n3. Warm it"),
        reply(tool_calls=[("get_changes", {"from_version": "v1", "to_version": "v2"})]),
        reply(tool_calls=[("bring_back", {"source_version": "v1", "label": label})]),
        reply(tool_calls=[("adjust", {"instruction": "warm it to match the dusk"})]),
        reply("Brought back the day sky from v1 and warmed the whole piece."),
    )
    monkeypatch.setattr(wonder, "model_api", lambda: fake)
    events = run(client, repo)

    assert [e["type"] for e in events] == ["plan", "tool_call", "tool_result", "tool_call", "tool_result", "tool_call", "tool_result", "final"]
    assert events[0]["text"].startswith("1. See what changed")
    assert [e["name"] for e in events if e["type"] == "tool_call"] == ["get_changes", "bring_back", "adjust"]
    assert events[2]["result"]["regions"][0]["label"] == label
    assert events[4]["result"]["version"] == "v3" and events[4]["result"]["thumb_url"]

    final = events[-1]
    assert final["text"].startswith("Brought back") and len(final["created"]) == 2
    assert final["branch"].startswith("assistant/")

    # main is untouched; the assistant's versions are on their own branch, chained.
    branches = {b["name"]: b for b in client.get(f"/api/repos/{repo['id']}").json()["branches"]}
    assert branches["main"]["head_commit_id"] == v2["id"]
    assert branches[final["branch"]]["head_commit_id"] == final["working_commit"]
    picked, adjusted = (client.get(f"/api/commits/{i}").json() for i in final["created"])
    assert picked["parent_id"] == v2["id"] and adjusted["parent_id"] == picked["id"]
    assert adjusted["origin"] == "assistant"
    # The sky really came back: v3's sky matches v1's.
    a = np.asarray(storage.load_rgb(conn, v1["blob_sha"]))
    b = np.asarray(storage.load_rgb(conn, picked["blob_sha"]))
    assert np.array_equal(a[40, 40], b[40, 40])
    # The plan request carried no tools; the loop requests did.
    assert "tools" not in fake.requests[0] and "tools" in fake.requests[1]


def test_tool_errors_are_reported_back_to_the_model(client, repo, upload, monkeypatch):
    two_versions(client, repo, upload)
    fake = ScriptedChat(
        reply("1. Bring back the hair"),
        reply(tool_calls=[("bring_back", {"source_version": "v1", "label": "hair"})]),
        reply(tool_calls=[("bring_back", {"source_version": "v9", "label": "sky"})]),
        reply("There is no changed hair region, so I left things as they were."),
    )
    monkeypatch.setattr(wonder, "model_api", lambda: fake)
    events = run(client, repo)
    errors = [e["error"] for e in events if e["type"] == "tool_result" and "error" in e]
    assert "No changed region called 'hair'" in errors[0] and "no version v9" in errors[1]
    assert events[-1]["type"] == "final" and events[-1]["created"] == []
    # The model saw the error as the tool's result.
    tool_msgs = [m for m in fake.requests[-1]["messages"] if m["role"] == "tool"]
    assert "No changed region" in tool_msgs[0]["content"]


def test_stops_at_six_tool_calls(client, repo, upload, monkeypatch):
    two_versions(client, repo, upload)
    fake = ScriptedChat(reply("1. Look around"), reply(tool_calls=[("list_commits", {})]))
    monkeypatch.setattr(wonder, "model_api", lambda: fake)
    events = run(client, repo)
    assert sum(e["type"] == "tool_call" for e in events) == 6
    assert events[-1]["type"] == "final" and "Stopped after 6 steps" in events[-1]["text"]


def test_json_tool_calls_in_text_work_too(client, repo, upload, monkeypatch):
    two_versions(client, repo, upload)
    fake = ScriptedChat(
        reply("1. List versions"),
        reply('Calling: {"tool": "list_commits", "arguments": {}}'),
        reply("There are two versions."),
    )
    monkeypatch.setattr(wonder, "model_api", lambda: fake)
    events = run(client, repo)
    assert [e["name"] for e in events if e["type"] == "tool_call"] == ["list_commits"]
    assert events[2]["result"]["working_version"] == "v2"


def test_without_wonder_simple_asks_still_run(client, conn, repo, upload):
    v1, v2, label = two_versions(client, repo, upload)
    events = run(client, repo, 'Take the sky from v1 and warm it, then call it "day sky, warmer"')

    assert events[0]["type"] == "plan" and "Muse Wonder is unavailable" in events[0]["text"]
    calls = [(e["name"], e["arguments"]) for e in events if e["type"] == "tool_call"]
    assert calls == [
        # "sky" found the changed area by place
        ("bring_back", {"source_version": "v1", "label": label, "drawn": False, "name": "sky"}),
        ("adjust", {"instruction": "warm it"}),
        ("set_message", {"message": "day sky, warmer"}),
    ]
    final = events[-1]
    assert final["type"] == "final" and len(final["created"]) == 2 and final["branch"].startswith("assistant/")
    picked, adjusted = (client.get(f"/api/commits/{i}").json() for i in final["created"])
    assert adjusted["parent_id"] == picked["id"] and adjusted["message"] == "day sky, warmer"
    a = np.asarray(storage.load_rgb(conn, v1["blob_sha"]))
    b = np.asarray(storage.load_rgb(conn, picked["blob_sha"]))
    assert np.array_equal(a[40, 40], b[40, 40])
    # main is untouched
    branches = {b["name"]: b for b in client.get(f"/api/repos/{repo['id']}").json()["branches"]}
    assert branches["main"]["head_commit_id"] == v2["id"]


def test_without_wonder_compare_and_variant(client, repo, upload):
    two_versions(client, repo, upload)
    events = run(client, repo, "What changed since v1, then try a moonlit variant, and add a dragon")
    assert 'Skipping (needs Muse Wonder): "add a dragon"' in events[0]["text"]
    calls = [(e["name"], e["arguments"]) for e in events if e["type"] == "tool_call"]
    assert calls == [("get_changes", {"from_version": "v1", "to_version": "v2"}), ("try_variant", {"direction": "moonlit"})]
    assert all("error" not in e for e in events if e["type"] == "tool_result")
    assert len(events[-1]["created"]) == 1


def test_without_wonder_an_unknown_region_is_refused_not_guessed(client, repo, upload):
    two_versions(client, repo, upload)
    events = run(client, repo, "Bring back the hair from v1")
    (result,) = [e for e in events if e["type"] == "tool_result"]
    assert "No changed region matches 'hair'" in result["error"]
    assert events[-1]["created"] == []


def test_without_wonder_an_ask_it_cant_follow_says_so(client, repo, upload):
    two_versions(client, repo, upload)
    (event,) = run(client, repo, "Make it pop")
    assert event["type"] == "error" and "Muse Wonder is unavailable" in event["message"] and "take the sky from v2" in event["message"]


def test_empty_repo(client, repo):
    (event,) = run(client, repo)
    assert event["type"] == "error" and "Upload a version first" in event["message"]
