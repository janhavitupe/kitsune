"""The demo story end to end on the generated art: what the assistant brings back is the artist's
own painting, and nothing drawn later is lost."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from app import storage

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


art = _load("make_demo_art")
LANTERN = (art.FIGURE_X + 98, art.HILLTOP_Y - 222)
COAT = (art.FIGURE_X, art.HILLTOP_Y - 60)
SKY = (300, 150)


@pytest.fixture
def story(client, tmp_path):
    seed = _load("seed_demo")
    for name, kw in art.VERSIONS.items():
        art.paint(**kw).save(tmp_path / name)
    rid = seed.seed(client, tmp_path, art.MANIFEST, log=lambda *_: None)
    return rid, {c["seq"]: c for c in client.get(f"/api/repos/{rid}/commits").json()}


def ask(client, rid, text):
    r = client.post(f"/api/repos/{rid}/assistant", json={"ask": text})
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    final = events[-1]
    assert final["type"] == "final" and final["created"], events
    return client.get(f"/api/commits/{final['created'][-1]}").json()


def px(conn, commit, at):
    return np.asarray(storage.load_rgb(conn, commit["blob_sha"]))[at[1], at[0]].astype(int)


def same(conn, a, b, at):
    return np.abs(px(conn, a, at) - px(conn, b, at)).max() <= 1


def test_day_sky_comes_back_and_the_lantern_and_coat_stay(client, conn, story):
    rid, c = story
    out = ask(client, rid, "Take the day sky from v2 and keep the lantern")
    assert same(conn, out, c[2], SKY)  # v2's day sky
    assert same(conn, out, c[6], LANTERN)  # v4's lantern
    assert same(conn, out, c[6], COAT)  # v5's red coat


def test_bring_back_the_lantern_after_it_was_painted_over(client, conn, story, upload):
    rid, c = story
    v7 = upload(rid, art.paint(sky="dusk", coat=art.COAT_RED))  # the lantern is gone
    assert not same(conn, v7, c[4], LANTERN)
    out = ask(client, rid, "bring back the lantern")
    assert out["message"] == "Brought back the lantern from v4"  # found by v4's message
    assert same(conn, out, c[4], LANTERN)  # copied from v4
    assert same(conn, out, v7, COAT) and same(conn, out, v7, SKY)  # the rest is v7's


def test_assistant_works_on_the_version_you_picked(client, conn, story):
    rid, c = story
    first = ask(client, rid, "Take the day sky from v2")
    assert first["branch"].startswith("assistant/")
    # Asked again from that version: the result follows it on the same branch, main is untouched.
    r = client.post(f"/api/repos/{rid}/assistant", json={"ask": "make it warmer", "start_commit": first["id"]})
    final = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")][-1]
    second = client.get(f"/api/commits/{final['created'][-1]}").json()
    assert second["parent_id"] == first["id"] and second["branch"] == first["branch"]
    main = next(b for b in client.get(f"/api/repos/{rid}").json()["branches"] if b["name"] == "main")
    assert main["head_commit_id"] == c[6]["id"]
