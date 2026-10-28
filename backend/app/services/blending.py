"""Put pixels of one version into another through a mask, softly, optionally with Muse Image
blending the seam. Shared by cherry-pick and merge."""

import logging
import sqlite3

import numpy as np

from app.ai import image as ai_image
from app.services import compose

log = logging.getLogger("kitsune.blend")

BLEND_MODES = ("auto", "ai", "fast")


class BlendUnavailable(RuntimeError):
    """blend="ai" was asked for, but the model can't be used."""


def blend_into(
    conn: sqlite3.Connection,
    target: np.ndarray,
    source: np.ndarray,
    take: np.ndarray,
    protect: np.ndarray,
    blend: str = "auto",
) -> tuple[np.ndarray, str]:
    """`source` inside `take` over `target`. Returns the image and the blend used ("ai" or "fast").

    take:    where the source's pixels go (bool, target size)
    protect: changed areas that must stay exactly as in the target; the soft edge of `take` stops
             at them, so it can't bleed the source's version of a neighbouring change in
    """
    a = compose.alpha(take, compose.feather_radius(target.shape))
    a[protect & ~take] = 0
    out = compose.composite(target, source, a)
    if blend == "fast":
        return out, "fast"

    band = compose.seam_band(a)
    box = compose.padded_bbox(band)
    if box is None:
        return out, "fast"
    x0, y0, x1, y1 = box
    try:
        patch = ai_image.blend_seam(conn, out[y0:y1, x0:x1], band[y0:y1, x0:x1])
    except Exception as e:  # no key, offline, unsupported request
        if blend == "ai":
            raise BlendUnavailable(f"AI seam blending is unavailable: {e}") from e
        log.info("seam blend fell back to fast: %s", e)
        return out, "fast"
    return compose.paste_inside(out, patch, band, box), "ai"
