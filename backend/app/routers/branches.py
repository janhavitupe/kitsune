import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db, now, transaction
from app.routers.common import get_repo_or_404, to_branch
from app.schemas import Branch, BranchCreate, BranchRebase, BranchRebased, BranchUpdate
from app.services import commits

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


@router.delete("/branches/{branch_id}")
def delete_branch(branch_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Delete a branch and the versions only it has; versions other branches use are kept."""
    try:
        return {"deleted_versions": commits.delete_branch(conn, branch_id)}
    except commits.CannotDelete as e:
        raise HTTPException(e.status_code, str(e)) from e


@router.post("/branches/{branch_id}/rebase", response_model=BranchRebased)
def rebase_branch(branch_id: int, body: BranchRebase, conn: sqlite3.Connection = Depends(get_db)):
    """Make any version the branch's latest. Versions it would leave behind are kept on a new branch."""
    if conn.execute("SELECT 1 FROM branches WHERE id = ?", (branch_id,)).fetchone() is None:
        raise HTTPException(404, f"Branch {branch_id} not found")
    try:
        kept = commits.rebase(conn, branch_id, body.to_commit)
    except commits.CannotRebase as e:
        raise HTTPException(409, str(e)) from e
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM branches WHERE id IN (?, ?)", (branch_id, kept))}
    return {"branch": to_branch(rows[branch_id]), "kept": to_branch(rows[kept]) if kept else None}


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
