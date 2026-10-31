import io
import re
import zipfile

import numpy as np
import pytest
from PIL import Image
from scenes import scene

from app.services import kra_merge

W, H = 128, 128


def rgba(*boxes):
    """A layer's pixels (B, G, R, A): transparent, with each (x0, y0, x1, y1, bgra) painted."""
    px = np.zeros((H, W, 4), np.uint8)
    for x0, y0, x1, y1, color in boxes:
        px[y0:y1, x0:x1] = color
    return px


def layer(uuid, name, px, nodetype="paintlayer", **attrs):
    return {"uuid": uuid, "name": name, "px": px, "nodetype": nodetype, **attrs}


def lzf_literals(data):
    out = bytearray()
    for i in range(0, len(data), 32):
        chunk = data[i:i + 32]
        out += bytes([len(chunk) - 1]) + chunk
    return bytes(out)


def pixel_file(px):
    records = []
    for ty in range(0, H, 64):
        for tx in range(0, W, 64):
            tile = px[ty:ty + 64, tx:tx + 64]
            if not tile[..., 3].any():
                continue
            data = bytes([kra_merge.LZF]) + lzf_literals(tile.transpose(2, 0, 1).tobytes())
            records.append((f"{tx},{ty},LZF,{len(data)}\n".encode(), data))
    header = f"VERSION 2\nTILEWIDTH 64\nTILEHEIGHT 64\nPIXELSIZE 4\nDATA {len(records)}\n".encode()
    return header, records


def kra(path, layers, width=W, reverse_tiles=False):
    nodes, files = [], {}
    for i, lay in enumerate(layers, start=2):
        extra = "".join(f' {k}="{v}"' for k, v in lay.items() if k not in ("uuid", "name", "px", "nodetype", "x", "y"))
        nodes.append(f'<layer name="{lay["name"]}" uuid="{{{lay["uuid"]}}}" nodetype="{lay["nodetype"]}" filename="layer{i}"'
                     f' colorspacename="RGBA" x="{lay.get("x", 0)}" y="{lay.get("y", 0)}"{extra}/>')
        header, records = pixel_file(lay["px"])
        ordered = reversed(records) if reverse_tiles else records
        files[f"Art/layers/layer{i}"] = header + b"".join(a + b for a, b in ordered)
        files[f"Art/layers/layer{i}.defaultpixel"] = bytes(4)
    doc = (f'<?xml version="1.0"?><DOC xmlns="{kra_merge.NS}"><IMAGE name="Art" width="{width}" height="{H}"'
           f' colorspacename="RGBA" profile="sRGB"><layers>{"".join(nodes)}</layers></IMAGE></DOC>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/x-krita")
        z.writestr("maindoc.xml", doc)
        for name, data in files.items():
            z.writestr(name, data)
        z.writestr("mergedimage.png", flat())
    return path


def flat():
    out = io.BytesIO()
    scene().save(out, format="PNG")
    return out.getvalue()


def stack(path):
    """(name, colorlabel) of each layer in a merged file, top first."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("maindoc.xml").decode()
    return [(re.search(r' name="([^"]*)"', m)[1], (re.search(r'colorlabel="(\d)"', m) or [None, None])[1])
            for m in re.findall(r"<layer [^>]*>", xml)]


def pixels(path, name):
    doc = kra_merge.Doc(path)
    node = next(n for n in doc.layers if n.get("name") == name)
    px = kra_merge._pixels(doc, node, (W, H))
    doc.close()
    return px


RED, BLUE, GREEN = (0, 0, 255, 255), (255, 0, 0, 255), (0, 255, 0, 255)
SKY = rgba((0, 0, W, 60, RED))
HILL = rgba((0, 60, W, H, GREEN))


def merge(tmp_path, base, ours, theirs):
    paths = [kra(tmp_path / f"{n}.kra", lay) for n, lay in (("base", base), ("ours", ours), ("theirs", theirs))]
    plan = kra_merge.plan(*paths)
    out = tmp_path / "merged.kra"
    out.write_bytes(kra_merge.merged_file(*paths, flat(), "main", "night"))
    return plan, out


def test_each_branch_adding_a_layer_keeps_both(tmp_path):
    base = [layer("s", "sky", SKY)]
    plan, out = merge(tmp_path, base, [layer("sun", "sun", rgba((0, 0, 9, 9, BLUE))), *base],
                      [layer("star", "star", rgba((20, 20, 29, 29, BLUE))), *base])
    assert plan == {"added": ["star"], "updated": [], "removed": [], "both": []}
    assert [n for n, _ in stack(out)] == ["sun", "star", "sky"]
    assert (pixels(out, "star")[25, 25] == BLUE).all()
    assert (pixels(out, "sun")[5, 5] == BLUE).all()


def test_a_layer_changed_on_one_branch_is_taken_from_it(tmp_path):
    base = [layer("s", "sky", SKY), layer("h", "hill", HILL)]
    painted = rgba((0, 60, W, H, BLUE))
    plan, out = merge(tmp_path, base, base, [base[0], layer("h", "hill", painted)])
    assert plan["updated"] == ["hill"]
    assert (pixels(out, "hill") == painted).all()
    assert (pixels(out, "sky") == SKY).all()


def test_a_moved_layer_counts_as_changed(tmp_path):
    base = [layer("s", "sky", SKY)]
    plan, _ = merge(tmp_path, base, [layer("s", "sky", SKY, x=5, y=7)], base)
    assert plan == {"added": [], "updated": [], "removed": [], "both": []}  # ours already has the move
    plan, out = merge(tmp_path, base, base, [layer("s", "sky", SKY, x=5, y=7)])
    assert plan["updated"] == ["sky"]
    assert 'x="5"' in zipfile.ZipFile(out).read("maindoc.xml").decode()


def test_the_same_tiles_in_another_order_are_unchanged(tmp_path):
    two = rgba((0, 0, W, H, RED))
    paths = [kra(tmp_path / "base.kra", [layer("s", "sky", two)]),
             kra(tmp_path / "ours.kra", [layer("s", "sky", two)], reverse_tiles=True),
             kra(tmp_path / "theirs.kra", [layer("s", "sky", two)])]
    assert kra_merge.plan(*paths) == {"added": [], "updated": [], "removed": [], "both": []}


def test_a_layer_deleted_on_one_branch_stays_deleted(tmp_path):
    sky, hill = layer("s", "sky", SKY), layer("h", "hill", HILL)
    plan, out = merge(tmp_path, [sky, hill], [sky, hill], [sky])
    assert plan["removed"] == ["hill"]
    assert [n for n, _ in stack(out)] == ["sky"]
    assert not [n for n in zipfile.ZipFile(out).namelist() if n.startswith("Art/layers/layer3")]


def test_deleted_on_one_branch_but_repainted_on_the_other_is_kept(tmp_path):
    sky, hill = layer("s", "sky", SKY), layer("h", "hill", HILL)
    plan, out = merge(tmp_path, [sky, hill], [sky], [sky, layer("h", "hill", rgba((0, 0, 5, 5, BLUE)))])
    assert "hill" in plan["added"]
    assert [n for n, _ in stack(out)] == ["sky", "hill"]


def test_both_branches_changing_a_layer_keeps_both_and_the_overlap(tmp_path):
    """The artist's drawing: a tree on one branch, a house on the other, on the same layer."""
    tree = rgba((20, 10, 80, 90, GREEN))
    house = rgba((50, 50, 120, 120, BLUE))
    below = layer("h", "hill", HILL)
    plan, out = merge(tmp_path, [layer("l", "L3", rgba()), below],
                      [layer("l", "L3", tree), below], [layer("l", "L3", house), below])

    assert plan["both"] == ["L3"]
    assert stack(out)[:3] == [("L3 overlap (main + night)", "7"), ("L3 (night)", "4"), ("L3 (main)", "1")]
    assert (pixels(out, "L3 (main)") == tree).all()  # each branch's layer is whole
    assert (pixels(out, "L3 (night)") == house).all()

    overlap = pixels(out, "L3 overlap (main + night)")
    assert (overlap[70, 60] == BLUE).all()  # the top layer's pixels where they collide
    assert overlap[30, 30, 3] == 0 and overlap[110, 110, 3] == 0  # and nothing anywhere else

    with zipfile.ZipFile(out) as z:
        xml = z.read("maindoc.xml").decode()
    uuids = re.findall(r'uuid="([^"]+)"', xml)
    assert len(uuids) == len(set(uuids))


def test_no_overlap_layer_when_the_changes_dont_touch(tmp_path):
    left, right = rgba((0, 0, 20, 20, GREEN)), rgba((100, 100, 120, 120, BLUE))
    plan, out = merge(tmp_path, [layer("l", "L3", rgba())], [layer("l", "L3", left)], [layer("l", "L3", right)])
    assert plan["both"] == ["L3"]
    assert [n for n, _ in stack(out)] == ["L3 (night)", "L3 (main)"]


def test_what_both_left_alone_on_a_shared_layer_is_no_collision(tmp_path):
    old = rgba((0, 0, W, H, RED))
    ours = old.copy()
    ours[0:10, 0:10] = GREEN
    theirs = old.copy()
    theirs[100:110, 100:110] = BLUE
    _, out = merge(tmp_path, [layer("l", "paint", old)], [layer("l", "paint", ours)], [layer("l", "paint", theirs)])
    assert [n for n, _ in stack(out)] == ["paint (night)", "paint (main)"]


def test_without_an_ancestor_nothing_is_lost(tmp_path):
    ours = kra(tmp_path / "ours.kra", [layer("s", "sky", SKY)])
    theirs = kra(tmp_path / "theirs.kra", [layer("s", "sky", HILL)])
    assert kra_merge.plan(None, ours, theirs)["both"] == ["sky"]


def test_a_layer_file_written_for_krita_reads_back(tmp_path):
    px = rgba((3, 5, 100, 70, (9, 8, 7, 200)))
    data = kra_merge._encode(px, px[..., 3] > 0)
    header, tiles = kra_merge._tiles(data)
    assert header["PIXELSIZE"] == "4" and len(tiles) == 4
    assert all(t[0] == kra_merge.RAW and len(t) == 64 * 64 * 4 + 1 for t in tiles.values())


@pytest.mark.parametrize("make", [
    lambda p: kra(p / "other.kra", [layer("s", "sky", SKY)], width=W * 2),
    lambda p: kra(p / "other.kra", [layer("s", "sky", SKY, keyframes="layer2.keyframes.xml")]),
])
def test_what_it_cant_merge_is_refused_not_guessed(tmp_path, make):
    ours = kra(tmp_path / "ours.kra", [layer("s", "sky", SKY)])
    with pytest.raises(kra_merge.Unsupported):
        kra_merge.plan(ours, ours, make(tmp_path))


def test_a_broken_file_is_refused(tmp_path):
    bad = tmp_path / "bad.kra"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("maindoc.xml", "not xml")
    with pytest.raises(kra_merge.Unsupported):
        kra_merge.plan(None, bad, bad)


def upload(client, repo_id, data, branch, name="art.kra"):
    r = client.post(f"/api/repos/{repo_id}/commits", files={"image": (name, data)}, data={"branch": branch, "message": "m"})
    assert r.status_code == 201, r.text
    return r.json()


def painted(tmp_path, name, layers, color):
    """A .kra whose flat image shows a change, so the region diff has something to see."""
    path = kra(tmp_path / name, layers)
    img = scene().copy()
    img.paste(color, (40, 40, 200, 200))
    png = io.BytesIO()
    img.save(png, format="PNG")
    with zipfile.ZipFile(path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    files["mergedimage.png"] = png.getvalue()
    with zipfile.ZipFile(path, "w") as z:
        for n, d in files.items():
            z.writestr(n, d)
    return path.read_bytes()


def test_merging_krita_versions_gives_a_version_with_layers(client, tmp_path):
    repo = client.post("/api/repos", json={"name": "piece"}).json()["id"]
    below = layer("h", "hill", HILL)
    first = upload(client, repo, kra(tmp_path / "a.kra", [layer("l", "L3", rgba()), below]).read_bytes(), "main")
    client.post(f"/api/repos/{repo}/branches", json={"name": "night", "from_commit": first["id"]}).raise_for_status()
    upload(client, repo, painted(tmp_path, "b.kra", [layer("l", "L3", rgba((0, 0, 60, 60, GREEN))), below], (10, 200, 10)), "main")
    upload(client, repo, painted(tmp_path, "c.kra", [layer("l", "L3", rgba((30, 30, 90, 90, BLUE))), below], (200, 10, 10)), "night")

    plan = client.post(f"/api/repos/{repo}/merges", json={"source": "night", "target": "main"}).json()
    assert plan["layers"]["both"] == ["L3"]
    assert plan["conflicts"] == []  # both stay in the file, so nothing to pick

    c = client.post(f"/api/merges/{plan['id']}/resolve", json={"choices": {}}).json()
    assert c["source_ext"] == "kra" and "Both versions of L3" in c["message"]
    merged = tmp_path / "merged.kra"
    merged.write_bytes(client.get(c["source_url"]).content)
    assert [n for n, _ in stack(merged)] == ["L3 overlap (main + night)", "L3 (night)", "L3 (main)", "hill"]
    with zipfile.ZipFile(merged) as z:
        assert z.namelist()[0] == "mimetype"
        assert Image.open(io.BytesIO(z.read("mergedimage.png"))).size == scene().size


def test_a_fast_forward_keeps_the_branch_file(client, tmp_path):
    repo = client.post("/api/repos", json={"name": "piece"}).json()["id"]
    first = upload(client, repo, kra(tmp_path / "a.kra", [layer("s", "sky", SKY)]).read_bytes(), "main")
    client.post(f"/api/repos/{repo}/branches", json={"name": "night", "from_commit": first["id"]}).raise_for_status()
    data = painted(tmp_path, "b.kra", [layer("s", "sky", HILL)], (200, 10, 10))
    upload(client, repo, data, "night")

    plan = client.post(f"/api/repos/{repo}/merges", json={"source": "night", "target": "main"}).json()
    c = client.post(f"/api/merges/{plan['id']}/resolve", json={"choices": {}}).json()
    assert client.get(c["source_url"]).content == data
