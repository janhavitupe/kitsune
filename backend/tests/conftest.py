import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import db, ratelimit
from app.ai import client as ai_client
from app.config import settings


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Every test gets an empty data dir and a fresh database."""
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "ai_offline", False)
    # Tests never reach the real Model API, even when .env has a key; mock clients per test.
    monkeypatch.setattr(settings, "model_api_key", "")
    monkeypatch.setattr(settings, "openweights_base_url", "")
    monkeypatch.setattr(settings, "openweights_api_key", "")
    ai_client.model_api.cache_clear()
    ai_client.openweights.cache_clear()
    monkeypatch.setattr(settings, "rate_limit_enabled", False)  # test_ratelimit turns it back on
    ratelimit.reset()
    db.init_db()
    return settings.data_dir


@pytest.fixture
def conn(data_dir):
    c = db.connect()
    yield c
    c.close()


@pytest.fixture
def client(data_dir):
    from app.main import app

    with TestClient(app) as c:
        yield c


def image_bytes(color=(40, 90, 200), size=(64, 48), fmt="PNG", mode="RGB") -> bytes:
    img = Image.new(mode, size, color)
    out = io.BytesIO()
    img.save(out, format=fmt)
    return out.getvalue()


@pytest.fixture
def make_image():
    return image_bytes


@pytest.fixture
def repo(client):
    return client.post("/api/repos", json={"name": "forest girl"}).json()


@pytest.fixture
def upload(client):
    """Upload a version: `image` is an RGB color tuple (solid image) or a PIL image."""

    def _upload(repo_id, image, branch="main", message=None):
        data = {"branch": branch}
        if message is not None:
            data["message"] = message
        if isinstance(image, Image.Image):
            out = io.BytesIO()
            image.save(out, format="PNG")
            png = out.getvalue()
        else:
            png = image_bytes(image)
        r = client.post(
            f"/api/repos/{repo_id}/commits",
            files={"image": ("v.png", png, "image/png")},
            data=data,
        )
        assert r.status_code == 201, r.text
        return r.json()

    return _upload
