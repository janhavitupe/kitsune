"""Put the artist's own pixels from one version into another through a mask. Shared by cherry-pick
and merge.

Nothing is generated or repainted: every output pixel is the target's, the source's, or (in the
narrow soft edge) a mix of the two.
"""

import numpy as np

from app.services import compose


def paste(target: np.ndarray, source: np.ndarray, take: np.ndarray, protect: np.ndarray) -> np.ndarray:
    """`source` inside `take` over `target`.

    take:    where the source's pixels go (bool, target size)
    protect: changed areas outside `take` that must stay exactly as in the target; the soft edge of
             `take` stops at them, so it can't bleed the source's version of a neighbouring change in
    """
    a = compose.alpha(take, compose.feather_radius(target.shape))
    a[protect & ~take] = 0
    return compose.composite(target, source, a)
