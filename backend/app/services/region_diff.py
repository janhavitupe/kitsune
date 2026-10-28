"""Turn a change mask into named changed regions with color-change hints (M2).

Each changed pixel is credited to the smallest region that covers it (face beats figure). Change
that falls outside every region is grouped into areas named by where they sit on the canvas, so
no change is ever hidden, and the diff still reads well before SAM is connected.
"""

from dataclasses import dataclass, field, fields

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
# Splitting change by kind: up to this many kinds of color shift, merged when their directions in
# Lab are within about 35° of each other.
MAX_KINDS = 4
SAME_KIND_COS = 0.82
KMEANS_SAMPLE = 20000
# Two kinds that meet are one change if pixels BOUNDARY_STEP px apart across their boundary differ
# by less than SMOOTH_JUMP (Lab) on average: a gradient, not an edge.
BOUNDARY_STEP = 4
SMOOTH_JUMP = 15.0
MIN_BOUNDARY_PX = 20


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
    # Exact pixels at analysis size, for cherry-pick. Not stored or sent: polygons are for display.
    mask: np.ndarray | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "mask"}


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


def core_bbox(mask: np.ndarray) -> list[float]:
    """Like bbox, but over the 2nd–98th percentile of the mask's pixels, so a few stray edge pixels
    can't stretch "top area" into "whole canvas"."""
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    x0, x1 = np.percentile(xs, [2, 98])
    y0, y1 = np.percentile(ys, [2, 98])
    return [x0 / w, y0 / h, (x1 - x0 + 1) / w, (y1 - y0 + 1) / h]


def position_label(box: list[float]) -> str:
    x, y, w, h = box
    if w > 0.66 and h > 0.66:
        return "whole canvas"
    row = ("top", "", "bottom")[min(int((y + h / 2) * 3), 2)]
    col = ("left", "", "right")[min(int((x + w / 2) * 3), 2)]
    return ("-".join(p for p in (row, col) if p) or "center") + " area"


def _by_kind_of_change(lab_a: np.ndarray, lab_b: np.ndarray, where: np.ndarray) -> list[np.ndarray]:
    """Split changed pixels by how they changed (their Lab shift), so a warmed sky and a coat
    repainted blue stay two areas even where they touch.

    Clusters the *direction* of each pixel's Lab shift, not its size: a patch's soft edge shifts
    the same way as its middle, only less, and must stay part of it. Clusters pointing in similar
    directions are merged back together. Seeded and sampled deterministically, so the same diff
    always gives the same masks.
    """
    ys, xs = np.nonzero(where)
    if len(ys) < 2 * MAX_KINDS:
        return [where]
    shift = (lab_b[ys, xs] - lab_a[ys, xs]).astype(np.float32)
    unit = shift / (np.linalg.norm(shift, axis=1, keepdims=True) + 1e-6)
    sample = np.ascontiguousarray(unit[:: max(1, len(unit) // KMEANS_SAMPLE)])
    cv2.setRNGSeed(0)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 0.01)
    _, sample_labels, centers = cv2.kmeans(sample, MAX_KINDS, None, criteria, 2, cv2.KMEANS_PP_CENTERS)
    centers /= np.linalg.norm(centers, axis=1, keepdims=True) + 1e-6

    # Merge directions closer than SAME_KIND_COS, biggest cluster first.
    sizes = np.bincount(sample_labels.ravel(), minlength=MAX_KINDS)
    kept: list[np.ndarray] = []
    for c in np.argsort(-sizes):
        if sizes[c] and all(float(centers[c] @ k) < SAME_KIND_COS for k in kept):
            kept.append(centers[c])
    if len(kept) == 1:
        return [where]

    nearest = np.argmax(unit @ np.array(kept).T, axis=1)
    kinds = np.zeros(where.shape, dtype=np.int32)  # 0 = unchanged, 1..n = kind
    kinds[ys, xs] = nearest + 1
    full_shift = np.zeros((*where.shape, 3), dtype=np.float32)
    full_shift[ys, xs] = shift
    groups = _merge_smooth_boundaries(kinds, full_shift, len(kept))

    out = []
    for members in groups:
        out.append(np.isin(kinds, [m + 1 for m in members]))
    return out


def _merge_smooth_boundaries(kinds: np.ndarray, shift: np.ndarray, n: int) -> list[list[int]]:
    """Group kinds whose shared boundary is a smooth transition, not a jump.

    A gradient (a dusk sky going from purple to orange) changes direction slowly across the canvas,
    so k-means cuts it in two; but pixels a few steps apart across that cut have almost the same
    shift. Where the sky meets a repainted coat, the shift jumps. Returns lists of 0-based kinds.
    """
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    d = BOUNDARY_STEP
    sums = np.zeros((n, n))
    counts = np.zeros((n, n))
    for ka, kb, sa, sb in (
        (kinds[:, :-d], kinds[:, d:], shift[:, :-d], shift[:, d:]),
        (kinds[:-d], kinds[d:], shift[:-d], shift[d:]),
    ):
        across = (ka > 0) & (kb > 0) & (ka != kb)
        if not across.any():
            continue
        jump = np.linalg.norm(sa[across] - sb[across], axis=1)
        np.add.at(sums, (ka[across] - 1, kb[across] - 1), jump)
        np.add.at(counts, (ka[across] - 1, kb[across] - 1), 1)

    counts, sums = counts + counts.T, sums + sums.T
    for i in range(n):
        for j in range(i + 1, n):
            if counts[i, j] >= MIN_BOUNDARY_PX and sums[i, j] / counts[i, j] < SMOOTH_JUMP:
                parent[find(i)] = find(j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _change_areas(lab_a: np.ndarray, lab_b: np.ndarray, leftover: np.ndarray) -> list[np.ndarray]:
    """Split leftover change into areas: by kind of change, then by place, grouping nearby specks."""
    h, w = leftover.shape
    k = max(3, int(GROUP_DISTANCE * np.hypot(w, h)) | 1)
    disk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    min_px = settings.diff_min_component * leftover.size
    areas = []
    for kind in _by_kind_of_change(lab_a, lab_b, leftover):
        n, labels = cv2.connectedComponents(cv2.dilate(kind.astype(np.uint8), disk), connectivity=8)
        areas += [a for a in (kind & (labels == i) for i in range(1, n)) if a.sum() >= min_px]
    return areas


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
            bbox=bbox(own), hints=hints(lab_a, lab_b, changed), polygons=polygons(own), mask=own,
        ))

    if claimed.any():
        h, w = change.shape
        k = max(7, int(REGION_BLEED * np.hypot(w, h)) | 1)
        near = cv2.dilate(claimed.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    else:
        near = claimed

    labels_used: dict[str, int] = {}
    for area in _change_areas(lab_a, lab_b, change & ~near):
        box = bbox(area)
        label = position_label(core_bbox(area))
        labels_used[label] = labels_used.get(label, 0) + 1
        if labels_used[label] > 1:
            label = f"{label} {labels_used[label]}"
        n = int(area.sum())
        out.append(ChangedRegion(
            label=label, source="change", region_id=None, changed_px=n,
            changed_ratio=1.0, image_share=round(n / total, 4),
            bbox=box, hints=hints(lab_a, lab_b, area), polygons=polygons(area), mask=area,
        ))

    return sorted(out, key=lambda r: r.changed_px, reverse=True)
