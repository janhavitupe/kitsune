"""Commit graph queries: ancestry and common ancestors (used by merge in M3)."""

import sqlite3
from collections import deque

Parents = dict[int, tuple[int | None, int | None]]


def _load(conn: sqlite3.Connection, commit_id: int) -> tuple[Parents, dict[int, int]] | None:
    """Load the parent links and seq numbers for the commit's whole repo in one query."""
    row = conn.execute("SELECT repo_id FROM commits WHERE id = ?", (commit_id,)).fetchone()
    if row is None:
        return None
    rows = conn.execute(
        "SELECT id, seq, parent_id, merge_parent_id FROM commits WHERE repo_id = ?", (row["repo_id"],)
    ).fetchall()
    parents = {r["id"]: (r["parent_id"], r["merge_parent_id"]) for r in rows}
    seqs = {r["id"]: r["seq"] for r in rows}
    return parents, seqs


def _walk(parents: Parents, start: int) -> set[int]:
    seen = {start}
    queue = deque([start])
    while queue:
        for p in parents.get(queue.popleft(), (None, None)):
            if p is not None and p not in seen:
                seen.add(p)
                queue.append(p)
    return seen


def ancestors(conn: sqlite3.Connection, commit_id: int) -> set[int]:
    """The commit itself plus every commit reachable through parent and merge-parent links."""
    loaded = _load(conn, commit_id)
    if loaded is None:
        return set()
    return _walk(loaded[0], commit_id)


def common_ancestor(conn: sqlite3.Connection, a: int, b: int) -> int | None:
    """The nearest shared ancestor of two commits (either may be the ancestor itself).

    A child always has a higher seq than its parents, so the common ancestor with the highest
    seq can't be an ancestor of any other common ancestor: it is a lowest common ancestor.
    """
    loaded = _load(conn, a)
    if loaded is None:
        return None
    parents, seqs = loaded
    if b not in parents:
        return None  # different repos, or b doesn't exist
    common = _walk(parents, a) & _walk(parents, b)
    return max(common, key=seqs.__getitem__) if common else None
