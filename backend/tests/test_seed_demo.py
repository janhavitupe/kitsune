import importlib.util
from pathlib import Path

import pytest
from PIL import ImageDraw
from scenes import SKY_DUSK, scene

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed_demo.py"
spec = importlib.util.spec_from_file_location("seed_demo", SCRIPT)
seed_demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed_demo)


@pytest.fixture
def art(tmp_path):
    folder = tmp_path / "art"
    folder.mkdir()
    scene().save(folder / "01-sketch.png")
    scene(sky=SKY_DUSK).save(folder / "02-dusk.png")
    red = scene(sky=SKY_DUSK)
    ImageDraw.Draw(red).rectangle((420, 300, 490, 360), fill=(240, 220, 40))
    red.save(folder / "03-patch.jpg", quality=95)
    (folder / "notes.txt").write_text("not an image")
    return folder


def test_without_a_manifest_images_go_to_main_in_order(client, art):
    rid = seed_demo.seed(client, art, log=lambda *_: None)
    commits = client.get(f"/api/repos/{rid}/commits").json()
    assert [c["seq"] for c in commits] == [1, 2, 3] and {c["branch"] for c in commits} == {"main"}
    assert client.get(f"/api/repos/{rid}").json()["name"] == "art"
    assert all(c["analysis_status"] == "done" for c in commits)


def test_manifest_with_branch_notes_and_merge(client, art):
    manifest = {
        "name": "Hilltop wanderer",
        "steps": [
            {"image": "01-sketch.png", "message": "First color pass"},
            {"image": "02-dusk.png", "notes": [{"kind": "client", "text": "Can the sky be dusk?"}]},
            {"new_branch": "patch", "from": "v1"},
            {"image": "03-patch.jpg", "branch": "patch"},
            {"merge": "patch", "into": "main"},
        ],
    }
    rid = seed_demo.seed(client, art, manifest, log=lambda *_: None)
    commits = client.get(f"/api/repos/{rid}/commits").json()
    assert [(c["seq"], c["branch"], c["origin"]) for c in commits] == [
        (1, "main", "upload"), (2, "main", "upload"), (3, "patch", "upload"), (4, "main", "merge"),
    ]
    assert commits[0]["message"] == "First color pass" and commits[1]["note_count"] == 1
    assert commits[3]["merge_parent_id"] == commits[2]["id"]


def test_bad_manifests(client, art, tmp_path):
    with pytest.raises(seed_demo.SeedError, match="unknown version v9"):
        seed_demo.seed(client, art, {"steps": [{"new_branch": "x", "from": "v9"}]}, log=lambda *_: None)
    with pytest.raises(seed_demo.SeedError, match="needs image"):
        seed_demo.seed(client, art, {"steps": [{"paint": "x"}]}, log=lambda *_: None)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(seed_demo.SeedError, match="No images"):
        seed_demo.seed(client, empty, log=lambda *_: None)
