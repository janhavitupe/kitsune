import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from scenes import scene

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cli"))
from kitsune_cli import main as cli  # noqa: E402

TOP_LEFT = (20, 20, 90, 70)
BOTTOM_RIGHT = (420, 300, 490, 360)
WHITE, YELLOW, PINK = (250, 250, 250), (240, 220, 40), (230, 90, 160)


def paint(path, *patches, base=None):
    img = base or scene()
    d = ImageDraw.Draw(img)
    for box, color in patches:
        d.rectangle(box, fill=color)
    img.save(path)


def pixel(path, box):
    with Image.open(path) as img:
        return img.convert("RGB").getpixel(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))


@pytest.fixture
def studio(client, tmp_path):
    """An art folder with a tracked painting, initialised with its first version."""
    lines = []
    root = tmp_path / "art"
    root.mkdir()
    painting = root / "girl.png"
    scene().save(painting)
    k = cli.Kitsune.init(client, root, painting, None, None, "http://testserver", "http://web", None, out=lines.append)
    k.lines = lines
    return k


def test_init_creates_the_piece_and_first_version(client, studio):
    ws = studio.ws
    cfg = json.loads((ws.root / ".kitsune" / "config.json").read_text())
    assert cfg["file"] == "girl.png" and cfg["branch"] == "main"
    assert client.get(f"/api/repos/{ws.repo_id}").json()["name"] == "girl"
    assert [c["seq"] for c in studio.commits()] == [1]
    assert cli.Workspace.find(ws.root / "sub" / "dir").repo_id == ws.repo_id  # found from a subfolder


def test_commit_status_log_diff(studio):
    ws = studio.ws
    assert studio.commit(None) is None  # unchanged file
    paint(ws.path, (TOP_LEFT, WHITE))
    assert ws.dirty()
    c = studio.commit(None)
    assert c["seq"] == 2 and c["auto_message"] and not ws.dirty()

    studio.lines.clear()
    studio.status()
    assert "Nothing to commit." in studio.lines

    studio.lines.clear()
    studio.log()
    assert studio.lines[0].startswith("v2") and "(main)" in studio.lines[0] and studio.lines[1].startswith("v1")

    d = studio.diff(None, None)
    assert [r["label"] for r in d["regions"]] == ["top-left area"]
    assert studio.diff("v2", "1")["id"] == d["id"]


def test_branch_switch_and_merge_with_a_conflict(studio):
    ws = studio.ws
    paint(ws.path, (TOP_LEFT, WHITE))
    studio.commit("white patch")
    studio.branch("pink", "v1")

    paint(ws.path, (TOP_LEFT, YELLOW))
    with pytest.raises(cli.CliError, match="aren't committed"):
        studio.switch("pink")
    studio.switch("pink", force=True)
    assert ws.branch == "pink" and pixel(ws.path, TOP_LEFT) != WHITE  # v1 loaded into the file

    paint(ws.path, (TOP_LEFT, PINK), (BOTTOM_RIGHT, YELLOW))
    assert studio.commit("pink and yellow")["branch"] == "pink"

    studio.switch("main")
    assert pixel(ws.path, TOP_LEFT) == WHITE
    assert studio.merge("pink", {}) is None  # conflict reported, merge aborted
    assert any("[0] top-left area" in line for line in studio.lines)

    m = studio.merge("pink", cli.parse_take("0=source"))
    assert m["merge_parent_id"] and m["branch"] == "main"
    assert pixel(ws.path, TOP_LEFT) == PINK and pixel(ws.path, BOTTOM_RIGHT) == YELLOW
    assert not ws.dirty()


def test_checkout_and_pick(studio):
    ws = studio.ws
    original = pixel(ws.path, TOP_LEFT)
    paint(ws.path, (TOP_LEFT, WHITE), (BOTTOM_RIGHT, YELLOW))
    studio.commit(None)

    out = ws.root / "old.png"
    studio.checkout("v1", out)
    assert pixel(out, TOP_LEFT) == original and not ws.dirty()

    c = studio.pick("top-left area", "v1")
    assert c["origin"] == "cherry_pick" and c["seq"] == 3
    assert pixel(ws.path, TOP_LEFT) == original and pixel(ws.path, BOTTOM_RIGHT) == YELLOW

    studio.checkout("v1", None)
    assert ws.dirty()  # an old version is loaded but not committed
    with pytest.raises(cli.CliError, match="aren't committed"):
        studio.checkout("v2", None)


def test_notes_and_search(client, studio):
    paint(studio.ws.path, (TOP_LEFT, WHITE))
    studio.commit("warmer dusk sky")
    studio.note("client loves it", "HEAD", client=True)
    head = studio.head()
    assert head["note_count"] == 1
    assert client.get(f"/api/commits/{head['id']}/notes").json()[0]["kind"] == "client"
    studio.lines.clear()
    studio.search("dusk")
    assert studio.lines[0].startswith("v2")


def test_watch_commits_after_a_save(studio):
    paint(studio.ws.path, (TOP_LEFT, WHITE))
    studio.watch(settle_s=0, poll_s=0.01, max_commits=1)
    assert [c["seq"] for c in studio.commits()] == [1, 2]


def test_errors(client, studio, tmp_path, monkeypatch):
    with pytest.raises(cli.CliError, match="already"):
        cli.Kitsune.init(client, studio.ws.root, studio.ws.path, None, None, "b", "w", None, out=lambda *_: None)
    psd = tmp_path / "x.psd"
    psd.write_bytes(b"")
    with pytest.raises(cli.CliError, match="PNG or JPG"):
        cli.Kitsune.init(client, tmp_path, psd, None, None, "b", "w", None, out=lambda *_: None)
    with pytest.raises(cli.CliError, match="No version v9"):
        studio.version("v9")
    with pytest.raises(cli.CliError, match="isn't a version"):
        studio.version("sky")
    with pytest.raises(cli.CliError, match="No branch"):
        studio.switch("nope")
    with pytest.raises(cli.CliError, match="Bad --take"):
        cli.parse_take("0=mine")

    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    assert cli.main(["status"]) == 1
