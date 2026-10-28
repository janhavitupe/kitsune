"""Synthetic 'paintings' for diff tests: sky on top, ground below, a figure standing in the middle."""

import numpy as np
from PIL import Image, ImageDraw

W, H = 512, 384
SKY_BOX = (0, 0, W, 240)
FIGURE_BOX = (220, 150, 290, 330)
SKY_DAY = (120, 170, 230)
SKY_DUSK = (240, 150, 90)
GROUND = (70, 110, 60)
FIGURE = (160, 40, 50)


def scene(sky=SKY_DAY, figure=FIGURE, ground=GROUND, extra=None) -> Image.Image:
    img = Image.new("RGB", (W, H), sky)
    d = ImageDraw.Draw(img)
    d.rectangle((0, SKY_BOX[3], W, H), fill=ground)
    d.rectangle(FIGURE_BOX, fill=figure)
    if extra:
        box, color = extra
        d.rectangle(box, fill=color)
    return img


def box_mask(box) -> np.ndarray:
    m = np.zeros((H, W), dtype=bool)
    x0, y0, x1, y1 = box
    m[y0 : y1 + 1, x0 : x1 + 1] = True
    return m


def sky_mask() -> np.ndarray:
    return box_mask((0, 0, W - 1, SKY_BOX[3] - 1)) & ~box_mask(FIGURE_BOX)


def figure_mask() -> np.ndarray:
    return box_mask(FIGURE_BOX)
