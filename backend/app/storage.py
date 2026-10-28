"""Content-addressed blob store.

Every upload is normalized to an RGB PNG (alpha flattened onto white) and stored under the
SHA-256 of its decoded pixels, sharded like Git: data/blobs/ab/cdef....png. Hashing pixels rather
than file bytes means the same picture saved as a JPG, or as a PNG by a different app, is still
stored once. Thumbnails live next to them under data/thumbs/.
"""

import hashlib
import io
import os
import sqlite3
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings

# Encoding dominates upload time (4K: ~270 ms at level 1, ~500 ms at level 6), so favor speed.
PNG_COMPRESS_LEVEL = 1
EXIF_ORIENTATION = 0x0112


class ImageRejected(ValueError):
    def __init__(self, message: str, status_code: int = 415):
        super().__init__(message)
        self.status_code = status_code


def abs_path(rel: str) -> Path:
    return settings.data_dir / rel


def _shard(kind: str, sha: str, ext: str) -> str:
    return f"{kind}/{sha[:2]}/{sha[2:]}.{ext}"


def _write_atomic(rel: str, data: bytes) -> None:
    path = abs_path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def decode(data: bytes) -> tuple[Image.Image, bool]:
    """Decode an upload to RGB, or raise ImageRejected.

    Returns (rgb_image, passthrough). passthrough is True when the upload already is an RGB PNG
    with no rotation to apply, so its bytes can be stored as they are without re-encoding.
    """
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise ImageRejected(f"Image is larger than {settings.max_upload_mb} MB", status_code=413)
    try:
        img = Image.open(io.BytesIO(data))
        if max(img.size) > settings.max_side_px:
            raise ImageRejected(
                f"Image is larger than {settings.max_side_px}px on a side", status_code=413
            )
        rotated = img.getexif().get(EXIF_ORIENTATION, 1) != 1
        passthrough = img.format == "PNG" and img.mode == "RGB" and not rotated
        if rotated:
            img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            img = Image.new("RGB", rgba.size, (255, 255, 255))
            img.paste(rgba, mask=rgba.getchannel("A"))
        else:
            img = img.convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as e:
        raise ImageRejected("Not a readable image. Upload a PNG or JPG.") from e
    return img, passthrough


def pixel_sha(img: Image.Image) -> str:
    h = hashlib.sha256(f"{img.width}x{img.height}\n".encode())
    h.update(img.tobytes())
    return h.hexdigest()


def _make_thumb(sha: str, img: Image.Image) -> str:
    thumb = img.copy()
    thumb.thumbnail((settings.thumb_px, settings.thumb_px), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    thumb.save(out, format="WEBP", quality=85)
    rel = _shard("thumbs", sha, "webp")
    _write_atomic(rel, out.getvalue())
    return rel


def put_image(conn: sqlite3.Connection, data: bytes) -> sqlite3.Row:
    """Store an uploaded image (deduplicated) and return its blobs row."""
    img, passthrough = decode(data)
    sha = pixel_sha(img)

    row = conn.execute("SELECT * FROM blobs WHERE sha256 = ?", (sha,)).fetchone()
    if row is not None:
        return row

    if passthrough:
        png = data
    else:
        out = io.BytesIO()
        img.save(out, format="PNG", compress_level=PNG_COMPRESS_LEVEL)
        png = out.getvalue()
    rel = _shard("blobs", sha, "png")
    _write_atomic(rel, png)
    thumb_rel = _make_thumb(sha, img)
    conn.execute(
        "INSERT OR IGNORE INTO blobs (sha256, path, width, height, mime, thumb_path)"
        " VALUES (?, ?, ?, ?, 'image/png', ?)",
        (sha, rel, img.width, img.height, thumb_rel),
    )
    return conn.execute("SELECT * FROM blobs WHERE sha256 = ?", (sha,)).fetchone()
