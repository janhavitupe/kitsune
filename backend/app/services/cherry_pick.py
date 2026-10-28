"""Region cherry-pick (M3): bring one changed region of an older version back into the latest one.

The region comes from the diff source → target, so it is "what changed there since then": a SAM
region ("sky") once segmentation runs, a position-named area before that.

    source ──mask──▶ feather ──α──┐
                                  ▼
    target ───────────────▶ composite ──▶ seam band ──▶ Muse Image (inside the band only) ──▶ new commit
"""

import io
import logging
import sqlite3

import numpy as np
from PIL import Image

from app import storage
from app.ai import image as ai_image
from app.services import commits, compose, diffing

log = logging.getLogger("kitsune.cherry_pick")

BLEND_MODES = ("auto", "ai", "fast")


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


def build(
    conn: sqlite3.Connection, source_id: int, target_id: int, label: str, blend: str = "fast",
    max_side: int | None = None,
) -> tuple[np.ndarray, str]:
    """The cherry-picked image as an RGB array, and the blend actually used ("ai" or "fast")."""
    if blend not in BLEND_MODES:
        raise CherryPickError(f"blend must be one of {', '.join(BLEND_MODES)}")
    if source_id == target_id:
        raise CherryPickError("Pick a region from a different version")
    source, target = _commit(conn, source_id), _commit(conn, target_id)
    if source["repo_id"] != target["repo_id"]:
        raise CherryPickError("Versions are from different pieces")

    mask_small, others_small = _region_masks(conn, source_id, target_id, label)
    tgt_img = storage.load_rgb(conn, target["blob_sha"], max_side)
    size = tgt_img.size
    tgt = np.asarray(tgt_img)
    src = np.asarray(storage.load_rgb(conn, source["blob_sha"]).resize(size, Image.Resampling.LANCZOS))

    mask = compose.resize_mask(mask_small, size)
    a = compose.alpha(mask, compose.feather_radius(tgt.shape))
    # The soft edge may only fall on pixels nothing else changed. Where it would reach into another
    # changed region (the coat next to the sky), it would bleed the old version of that region in.
    a[compose.resize_mask(others_small, size) & ~mask] = 0
    out = compose.composite(tgt, src, a)
    if blend == "fast":
        return out, "fast"

    band = compose.seam_band(a)
    box = compose.padded_bbox(band)
    if box is None:
        return out, "fast"
    x0, y0, x1, y1 = box
    try:
        patch = ai_image.blend_seam(conn, out[y0:y1, x0:x1], band[y0:y1, x0:x1])
    except Exception as e:  # no key, offline, unsupported request: fall back unless AI was demanded
        if blend == "ai":
            raise CherryPickError(f"AI seam blending is unavailable: {e}", 503) from e
        log.info("seam blend fell back to fast: %s", e)
        return out, "fast"
    return compose.paste_inside(out, patch, band, box), "ai"


def cherry_pick(conn: sqlite3.Connection, target_id: int, source_id: int, label: str, blend: str = "auto") -> int:
    """Make the cherry-pick a new commit on top of the target. The target must be its branch's latest version."""
    target = _commit(conn, target_id)
    head = conn.execute("SELECT head_commit_id FROM branches WHERE id = ?", (target["branch_id"],)).fetchone()[0]
    if head != target_id:
        raise CherryPickError("Bring regions back into the latest version of a branch", 409)

    img, used = build(conn, source_id, target_id, label, blend)
    out = io.BytesIO()
    Image.fromarray(img).save(out, format="PNG", compress_level=storage.PNG_COMPRESS_LEVEL)
    blob = storage.put_image(conn, out.getvalue())
    source = _commit(conn, source_id)
    try:
        return commits.create(
            conn,
            repo_id=target["repo_id"],
            branch_id=target["branch_id"],
            blob_sha=blob["sha256"],
            message=f"Brought back the {label} from v{source['seq']}",
            origin="cherry_pick",
            origin_meta={"source_commit": source_id, "source_seq": source["seq"], "label": label, "blend": used},
            require_head=target_id,
        )
    except commits.HeadMoved as e:
        raise CherryPickError(str(e), 409) from e
