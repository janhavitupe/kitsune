import sqlite3

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from PIL import Image

from app import storage
from app.db import get_db
from app.routers.common import get_commit_or_404
from app.schemas import Diff, Region
from app.services import diffing, region_diff

router = APIRouter(tags=["diffs"])


@router.get("/diff", response_model=Diff)
def get_diff(
    from_: int = Query(alias="from"),
    to: int = Query(),
    conn: sqlite3.Connection = Depends(get_db),
):
    """What changed from one version to another, as named regions. Computed once, then cached."""
    get_commit_or_404(conn, from_)
    get_commit_or_404(conn, to)
    try:
        diff = diffing.get_or_compute(conn, from_, to)
    except diffing.DiffError as e:
        raise HTTPException(400, str(e)) from e
    return Diff(**diff, change_mask_url=f"/api/diffs/{diff['id']}/mask.png")


@router.get("/diffs/{diff_id}/mask.png")
def get_diff_mask(diff_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """The raw change mask as a translucent orange overlay, at analysis resolution."""
    row = conn.execute("SELECT change_mask_path FROM diffs WHERE id = ?", (diff_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Diff not found")
    return FileResponse(storage.abs_path(row["change_mask_path"]), media_type="image/png")


@router.get("/commits/{commit_id}/regions", response_model=list[Region])
def get_regions(commit_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """SAM regions of a version. Empty until SAM is connected."""
    commit = get_commit_or_404(conn, commit_id)
    rows = conn.execute("SELECT * FROM regions WHERE blob_sha = ? ORDER BY id", (commit.blob_sha,)).fetchall()
    out = []
    for r in rows:
        with Image.open(storage.abs_path(r["mask_path"])) as img:
            mask = np.asarray(img.convert("L")) > 127
        out.append(Region(
            id=r["id"], label=r["label"], bbox=region_diff.bbox(mask), area_px=r["area_px"],
            score=r["score"], source=r["source"], polygons=region_diff.polygons(mask),
        ))
    return out
