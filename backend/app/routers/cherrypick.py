import io
import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field

from app import jobs
from app.config import settings
from app.db import get_db
from app.routers.common import get_commit_or_404
from app.schemas import Commit
from app.services import cherry_pick

router = APIRouter(tags=["cherry-pick"])


class CherryPickRequest(BaseModel):
    source_commit: int
    label: str = "selected area"
    drawn: bool = False  # label names something drawn in the source itself, not a change since then
    outline: list[tuple[float, float]] | None = None  # the artist's own selection, as 0..1 shares of the image
    name: str | None = Field(default=None, max_length=80)  # what the artist calls it, for the version's message


@router.post("/commits/{target_id}/cherry-pick", status_code=201, response_model=Commit)
def create_cherry_pick(
    target_id: int,
    body: CherryPickRequest,
    background: BackgroundTasks,
    conn: sqlite3.Connection = Depends(get_db),
):
    """Copy one region of an older version back into the target, as a new commit."""
    get_commit_or_404(conn, target_id)
    try:
        commit_id = cherry_pick.cherry_pick(
            conn, target_id, body.source_commit, body.label, body.drawn, name=body.name, outline=body.outline,
        )
    except cherry_pick.CherryPickError as e:
        raise HTTPException(e.status_code, str(e)) from e
    background.add_task(jobs.run_analysis, commit_id)
    return get_commit_or_404(conn, commit_id)


@router.get("/commits/{target_id}/cherry-pick/preview")
def preview_cherry_pick(
    target_id: int,
    source: int = Query(),
    label: str = Query(),
    drawn: bool = Query(False),
    conn: sqlite3.Connection = Depends(get_db),
):
    """A quick look at the result at reduced size. Nothing is saved."""
    get_commit_or_404(conn, target_id)
    try:
        img = cherry_pick.build(conn, source, target_id, label, drawn, max_side=settings.diff_analysis_px)
    except cherry_pick.CherryPickError as e:
        raise HTTPException(e.status_code, str(e)) from e
    out = io.BytesIO()
    Image.fromarray(img).save(out, format="JPEG", quality=90)
    return Response(out.getvalue(), media_type="image/jpeg")
