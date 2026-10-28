import sqlite3
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app import jobs
from app.db import get_db
from app.routers.common import get_commit_or_404, get_repo_or_404
from app.schemas import Commit, MergePlan
from app.services import merge

router = APIRouter(tags=["merges"])


class MergeRequest(BaseModel):
    source: str  # branch to merge in
    target: str  # branch that receives the merge commit


class ResolveRequest(BaseModel):
    choices: dict[int, Literal["source", "target"]] = {}  # conflict index → side; default "target"
    blend: str = "auto"


def _plan(conn: sqlite3.Connection, merge_id: int) -> MergePlan:
    try:
        return MergePlan(**merge.get(conn, merge_id))
    except merge.MergeError as e:
        raise HTTPException(e.status_code, str(e)) from e


@router.post("/repos/{repo_id}/merges", status_code=201, response_model=MergePlan)
def plan_merge(repo_id: int, body: MergeRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Check what merging one branch into another would do: automatic picks and conflicts."""
    get_repo_or_404(conn, repo_id)
    try:
        merge_id = merge.plan(conn, repo_id, body.source, body.target)
    except merge.MergeError as e:
        raise HTTPException(e.status_code, str(e)) from e
    return _plan(conn, merge_id)


@router.get("/merges/{merge_id}", response_model=MergePlan)
def get_merge(merge_id: int, conn: sqlite3.Connection = Depends(get_db)):
    return _plan(conn, merge_id)


@router.post("/merges/{merge_id}/resolve", status_code=201, response_model=Commit)
def resolve_merge(
    merge_id: int, body: ResolveRequest, background: BackgroundTasks, conn: sqlite3.Connection = Depends(get_db)
):
    """Write the merge commit with the artist's picks for each conflict."""
    try:
        commit_id = merge.resolve(conn, merge_id, body.choices, body.blend)
    except merge.MergeError as e:
        raise HTTPException(e.status_code, str(e)) from e
    background.add_task(jobs.run_analysis, commit_id)
    return get_commit_or_404(conn, commit_id)


@router.post("/merges/{merge_id}/abort", response_model=MergePlan)
def abort_merge(merge_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        merge.abort(conn, merge_id)
    except merge.MergeError as e:
        raise HTTPException(e.status_code, str(e)) from e
    return _plan(conn, merge_id)
