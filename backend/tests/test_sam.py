import io
from types import SimpleNamespace

import pytest
from scenes import H, W, scene

from app import storage
from app.ai import cache, sam
from app.config import settings
from app.services import segmentation

# Real reply shapes from sam-3.1: one entry per instance, an empty string when nothing is found.
SKY = "<0f>0<|box;x1=0;y1=0;x2=255;y2=99;w=256;h=192|><|mask;x=0;y=0;data=100,256,~!!&(d#T|>\n"
HILLS = ("<0f>0<|box;x1=0;y1=100;x2=127;y2=191;w=256;h=192|><|mask;x=0;y=0;data=1,1,!|>,"
         "1<|box;x1=128;y1=110;x2=255;y2=191;w=256;h=192|><|mask;x=0;y=0;data=1,1,!|>\n")


def fake_sam(monkeypatch, replies, calls=None):
    def create(model, input):
        prompt = input[0]["content"][0]["text"]
        if calls is not None:
            calls.append(prompt)
        reply = replies[prompt]
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(output=[SimpleNamespace(content=[SimpleNamespace(text=reply)])])

    monkeypatch.setattr(sam, "model_api", lambda: SimpleNamespace(responses=SimpleNamespace(create=create)))


@pytest.fixture
def sha(conn):
    out = io.BytesIO()
    scene().save(out, format="PNG")
    return storage.put_image(conn, out.getvalue())["sha256"]


def test_boxes_become_regions_at_the_images_size(conn, sha, monkeypatch):
    calls = []
    fake_sam(monkeypatch, {"sky": SKY, "hills": HILLS, "person": ""}, calls)
    masks = sam.segment(conn, sha, {"sky": "sky", "hills": "hills", "figure": "person"})

    assert [m.label for m in masks] == ["sky", "hills", "hills"]  # nothing found for the figure
    sky = masks[0].mask
    assert sky.shape == (H, W) and sky[:200].all() and not sky[200:].any()  # 256×192 scaled up to 512×384
    assert masks[2].mask[220:, 256:].all() and not masks[2].mask[:, :256].any()

    assert sam.segment(conn, sha, {"sky": "sky", "hills": "hills", "figure": "person"})  # all from the cache
    assert sorted(calls) == ["hills", "person", "sky"]


def test_offline_replays_the_cache_only(conn, sha, monkeypatch):
    fake_sam(monkeypatch, {"sky": SKY})
    sam.segment(conn, sha, {"sky": "sky"})
    monkeypatch.setattr(settings, "ai_offline", True)
    assert len(sam.segment(conn, sha, {"sky": "sky"})) == 1
    with pytest.raises(cache.AIOffline):
        sam.segment(conn, sha, {"sky": "sky", "sun": "sun"})


def test_a_failed_call_costs_the_names_not_the_analysis(conn, sha, monkeypatch):
    monkeypatch.setattr(segmentation, "VOCABULARY", {"sky": "sky", "sun": "sun"})
    fake_sam(monkeypatch, {"sky": SKY, "sun": RuntimeError("503 from the Model API")})
    segmentation.segment_blob(conn, sha)  # doesn't raise
    assert not segmentation.has_regions(conn, sha)

    fake_sam(monkeypatch, {"sky": SKY, "sun": ""})
    segmentation.segment_blob(conn, sha)  # tried again with the next analysis
    assert [r.label for r in segmentation.load_regions(conn, sha, (W, H))] == ["sky"]
