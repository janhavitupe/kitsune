"""Compositing for cherry-pick and merge (M3): put one version's pixels into another through a
feathered mask, and find the seam band where the two meet.

Guarantee: pixels where alpha is 0 are copied from the target bit for bit, so a cherry-pick never
changes anything outside the picked region and its soft edge.
"""

import cv2
import numpy as np

FEATHER = 0.006  # feather radius as a share of the image diagonal
SEAM_PAD = 48  # context around the seam sent to the blending model, in pixels


def _disk(radius: int) -> np.ndarray:
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))


def feather_radius(shape: tuple[int, ...]) -> int:
    h, w = shape[:2]
    return max(4, int(FEATHER * np.hypot(w, h)))


def resize_mask(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Resize a bool mask to (width, height) with smooth edges."""
    if mask.shape[::-1] == size:
        return mask
    return cv2.resize(mask.astype(np.uint8) * 255, size, interpolation=cv2.INTER_LINEAR) > 127


def alpha(mask: np.ndarray, radius: int) -> np.ndarray:
    """Soft float alpha in 0..1: exactly 1 inside the mask, fading to 0 over about 2·radius px outside.

    The mask is grown by `radius` first so the blur's falloff starts outside the region: the
    picked region itself, corners included, comes over whole.
    """
    grown = cv2.dilate(mask.astype(np.uint8), _disk(radius)).astype(np.float32)
    soft = cv2.GaussianBlur(grown, (0, 0), sigmaX=radius / 3)
    return np.clip(np.maximum(soft, mask.astype(np.float32)), 0.0, 1.0)


def composite(target: np.ndarray, source: np.ndarray, a: np.ndarray) -> np.ndarray:
    """target·(1−a) + source·a for uint8 RGB images, exact where a is 0."""
    out = target.astype(np.float32) * (1 - a[..., None]) + source.astype(np.float32) * a[..., None]
    out = np.rint(out).astype(np.uint8)
    out[a == 0] = target[a == 0]
    return out


def seam_band(a: np.ndarray) -> np.ndarray:
    """Where the two versions are mixed: the ring the eye reads as a seam."""
    return (a > 0.02) & (a < 0.98)


def padded_bbox(mask: np.ndarray, pad: int = SEAM_PAD) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) around a mask plus padding, clamped to the image. None if the mask is empty."""
    if not mask.any():
        return None
    h, w = mask.shape
    x, y, bw, bh = cv2.boundingRect(mask.astype(np.uint8))
    return max(0, x - pad), max(0, y - pad), min(w, x + bw + pad), min(h, y + bh + pad)


def paste_inside(base: np.ndarray, patch: np.ndarray, band: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """Paste `patch` (covering `box`) onto `base`, but only inside `band`, softly.

    This is the guard around the blending model: whatever it returns, pixels outside the seam band
    stay exactly as they were.
    """
    x0, y0, x1, y1 = box
    band_crop = band[y0:y1, x0:x1]
    r = max(2, feather_radius(band.shape) // 2)
    soft = cv2.GaussianBlur(cv2.erode(band_crop.astype(np.uint8), _disk(r)).astype(np.float32), (0, 0), sigmaX=r / 3)
    soft = np.clip(soft, 0.0, 1.0) * band_crop
    out = base.copy()
    out[y0:y1, x0:x1] = composite(base[y0:y1, x0:x1], patch, soft)
    return out
