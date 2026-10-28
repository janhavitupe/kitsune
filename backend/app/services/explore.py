"""Explore branches (M4): "try 3 palettes for this" makes three preview branches off a version.

Each direction is painted by Muse Image when available, else by a fixed color-space transform
(the three presets only). Either way only color changes: the result keeps the original's
lightness detail, so composition and linework can't drift.
"""

import io
import logging
import re
import sqlite3
from collections.abc import Callable

import cv2
import numpy as np
from PIL import Image

from app import storage
from app.ai import image as ai_image
from app.ai import spark
from app.db import now
from app.services import commits

log = logging.getLogger("kitsune.explore")

MODES = ("auto", "ai", "fast")


class ExploreError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def _rgb(lab: np.ndarray) -> np.ndarray:
    return np.clip(cv2.cvtColor(lab, cv2.COLOR_LAB2RGB) * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _golden_hour(lab: np.ndarray) -> np.ndarray:
    out = lab.copy()
    out[..., 0] = np.clip(out[..., 0] * 1.03 + 3, 0, 100)
    out[..., 1] += 6
    out[..., 2] += 24
    return out


def _moonlit(lab: np.ndarray) -> np.ndarray:
    out = lab.copy()
    out[..., 0] *= 0.78
    out[..., 1] = out[..., 1] * 0.7 - 2
    out[..., 2] = out[..., 2] * 0.6 - 22
    return out


def _overcast(lab: np.ndarray) -> np.ndarray:
    out = lab.copy()
    out[..., 0] = out[..., 0] * 0.9 + 6
    out[..., 1:] *= 0.4
    return out


PRESETS: list[tuple[str, Callable[[np.ndarray], np.ndarray]]] = [
    ("warm golden hour", _golden_hour),
    ("cool moonlit night", _moonlit),
    ("muted overcast", _overcast),
]


def keep_composition(original: np.ndarray, variant: np.ndarray) -> np.ndarray:
    """The variant's colors on the original's structure: its overall light, the original's detail.

    Lightness = variant's lightness at a coarse scale + the original's fine detail, so a model that
    redraws a hand or moves a line can't change the drawing, only its color and light.
    """
    lo, lv = _lab(original), _lab(variant)
    sigma = max(2.0, 0.01 * float(np.hypot(*original.shape[:2])))
    blur = lambda ch: cv2.GaussianBlur(ch, (0, 0), sigma)  # noqa: E731
    out = lv.copy()
    out[..., 0] = np.clip(blur(lv[..., 0]) + (lo[..., 0] - blur(lo[..., 0])), 0, 100)
    out[..., 1] = blur(lv[..., 1])
    out[..., 2] = blur(lv[..., 2])
    return _rgb(out)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "variant"


def _branch_name(conn: sqlite3.Connection, repo_id: int, direction: str) -> str:
    base = f"explore/{slug(direction)}"
    name, n = base, 1
    while conn.execute("SELECT 1 FROM branches WHERE repo_id = ? AND name = ?", (repo_id, name)).fetchone():
        n += 1
        name = f"{base}-{n}"
    return name


def _variant(conn: sqlite3.Connection, img: np.ndarray, sha: str, direction: str, transform, mode: str) -> tuple[np.ndarray, str]:
    if mode != "fast":
        try:
            return keep_composition(img, ai_image.recolor(conn, img, sha, direction)), "ai"
        except Exception as e:
            if mode == "ai" or transform is None:
                raise ExploreError(f"Muse Image is unavailable: {e}", 503) from e
            log.info("explore '%s' fell back to the preset transform: %s", direction, e)
    return _rgb(transform(_lab(img))), "fast"


def explore(conn: sqlite3.Connection, commit_id: int, prompt: str | None = None, mode: str = "auto") -> list[int]:
    """Three explore branches off `commit_id`, one commit each. Returns the new commit ids."""
    if mode not in MODES:
        raise ExploreError(f"mode must be one of {', '.join(MODES)}")
    source = conn.execute("SELECT * FROM commits WHERE id = ?", (commit_id,)).fetchone()
    if source is None:
        raise ExploreError(f"Commit {commit_id} not found", 404)

    if prompt and prompt.strip():
        if mode == "fast":
            raise ExploreError("Custom directions need Muse Image; leave the prompt empty for the presets")
        try:
            directions = [(d, None) for d in spark.explore_directions(conn, prompt.strip())]
        except Exception as e:
            raise ExploreError(f"Muse Spark is unavailable to read the request: {e}", 503) from e
    else:
        directions = PRESETS

    img = np.asarray(storage.load_rgb(conn, source["blob_sha"]))
    rendered = [(d, *_variant(conn, img, source["blob_sha"], d, t, mode)) for d, t in directions]

    ids = []
    for direction, variant, used in rendered:
        out = io.BytesIO()
        Image.fromarray(variant).save(out, format="PNG", compress_level=storage.PNG_COMPRESS_LEVEL)
        blob = storage.put_image(conn, out.getvalue())
        branch_id = conn.execute(
            "INSERT INTO branches (repo_id, name, head_commit_id, kind, created_at) VALUES (?, ?, ?, 'explore', ?)",
            (source["repo_id"], _branch_name(conn, source["repo_id"], direction), commit_id, now()),
        ).lastrowid
        ids.append(commits.create(
            conn,
            repo_id=source["repo_id"],
            branch_id=branch_id,
            blob_sha=blob["sha256"],
            message=f"Explore: {direction} palette",
            origin="explore",
            origin_meta={"source_commit": commit_id, "direction": direction, "method": used},
        ))
    return ids
