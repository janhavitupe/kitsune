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


def test_whole_canvas_change():
    out = run(scene(), scene(sky=SKY_DUSK, ground=(120, 90, 40), figure=(200, 120, 40)), regions=[])
    assert out[0].label == "whole canvas"


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
