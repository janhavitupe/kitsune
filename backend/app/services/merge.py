"""Merging one branch into another, region by region (M3).

             base (common ancestor)
            ╱                      ╲
     diff  ╱                        ╲  diff
          X (source head)            Y (target head)
       {sky, coat}               {coat, ground}

    sky:    changed on X only  → taken from X automatically
    ground: changed on Y only  → stays as in Y
    coat:   changed on both    → conflict, the artist picks (unless both made the same change)

Planning stores the decision in `merges`; resolving rebuilds the masks (the diff is
deterministic) and writes a merge commit with two parents. If the target hasn't changed since
the branch split off, the merge commit simply carries the source's image.
"""

import io
import json
import sqlite3
from dataclasses import dataclass

import numpy as np
from PIL import Image

from app import storage
from app.services import blending, commits, compose, diffing, pixel_diff
from app.services.graph import common_ancestor
from app.services.region_diff import ChangedRegion

OVERLAP = 0.1  # two changes collide when they share this much of the smaller one
AGREE_DELTA_E = 4.0  # both sides changed an area but ended up looking the same: not a conflict


class MergeError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Conflict:
    change: ChangedRegion  # the source's change
    take: np.ndarray  # the source change plus the target changes it collides with
    target_labels: list[str]


@dataclass
class Classification:
    auto: list[ChangedRegion]  # source-only changes, taken automatically
    conflicts: list[Conflict]
    protect: np.ndarray  # every change on either side, so soft edges don't cross into them
    size: tuple[int, int]  # (width, height) the masks are at


def _branch(conn: sqlite3.Connection, repo_id: int, name: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM branches WHERE repo_id = ? AND name = ?", (repo_id, name)).fetchone()
    if row is None:
        raise MergeError(f"Branch '{name}' not found", 404)
    if row["head_commit_id"] is None:
        raise MergeError(f"Branch '{name}' has no versions yet")
    return row


def _blob_sha(conn: sqlite3.Connection, commit_id: int) -> str:
    return conn.execute("SELECT blob_sha FROM commits WHERE id = ?", (commit_id,)).fetchone()[0]


def _resized(regions: list[ChangedRegion], size: tuple[int, int]) -> list[ChangedRegion]:
    for r in regions:
        r.mask = compose.resize_mask(r.mask, size)
    return regions


def classify(conn: sqlite3.Connection, base: int, source_head: int, target_head: int) -> Classification:
    target_diff = diffing.analyze(conn, base, target_head)
    size = target_diff.size
    theirs = _resized(diffing.analyze(conn, base, source_head).regions, size)
    ours = target_diff.regions

    lab_x = pixel_diff.to_lab(pixel_diff.to_array(storage.load_rgb(conn, _blob_sha(conn, source_head)), size))
    lab_y = pixel_diff.to_lab(pixel_diff.to_array(storage.load_rgb(conn, _blob_sha(conn, target_head)), size))

    protect = np.zeros(size[::-1], dtype=bool)
    for r in theirs + ours:
        protect |= r.mask

    auto, conflicts = [], []
    for rx in theirs:
        hits = [
            ry for ry in ours
            if (rx.mask & ry.mask).sum() > OVERLAP * min(rx.mask.sum(), ry.mask.sum())
        ]
        if not hits:
            auto.append(rx)
            continue
        take = rx.mask.copy()
        for ry in hits:
            take |= ry.mask
        if np.linalg.norm(lab_x[take] - lab_y[take], axis=1).mean() < AGREE_DELTA_E:
            continue  # both made the same change
        conflicts.append(Conflict(rx, take, [ry.label for ry in hits]))
    return Classification(auto, conflicts, protect, size)


def _summary(r: ChangedRegion) -> dict:
    return {"label": r.label, "bbox": r.bbox, "hints": r.hints}


def plan(conn: sqlite3.Connection, repo_id: int, source: str, target: str) -> int:
    """Work out what merging `source` into `target` would do, and store it as an open merge."""
    if source == target:
        raise MergeError("Pick two different branches")
    src, tgt = _branch(conn, repo_id, source), _branch(conn, repo_id, target)
    x, y = src["head_commit_id"], tgt["head_commit_id"]
    base = common_ancestor(conn, x, y)
    if base is None:
        raise MergeError("These branches share no history")
    if base == x:
        raise MergeError(f"'{target}' already has everything from '{source}'")

    fast_forward = base == y
    if fast_forward:
        auto, conflicts = [_summary(r) for r in diffing.analyze(conn, y, x).regions], []
    else:
        c = classify(conn, base, x, y)
        auto = [_summary(r) for r in c.auto]
        conflicts = [
            {"index": i, **_summary(k.change), "target_labels": k.target_labels} for i, k in enumerate(c.conflicts)
        ]

    data = {
        "source": source, "target": target, "source_head": x, "target_head": y, "base": base,
        "fast_forward": fast_forward, "auto": auto, "conflicts": conflicts,
    }
    return conn.execute(
        "INSERT INTO merges (repo_id, source_branch, target_branch, base_commit, plan_json, status)"
        " VALUES (?, ?, ?, ?, ?, 'open')",
        (repo_id, src["id"], tgt["id"], base, json.dumps(data)),
    ).lastrowid


def get(conn: sqlite3.Connection, merge_id: int) -> dict:
    row = conn.execute("SELECT * FROM merges WHERE id = ?", (merge_id,)).fetchone()
    if row is None:
        raise MergeError(f"Merge {merge_id} not found", 404)
    return {"id": row["id"], "repo_id": row["repo_id"], "status": row["status"], **json.loads(row["plan_json"])}


def _message(p: dict, taken: list[str]) -> str:
    msg = f"Merged {p['source']} into {p['target']}"
    if taken:
        msg += ": took the " + ", the ".join(taken)
    return msg


def resolve(conn: sqlite3.Connection, merge_id: int, choices: dict[int, str]) -> int:
    """Write the merge commit. choices: conflict index → "source" | "target" (default "target")."""
    p = get(conn, merge_id)
    if p["status"] != "open":
        raise MergeError(f"This merge is already {p['status']}", 409)
    if bad := {v for v in choices.values()} - {"source", "target"}:
        raise MergeError(f"Choices must be 'source' or 'target', not {', '.join(sorted(bad))}")
    if unknown := set(choices) - {c["index"] for c in p["conflicts"]}:
        raise MergeError(f"No conflict number {', '.join(map(str, sorted(unknown)))}")

    tgt = _branch(conn, p["repo_id"], p["target"])
    src = _branch(conn, p["repo_id"], p["source"])
    if (src["head_commit_id"], tgt["head_commit_id"]) != (p["source_head"], p["target_head"]):
        conn.execute("UPDATE merges SET status = 'aborted' WHERE id = ?", (merge_id,))
        raise MergeError("A branch got a new version since this merge was checked; check it again", 409)

    x, y = p["source_head"], p["target_head"]
    taken = [a["label"] for a in p["auto"]]
    meta = {"source_branch": p["source"], "source_head": x, "base": p["base"], "merge_id": merge_id}
    if p["fast_forward"]:
        blob_sha = _blob_sha(conn, x)
    else:
        c = classify(conn, p["base"], x, y)
        take = np.zeros(c.size[::-1], dtype=bool)
        for r in c.auto:
            take |= r.mask
        for i, k in enumerate(c.conflicts):
            if choices.get(i, "target") == "source":
                take |= k.take
                taken.append(k.change.label)
        tgt_img = storage.load_rgb(conn, _blob_sha(conn, y))
        full = tgt_img.size
        src_img = storage.load_rgb(conn, _blob_sha(conn, x)).resize(full, Image.Resampling.LANCZOS)
        img = blending.paste(
            np.asarray(tgt_img), np.asarray(src_img), compose.resize_mask(take, full), compose.resize_mask(c.protect, full),
        )
        out = io.BytesIO()
        Image.fromarray(img).save(out, format="PNG", compress_level=storage.PNG_COMPRESS_LEVEL)
        blob_sha = storage.put_image(conn, out.getvalue())["sha256"]

    try:
        commit_id = commits.create(
            conn,
            repo_id=p["repo_id"],
            branch_id=tgt["id"],
            blob_sha=blob_sha,
            message=_message(p, taken),
            origin="merge",
            origin_meta={**meta, "taken": taken},
            require_head=y,
            merge_parent_id=x,
        )
    except commits.HeadMoved as e:
        raise MergeError(str(e), 409) from e
    conn.execute("UPDATE merges SET status = 'resolved' WHERE id = ?", (merge_id,))
    return commit_id


def abort(conn: sqlite3.Connection, merge_id: int) -> None:
    p = get(conn, merge_id)
    if p["status"] == "open":
        conn.execute("UPDATE merges SET status = 'aborted' WHERE id = ?", (merge_id,))
