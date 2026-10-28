"""Creating commits. Every way a version enters history (upload, cherry-pick, later merge and the
assistant) goes through create(), so parents, version numbers and branch heads stay consistent."""

import json
import sqlite3

from app.db import now, transaction


class HeadMoved(RuntimeError):
    """The branch moved on since the caller looked at it."""


def create(
    conn: sqlite3.Connection,
    *,
    repo_id: int,
    branch_id: int,
    blob_sha: str,
    message: str | None,
    origin: str = "upload",
    origin_meta: dict | None = None,
    require_head: int | None = None,
) -> int:
    """Append a commit to a branch: parent = the branch head, then the head moves to it.

    require_head: refuse (HeadMoved) unless the branch head is still this commit. Used when the
    new image was built from that head, so it can't land on top of a newer version.
    """
    with transaction(conn):
        # Read the head inside the write lock so two writers can't share a parent.
        head = conn.execute("SELECT head_commit_id FROM branches WHERE id = ?", (branch_id,)).fetchone()[0]
        if require_head is not None and head != require_head:
            raise HeadMoved("The branch has a newer version; open the latest one and try again")
        seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM commits WHERE repo_id = ?", (repo_id,)).fetchone()[0]
        commit_id = conn.execute(
            "INSERT INTO commits (repo_id, seq, branch_id, parent_id, blob_sha, message, origin, origin_meta_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (repo_id, seq, branch_id, head, blob_sha, message, origin,
             json.dumps(origin_meta) if origin_meta else None, now()),
        ).lastrowid
        conn.execute("UPDATE branches SET head_commit_id = ? WHERE id = ?", (commit_id, branch_id))
    return commit_id
