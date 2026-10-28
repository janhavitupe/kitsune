import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db, now, transaction
from app.routers.common import get_repo_or_404, to_branch
from app.schemas import CaptionIn, MissingCaption, Repo, RepoCreate, RepoDetail, RepoUpdate
from app.services import captions, search

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


@router.patch("/repos/{repo_id}", response_model=RepoDetail)
def update_repo(repo_id: int, body: RepoUpdate, conn: sqlite3.Connection = Depends(get_db)):
    """Rename a piece, or switch private mode (captions and search reading on open weights only)."""
    get_repo_or_404(conn, repo_id)
    if body.name is not None:
        conn.execute("UPDATE repos SET name = ? WHERE id = ?", (body.name.strip(), repo_id))
    if body.private_mode is not None:
        conn.execute("UPDATE repos SET private_mode = ? WHERE id = ?", (int(body.private_mode), repo_id))
    return _repo_detail(conn, repo_id)


@router.get("/repos/{repo_id}/captions/missing", response_model=list[MissingCaption])
def missing_captions(repo_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """Versions with no caption yet, for the Modal back-fill job."""
    get_repo_or_404(conn, repo_id)
    rows = conn.execute(
        "SELECT DISTINCT c.blob_sha FROM commits c WHERE c.repo_id = ?"
        " AND NOT EXISTS (SELECT 1 FROM captions k WHERE k.blob_sha = c.blob_sha)",
        (repo_id,),
    ).fetchall()
    return [MissingCaption(blob_sha=r[0], image_url=f"/api/blobs/{r[0]}") for r in rows]


@router.post("/blobs/{sha}/captions", status_code=201)
def add_caption(sha: str, body: CaptionIn, conn: sqlite3.Connection = Depends(get_db)):
    """Store a caption made elsewhere (the Modal back-fill job) and re-index the versions using it."""
    if not conn.execute("SELECT 1 FROM blobs WHERE sha256 = ?", (sha,)).fetchone():
        raise HTTPException(404, "Blob not found")
    captions.save(conn, sha, body.caption.strip(), body.model)
    for (commit_id,) in conn.execute("SELECT id FROM commits WHERE blob_sha = ?", (sha,)).fetchall():
        search.index_commit(conn, commit_id)
    return {"blob_sha": sha, "model": body.model}
