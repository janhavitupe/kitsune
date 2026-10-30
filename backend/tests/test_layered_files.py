import io
import struct
import zipfile

import pytest
from PIL import Image
from scenes import scene

from app import storage
from app.config import settings
from app.db import connect


def kra(img=None, layer=b"layer", mimetype=b"application/x-krita"):
    png = io.BytesIO()
    (img or scene()).save(png, format="PNG")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("mimetype", mimetype)
        z.writestr("mergedimage.png", png.getvalue())
        z.writestr("layers/layer1", layer)
    return out.getvalue()


def psd(img):
    w, h = img.size
    header = b"8BPS" + struct.pack(">H6xHIIHH", 1, 3, h, w, 8, 3)
    planes = b"".join(img.getchannel(c).tobytes() for c in "RGB")
    return header + struct.pack(">III", 0, 0, 0) + struct.pack(">H", 0) + planes


def upload(client, repo_id, data, name="girl.kra"):
    r = client.post(f"/api/repos/{repo_id}/commits", files={"image": (name, data)}, data={"branch": "main", "message": "m"})
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def repo_id(client):
    return client.post("/api/repos", json={"name": "piece"}).json()["id"]


@pytest.mark.parametrize(("make", "ext"), [
    (kra, "kra"),
    (lambda: kra(mimetype=b"image/openraster\n"), "ora"),
    (lambda: psd(scene()), "psd"),
])
def test_a_paint_file_comes_back_byte_for_byte(client, repo_id, make, ext):
    data = make()
    c = upload(client, repo_id, data)
    assert c["source_ext"] == ext
    r = client.get(c["source_url"])
    assert r.content == data
    assert f'filename="v1.{ext}"' in r.headers["content-disposition"]
    assert client.get(c["image_url"]).content.startswith(b"\x89PNG")  # diffs still have their flat image


def test_same_picture_with_different_layers_stays_two_files(client, repo_id):
    one, two = kra(layer=b"sketch"), kra(layer=b"sketch and lineart")
    a, b = upload(client, repo_id, one), upload(client, repo_id, two)
    assert a["blob_sha"] == b["blob_sha"]  # looks identical, so one flat image
    assert client.get(a["source_url"]).content == one
    assert client.get(b["source_url"]).content == two


def test_a_plain_image_keeps_no_source(client, repo_id):
    png = io.BytesIO()
    scene().save(png, format="PNG")
    c = upload(client, repo_id, png.getvalue(), "girl.png")
    assert c["source_url"] is None and c["source_ext"] is None
    assert client.get(f"/api/commits/{c['id']}/source").status_code == 404


def test_big_files_are_fine_up_to_the_source_limit(client, repo_id, monkeypatch):
    data = psd(Image.new("RGB", (1200, 1000), (10, 20, 30)))
    monkeypatch.setattr(settings, "max_upload_mb", 1)  # bigger than a plain upload may be
    assert client.get(upload(client, repo_id, data, "big.psd")["source_url"]).content == data

    monkeypatch.setattr(settings, "max_source_mb", 1)
    r = client.post(f"/api/repos/{repo_id}/commits", files={"image": ("big.psd", data)}, data={"branch": "main"})
    assert r.status_code == 413 and "larger than 1 MB" in r.json()["detail"]


def test_deleting_a_version_drops_a_file_nothing_else_uses(client, repo_id):
    shared = kra(layer=b"same")
    first = upload(client, repo_id, shared)
    second = upload(client, repo_id, shared)
    third = upload(client, repo_id, kra(layer=b"only here"))

    conn = connect()

    def path(c):
        sql = "SELECT s.path FROM commits c JOIN sources s ON s.sha256 = c.source_sha WHERE c.id = ?"
        return storage.abs_path(conn.execute(sql, (c["id"],)).fetchone()[0])

    only, both = path(third), path(first)

    assert client.delete(f"/api/commits/{third['id']}").status_code == 204
    assert not only.exists()
    assert client.delete(f"/api/commits/{second['id']}").status_code == 204
    assert both.exists() and client.get(first["source_url"]).content == shared
    conn.close()


def test_a_database_from_before_layers_gets_the_column(tmp_path, monkeypatch):
    import sqlite3

    from app import db

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    old = sqlite3.connect(tmp_path / "kitsune.db")
    old.execute("CREATE TABLE commits (id INTEGER PRIMARY KEY, repo_id INTEGER, seq INTEGER, blob_sha TEXT)")
    old.execute("INSERT INTO commits VALUES (1, 1, 1, 'abc')")
    old.commit()
    old.close()

    db.init_db()
    conn = db.connect()
    assert conn.execute("SELECT source_sha FROM commits WHERE id = 1").fetchone()[0] is None
    conn.close()
