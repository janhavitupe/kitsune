import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

from app import jobs
from app.db import get_db
from app.routers.common import get_commit_or_404, get_repo_or_404
from app.schemas import Commit, SearchResponse
from app.services import explore, search

router = APIRouter(tags=["search", "explore"])


@router.get("/repos/{repo_id}/search", response_model=SearchResponse)
def search_history(repo_id: int, q: str = Query(min_length=1, max_length=200), conn: sqlite3.Connection = Depends(get_db)):
    """Search messages, notes, captions and changed regions; understands "before / after / when I changed X"."""
    get_repo_or_404(conn, repo_id)
    return search.search(conn, repo_id, q)


class ExploreRequest(BaseModel):
    prompt: str | None = None  # e.g. "try 3 palettes for this"; empty = the three presets


@router.post("/commits/{commit_id}/explore", status_code=201, response_model=list[Commit])
def explore_commit(
    commit_id: int, body: ExploreRequest, background: BackgroundTasks, conn: sqlite3.Connection = Depends(get_db)
):
    """Three palette variations of a version, each on its own explore branch."""
    get_commit_or_404(conn, commit_id)
    try:
        ids = explore.explore(conn, commit_id, body.prompt)
    except explore.ExploreError as e:
        raise HTTPException(e.status_code, str(e)) from e
    for i in ids:
        background.add_task(jobs.run_analysis, i)
    return [get_commit_or_404(conn, i) for i in ids]
