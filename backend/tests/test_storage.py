import io
import struct
import zipfile

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


def _png(img):
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _paint_file(img, extra=()):
    """A Krita/OpenRaster-style zip: layers plus the flattened image at mergedimage.png."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("mimetype", "application/x-krita")
        for name in extra:
            z.writestr(name, b"layer data")
        if img is not None:
            z.writestr("mergedimage.png", _png(img))
    return out.getvalue()


def _psd(img):
    """A minimal flattened RGB Photoshop file: header, empty sections, raw planar composite."""
    w, h = img.size
    header = b"8BPS" + struct.pack(">H6xHIIHH", 1, 3, h, w, 8, 3)
    planes = b"".join(img.getchannel(c).tobytes() for c in "RGB")
    return header + struct.pack(">III", 0, 0, 0) + struct.pack(">H", 0) + planes


@pytest.mark.parametrize("wrap", [_paint_file, _psd], ids=["kra-ora", "psd"])
def test_paint_app_files_store_their_flattened_image(conn, wrap):
    img = Image.merge("RGB", [Image.radial_gradient("L"), Image.linear_gradient("L"), Image.new("L", (256, 256), 90)])
    img = img.resize((120, 80))  # RGB, so the PNG inside a .kra is stored as it is
    row = storage.put_image(conn, wrap(img))
    assert (row["width"], row["height"]) == (120, 80)
    assert storage.load_rgb(conn, row["sha256"]).tobytes() == img.tobytes()  # the stored file is a real PNG
    # Same pixels as the PNG export, so it's the same blob.
    assert row["sha256"] == storage.put_image(conn, _png(img))["sha256"]


def test_paint_file_without_a_flattened_image(conn):
    with pytest.raises(storage.ImageRejected, match="no flattened image"):
        storage.put_image(conn, _paint_file(None, extra=["layers/layer1.png"]))
    with pytest.raises(storage.ImageRejected, match="PSD"):
        storage.put_image(conn, b"PK\x03\x04 not really a zip")
