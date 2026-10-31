"""Merging two Krita files layer by layer, so a merge lands in the painting itself.

A .kra is a zip: maindoc.xml lists the layers, and each layer's pixels are in their own file. Krita
gives every layer a uuid that survives saves and branches, so layers can be matched across versions
even when their files get renumbered, and each is merged on its own against the common ancestor:

    changed on one branch only   → that branch's layer
    added on either branch       → added
    deleted on one, untouched    → deleted
    changed on both              → both kept as their own layers, plus a third holding the pixels
                                   where the two collide, for the artist to settle in Krita

Layer files are copied as Krita wrote them, so nothing the artist drew is re-encoded. The only new
pixels are in the overlap layer, and those are the artist's own two layers stacked.

Anything this can't merge safely (animation, a different canvas) raises Unsupported, and the caller
falls back to a flat merge that leaves the artist's file alone.

An older version can also be merged into a newer one on the same line of work (see restored_file).
The older file is both ancestor and source, so every layer the newer one has stays as it is, and
what merging adds is the layers it no longer has, back in the places they sat. No region diff can
say which side of a changed area to keep here, so the flat image is stacked from the merged layers;
a file that can't be stacked faithfully (groups, masks, blend modes) raises Unsupported.
"""

import copy
import hashlib
import io
import itertools
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

NS = "http://www.calligra.org/DTD/krita"
HEADER = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
          b"<!DOCTYPE DOC PUBLIC '-//KDE//DTD krita 2.0//EN' 'http://www.calligra.org/DTD/krita-2.0.dtd'>\n")
ET.register_namespace("", NS)

TILE = 64  # Krita stores layers in 64 px tiles of B, G, R, A: as 4 planes when compressed, pixel by pixel when raw
PIXEL_SIZE = 4
RAW, LZF = 0, 1  # the flag byte in front of every tile's data
TILE_BYTES = TILE * TILE * PIXEL_SIZE
BLUE, ORANGE, PURPLE = "1", "4", "7"  # Krita's color labels: this branch, that branch, the overlap
PREVIEW_PX = 256

# Saving rewrites these even when the layer wasn't touched
VOLATILE = {"filename", "selected", "channellockflags", "intimeline", "collapsed", "onionskin"}
SAME_CANVAS = ("width", "height", "colorspacename", "profile")


class Unsupported(ValueError):
    pass


def _tag(name: str) -> str:
    return f"{{{NS}}}{name}"


class Doc:
    def __init__(self, path: Path):
        self.zip = zipfile.ZipFile(path)
        self.root = ET.fromstring(self.zip.read("maindoc.xml"))  # noqa: S314 - stdlib ET expands no external entities
        self.image = self.root.find(_tag("IMAGE"))
        self.layers = None if self.image is None else self.image.find(_tag("layers"))
        if self.layers is None:
            raise Unsupported("No layers in this file")
        if any(el.get("keyframes") for el in self.root.iter()):
            raise Unsupported("Animated layers can't be merged yet")
        if any(not n.get("uuid") for n in self.layers):
            raise Unsupported("This file's layers have no ids")
        self.nodes = {n.get("uuid"): n for n in self.layers}
        self.dir = f"{self.image.get('name')}/layers/"
        self.files: dict[str, list[str]] = {}  # layer file name → that layer's entries in the zip
        for name in self.zip.namelist():
            if name.startswith(self.dir):
                self.files.setdefault(name[len(self.dir):].split(".", 1)[0], []).append(name)

    def close(self) -> None:
        self.zip.close()

    def suffixed(self, filename: str) -> list[tuple[str, str]]:
        """(suffix, zip entry) for each file belonging to a layer, e.g. ('.icc', 'Art/layers/layer2.icc')."""
        return [(name[len(self.dir) + len(filename):], name) for name in sorted(self.files.get(filename, []))]


def _tiles(data: bytes) -> tuple[dict[str, str], dict[tuple[int, int], bytes]]:
    """Split a layer's pixel file: its header, then (x, y) → that tile's stored bytes."""
    pos, header = 0, {}
    for _ in range(5):
        end = data.index(b"\n", pos)
        key, value = data[pos:end].decode().split(" ")
        header[key] = value
        pos = end + 1
    tiles = {}
    for _ in range(int(header["DATA"])):
        end = data.index(b"\n", pos)
        x, y, _codec, size = data[pos:end].decode().split(",")
        pos = end + 1
        tiles[(int(x), int(y))] = data[pos:pos + int(size)]
        pos += int(size)
    return header, tiles


def _canonical(data: bytes) -> bytes:
    """A layer's pixels in a fixed order. Krita can write the same tiles in a different order each save."""
    try:
        header, tiles = _tiles(data)
    except (ValueError, KeyError):
        return data  # not a pixel file
    return repr(sorted(header.items())).encode() + b"".join(repr(k).encode() + tiles[k] for k in sorted(tiles))


def _fingerprint(doc: Doc, node: ET.Element) -> str:
    """Equal when a layer (with its masks or, for a group, what's inside) hasn't changed."""
    h = hashlib.sha256()
    for el in node.iter():
        h.update(repr((el.tag, sorted((k, v) for k, v in el.attrib.items() if k not in VOLATILE))).encode())
        if filename := el.get("filename"):
            for suffix, name in doc.suffixed(filename):
                h.update(suffix.encode())
                h.update(_canonical(doc.zip.read(name)))
    return h.hexdigest()


@dataclass
class Keep:
    doc: Doc
    node: ET.Element
    name: str | None = None  # renamed, when both branches changed this layer
    color: str | None = None
    fresh: bool = False  # a second copy of a layer: it needs its own uuid

    @property
    def uuid(self) -> str:
        return self.node.get("uuid")


@dataclass
class Overlap:
    ours: Keep
    theirs: Keep
    base: tuple[Doc, ET.Element] | None

    @property
    def uuid(self) -> str:
        return self.ours.uuid


def _three_way(
    base: Doc | None, ours: Doc, theirs: Doc, restore: bool = False,
) -> tuple[list[Keep | Overlap], dict[str, list[str]]]:
    """The merged layer stack, top layer first, and what happened to each layer. With `restore`, a
    layer we deleted and they left alone comes back instead of staying deleted."""
    if any(ours.image.get(k) != theirs.image.get(k) for k in SAME_CANVAS):
        raise Unsupported("The two versions have different canvases")

    def was(u: str) -> str | None:
        return _fingerprint(base, base.nodes[u]) if base and u in base.nodes else None

    stack: list[Keep | Overlap] = []
    summary: dict[str, list[str]] = {"added": [], "updated": [], "removed": [], "both": []}
    for u, node in ours.nodes.items():
        name, mine = node.get("name"), _fingerprint(ours, node)
        if u not in theirs.nodes:
            if was(u) == mine:
                summary["removed"].append(name)  # they deleted it and we left it alone
            else:
                stack.append(Keep(ours, node))
            continue
        them, old = _fingerprint(theirs, theirs.nodes[u]), was(u)
        if them in (mine, old):
            stack.append(Keep(ours, node))
        elif mine == old:
            stack.append(Keep(theirs, theirs.nodes[u]))
            summary["updated"].append(name)
        else:
            summary["both"].append(name)
            a, b = Keep(ours, node, color=BLUE), Keep(theirs, theirs.nodes[u], color=ORANGE, fresh=True)
            stack += [Overlap(a, b, (base, base.nodes[u]) if old else None), b, a]

    # Their new layers go where they painted them: above the same layer they sat on
    order = list(theirs.nodes.items())
    for i, (u, node) in reversed(list(enumerate(order))):
        if u in ours.nodes or (not restore and was(u) is not None and was(u) == _fingerprint(theirs, node)):
            continue  # we have it, or we deleted it and they left it alone
        placed = [k.uuid for k in stack]
        below = next((v for v, _ in order[i + 1:] if v in placed), None)
        stack.insert(placed.index(below) if below else len(stack), Keep(theirs, node))
        summary["added"].append(node.get("name"))
    return stack, summary


def _with_docs(base: Path | None, ours: Path, theirs: Path, work):
    docs = []
    try:
        for path in (base, ours, theirs):
            docs.append(Doc(path) if path else None)
        return work(*docs)
    except (KeyError, ValueError, ET.ParseError, zipfile.BadZipFile) as e:
        raise Unsupported(str(e)) from e
    finally:
        for doc in docs:
            if doc:
                doc.close()


def plan(base: Path | None, ours: Path, theirs: Path) -> dict[str, list[str]]:
    """What merging these files would do to their layers. Raises Unsupported."""
    return _with_docs(base, ours, theirs, lambda *docs: _three_way(*docs)[1])


def plan_restore(older: Path, newer: Path) -> dict[str, list[str]]:
    """What merging an older version into a newer one would do. Raises Unsupported."""
    def work(o: Doc, n: Doc, t: Doc) -> dict[str, list[str]]:
        stack, summary = _three_way(o, n, t, restore=True)
        _flatten(stack, _size(n))  # refuse now, not after the artist has confirmed
        return summary
    return _with_docs(older, newer, older, work)


def _size(doc: Doc) -> tuple[int, int]:
    return int(doc.image.get("width")), int(doc.image.get("height"))


def _lzf(data: bytes) -> bytes:
    out, i = bytearray(), 0
    while i < len(data):
        c = data[i]
        i += 1
        if c < 32:  # a run of literals
            out += data[i:i + c + 1]
            i += c + 1
            continue
        length = c >> 5  # a back-reference
        if length == 7:
            length += data[i]
            i += 1
        ref = len(out) - ((c & 31) << 8) - data[i] - 1
        i += 1
        for _ in range(length + 2):  # may overlap what it's writing
            out.append(out[ref])
            ref += 1
    return bytes(out)


def _pixels(doc: Doc, node: ET.Element, size: tuple[int, int]) -> np.ndarray | None:
    """A paint layer on the canvas as H×W×4 (B, G, R, A), or None for anything else."""
    if node.get("nodetype") != "paintlayer" or node.get("colorspacename") != "RGBA":
        return None
    filename = node.get("filename")
    files = dict(doc.suffixed(filename))
    header, tiles = _tiles(doc.zip.read(files[""]))
    if int(header["PIXELSIZE"]) != PIXEL_SIZE or int(header["TILEWIDTH"]) != TILE or int(header["TILEHEIGHT"]) != TILE:
        return None
    w, h = size
    default = doc.zip.read(files[".defaultpixel"]) if ".defaultpixel" in files else bytes(PIXEL_SIZE)
    canvas = np.tile(np.frombuffer(default, np.uint8), (h, w, 1)).copy()
    dx, dy = int(node.get("x", 0)), int(node.get("y", 0))
    for (tx, ty), stored in tiles.items():
        x0, y0 = tx + dx, ty + dy
        left, top, right, bottom = max(x0, 0), max(y0, 0), min(x0 + TILE, w), min(y0 + TILE, h)
        if left >= right or top >= bottom:
            continue  # off the canvas
        if stored[0] == LZF:
            tile = np.frombuffer(_lzf(stored[1:]), np.uint8).reshape(PIXEL_SIZE, TILE, TILE).transpose(1, 2, 0)
        else:
            tile = np.frombuffer(stored[1:], np.uint8).reshape(TILE, TILE, PIXEL_SIZE)
        canvas[top:bottom, left:right] = tile[top - y0:bottom - y0, left - x0:right - x0]
    return canvas


def _encode(pixels: np.ndarray, mask: np.ndarray) -> bytes:
    """A Krita layer file holding `pixels` wherever `mask` is set."""
    h, w = mask.shape
    records = []
    for ty, tx in itertools.product(range(0, h, TILE), range(0, w, TILE)):
        if not mask[ty:ty + TILE, tx:tx + TILE].any():
            continue
        tile = np.zeros((TILE, TILE, PIXEL_SIZE), np.uint8)
        part = pixels[ty:ty + TILE, tx:tx + TILE]
        tile[:part.shape[0], :part.shape[1]] = part
        records.append(f"{tx},{ty},LZF,{TILE_BYTES + 1}\n".encode() + bytes([RAW]) + tile.tobytes())
    header = f"VERSION 2\nTILEWIDTH {TILE}\nTILEHEIGHT {TILE}\nPIXELSIZE {PIXEL_SIZE}\nDATA {len(records)}\n".encode()
    return header + b"".join(records)


def _over(under: np.ndarray, over: np.ndarray) -> np.ndarray:
    """One B, G, R, A layer on top of another, as Krita's normal blending stacks them."""
    top, bottom = over[..., 3:] / 255, under[..., 3:] / 255
    alpha = top + bottom * (1 - top)
    color = (over[..., :3] * top + under[..., :3] * bottom * (1 - top)) / np.maximum(alpha, 1e-6)
    return np.dstack([color, alpha * 255]).round().astype(np.uint8)


def _flatten(stack: list[Keep | Overlap], size: tuple[int, int]) -> bytes:
    """A PNG of the layers stacked, top first in `stack`. Raises Unsupported rather than guess at
    anything but plain paint layers."""
    w, h = size
    canvas = np.zeros((h, w, PIXEL_SIZE), np.uint8)
    for item in reversed(stack):
        node = item.node
        if node.get("visible", "1") == "0":
            continue
        px = _pixels(item.doc, node, size)
        if px is None or len(node) or node.get("compositeop", "normal") != "normal":
            raise Unsupported(f"the layer '{node.get('name')}' is a group, has a mask or uses a blend mode")
        px[..., 3] = (px[..., 3] * (int(node.get("opacity", 255)) / 255)).round()
        canvas = _over(canvas, px)
    shown = canvas[..., 3:] / 255
    rgb = canvas[..., 2::-1] * shown + 255 * (1 - shown)  # what's left transparent shows as Krita's white
    out = io.BytesIO()
    Image.fromarray(rgb.round().astype(np.uint8)).save(out, format="PNG")
    return out.getvalue()


def _collision(item: Overlap, size: tuple[int, int]) -> bytes | None:
    """The layer file for where both branches changed the same pixels differently, or None if they didn't.
    Its pixels are their layer over ours, exactly as the two stack."""
    a = _pixels(item.ours.doc, item.ours.node, size)
    b = _pixels(item.theirs.doc, item.theirs.node, size)
    if a is None or b is None:
        return None
    old = _pixels(*item.base, size) if item.base else None
    if old is None:
        old = np.zeros_like(a)  # a layer both added: anything on it counts as a change
    mask = (a != old).any(axis=2) & (b != old).any(axis=2) & (a != b).any(axis=2)
    if not mask.any():
        return None
    out = _over(a, b)
    out[~mask] = 0
    return _encode(out, mask)


def _new_uuid() -> str:
    return "{" + str(uuid.uuid4()) + "}"


def _build(ours: Doc, stack: list[Keep | Overlap], flat_png: bytes, ours_name: str, theirs_name: str) -> bytes:
    numbers = [int(f[5:]) for f in ours.files if f.startswith("layer") and f[5:].isdigit()]
    names = (f"layer{n}" for n in itertools.count(max(numbers, default=0) + 1))
    size = _size(ours)
    kept, added, nodes = set(), {}, []

    for item in stack:
        if isinstance(item, Overlap):
            layer = _collision(item, size)
            if layer is None:
                continue
            source = item.theirs.node
            node = copy.deepcopy(source)
            for child in list(node):
                node.remove(child)  # masks
            filename = next(names)
            label = source.get("name")
            node.attrib.update(name=f"{label} overlap ({ours_name} + {theirs_name})", filename=filename, x="0", y="0",
                               uuid=_new_uuid(), opacity="255", compositeop="normal", colorlabel=PURPLE, visible="1")
            node.attrib.pop("selected", None)
            added[f"{ours.dir}{filename}"] = layer
            added[f"{ours.dir}{filename}.defaultpixel"] = bytes(PIXEL_SIZE)
            icc = dict(item.theirs.doc.suffixed(source.get("filename"))).get(".icc")
            if icc:
                added[f"{ours.dir}{filename}.icc"] = item.theirs.doc.zip.read(icc)
            nodes.append(node)
            continue

        node = copy.deepcopy(item.node)
        if item.color:
            side = ours_name if item.doc is ours else theirs_name
            node.attrib.update(name=f"{node.get('name')} ({side})", colorlabel=item.color)
        if item.fresh:
            node.set("uuid", _new_uuid())
        for el in node.iter():
            if not (filename := el.get("filename")):
                continue
            if item.doc is ours:
                kept.add(filename)
                continue
            new = next(names)
            for suffix, entry in item.doc.suffixed(filename):
                added[f"{ours.dir}{new}{suffix}"] = item.doc.zip.read(entry)
            el.set("filename", new)
        if item.doc is not ours:
            node.attrib.pop("selected", None)
        nodes.append(node)

    for child in list(ours.layers):
        ours.layers.remove(child)
    ours.layers.extend(nodes)

    preview = Image.open(io.BytesIO(flat_png))
    preview.thumbnail((PREVIEW_PX, PREVIEW_PX))
    thumb = io.BytesIO()
    preview.save(thumb, format="PNG")

    replaced = {"maindoc.xml": HEADER + ET.tostring(ours.root, encoding="utf-8"), "mergedimage.png": flat_png,
                "preview.png": thumb.getvalue()}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info in ours.zip.infolist():  # same order and compression: mimetype has to stay first and stored
            name = info.filename
            if name.startswith(ours.dir) and name[len(ours.dir):].split(".", 1)[0] not in kept:
                continue
            z.writestr(name, replaced[name] if name in replaced else ours.zip.read(name), compress_type=info.compress_type)
        for name, data in added.items():
            z.writestr(name, data)
    return out.getvalue()


def merged_file(base: Path | None, ours: Path, theirs: Path, flat_png: bytes, ours_name: str, theirs_name: str) -> bytes:
    """The merged .kra. flat_png becomes its flattened image; Krita rebuilds that from the layers on open."""
    def work(b: Doc | None, a: Doc, t: Doc) -> bytes:
        return _build(a, _three_way(b, a, t)[0], flat_png, ours_name, theirs_name)
    return _with_docs(base, ours, theirs, work)


def restored_file(older: Path, newer: Path, newer_name: str, older_name: str) -> tuple[bytes, bytes]:
    """(merged .kra, its flat PNG): the newer file with the layers only the older one has put back."""
    def work(o: Doc, n: Doc, t: Doc) -> tuple[bytes, bytes]:
        stack = _three_way(o, n, t, restore=True)[0]
        flat_png = _flatten(stack, _size(n))
        return _build(n, stack, flat_png, newer_name, older_name), flat_png
    return _with_docs(older, newer, older, work)
