import sqlite3

from fastapi import APIRouter, Depends

from app.db import get_db, now, transaction
from app.routers.common import get_repo_or_404, to_branch
from app.schemas import Repo, RepoCreate, RepoDetail

router = APIRouter(tags=["repos"])


def _repo_detail(conn: sqlite3.Connection, repo_id: int) -> RepoDetail:
    repo = get_repo_or_404(conn, repo_id)
    branches = conn.execute(
        "SELECT * FROM branches WHERE repo_id = ? ORDER BY id", (repo_id,)
    ).fetchall()
    return RepoDetail(**dict(repo), branches=[to_branch(b) for b in branches])


@router.post("/repos", status_code=201, response_model=RepoDetail)
def create_repo(body: RepoCreate, conn: sqlite3.Connection = Depends(get_db)):
    ts = now()
    with transaction(conn):
        repo_id = conn.execute(
            "INSERT INTO repos (name, created_at) VALUES (?, ?)", (body.name.strip(), ts)
        ).lastrowid
        conn.execute(
            "INSERT INTO branches (repo_id, name, created_at) VALUES (?, 'main', ?)",
            (repo_id, ts),
        )
    return _repo_detail(conn, repo_id)


@router.get("/repos", response_model=list[Repo])
def list_repos(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute("SELECT * FROM repos ORDER BY id DESC").fetchall()
    return [Repo(**dict(r)) for r in rows]


@router.get("/repos/{repo_id}", response_model=RepoDetail)
def get_repo(repo_id: int, conn: sqlite3.Connection = Depends(get_db)):
    return _repo_detail(conn, repo_id)
