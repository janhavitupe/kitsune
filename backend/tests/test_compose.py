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
