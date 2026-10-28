import numpy as np
from PIL import Image, ImageDraw

from app.services.diffing import summarize
from app.services.pixel_diff import change_mask, to_array, to_lab
from app.services.region_diff import analyze, position_label
from app.services.segmentation import Region
from scenes import FIGURE_BOX, SKY_DUSK, box_mask, figure_mask, scene, sky_mask


def run(a, b, regions):
    lab_a, lab_b = to_lab(to_array(a)), to_lab(to_array(b))
    return analyze(lab_a, lab_b, change_mask(lab_a, lab_b), regions)


def sam_regions():
    return [Region(1, "sky", sky_mask(), "sam-3.1"), Region(2, "figure", figure_mask(), "sam-3.1")]


def test_only_the_changed_region_is_reported():
    out = run(scene(), scene(sky=SKY_DUSK), sam_regions())
    assert [r.label for r in out] == ["sky"]
    sky = out[0]
    assert sky.changed_ratio > 0.95 and sky.region_id == 1 and sky.source == "sam-3.1"
    assert "warmer" in sky.hints
    assert sky.polygons and all(0 <= x <= 1 and 0 <= y <= 1 for poly in sky.polygons for x, y in poly)


def test_darker_cooler_hints():
    out = run(scene(), scene(figure=(40, 40, 120)), sam_regions())
    assert [r.label for r in out] == ["figure"]
    assert "cooler" in out[0].hints


def test_smaller_region_wins_overlap():
    face_box = (235, 150, 275, 190)  # top of the figure
    regions = sam_regions() + [Region(3, "face", box_mask(face_box), "sam-3.1")]
    out = run(scene(), scene(extra=(face_box, (235, 200, 170))), regions)
    assert [r.label for r in out] == ["face"]


def test_change_outside_regions_is_named_by_position():
    out = run(scene(), scene(extra=((20, 20, 90, 70), (250, 250, 250))), regions=[])
    assert [r.label for r in out] == ["top-left area"]
    assert out[0].source == "change" and out[0].region_id is None
    assert "lighter" in out[0].hints


def test_touching_changes_of_different_kinds_stay_apart():
    # Sky warmed and the coat repainted blue: they touch, but changed in very different ways.
    out = run(scene(), scene(sky=SKY_DUSK, figure=(40, 70, 140)), regions=[])
    assert sorted(r.label for r in out) == ["center area", "top area"]
    hints = {r.label: r.hints for r in out}
    assert "warmer" in hints["top area"] and "cooler" in hints["center area"]


def gradient_sky(top, bottom, figure=None):
    img = scene(figure=figure) if figure else scene()
    px = np.asarray(img).copy()
    t = np.linspace(0, 1, 240)[:, None, None]
    sky = (np.array(top) + (np.array(bottom) - np.array(top)) * t).astype(np.uint8)
    figure_cols = np.zeros(px.shape[1], bool)
    figure_cols[FIGURE_BOX[0] : FIGURE_BOX[2] + 1] = True
    rows = np.arange(240)
    for x in range(px.shape[1]):
        keep = rows < FIGURE_BOX[1] if figure_cols[x] else rows < 240
        px[rows[keep], x] = sky[rows[keep], 0]
    return Image.fromarray(px)


def test_a_gradient_change_stays_one_area():
    # Day sky → purple-to-orange dusk: the shift turns as you go down, but smoothly.
    a = gradient_sky((90, 140, 210), (170, 200, 235))
    b = gradient_sky((70, 60, 140), (240, 150, 90))
    assert [r.label for r in run(a, b, [])] == ["top area"]


def test_gradient_sky_and_repainted_coat_are_two_areas():
    a = gradient_sky((90, 140, 210), (170, 200, 235))
    b = gradient_sky((70, 60, 140), (240, 150, 90), figure=(40, 70, 140))
    assert sorted(r.label for r in run(a, b, [])) == ["center area", "top area"]


def test_a_patch_and_its_soft_edge_are_one_area():
    out = run(scene(), scene(extra=((20, 20, 90, 70), (230, 90, 160))), regions=[])
    assert [r.label for r in out] == ["top-left area"]


def test_a_thin_new_line_on_its_own_is_kept():
    b = scene()
    ImageDraw.Draw(b).line((380, 60, 460, 80), fill=(30, 30, 40), width=3)
    assert [r.label for r in run(scene(), b, regions=[])] == ["top-right area"]


def test_kind_split_is_deterministic():
    a, b = scene(), scene(sky=SKY_DUSK, figure=(40, 70, 140))
    first, second = run(a, b, []), run(a, b, [])
    assert all((x.mask == y.mask).all() for x, y in zip(first, second, strict=True))


def test_whole_canvas_change():
    # The same warm shift over every pixel is one change, not one per object.
    a = scene()
    b = Image.fromarray(np.clip(np.asarray(a).astype(int) + [40, 10, -40], 0, 255).astype(np.uint8))
    out = run(a, b, regions=[])
    assert [r.label for r in out] == ["whole canvas"]


def test_different_changes_everywhere_are_listed_separately():
    out = run(scene(), scene(sky=SKY_DUSK, ground=(120, 90, 40), figure=(200, 120, 40)), regions=[])
    assert sorted(r.label for r in out) == ["bottom area", "center area", "top area"]


def test_position_label():
    assert position_label([0.7, 0.75, 0.2, 0.2]) == "bottom-right area"
    assert position_label([0.4, 0.4, 0.2, 0.2]) == "center area"
    assert position_label([0.4, 0.0, 0.2, 0.2]) == "top area"


def test_summarize():
    r = lambda label, *hints: {"label": label, "hints": list(hints)}  # noqa: E731
    assert summarize([]) == "No visible changes."
    assert summarize([r("sky", "warmer")]) == "Changed the sky (warmer)."
    assert summarize([r("sky", "warmer"), r("hair", "darker")]) == "Changed the sky (warmer) and the hair (darker)."
    assert summarize([r("a", "x"), r("b", "y"), r("c", "z"), r("d", "w")]) == (
        "Changed the a (x), the b (y), and the c (z), plus 1 smaller changes."
    )


def test_figure_box_constant_matches_mask():
    assert figure_mask().sum() == (FIGURE_BOX[2] - FIGURE_BOX[0] + 1) * (FIGURE_BOX[3] - FIGURE_BOX[1] + 1)
