import io

import pytest
from PIL import Image

from app import storage
from app.config import settings


def test_same_bytes_stored_once(conn, make_image):
    a = storage.put_image(conn, make_image())
    b = storage.put_image(conn, make_image())
    assert a["sha256"] == b["sha256"]
    assert conn.execute("SELECT COUNT(*) FROM blobs").fetchone()[0] == 1


def test_same_pixels_encoded_differently_stored_once(conn):
    img = Image.radial_gradient("L").convert("RGB")
    encodings = []
    for level in (0, 9):
        out = io.BytesIO()
        img.save(out, format="PNG", compress_level=level)
        encodings.append(out.getvalue())
    assert encodings[0] != encodings[1]
    assert storage.put_image(conn, encodings[0])["sha256"] == storage.put_image(conn, encodings[1])["sha256"]


def test_jpg_is_stored_as_png(conn, make_image):
    row = storage.put_image(conn, make_image(fmt="JPEG"))
    assert row["mime"] == "image/png"
    assert row["path"].endswith(".png")
    with Image.open(storage.abs_path(row["path"])) as img:
        assert img.format == "PNG" and img.mode == "RGB"


def test_alpha_is_flattened_onto_white(conn, make_image):
    row = storage.put_image(conn, make_image(color=(255, 0, 0, 0), mode="RGBA"))
    with Image.open(storage.abs_path(row["path"])) as img:
        assert img.mode == "RGB"
        assert img.getpixel((0, 0)) == (255, 255, 255)


def test_thumbnail_longest_side(conn, make_image):
    row = storage.put_image(conn, make_image(size=(1000, 500)))
    with Image.open(storage.abs_path(row["thumb_path"])) as thumb:
        assert thumb.format == "WEBP"
        assert thumb.size == (settings.thumb_px, settings.thumb_px // 2)
    assert (row["width"], row["height"]) == (1000, 500)


def test_rejects_non_image(conn):
    with pytest.raises(storage.ImageRejected) as e:
        storage.put_image(conn, b"definitely not an image")
    assert e.value.status_code == 415


def test_rejects_oversized_dimensions(conn, make_image, monkeypatch):
    monkeypatch.setattr(settings, "max_side_px", 100)
    with pytest.raises(storage.ImageRejected) as e:
        storage.put_image(conn, make_image(size=(101, 10)))
    assert e.value.status_code == 413
