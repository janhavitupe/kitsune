"""Visual diff between two commits, cached in the `diffs` table (M2).

    A, B ──▶ scale to analysis size ──▶ Lab ──▶ change mask ──▶ ∩ B's regions ──▶ changed regions
                                                                                 └▶ summary / message
"""

import io
import json
import logging
import sqlite3

import numpy as np
from PIL import Image

from app import storage
from app.ai import spark
from app.config import settings
from app.services import pixel_diff, region_diff, segmentation

log = logging.getLogger("kitsune.diff")

OVERLAY_RGBA = (249, 115, 22, 150)  # orange, matches the UI accent


class DiffError(ValueError):
    pass


def summarize(regions: list[dict]) -> str:
    """A plain-words message built from the measurements alone (used until Muse Spark is available)."""
    if not regions:
        return "No visible changes."
    parts = [f"the {r['label']} ({', '.join(r['hints'])})" for r in regions[:3]]
    if len(parts) > 1:
        parts[-1] = "and " + parts[-1]
    joined = ", ".join(parts) if len(parts) > 2 else " ".join(parts)
    more = f", plus {len(regions) - 3} smaller changes" if len(regions) > 3 else ""
    return f"Changed {joined}{more}."


def _commit(conn: sqlite3.Connection, commit_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT id, repo_id, blob_sha FROM commits WHERE id = ?", (commit_id,)).fetchone()
    if row is None:
        raise DiffError(f"Commit {commit_id} not found")
    return row


def _save_overlay(rel: str, change: np.ndarray) -> None:
    rgba = np.zeros((*change.shape, 4), dtype=np.uint8)
    rgba[change] = OVERLAY_RGBA
    out = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(out, format="PNG")
    path = storage.abs_path(rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(out.getvalue())


def compute(conn: sqlite3.Connection, from_id: int, to_id: int) -> dict:
    a, b = _commit(conn, from_id), _commit(conn, to_id)
    blob_a, blob_b = storage.get_blob(conn, a["blob_sha"]), storage.get_blob(conn, b["blob_sha"])
    resized = (blob_a["width"], blob_a["height"]) != (blob_b["width"], blob_b["height"])
    img_b = storage.load_rgb(conn, b["blob_sha"], settings.diff_analysis_px)
    img_a = storage.load_rgb(conn, a["blob_sha"])
    size = img_b.size  # (width, height); A is resized onto B's canvas

    lab_a = pixel_diff.to_lab(pixel_diff.to_array(img_a, size))
    lab_b = pixel_diff.to_lab(pixel_diff.to_array(img_b))
    change = pixel_diff.change_mask(lab_a, lab_b)
    regions = segmentation.load_regions(conn, b["blob_sha"], size)
    changed = [r.to_dict() for r in region_diff.analyze(lab_a, lab_b, change, regions)]

    rel = f"diffs/{from_id}_{to_id}.png"
    _save_overlay(rel, change)
    payload = {
        "regions": changed,
        "changed_fraction": round(float(change.mean()), 4),
        "resized": resized,
        "segmented": bool(regions),
        "size": list(size),
    }
    summary = summarize(changed)
    conn.execute(
        "INSERT INTO diffs (from_commit, to_commit, changed_regions_json, change_mask_path, summary)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (from_commit, to_commit) DO UPDATE SET"
        " changed_regions_json = excluded.changed_regions_json,"
        " change_mask_path = excluded.change_mask_path, summary = excluded.summary",
        (from_id, to_id, json.dumps(payload), rel, summary),
    )
    return get_cached(conn, from_id, to_id)


def get_cached(conn: sqlite3.Connection, from_id: int, to_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM diffs WHERE from_commit = ? AND to_commit = ?", (from_id, to_id)).fetchone()
    if row is None:
        return None
    return {"id": row["id"], "from_commit": from_id, "to_commit": to_id, "summary": row["summary"],
            **json.loads(row["changed_regions_json"])}


def get_or_compute(conn: sqlite3.Connection, from_id: int, to_id: int) -> dict:
    """The diff A→B, computed once. Recomputed if B gained SAM regions since it was cached."""
    if from_id == to_id:
        raise DiffError("Pick two different versions")
    a, b = _commit(conn, from_id), _commit(conn, to_id)
    if a["repo_id"] != b["repo_id"]:
        raise DiffError("Versions are from different pieces")
    hit = get_cached(conn, from_id, to_id)
    if hit and (hit["segmented"] or not segmentation.has_regions(conn, b["blob_sha"])):
        return hit
    return compute(conn, from_id, to_id)


def commit_message(conn: sqlite3.Connection, diff: dict, a_sha: str, b_sha: str) -> str:
    """Muse Spark's message, or the measured summary when Spark isn't available."""
    if not diff["regions"]:
        return diff["summary"]
    try:
        return spark.commit_message(conn, a_sha, b_sha, diff["regions"]) or diff["summary"]
    except Exception as e:  # no key, offline, rate limit, network: never fail the commit over a message
        log.info("commit message fell back to the measured summary: %s", e)
        return diff["summary"]


def diff_commit_with_parent(conn: sqlite3.Connection, commit_id: int) -> None:
    """Analysis step: diff against the parent and write the auto message."""
    c = conn.execute("SELECT id, parent_id, blob_sha FROM commits WHERE id = ?", (commit_id,)).fetchone()
    if c["parent_id"] is None:
        return
    diff = get_or_compute(conn, c["parent_id"], commit_id)
    parent_sha = _commit(conn, c["parent_id"])["blob_sha"]
    message = commit_message(conn, diff, parent_sha, c["blob_sha"])
    conn.execute("UPDATE commits SET auto_message = ? WHERE id = ?", (message, commit_id))
