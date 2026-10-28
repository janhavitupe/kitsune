import numpy as np

from app import storage
from app.services.segmentation import RawMask, has_regions, load_regions, postprocess, save_regions
from scenes import H, W, box_mask, scene


def test_postprocess_drops_confetti_and_duplicates():
    sky = box_mask((0, 0, W - 1, 200))
    raw = [
        RawMask("sky", sky, 0.9),
        RawMask("sky", sky.copy(), 0.7),  # duplicate of the same sky
        RawMask("eyes", box_mask((10, 10, 12, 12)), 0.9),  # 9 px: confetti
    ]
    assert [(m.label, m.score) for m in postprocess(raw)] == [("sky", 0.9)]


def test_postprocess_names_figures_by_position():
    raw = [
        RawMask("figure", box_mask((400, 100, 480, 300))),
        RawMask("figure", box_mask((20, 100, 100, 300))),
    ]
    assert sorted(m.label for m in postprocess(raw)) == ["left figure", "right figure"]


def test_regions_round_trip(conn):
    sha = storage.put_image(conn, _png(scene()))["sha256"]
    assert not has_regions(conn, sha)
    sky = box_mask((0, 0, W - 1, 200))
    save_regions(conn, sha, [RawMask("sky", sky, 0.9)], source="sam-3.1")

    assert has_regions(conn, sha)
    (region,) = load_regions(conn, sha, (W // 2, H // 2))
    assert region.label == "sky" and region.mask.shape == (H // 2, W // 2)
    assert abs(region.mask.mean() - sky.mean()) < 0.01


def _png(img) -> bytes:
    import io

    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_mask_dtype():
    assert box_mask((0, 0, 1, 1)).dtype == np.bool_
