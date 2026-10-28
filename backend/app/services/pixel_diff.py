"""Per-pixel change mask between two versions (M2).

Works in CIE Lab so that "changed" means "looks different" rather than "numbers differ":
the Lab distance between two pixels is an approximation of ΔE, the perceived color difference.
"""

import cv2
import numpy as np
from PIL import Image

from app.config import settings


def to_array(img: Image.Image, size: tuple[int, int] | None = None) -> np.ndarray:
    """RGB uint8 array, resized to (width, height) if given."""
    if size is not None and img.size != size:
        img = img.resize(size, Image.Resampling.LANCZOS)
    return np.asarray(img.convert("RGB"))


def to_lab(rgb: np.ndarray) -> np.ndarray:
    """float32 Lab: L in 0..100, a and b roughly -127..127."""
    return cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def drop_small(mask: np.ndarray, min_fraction: float) -> np.ndarray:
    """Remove connected parts smaller than min_fraction of the image. Returns a bool mask."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_fraction * mask.size
    return keep[labels]


def change_mask(lab_a: np.ndarray, lab_b: np.ndarray) -> np.ndarray:
    """Bool mask of pixels that visibly changed between two same-sized Lab images."""
    delta = np.linalg.norm(lab_a - lab_b, axis=2)
    delta = cv2.GaussianBlur(delta, (5, 5), 0)
    mask = (delta > settings.diff_delta_e).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    return drop_small(mask, settings.diff_min_component)
