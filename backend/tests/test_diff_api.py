from types import SimpleNamespace

from scenes import SKY_DUSK, scene, sky_mask

from app.ai import spark
from app.config import settings
from app.services import diffing
from app.services.segmentation import RawMask, save_regions


def two_versions(repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(extra=((20, 20, 90, 70), (250, 250, 250))))
    return v1, v2


def test_diff_names_changed_areas(client, repo, upload):
    v1, v2 = two_versions(repo, upload)
    r = client.get(f"/api/diff?from={v1['id']}&to={v2['id']}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert [x["label"] for x in d["regions"]] == ["top-left area"]
    assert d["segmented"] is False and d["resized"] is False
    assert d["summary"] == "Changed the top-left area (lighter, more muted)."
    assert 0 < d["changed_fraction"] < 0.05

    mask = client.get(d["change_mask_url"])
    assert mask.status_code == 200 and mask.headers["content-type"] == "image/png"


def test_diff_is_cached(client, repo, upload):
    v1, v2 = two_versions(repo, upload)
    first = client.get(f"/api/diff?from={v1['id']}&to={v2['id']}").json()
    second = client.get(f"/api/diff?from={v1['id']}&to={v2['id']}").json()
    assert first == second


def test_diff_recomputed_when_thresholds_change(client, repo, upload, monkeypatch):
    v1, v2 = two_versions(repo, upload)
    url = f"/api/diff?from={v1['id']}&to={v2['id']}"
    assert client.get(url).json()["regions"]
    # A threshold so high nothing counts as changed: the cached diff must not be reused.
    monkeypatch.setattr(settings, "diff_delta_e", 500.0)
    assert client.get(url).json()["regions"] == []


def test_upload_writes_auto_message(client, repo, upload):
    v1, v2 = two_versions(repo, upload)
    # No model key in tests, so the message is the measured summary.
    assert client.get(f"/api/commits/{v2['id']}").json()["auto_message"] == "Changed the top-left area (lighter, more muted)."
    assert client.get(f"/api/commits/{v1['id']}").json()["auto_message"] is None


def test_diff_errors(client, repo, upload):
    v1 = upload(repo["id"], scene())
    other = client.post("/api/repos", json={"name": "other"}).json()
    o1 = upload(other["id"], scene(sky=SKY_DUSK))
    assert client.get(f"/api/diff?from={v1['id']}&to={v1['id']}").status_code == 400
    assert client.get(f"/api/diff?from={v1['id']}&to={o1['id']}").status_code == 400
    assert client.get(f"/api/diff?from={v1['id']}&to=999").status_code == 404
    assert client.get("/api/diffs/999/mask.png").status_code == 404


def test_diff_recomputed_once_regions_exist(client, conn, repo, upload):
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))
    before = client.get(f"/api/diff?from={v1['id']}&to={v2['id']}").json()
    assert before["segmented"] is False

    # SAM arrives later and segments v2: the cached diff is replaced with named regions.
    save_regions(conn, v2["blob_sha"], [RawMask("sky", sky_mask(), 0.9)], source="sam-3.1")
    after = client.get(f"/api/diff?from={v1['id']}&to={v2['id']}").json()
    assert after["segmented"] is True
    assert after["regions"][0]["label"] == "sky" and "warmer" in after["regions"][0]["hints"]

    regions = client.get(f"/api/commits/{v2['id']}/regions").json()
    assert [r["label"] for r in regions] == ["sky"] and regions[0]["polygons"]


class FakeClient:
    def __init__(self, text):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.text = text

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.text))])


def test_spark_message_used_when_available(client, conn, repo, upload, monkeypatch):
    fake = FakeClient('"Warmed the sky into a dusk palette."')
    monkeypatch.setattr(spark, "model_api", lambda: fake)
    v1 = upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(sky=SKY_DUSK))

    assert client.get(f"/api/commits/{v2['id']}").json()["auto_message"] == "Warmed the sky into a dusk palette."
    # Spark also captions each version; the commit-message call is the one with the system prompt.
    message_calls = lambda: [c for c in fake.calls if c["messages"][0]["role"] == "system"]  # noqa: E731
    (call,) = message_calls()
    prompt = call["messages"][-1]["content"][-1]["text"]
    assert "whole canvas" in prompt or "area" in prompt  # measured regions are in the prompt
    assert sum(1 for part in call["messages"][-1]["content"] if part["type"] == "image_url") == 2

    # Same inputs again: served from the AI cache, no second call.
    diff = diffing.get_or_compute(conn, v1["id"], v2["id"])
    diffing.commit_message(conn, diff, v1["blob_sha"], v2["blob_sha"])
    assert len(message_calls()) == 1


def test_spark_failure_falls_back_to_summary(client, repo, upload, monkeypatch):
    def broken():
        raise RuntimeError("rate limited")

    monkeypatch.setattr(spark, "model_api", broken)
    upload(repo["id"], scene())
    v2 = upload(repo["id"], scene(extra=((20, 20, 90, 70), (250, 250, 250))))
    assert client.get(f"/api/commits/{v2['id']}").json()["auto_message"] == "Changed the top-left area (lighter, more muted)."
