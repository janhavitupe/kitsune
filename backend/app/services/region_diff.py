"""Turn a change mask into named changed regions with color-change hints (M2).

Each changed pixel is credited to the smallest region that covers it (face beats figure). Change
that falls outside every region is grouped into areas named by where they sit on the canvas, so
no change is ever hidden, and the diff still reads well before SAM is connected.
"""

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from app.config import settings
from app.services.segmentation import Region

# Thresholds on mean Lab shift inside the changed pixels.
LIGHTNESS = 5.0
WARMTH = 4.0
CHROMA = 5.0
MIN_CHROMA_FOR_WARMTH = 15.0  # turning blue into white or grey is "muted", not "warmer"
# Change areas closer than this share of the image diagonal are grouped into one area.
GROUP_DISTANCE = 0.03
# The blur and closing in the change mask bleed a few pixels past a region's edge. Change this close
# to a region (share of the diagonal) is that region's bleed, not a separate area.
REGION_BLEED = 0.01
MAX_POLYGONS = 12


@dataclass
class ChangedRegion:
    label: str
    source: str  # "sam-3.1" for named regions, "change" for position-named change areas
    region_id: int | None
    changed_px: int
    changed_ratio: float  # share of the region that changed (1.0 for change areas)
    image_share: float  # share of the whole image that changed in this region
    bbox: list[float]  # x, y, w, h as fractions of the image
    hints: list[str]
    polygons: list[list[list[float]]]  # outlines as [x, y] fractions of the image

    def to_dict(self) -> dict:
        return asdict(self)


def hints(lab_a: np.ndarray, lab_b: np.ndarray, where: np.ndarray) -> list[str]:
    """Words for how the pixels in `where` changed from A to B."""
    pa, pb = lab_a[where], lab_b[where]
    d_light = float(pb[:, 0].mean() - pa[:, 0].mean())
    d_warm = float(pb[:, 2].mean() - pa[:, 2].mean())
    # Saturation per pixel, then averaged: averaging colors first would make a vivid
    # purple-to-orange gradient look grey.
    chroma_a = float(np.hypot(pa[:, 1], pa[:, 2]).mean())
    chroma_b = float(np.hypot(pb[:, 1], pb[:, 2]).mean())
    d_chroma = chroma_b - chroma_a
    out = []
    if d_light > LIGHTNESS:
        out.append("lighter")
    elif d_light < -LIGHTNESS:
        out.append("darker")
    if min(chroma_a, chroma_b) >= MIN_CHROMA_FOR_WARMTH:
        if d_warm > WARMTH:
            out.append("warmer")
        elif d_warm < -WARMTH:
            out.append("cooler")
    if d_chroma > CHROMA:
        out.append("more saturated")
    elif d_chroma < -CHROMA:
        out.append("more muted")
    return out or ["redrawn"]


def polygons(mask: np.ndarray) -> list[list[list[float]]]:
    """Simplified outer outlines of a mask, normalized to 0..1, largest first."""
    h, w = mask.shape
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:MAX_POLYGONS]:
        if cv2.contourArea(c) < settings.diff_min_component * w * h:
            continue
        pts = cv2.approxPolyDP(c, 0.003 * cv2.arcLength(c, True), True).reshape(-1, 2)
        if len(pts) >= 3:
            out.append([[round(x / w, 4), round(y / h, 4)] for x, y in pts.tolist()])
    return out


def bbox(mask: np.ndarray) -> list[float]:
    h, w = mask.shape
    x, y, bw, bh = cv2.boundingRect(mask.astype(np.uint8))
    return [round(x / w, 4), round(y / h, 4), round(bw / w, 4), round(bh / h, 4)]


def position_label(box: list[float]) -> str:
    x, y, w, h = box
    if w > 0.66 and h > 0.66:
        return "whole canvas"
    row = ("top", "", "bottom")[min(int((y + h / 2) * 3), 2)]
    col = ("left", "", "right")[min(int((x + w / 2) * 3), 2)]
    return ("-".join(p for p in (row, col) if p) or "center") + " area"


def _change_areas(leftover: np.ndarray) -> list[np.ndarray]:
    """Split leftover change into areas, grouping specks that sit close together."""
    h, w = leftover.shape
    k = max(3, int(GROUP_DISTANCE * np.hypot(w, h)) | 1)
    grouped = cv2.dilate(leftover.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, labels = cv2.connectedComponents(grouped, connectivity=8)
    min_px = settings.diff_min_component * leftover.size
    areas = [leftover & (labels == i) for i in range(1, n)]
    return [a for a in areas if a.sum() >= min_px]


def analyze(lab_a: np.ndarray, lab_b: np.ndarray, change: np.ndarray, regions: list[Region]) -> list[ChangedRegion]:
    """Changed regions of B, biggest visual change first."""
    total = change.size
    out: list[ChangedRegion] = []

    claimed = np.zeros_like(change)
    for r in sorted(regions, key=lambda r: int(r.mask.sum())):
        own = r.mask & ~claimed
        claimed |= r.mask
        size = int(own.sum())
        if not size:
            continue
        changed = change & own
        n = int(changed.sum())
        if n / size <= settings.diff_min_region_change:
            continue
        out.append(ChangedRegion(
            label=r.label, source=r.source, region_id=r.id, changed_px=n,
            changed_ratio=round(n / size, 4), image_share=round(n / total, 4),
            bbox=bbox(own), hints=hints(lab_a, lab_b, changed), polygons=polygons(own),
        ))

    if claimed.any():
        h, w = change.shape
        k = max(7, int(REGION_BLEED * np.hypot(w, h)) | 1)
        near = cv2.dilate(claimed.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    else:
        near = claimed

    labels_used: dict[str, int] = {}
    for area in _change_areas(change & ~near):
        box = bbox(area)
        label = position_label(box)
        labels_used[label] = labels_used.get(label, 0) + 1
        if labels_used[label] > 1:
            label = f"{label} {labels_used[label]}"
        n = int(area.sum())
        out.append(ChangedRegion(
            label=label, source="change", region_id=None, changed_px=n,
            changed_ratio=1.0, image_share=round(n / total, 4),
            bbox=box, hints=hints(lab_a, lab_b, area), polygons=polygons(area),
        ))

    return sorted(out, key=lambda r: r.changed_px, reverse=True)
