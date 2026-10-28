"""Named regions per blob: SAM 3.1 masks, post-processed and cached in the `regions` table (M2).

SAM itself lives behind app.ai.sam. Until that is wired up (it waits on the Model API probe), no
regions are stored and the diff falls back to position-named change areas ("top-left area").
"""

import io
import json
import logging
import sqlite3
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from app import storage
from app.ai import sam
from app.ai.cache import AIOffline
from app.ai.client import AIUnavailable
from app.config import settings

log = logging.getLogger("kitsune.segmentation")

# Text prompts sent to SAM, one per label.
VOCABULARY = [
    "sky", "background", "foreground", "figure", "face", "hair", "eyes", "hands", "clothing",
    "building", "tree", "water", "ground", "light source", "shadow", "text",
]
SAME_LABEL_IOU = 0.8


@dataclass
class RawMask:
    label: str
    mask: np.ndarray  # bool, H×W at blob resolution
    score: float = 1.0


@dataclass
class Region:
    id: int
    label: str
    mask: np.ndarray  # bool, at the size requested from load_regions
    source: str


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum() / union) if union else 0.0


def _center_x(mask: np.ndarray) -> float:
    return float(np.nonzero(mask)[1].mean() / mask.shape[1])


def postprocess(raw: list[RawMask]) -> list[RawMask]:
    """Drop confetti, merge duplicate masks of one label, and tell figures apart by position."""
    if not raw:
        return []
    min_px = settings.region_min_area * raw[0].mask.size
    kept: list[RawMask] = []
    for m in sorted(raw, key=lambda m: m.score, reverse=True):
        if m.mask.sum() < min_px:
            continue
        if any(k.label == m.label and _iou(k.mask, m.mask) > SAME_LABEL_IOU for k in kept):
            continue
        kept.append(m)

    figures = sorted((m for m in kept if m.label == "figure"), key=lambda m: _center_x(m.mask))
    if len(figures) > 1:
        seen: dict[str, int] = {}
        for f in figures:
            side = ("left", "center", "right")[min(int(_center_x(f.mask) * 3), 2)]
            seen[side] = seen.get(side, 0) + 1
            f.label = f"{side} figure" + (f" {seen[side]}" if seen[side] > 1 else "")
    return kept


def has_regions(conn: sqlite3.Connection, sha: str) -> bool:
    return conn.execute("SELECT 1 FROM regions WHERE blob_sha = ? LIMIT 1", (sha,)).fetchone() is not None


def save_regions(conn: sqlite3.Connection, sha: str, masks: list[RawMask], source: str) -> None:
    for i, m in enumerate(masks):
        rel = f"masks/{sha}/{i:02d}.png"
        path = storage.abs_path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        out = io.BytesIO()
        Image.fromarray(m.mask.astype(np.uint8) * 255).convert("1").save(out, format="PNG")
        path.write_bytes(out.getvalue())
        x, y, w, h = cv2.boundingRect(m.mask.astype(np.uint8))
        conn.execute(
            "INSERT INTO regions (blob_sha, label, mask_path, bbox_json, area_px, score, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (sha, m.label, rel, json.dumps([x, y, w, h]), int(m.mask.sum()), m.score, source),
        )


def load_regions(conn: sqlite3.Connection, sha: str, size: tuple[int, int]) -> list[Region]:
    """Stored regions of a blob with masks resized to (width, height)."""
    rows = conn.execute("SELECT * FROM regions WHERE blob_sha = ? ORDER BY id", (sha,)).fetchall()
    regions = []
    for r in rows:
        with Image.open(storage.abs_path(r["mask_path"])) as img:
            mask = img.convert("L").resize(size, Image.Resampling.NEAREST)
        regions.append(Region(r["id"], r["label"], np.asarray(mask) > 127, r["source"]))
    return regions


def segment_blob(conn: sqlite3.Connection, sha: str) -> None:
    """Run SAM on a blob once. Quietly does nothing while SAM is unavailable."""
    if has_regions(conn, sha):
        return
    try:
        raw = sam.segment(conn, sha, VOCABULARY)
    except (AIUnavailable, AIOffline) as e:
        log.info("segmentation skipped for %s: %s", sha[:12], e)
        return
    save_regions(conn, sha, postprocess(raw), source="sam-3.1")


def segment_commit(conn: sqlite3.Connection, commit_id: int) -> None:
    """Analysis step: segment the commit's image."""
    row = conn.execute("SELECT blob_sha FROM commits WHERE id = ?", (commit_id,)).fetchone()
    segment_blob(conn, row["blob_sha"])
