import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app import jobs, storage
from app.db import get_db
from app.routers.common import COMMIT_SELECT, get_commit_or_404, get_repo_or_404, to_commit
from app.schemas import Commit
from app.services import commits

router = APIRouter(tags=["commits"])


@router.post("/repos/{repo_id}/commits", status_code=201, response_model=Commit)
def create_commit(
    repo_id: int,
    background: BackgroundTasks,
    image: UploadFile = File(...),
    branch: str = Form("main"),
    message: str | None = Form(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    get_repo_or_404(conn, repo_id)
    branch_row = conn.execute(
        "SELECT * FROM branches WHERE repo_id = ? AND name = ?", (repo_id, branch)
    ).fetchone()
    if branch_row is None:
        raise HTTPException(404, f"Branch '{branch}' not found")

    try:
        blob, source_sha = storage.put_upload(conn, image.file.read())
    except storage.ImageRejected as e:
        raise HTTPException(e.status_code, str(e)) from e

    commit_id = commits.create(
        conn,
        repo_id=repo_id,
        branch_id=branch_row["id"],
        blob_sha=blob["sha256"],
        source_sha=source_sha,
        message=(message or "").strip() or None,
    )
    background.add_task(jobs.run_analysis, commit_id)
    return get_commit_or_404(conn, commit_id)


@router.get("/repos/{repo_id}/commits", response_model=list[Commit])
def list_commits(repo_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """The whole commit graph, all branches, oldest first."""
    get_repo_or_404(conn, repo_id)
    rows = conn.execute(COMMIT_SELECT + " WHERE c.repo_id = ? ORDER BY c.seq", (repo_id,)).fetchall()
    return [to_commit(r) for r in rows]


@router.get("/commits/{commit_id}", response_model=Commit)
def get_commit(commit_id: int, conn: sqlite3.Connection = Depends(get_db)):
    return get_commit_or_404(conn, commit_id)


@router.get("/commits/{commit_id}/source")
def get_source(commit_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """The file exactly as the artist saved it, layers and all."""
    row = conn.execute(
        "SELECT c.seq, s.path, s.ext FROM commits c JOIN sources s ON s.sha256 = c.source_sha WHERE c.id = ?", (commit_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "This version has no layered file")
    return FileResponse(storage.abs_path(row["path"]), media_type="application/octet-stream", filename=f"v{row['seq']}.{row['ext']}")


@router.post("/commits/{commit_id}/analyze", status_code=202, response_model=Commit)
def retry_analysis(commit_id: int, background: BackgroundTasks, conn: sqlite3.Connection = Depends(get_db)):
    """Run analysis again after it failed. Every step is safe to repeat."""
    commit = get_commit_or_404(conn, commit_id)
    if commit.analysis_status != "failed":
        raise HTTPException(409, f"Analysis is {commit.analysis_status}, not failed")
    conn.execute("UPDATE commits SET analysis_status = 'pending' WHERE id = ?", (commit_id,))
    background.add_task(jobs.run_analysis, commit_id)
    return get_commit_or_404(conn, commit_id)


@router.delete("/commits/{commit_id}", status_code=204)
def delete_commit(commit_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Delete the latest version of a branch, when nothing is built on it."""
    try:
        commits.delete(conn, commit_id)
    except commits.CannotDelete as e:
        raise HTTPException(e.status_code, str(e)) from e
