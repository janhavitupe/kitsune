import io

import numpy as np
from PIL import Image, ImageDraw

from app.services.pixel_diff import change_mask, to_array, to_lab


def lab(img):
    return to_lab(to_array(img))


def circle_scene(circle):
    img = Image.radial_gradient("L").resize((512, 512)).convert("RGB")
    ImageDraw.Draw(img).ellipse((180, 180, 330, 330), fill=circle)
    return img


def test_recolored_circle_is_found():
    change = change_mask(lab(circle_scene((200, 60, 60))), lab(circle_scene((60, 60, 200))))
    truth = Image.new("L", (512, 512), 0)
    ImageDraw.Draw(truth).ellipse((180, 180, 330, 330), fill=255)
    truth = np.asarray(truth) > 0
    iou = (change & truth).sum() / (change | truth).sum()
    assert iou > 0.9


def test_jpeg_noise_is_ignored():
    a = circle_scene((200, 60, 60))
    out = io.BytesIO()
    a.save(out, format="JPEG", quality=90)
    b = Image.open(io.BytesIO(out.getvalue())).convert("RGB")
    # A thin chroma-subsampling ring survives around the saturated red edge (~0.1%); kept on
    # purpose, since filtering thin change out would also hide thin new linework.
    assert change_mask(lab(a), lab(b)).mean() < 0.002


def test_identical_images_have_no_change():
    a = circle_scene((200, 60, 60))
    assert not change_mask(lab(a), lab(a)).any()
