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
    source_sha: str | None = None,
    origin: str = "upload",
    origin_meta: dict | None = None,
    require_head: int | None = None,
    merge_parent_id: int | None = None,
) -> int:
    """Append a commit to a branch: parent = the branch head, then the head moves to it.

    require_head: refuse (HeadMoved) unless the branch head is still this commit. Used when the
    new image was built from that head, so it can't land on top of a newer version.
    merge_parent_id: the second parent of a merge commit (the merged branch's head).
    source_sha: the artist's layered file, when this version is one they saved.
    """
    with transaction(conn):
        # Read the head inside the write lock so two writers can't share a parent.
        head = conn.execute("SELECT head_commit_id FROM branches WHERE id = ?", (branch_id,)).fetchone()[0]
        if require_head is not None and head != require_head:
            raise HeadMoved("The branch has a newer version; open the latest one and try again")
        seq = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM commits WHERE repo_id = ?", (repo_id,)).fetchone()[0]
        commit_id = conn.execute(
            "INSERT INTO commits (repo_id, seq, branch_id, parent_id, merge_parent_id, blob_sha, source_sha, message,"
            " origin, origin_meta_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (repo_id, seq, branch_id, head, merge_parent_id, blob_sha, source_sha, message, origin,
             json.dumps(origin_meta) if origin_meta else None, now()),
        ).lastrowid
        conn.execute("UPDATE branches SET head_commit_id = ? WHERE id = ?", (commit_id, branch_id))
    return commit_id


class CannotRebase(ValueError):
    pass


def rebase(conn: sqlite3.Connection, branch_id: int, to_commit: int) -> int | None:
    """Make any version of the piece the branch's latest, so the next commit continues from it.

    Nothing is deleted. Versions of the branch that the new head isn't built on (everything after
    an older version, or the branch's own work when jumping to another line) move to a new branch
    named "<branch>-before-v<n>", which keeps the old head. Returns that branch's id, or None when
    every version stays reachable (moving forward along a line the branch is part of)."""
    with transaction(conn):
        br = conn.execute("SELECT * FROM branches WHERE id = ?", (branch_id,)).fetchone()
        target = conn.execute("SELECT * FROM commits WHERE id = ? AND repo_id = ?", (to_commit, br["repo_id"])).fetchone()
        if target is None:
            raise CannotRebase(f"Commit {to_commit} not found in this repo")
        v = f"v{target['seq']}"
        if br["head_commit_id"] == to_commit:
            raise CannotRebase(f"{v} is already the latest version of {br['name']}")
        built_on, todo = set(), [to_commit]  # the target and every version it's built on
        while todo:
            c = todo.pop()
            if c is None or c in built_on:
                continue
            built_on.add(c)
            todo += conn.execute("SELECT parent_id, merge_parent_id FROM commits WHERE id = ?", (c,)).fetchone()
        later, cur = [], br["head_commit_id"]
        while cur is not None and cur not in built_on:
            later.append(cur)
            cur = conn.execute("SELECT parent_id FROM commits WHERE id = ?", (cur,)).fetchone()[0]
        if not later:
            conn.execute("UPDATE branches SET head_commit_id = ? WHERE id = ?", (to_commit, branch_id))
            return None

        name, n = f"{br['name']}-before-{v}", 1
        while conn.execute("SELECT 1 FROM branches WHERE repo_id = ? AND name = ?", (br["repo_id"], name)).fetchone():
            n += 1
            name = f"{br['name']}-before-{v}-{n}"
        kept = conn.execute(
            "INSERT INTO branches (repo_id, name, head_commit_id, created_at) VALUES (?, ?, ?, ?)",
            (br["repo_id"], name, br["head_commit_id"], now()),
        ).lastrowid
        # Only versions made on this branch move lanes; ones it got from a fast-forward stay where they are.
        conn.executemany("UPDATE commits SET branch_id = ? WHERE id = ? AND branch_id = ?",
                         [(kept, c, branch_id) for c in later])
        conn.execute("UPDATE branches SET head_commit_id = ? WHERE id = ?", (to_commit, branch_id))
    return kept


class CannotDelete(ValueError):
    def __init__(self, message: str, status_code: int = 409):
        super().__init__(message)
        self.status_code = status_code


def delete(conn: sqlite3.Connection, commit_id: int) -> None:
    """Delete any version. Versions built on it are rejoined to the version before it, and branches
    that ended at it end there instead (an empty branch if it was the first). Its notes go with it,
    and its image and layered file too unless another version uses them."""
    with transaction(conn):
        files = _delete(conn, commit_id)
    for rel in files:
        storage.abs_path(rel).unlink(missing_ok=True)


def _delete(conn: sqlite3.Connection, commit_id: int) -> list[str]:
    """delete() inside the caller's transaction; returns the files to remove once it commits."""
    c = conn.execute("SELECT * FROM commits WHERE id = ?", (commit_id,)).fetchone()
    if c is None:
        raise CannotDelete(f"Commit {commit_id} not found", 404)
    parent = c["parent_id"]
    conn.execute("UPDATE commits SET parent_id = ? WHERE parent_id = ?", (parent, commit_id))
    # A merge of the deleted version now merges the one before it, unless that's already its parent.
    conn.execute("UPDATE commits SET merge_parent_id = CASE WHEN parent_id IS ? THEN NULL ELSE ? END"
                 " WHERE merge_parent_id = ?", (parent, parent, commit_id))
    conn.execute("UPDATE branches SET head_commit_id = ? WHERE head_commit_id = ?", (parent, commit_id))

    files = [r[0] for r in conn.execute("SELECT audio_path FROM voice_notes WHERE commit_id = ? AND audio_path IS NOT NULL", (commit_id,))]
    conn.execute("UPDATE merges SET base_commit = NULL WHERE base_commit = ?", (commit_id,))
    # Includes the diffs of versions that were built on it; they're recomputed against their new parent.
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
    if c["source_sha"] and not conn.execute("SELECT 1 FROM commits WHERE source_sha = ?", (c["source_sha"],)).fetchone():
        files.append(conn.execute("SELECT path FROM sources WHERE sha256 = ?", (c["source_sha"],)).fetchone()["path"])
        conn.execute("DELETE FROM sources WHERE sha256 = ?", (c["source_sha"],))
    return files


def delete_branch(conn: sqlite3.Connection, branch_id: int) -> list[int]:
    """Delete a branch and the versions only it has. Versions another branch's history still uses
    stay, moved onto that branch. Returns the version numbers deleted."""
    with transaction(conn):
        br = conn.execute("SELECT * FROM branches WHERE id = ?", (branch_id,)).fetchone()
        if br is None:
            raise CannotDelete(f"Branch {branch_id} not found", 404)
        if br["name"] == "main":
            raise CannotDelete("main can't be deleted", 400)
        others = conn.execute("SELECT id, head_commit_id FROM branches WHERE repo_id = ? AND id != ? ORDER BY name != 'main', id",
                              (br["repo_id"], branch_id)).fetchall()
        used_by = {}  # commit -> the first other branch whose history includes it
        for other in others:
            todo = [other["head_commit_id"]]
            while todo:
                c = todo.pop()
                if c is None or c in used_by:
                    continue
                used_by[c] = other["id"]
                todo += conn.execute("SELECT parent_id, merge_parent_id FROM commits WHERE id = ?", (c,)).fetchone()
        own = conn.execute("SELECT id, seq FROM commits WHERE branch_id = ? ORDER BY seq DESC", (branch_id,)).fetchall()
        deleted, files = [], []
        for c in own:
            if c["id"] in used_by:
                conn.execute("UPDATE commits SET branch_id = ? WHERE id = ?", (used_by[c["id"]], c["id"]))
            else:
                files += _delete(conn, c["id"])
                deleted.append(c["seq"])
        conn.execute("DELETE FROM merges WHERE source_branch = ? OR target_branch = ?", (branch_id, branch_id))
        conn.execute("DELETE FROM branches WHERE id = ?", (branch_id,))
    for rel in files:
        storage.abs_path(rel).unlink(missing_ok=True)
    return sorted(deleted)
