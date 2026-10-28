import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import FileResponse

from app import storage
from app.db import get_db

router = APIRouter(tags=["blobs"])

SHA = Path(pattern=r"^[0-9a-f]{64}$")
# Blobs are content-addressed, so a URL's bytes never change.
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}


def _blob_or_404(conn: sqlite3.Connection, sha: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM blobs WHERE sha256 = ?", (sha,)).fetchone()
    if row is None:
        raise HTTPException(404, "Blob not found")
    return row


@router.get("/blobs/{sha}")
def get_blob(sha: str = SHA, conn: sqlite3.Connection = Depends(get_db)):
    row = _blob_or_404(conn, sha)
    return FileResponse(storage.abs_path(row["path"]), media_type=row["mime"], headers=IMMUTABLE)


@router.get("/blobs/{sha}/thumb")
def get_thumb(sha: str = SHA, conn: sqlite3.Connection = Depends(get_db)):
    row = _blob_or_404(conn, sha)
    return FileResponse(storage.abs_path(row["thumb_path"]), media_type="image/webp", headers=IMMUTABLE)
