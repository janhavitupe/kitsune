import json
import sqlite3

from fastapi import HTTPException

from app.schemas import Branch, Commit

COMMIT_SELECT = """
SELECT c.*, b.name AS branch, bl.width, bl.height
FROM commits c
JOIN branches b ON b.id = c.branch_id
JOIN blobs bl ON bl.sha256 = c.blob_sha
"""


def get_repo_or_404(conn: sqlite3.Connection, repo_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM repos WHERE id = ?", (repo_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"Repo {repo_id} not found")
    return row


def to_branch(row: sqlite3.Row) -> Branch:
    return Branch(**dict(row))


def to_commit(row: sqlite3.Row) -> Commit:
    d = dict(row)
    meta = d.pop("origin_meta_json")
    sha = d["blob_sha"]
    return Commit(
        **d,
        origin_meta=json.loads(meta) if meta else None,
        image_url=f"/api/blobs/{sha}",
        thumb_url=f"/api/blobs/{sha}/thumb",
    )


def get_commit_or_404(conn: sqlite3.Connection, commit_id: int) -> Commit:
    row = conn.execute(COMMIT_SELECT + " WHERE c.id = ?", (commit_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"Commit {commit_id} not found")
    return to_commit(row)
