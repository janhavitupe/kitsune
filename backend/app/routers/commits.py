import sqlite3

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile

from app import jobs, storage
from app.db import get_db, now, transaction
from app.routers.common import COMMIT_SELECT, get_commit_or_404, get_repo_or_404, to_commit
from app.schemas import Commit

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
        blob = storage.put_image(conn, image.file.read())
    except storage.ImageRejected as e:
        raise HTTPException(e.status_code, str(e)) from e

    message = (message or "").strip() or None
    with transaction(conn):
        # Re-read the head inside the write lock so two uploads can't share a parent.
        head = conn.execute(
            "SELECT head_commit_id FROM branches WHERE id = ?", (branch_row["id"],)
        ).fetchone()["head_commit_id"]
        seq = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) + 1 FROM commits WHERE repo_id = ?", (repo_id,)
        ).fetchone()[0]
        commit_id = conn.execute(
            "INSERT INTO commits (repo_id, seq, branch_id, parent_id, blob_sha, message, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (repo_id, seq, branch_row["id"], head, blob["sha256"], message, now()),
        ).lastrowid
        conn.execute(
            "UPDATE branches SET head_commit_id = ? WHERE id = ?", (commit_id, branch_row["id"])
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
