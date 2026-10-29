"""Region cherry-pick (M3): bring part of an older version back into the latest one.

Only the artist's own pixels move: the region is copied from the source and pasted over the target,
with a soft edge mixed from the two. Nothing is generated or repainted.

The region is either what changed between source and target there (a SAM region such as "sky" once
segmentation runs, a position-named area before that), or what the artist drew in the source version
itself. Anything drawn later on the way to the target (a lantern added to the sky) is protected.

    source ──mask──▶ minus later drawings ──▶ feather ──α──▶ composite over target ──▶ new commit
"""

import io
import sqlite3

import numpy as np
from PIL import Image

from app import storage
from app.services import blending, commits, compose, diffing


class CherryPickError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _commit(conn: sqlite3.Connection, commit_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM commits WHERE id = ?", (commit_id,)).fetchone()
    if row is None:
        raise CherryPickError(f"Commit {commit_id} not found", 404)
    return row


def _region_masks(conn: sqlite3.Connection, source_id: int, target_id: int, label: str) -> tuple[np.ndarray, np.ndarray]:
    """The picked region's mask, and the union of every other changed region (at analysis size)."""
    result = diffing.analyze(conn, source_id, target_id)
    picked = [r for r in result.regions if r.label == label]
    if not picked:
        names = ", ".join(r.label for r in result.regions) or "none"
        raise CherryPickError(f"No changed region called '{label}' between these versions (found: {names})", 404)
    others = np.zeros_like(picked[0].mask)
    for r in result.regions:
        if r.label != label:
            others |= r.mask
    return picked[0].mask, others


def _drawn_mask(conn: sqlite3.Connection, source: sqlite3.Row, label: str) -> np.ndarray:
    """What the artist drew in `source` itself (its change from its parent) under `label`."""
    if source["parent_id"] is None:
        raise CherryPickError(f"v{source['seq']} is the first version, so nothing was drawn on top of an earlier one")
    regions = diffing.analyze(conn, source["parent_id"], source["id"]).regions
    picked = [r for r in regions if r.label == label]
    if not picked:
        names = ", ".join(r.label for r in regions) or "none"
        raise CherryPickError(f"Nothing called '{label}' was drawn in v{source['seq']} (found: {names})", 404)
    return picked[0].mask


def drawn_labels(conn: sqlite3.Connection, source_id: int) -> list[str]:
    """Names of what the artist drew in this version (its own change from its parent)."""
    source = _commit(conn, source_id)
    if source["parent_id"] is None:
        return []
    return [r.label for r in diffing.analyze(conn, source["parent_id"], source_id).regions]


def _ancestors(conn: sqlite3.Connection, commit_id: int) -> set[int]:
    seen, todo = set(), [commit_id]
    while todo:
        c = todo.pop()
        if c in seen:
            continue
        seen.add(c)
        row = conn.execute("SELECT parent_id, merge_parent_id FROM commits WHERE id = ?", (c,)).fetchone()
        todo += [p for p in row if p is not None]
    return seen


MAX_LATER = 30
UNDOING = 0.5  # a later change covering this much of the picked region is the change being undone


def _later_drawings(conn: sqlite3.Connection, source_id: int, target_id: int, take: np.ndarray) -> np.ndarray:
    """Everything the artist drew after `source` on the way to `target` that isn't the change being
    undone: a lantern added to the sky later stays when the old sky comes back.

    Each version's own change (from its first parent) is a drawing; merges only bring in drawings
    already counted on their branch. A drawing that covers most of the picked region is the very
    change being undone, so it isn't protected.
    """
    later = sorted(_ancestors(conn, target_id) - _ancestors(conn, source_id))[-MAX_LATER:]
    size = take.shape[::-1]
    protect = np.zeros_like(take)
    for cid in later:
        row = conn.execute("SELECT parent_id, merge_parent_id FROM commits WHERE id = ?", (cid,)).fetchone()
        if row["parent_id"] is None or row["merge_parent_id"] is not None:
            continue
        for r in diffing.analyze(conn, row["parent_id"], cid).regions:
            m = compose.resize_mask(r.mask, size)
            if (m & take).sum() < UNDOING * take.sum():
                protect |= m
    return protect


def build(
    conn: sqlite3.Connection, source_id: int, target_id: int, label: str, drawn: bool = False,
    max_side: int | None = None,
) -> np.ndarray:
    """The cherry-picked image as an RGB array: the source's own pixels pasted into the target.

    drawn=False: `label` is a region that changed between source and target.
    drawn=True:  `label` is something the artist drew in the source version itself.
    """
    if source_id == target_id:
        raise CherryPickError("Pick a region from a different version")
    source, target = _commit(conn, source_id), _commit(conn, target_id)
    if source["repo_id"] != target["repo_id"]:
        raise CherryPickError("Versions are from different pieces")

    if drawn:
        mask_small, others_small = _drawn_mask(conn, source, label), None
    else:
        mask_small, others_small = _region_masks(conn, source_id, target_id, label)
    tgt_img = storage.load_rgb(conn, target["blob_sha"], max_side)
    size = tgt_img.size
    tgt = np.asarray(tgt_img)
    src = np.asarray(storage.load_rgb(conn, source["blob_sha"]).resize(size, Image.Resampling.LANCZOS))

    take = compose.resize_mask(mask_small, size)
    # The other changed regions are protected: the sky's soft edge must not pull the old coat in.
    protect = compose.resize_mask(others_small, size) if others_small is not None else np.zeros_like(take)
    later = _later_drawings(conn, source_id, target_id, take)
    take &= ~later  # a lantern drawn into the sky later is never pasted over
    if not take.any():
        raise CherryPickError(f"Everything in the {label} was drawn over later; nothing to bring back", 409)
    return blending.paste(tgt, src, take, protect | later)


def cherry_pick(
    conn: sqlite3.Connection, target_id: int, source_id: int, label: str, drawn: bool = False,
    branch_id: int | None = None, name: str | None = None,
) -> int:
    """Make the cherry-pick a new commit on top of the target, on the target's branch (or `branch_id`,
    e.g. the assistant's branch). The target must be that branch's latest version."""
    target = _commit(conn, target_id)
    branch_id = branch_id or target["branch_id"]
    head = conn.execute("SELECT head_commit_id FROM branches WHERE id = ?", (branch_id,)).fetchone()[0]
    if head != target_id:
        raise CherryPickError("Bring regions back into the latest version of a branch", 409)

    img = build(conn, source_id, target_id, label, drawn)
    out = io.BytesIO()
    Image.fromarray(img).save(out, format="PNG", compress_level=storage.PNG_COMPRESS_LEVEL)
    blob = storage.put_image(conn, out.getvalue())
    source = _commit(conn, source_id)
    try:
        return commits.create(
            conn,
            repo_id=target["repo_id"],
            branch_id=branch_id,
            blob_sha=blob["sha256"],
            message=f"Brought back the {name or label} from v{source['seq']}",
            origin="cherry_pick",
            origin_meta={"source_commit": source_id, "source_seq": source["seq"], "label": label, "drawn": drawn},
            require_head=target_id,
        )
    except commits.HeadMoved as e:
        raise CherryPickError(str(e), 409) from e
