import numpy as np
from scenes import box_mask

from app.services import compose


def test_alpha_is_full_inside_and_fades_outside():
    mask = box_mask((100, 100, 200, 200))
    a = compose.alpha(mask, radius=8)
    assert a.min() >= 0 and a.max() <= 1
    assert a[mask].min() == 1.0
    assert a[0, 0] == 0  # far away: exactly zero
    assert 0 < a[150, 212] < 1  # just outside the edge: blended


def test_composite_is_exact_where_alpha_is_zero():
    rng = np.random.default_rng(0)
    target = rng.integers(0, 256, (384, 512, 3), dtype=np.uint8)
    source = rng.integers(0, 256, (384, 512, 3), dtype=np.uint8)
    a = compose.alpha(box_mask((100, 100, 200, 200)), radius=8)
    out = compose.composite(target, source, a)
    assert np.array_equal(out[a == 0], target[a == 0])
    assert np.array_equal(out[150, 150], source[150, 150])


def test_seam_band_is_a_ring():
    a = compose.alpha(box_mask((100, 100, 200, 200)), radius=8)
    band = compose.seam_band(a)
    assert band.any()
    assert not band[150, 150] and not band[0, 0]


def test_paste_inside_never_touches_outside_the_band():
    rng = np.random.default_rng(1)
    base = rng.integers(0, 256, (384, 512, 3), dtype=np.uint8)
    band = compose.seam_band(compose.alpha(box_mask((100, 100, 200, 200)), radius=8))
    box = compose.padded_bbox(band)
    x0, y0, x1, y1 = box
    noise = rng.integers(0, 256, (y1 - y0, x1 - x0, 3), dtype=np.uint8)  # a model gone wrong
    out = compose.paste_inside(base, noise, band, box)
    assert np.array_equal(out[~band], base[~band])
    assert not np.array_equal(out[band], base[band])
