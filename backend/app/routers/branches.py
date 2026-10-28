import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db, now, transaction
from app.routers.common import get_repo_or_404, to_branch
from app.schemas import Branch, BranchCreate

router = APIRouter(tags=["branches"])


@router.get("/repos/{repo_id}/branches", response_model=list[Branch])
def list_branches(repo_id: int, conn: sqlite3.Connection = Depends(get_db)):
    get_repo_or_404(conn, repo_id)
    rows = conn.execute("SELECT * FROM branches WHERE repo_id = ? ORDER BY id", (repo_id,)).fetchall()
    return [to_branch(r) for r in rows]


@router.post("/repos/{repo_id}/branches", status_code=201, response_model=Branch)
def create_branch(repo_id: int, body: BranchCreate, conn: sqlite3.Connection = Depends(get_db)):
    get_repo_or_404(conn, repo_id)
    with transaction(conn):
        if conn.execute(
            "SELECT 1 FROM branches WHERE repo_id = ? AND name = ?", (repo_id, body.name)
        ).fetchone():
            raise HTTPException(409, f"Branch '{body.name}' already exists")

        if body.from_commit is None:
            head = conn.execute(
                "SELECT head_commit_id FROM branches WHERE repo_id = ? AND name = 'main'", (repo_id,)
            ).fetchone()
            from_commit = head["head_commit_id"] if head else None
        else:
            if not conn.execute(
                "SELECT 1 FROM commits WHERE id = ? AND repo_id = ?", (body.from_commit, repo_id)
            ).fetchone():
                raise HTTPException(404, f"Commit {body.from_commit} not found in this repo")
            from_commit = body.from_commit

        branch_id = conn.execute(
            "INSERT INTO branches (repo_id, name, head_commit_id, created_at) VALUES (?, ?, ?, ?)",
            (repo_id, body.name, from_commit, now()),
        ).lastrowid
    return to_branch(conn.execute("SELECT * FROM branches WHERE id = ?", (branch_id,)).fetchone())
