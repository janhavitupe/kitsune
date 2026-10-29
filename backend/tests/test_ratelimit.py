import io

import pytest

from app.config import settings
from scenes import scene


@pytest.fixture(autouse=True)
def limits(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_ai_per_min", 2)
    monkeypatch.setattr(settings, "rate_limit_writes_per_min", 3)


def test_writes_are_limited_but_reads_are_not(client):
    codes = [client.post("/api/repos", json={"name": f"r{i}"}).status_code for i in range(4)]
    assert codes == [201, 201, 201, 429]
    r = client.post("/api/repos", json={"name": "again"})
    assert "Too many changes" in r.json()["detail"] and int(r.headers["retry-after"]) > 0
    assert all(client.get("/api/repos").status_code == 200 for _ in range(10))


def test_ai_requests_have_their_own_smaller_budget(client, repo, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_writes_per_min", 100)
    commit = client.post(
        f"/api/repos/{repo['id']}/commits", files={"image": ("v.png", _png(), "image/png")}
    ).json()
    codes = [client.post(f"/api/repos/{repo['id']}/story").status_code for _ in range(3)]
    assert codes == [200, 200, 429]
    assert "Too many AI requests" in client.post(f"/api/commits/{commit['id']}/explore", json={}).json()["detail"]
    # Ordinary writes still go through.
    assert client.post(f"/api/repos/{repo['id']}/branches", json={"name": "b"}).status_code == 201


def test_limits_are_per_client(client):
    for _ in range(3):
        client.post("/api/repos", json={"name": "x"}, headers={"x-forwarded-for": "1.1.1.1"})
    assert client.post("/api/repos", json={"name": "x"}, headers={"x-forwarded-for": "1.1.1.1"}).status_code == 429
    # A spoofed first entry doesn't help: the last one (added by the proxy) identifies the client.
    assert client.post("/api/repos", json={"name": "x"}, headers={"x-forwarded-for": "9.9.9.9, 1.1.1.1"}).status_code == 429
    assert client.post("/api/repos", json={"name": "x"}, headers={"x-forwarded-for": "2.2.2.2"}).status_code == 201


def _png() -> bytes:
    out = io.BytesIO()
    scene().save(out, format="PNG")
    return out.getvalue()
