import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db, now, transaction
from app.routers.common import get_repo_or_404, to_branch
from app.schemas import Branch, BranchCreate, BranchUpdate

router = APIRouter(tags=["branches"])


@router.get("/repos/{repo_id}/branches", response_model=list[Branch])
def list_branches(repo_id: int, conn: sqlite3.Connection = Depends(get_db)):
    get_repo_or_404(conn, repo_id)
    rows = conn.execute("SELECT * FROM branches WHERE repo_id = ? ORDER BY id", (repo_id,)).fetchall()
    return [to_branch(r) for r in rows]


@router.patch("/branches/{branch_id}", response_model=Branch)
def update_branch(branch_id: int, body: BranchUpdate, conn: sqlite3.Connection = Depends(get_db)):
    """Rename a branch, keep an explore branch (kind → normal) or hide it (kind → discarded).
    History is append-only, so discarding hides a branch rather than deleting it."""
    row = conn.execute("SELECT * FROM branches WHERE id = ?", (branch_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"Branch {branch_id} not found")
    if row["name"] == "main" and (body.name not in (None, "main") or body.kind not in (None, "normal")):
        raise HTTPException(400, "main can't be renamed or hidden")
    with transaction(conn):
        if body.name and body.name != row["name"]:
            if conn.execute(
                "SELECT 1 FROM branches WHERE repo_id = ? AND name = ?", (row["repo_id"], body.name)
            ).fetchone():
                raise HTTPException(409, f"Branch '{body.name}' already exists")
            conn.execute("UPDATE branches SET name = ? WHERE id = ?", (body.name, branch_id))
        if body.kind:
            conn.execute("UPDATE branches SET kind = ? WHERE id = ?", (body.kind, branch_id))
    return to_branch(conn.execute("SELECT * FROM branches WHERE id = ?", (branch_id,)).fetchone())


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
