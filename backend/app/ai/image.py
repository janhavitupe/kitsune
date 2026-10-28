"""Muse Image: targeted edits (seam blending now; explore variants in M4).

The request shape is a guess at an OpenAI-style image edit, where the mask's transparent pixels
mark what may change. Confirm it with scripts/probe_model_api.py once the key is in. Callers never
trust the result outside the area they asked to change (see compose.paste_inside).
"""

import base64
import hashlib
import io
import sqlite3

import numpy as np
from PIL import Image

from app.ai import prompts
from app.ai.cache import cached
from app.ai.client import model_api
from app.config import settings


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def blend_seam(conn: sqlite3.Connection, crop: np.ndarray, band: np.ndarray) -> np.ndarray:
    """Ask Muse Image to blend the seam inside `band` of an RGB crop. Returns an RGB crop of the same size."""
    crop_png = _png(Image.fromarray(crop))
    # Edit mask: transparent where the model may paint (the seam), opaque elsewhere.
    mask = np.full((*band.shape, 4), 255, dtype=np.uint8)
    mask[band, 3] = 0
    mask_png = _png(Image.fromarray(mask, "RGBA"))
    inputs = {
        "task": "blend_seam",
        "v": prompts.BLEND_SEAM_VERSION,
        "crop": hashlib.sha256(crop_png).hexdigest(),
        "mask": hashlib.sha256(mask_png).hexdigest(),
    }

    def call() -> dict:
        r = model_api().images.edit(
            model=settings.image_model,
            image=("crop.png", crop_png, "image/png"),
            mask=("mask.png", mask_png, "image/png"),
            prompt=prompts.BLEND_SEAM,
        )
        return {"png_b64": r.data[0].b64_json}

    return _decode(cached(conn, settings.image_model, inputs, call)["png_b64"], crop.shape)


def _decode(png_b64: str, shape: tuple[int, ...]) -> np.ndarray:
    out = Image.open(io.BytesIO(base64.b64decode(png_b64))).convert("RGB")
    if out.size != (shape[1], shape[0]):
        out = out.resize((shape[1], shape[0]), Image.Resampling.LANCZOS)
    return np.asarray(out)


def recolor(conn: sqlite3.Connection, img: np.ndarray, sha: str, direction: str) -> np.ndarray:
    """Muse Image's take on `img` (the blob `sha`) in another palette, same size as the input."""
    inputs = {"task": "recolor", "v": prompts.EXPLORE_VERSION, "blob": sha, "direction": direction}

    def call() -> dict:
        r = model_api().images.edit(
            model=settings.image_model,
            image=("art.png", _png(Image.fromarray(img)), "image/png"),
            prompt=prompts.EXPLORE_EDIT.format(direction=direction),
        )
        return {"png_b64": r.data[0].b64_json}

    return _decode(cached(conn, settings.image_model, inputs, call)["png_b64"], img.shape)
