"""Creating commits. Every way a version enters history (upload, cherry-pick, later merge and the
assistant) goes through create(), so parents, version numbers and branch heads stay consistent."""

import json
import sqlite3

from app import storage
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
    merge_parent_id: int | None = None,
) -> int:
    """Append a commit to a branch: parent = the branch head, then the head moves to it.

    require_head: refuse (HeadMoved) unless the branch head is still this commit. Used when the
    new image was built from that head, so it can't land on top of a newer version.
    merge_parent_id: the second parent of a merge commit (the merged branch's head).
    """
    with transaction(conn):
        # Read the head inside the write lock so two writers can't share a parent.
        head = conn.execute("SELECT head_commit_id FROM branches WHERE id = ?", (branch_id,)).fetchone()[0]
        if require_head is not None and head != require_head:
            raise HeadMoved("The branch has a newer version; open the latest one and try again")
        seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM commits WHERE repo_id = ?", (repo_id,)).fetchone()[0]
        commit_id = conn.execute(
            "INSERT INTO commits (repo_id, seq, branch_id, parent_id, merge_parent_id, blob_sha, message,"
            " origin, origin_meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (repo_id, seq, branch_id, head, merge_parent_id, blob_sha, message, origin,
             json.dumps(origin_meta) if origin_meta else None, now()),
        ).lastrowid
        conn.execute("UPDATE branches SET head_commit_id = ? WHERE id = ?", (commit_id, branch_id))
    return commit_id


class CannotDelete(ValueError):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def delete(conn: sqlite3.Connection, commit_id: int) -> None:
    """Delete a version nothing is built on: the latest one on its branch, with no later version,
    merge or other branch starting from it. Its branch goes back to the version before. Its notes
    go with it, and its image too unless another version uses the same pixels."""
    with transaction(conn):
        c = conn.execute("SELECT * FROM commits WHERE id = ?", (commit_id,)).fetchone()
        if c is None:
            raise CannotDelete(f"Commit {commit_id} not found", 404)
        v = f"v{c['seq']}"
        head = conn.execute("SELECT head_commit_id FROM branches WHERE id = ?", (c["branch_id"],)).fetchone()[0]
        if head != commit_id:
            raise CannotDelete(f"Only the latest version of a branch can be deleted; {v} has later versions")
        child = conn.execute(
            "SELECT seq FROM commits WHERE parent_id = ? OR merge_parent_id = ? ORDER BY seq LIMIT 1", (commit_id, commit_id)
        ).fetchone()
        if child:
            raise CannotDelete(f"v{child[0]} is built on {v}; delete that first")
        other = conn.execute(
            "SELECT name FROM branches WHERE head_commit_id = ? AND id != ?", (commit_id, c["branch_id"])
        ).fetchone()
        if other:
            raise CannotDelete(f"The branch '{other[0]}' starts from {v}")
        if c["analysis_status"] in ("pending", "running"):
            raise CannotDelete(f"{v} is still being analyzed; try again in a few seconds")

        files = [r[0] for r in conn.execute("SELECT audio_path FROM voice_notes WHERE commit_id = ? AND audio_path IS NOT NULL", (commit_id,))]
        conn.execute("UPDATE branches SET head_commit_id = ? WHERE id = ?", (c["parent_id"], c["branch_id"]))
        conn.execute("UPDATE merges SET base_commit = NULL WHERE base_commit = ?", (commit_id,))
        conn.execute("DELETE FROM diffs WHERE from_commit = ? OR to_commit = ?", (commit_id, commit_id))
        conn.execute("DELETE FROM voice_notes WHERE commit_id = ?", (commit_id,))
        conn.execute("DELETE FROM search_index WHERE commit_id = ?", (commit_id,))
        conn.execute("DELETE FROM commits WHERE id = ?", (commit_id,))
        if not conn.execute("SELECT 1 FROM commits WHERE blob_sha = ?", (c["blob_sha"],)).fetchone():
            for table in ("regions", "captions"):
                conn.execute(f"DELETE FROM {table} WHERE blob_sha = ?", (c["blob_sha"],))  # noqa: S608
            blob = conn.execute("SELECT path, thumb_path FROM blobs WHERE sha256 = ?", (c["blob_sha"],)).fetchone()
            files += [blob["path"], blob["thumb_path"]]
            conn.execute("DELETE FROM blobs WHERE sha256 = ?", (c["blob_sha"],))
    for rel in files:
        storage.abs_path(rel).unlink(missing_ok=True)
