"""Compositing for cherry-pick and merge (M3): put one version's pixels into another through a
feathered mask. Only the artist's pixels are used; nothing is generated.

Guarantee: pixels where alpha is 0 are copied from the target bit for bit, so a cherry-pick never
changes anything outside the picked region and its soft edge.
"""

import cv2
import numpy as np

FEATHER = 0.006  # feather radius as a share of the image diagonal


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
