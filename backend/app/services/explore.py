"""Explore branches (M4): "try 3 palettes for this" makes three preview branches off a version.

Each direction is a fixed color shift of the artist's own pixels (like an adjustment layer). Nothing
is generated or repainted: every line and shape stays exactly as drawn.
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
from app.ai import spark
from app.db import now
from app.services import commits

log = logging.getLogger("kitsune.explore")

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


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "variant"


def _branch_name(conn: sqlite3.Connection, repo_id: int, direction: str) -> str:
    base = f"explore/{slug(direction)}"
    name, n = base, 1
    while conn.execute("SELECT 1 FROM branches WHERE repo_id = ? AND name = ?", (repo_id, name)).fetchone():
        n += 1
        name = f"{base}-{n}"
    return name


def _brighter(lab: np.ndarray) -> np.ndarray:
    out = lab.copy()
    out[..., 0] = np.clip(out[..., 0] * 1.08 + 6, 0, 100)
    return out


def _darker(lab: np.ndarray) -> np.ndarray:
    out = lab.copy()
    out[..., 0] *= 0.85
    return out


PRESET_WORDS: list[tuple[tuple[str, ...], Callable[[np.ndarray], np.ndarray]]] = [
    (("warm", "golden", "sunset", "dusk", "sunny", "orange"), _golden_hour),
    (("cool", "cold", "moon", "night", "blue", "icy"), _moonlit),
    (("muted", "overcast", "desaturat", "grey", "gray", "foggy", "soft"), _overcast),
    (("bright", "lighter", "lighten"), _brighter),
    (("dark", "dim", "mood"), _darker),
]


def preset_for(direction: str) -> Callable[[np.ndarray], np.ndarray] | None:
    """The preset closest to a free-text direction ("warm it to match" → golden hour), if any."""
    d = direction.lower()
    return next((t for words, t in PRESET_WORDS if any(w in d for w in words)), None)


PRESET_HINT = "warm, cool, muted, brighter or darker"


def render(img: np.ndarray, direction: str) -> np.ndarray:
    """`img` with its colors shifted toward `direction` (the closest preset)."""
    transform = preset_for(direction)
    if transform is None:
        raise ExploreError(f"Explore only shifts the colors you painted; try {PRESET_HINT} instead of '{direction}'")
    return _rgb(transform(_lab(img)))


def save(conn: sqlite3.Connection, img: np.ndarray) -> str:
    out = io.BytesIO()
    Image.fromarray(img).save(out, format="PNG", compress_level=storage.PNG_COMPRESS_LEVEL)
    return storage.put_image(conn, out.getvalue())["sha256"]


def branch_variant(
    conn: sqlite3.Connection, source: sqlite3.Row, direction: str, img: np.ndarray, origin: str = "explore",
) -> int:
    """Put a rendered variant of `source` on a new explore branch. Returns the commit id."""
    branch_id = conn.execute(
        "INSERT INTO branches (repo_id, name, head_commit_id, kind, created_at) VALUES (?, ?, ?, 'explore', ?)",
        (source["repo_id"], _branch_name(conn, source["repo_id"], direction), source["id"], now()),
    ).lastrowid
    return commits.create(
        conn,
        repo_id=source["repo_id"],
        branch_id=branch_id,
        blob_sha=save(conn, img),
        message=f"Explore: {direction} palette",
        origin=origin,
        origin_meta={"source_commit": source["id"], "direction": direction},
    )


def _directions(conn: sqlite3.Connection, prompt: str) -> list[str]:
    """Up to three directions from a request ("try 3 palettes for a stormy mood") that a preset covers.
    Muse Spark reads the request when available; the request's own words are always tried too."""
    try:
        asked = spark.explore_directions(conn, prompt)
    except Exception as e:
        log.info("reading the explore request without Muse Spark: %s", e)
        asked = []
    asked += [part for part in re.split(r",|\band\b|\bor\b", prompt) if part.strip()]
    seen, out = set(), []
    for d in asked:
        t = preset_for(d)
        if t is not None and t not in seen:
            seen.add(t)
            out.append(d.strip())
    return out[:3]


def explore(conn: sqlite3.Connection, commit_id: int, prompt: str | None = None) -> list[int]:
    """Explore branches off `commit_id`, one commit each. Returns the new commit ids."""
    source = conn.execute("SELECT * FROM commits WHERE id = ?", (commit_id,)).fetchone()
    if source is None:
        raise ExploreError(f"Commit {commit_id} not found", 404)

    if prompt and prompt.strip():
        directions = _directions(conn, prompt.strip())
        if not directions:
            raise ExploreError(f"Explore only shifts the colors you painted; try {PRESET_HINT}")
    else:
        directions = [d for d, _ in PRESETS]

    img = np.asarray(storage.load_rgb(conn, source["blob_sha"]))
    # Render all of them before writing anything, so a failure leaves no half-made set of branches.
    rendered = [(d, render(img, d)) for d in directions]
    return [branch_variant(conn, source, d, variant) for d, variant in rendered]
