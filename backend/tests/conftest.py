import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import db
from app.config import settings


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Every test gets an empty data dir and a fresh database."""
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "ai_offline", False)
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
    def _upload(repo_id, color, branch="main", message=None):
        data = {"branch": branch}
        if message is not None:
            data["message"] = message
        r = client.post(
            f"/api/repos/{repo_id}/commits",
            files={"image": ("v.png", image_bytes(color), "image/png")},
            data=data,
        )
        assert r.status_code == 201, r.text
        return r.json()

    return _upload
