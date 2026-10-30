"""Content-addressed blob store.

Uploads can be PNG, JPG, or a paint app's own file (Photoshop .psd, Krita .kra, OpenRaster .ora),
in which case its flattened image is used. Every upload is normalized to an RGB PNG (alpha flattened onto white) and stored under the
SHA-256 of its decoded pixels, sharded like Git: data/blobs/ab/cdef....png. Hashing pixels rather
than file bytes means the same picture saved as a JPG, or as a PNG by a different app, is still
stored once. Thumbnails live next to them under data/thumbs/.

Those PNGs are what Kitsune diffs and copies. A paint app's file is also kept whole, byte for byte
and with its layers, under data/sources/, so any version can be handed back exactly as it was saved.
"""

import base64
import hashlib
import io
import os
import sqlite3
import zipfile
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


def _flattened(data: bytes) -> bytes:
    """The flattened image inside a Krita (.kra) or OpenRaster (.ora, MyPaint/GIMP/Krita) file: both
    are zips with the full-size composite at mergedimage.png. Other uploads are returned as they are;
    Pillow reads a Photoshop file's composite itself."""
    if not data.startswith(b"PK\x03\x04"):
        return data
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            try:
                info = z.getinfo("mergedimage.png")
            except KeyError:
                raise ImageRejected("This file has no flattened image inside. Export a PNG from your paint app.") from None
            if info.file_size > settings.max_source_mb * 1024 * 1024:  # still guard against zip bombs
                raise ImageRejected("The image inside this file is too large", status_code=413)
            return z.read(info)
    except zipfile.BadZipFile as e:
        raise ImageRejected(UNREADABLE) from e


UNREADABLE = "Not a readable image. Upload a PNG, JPG, PSD (Photoshop), KRA (Krita) or ORA file."


def decode(data: bytes, max_mb: int | None = None) -> tuple[Image.Image, bool]:
    """Decode an upload to RGB, or raise ImageRejected.

    Returns (rgb_image, passthrough). passthrough is True when the upload already is an RGB PNG
    with no rotation to apply, so its bytes can be stored as they are without re-encoding.
    """
    max_mb = max_mb or settings.max_upload_mb
    if len(data) > max_mb * 1024 * 1024:
        raise ImageRejected(f"Image is larger than {max_mb} MB", status_code=413)
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
        raise ImageRejected(UNREADABLE) from e
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


def get_blob(conn: sqlite3.Connection, sha: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM blobs WHERE sha256 = ?", (sha,)).fetchone()
    if row is None:
        raise KeyError(f"blob {sha} not found")
    return row


def load_rgb(conn: sqlite3.Connection, sha: str, max_side: int | None = None) -> Image.Image:
    """Open a stored blob as RGB, optionally scaled down so its long side is at most max_side."""
    with Image.open(abs_path(get_blob(conn, sha)["path"])) as img:
        img = img.convert("RGB")
    if max_side and max(img.size) > max_side:
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return img


def data_uri(conn: sqlite3.Connection, sha: str, max_side: int = 1024) -> str:
    """A downscaled JPEG data URI of a blob, for sending to vision models."""
    out = io.BytesIO()
    load_rgb(conn, sha, max_side).save(out, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def layered_ext(data: bytes) -> str | None:
    """'kra', 'ora' or 'psd' when this upload is a paint app's own file, else None."""
    if data.startswith(b"8BPS"):
        return "psd"
    if not data.startswith(b"PK\x03\x04"):
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return "ora" if "mimetype" in z.namelist() and z.read("mimetype").strip() == b"image/openraster" else "kra"
    except zipfile.BadZipFile:
        return None


def put_upload(conn: sqlite3.Connection, data: bytes) -> tuple[sqlite3.Row, str | None]:
    """Store what an artist uploaded: its image, plus the file itself if it holds layers.
    Returns the blobs row and the sources sha (None for a plain PNG or JPG)."""
    ext = layered_ext(data)
    if ext is None:
        return put_image(conn, data), None
    if len(data) > settings.max_source_mb * 1024 * 1024:
        raise ImageRejected(f"File is larger than {settings.max_source_mb} MB", status_code=413)
    blob = put_image(conn, data, max_mb=settings.max_source_mb)

    sha = hashlib.sha256(data).hexdigest()
    if not conn.execute("SELECT 1 FROM sources WHERE sha256 = ?", (sha,)).fetchone():
        rel = _shard("sources", sha, ext)
        _write_atomic(rel, data)
        conn.execute("INSERT OR IGNORE INTO sources (sha256, path, ext, size) VALUES (?, ?, ?, ?)", (sha, rel, ext, len(data)))
    return blob, sha


def put_image(conn: sqlite3.Connection, data: bytes, max_mb: int | None = None) -> sqlite3.Row:
    """Store an uploaded image (deduplicated) and return its blobs row."""
    data = _flattened(data)  # before decoding, so a passthrough stores the inner PNG, not the .kra
    img, passthrough = decode(data, max_mb)
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
