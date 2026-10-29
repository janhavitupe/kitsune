"""Paint a placeholder demo series: a wanderer on a hilltop, version by version, with the
kitsune-demo.json that seed_demo.py replays. Use it until the real artwork is ready.

    backend/.venv/Scripts/python scripts/make_demo_art.py demo-art
    backend/.venv/Scripts/python scripts/seed_demo.py demo-art --backend https://<render-url>

The story it tells (each step only changes what it says, so the diffs are clean):

    v1  blocking in          flat shapes
    v2  rendered, day sky    client: "could the sky be dusk?"
    v3  dusk sky             only the sky changes
    ├─ main      v4  lantern on the staff
    └─ red-coat  v5  the coat goes red
    v6  merge red-coat into main (no conflict: different regions)

Live in the demo: "bring back the day sky from v2", compare v2/v3, search "before the dusk sky".
Deterministic: the same files every run.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

W, H = 1600, 1000
DAY = ((70, 130, 205), (190, 220, 240))  # sky top, horizon
DUSK = ((52, 40, 105), (250, 150, 90))
COAT_BLUE, COAT_RED = (45, 70, 110), (165, 40, 45)
FIGURE_X, HILLTOP_Y = 1060, 600


def ridge(base: float, waves: list[tuple[float, float, float]]) -> np.ndarray:
    x = np.arange(W)
    return base + sum(a * np.sin(x / period + phase) for a, period, phase in waves)


FAR = ridge(560, [(28, 140, 0.4), (14, 53, 1.7)])
MID = ridge(640, [(40, 220, 2.1), (12, 61, 0.3)])
NEAR = ridge(720, [(0, 1, 0)]) - 120 * np.exp(-(((np.arange(W) - FIGURE_X) / 330.0) ** 2))  # the hill the figure stands on


def noise(rng: np.random.Generator, scale: int, size=(W, H)) -> np.ndarray:
    """Smooth value noise in 0..1."""
    small = rng.random((size[1] // scale + 2, size[0] // scale + 2))
    img = Image.fromarray((small * 255).astype(np.uint8)).resize((size[0] + scale * 2, size[1] + scale * 2), Image.Resampling.BICUBIC)
    return np.asarray(img, dtype=np.float32)[:size[1], :size[0]] / 255.0


def gradient(top, bottom, y0=0, y1=H) -> np.ndarray:
    t = np.clip((np.arange(H)[:, None] - y0) / max(1, y1 - y0), 0, 1)[..., None]
    return (np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t) * np.ones((1, W, 1), np.float32)


def below(r: np.ndarray) -> np.ndarray:
    return np.arange(H)[:, None] >= r[None, :]


def paint(sky: str = "day", coat=COAT_BLUE, lantern: bool = False, rendered: bool = True) -> Image.Image:
    rng = np.random.default_rng(7)
    top, horizon = DAY if sky == "day" else DUSK
    if rendered:
        canvas = gradient(top, horizon, 0, 640)
        # Sun low on the left, with a soft glow.
        yy, xx = np.mgrid[0:H, 0:W]
        sun = (330, 430) if sky == "day" else (360, 560)
        d = np.hypot(xx - sun[0], yy - sun[1])
        glow_color = np.array((255, 245, 210) if sky == "day" else (255, 190, 120), np.float32)
        glow = np.exp(-d / (90 if sky == "day" else 160))[..., None]
        canvas = canvas * (1 - 0.6 * glow) + glow_color * 0.6 * glow
        canvas[d < 38] = glow_color
        # Clouds: soft noise bands, lit from the sun's side.
        n = noise(rng, 90) * 0.7 + noise(rng, 30) * 0.3
        band = np.exp(-((np.arange(H)[:, None] - 250) / 120.0) ** 2)
        cover = np.clip((n - 0.52) * 4, 0, 1) * band
        cloud = np.array((248, 248, 250) if sky == "day" else (240, 130, 120), np.float32)
        canvas = canvas * (1 - 0.75 * cover[..., None]) + cloud * 0.75 * cover[..., None]
    else:
        canvas = np.ones((H, W, 3), np.float32) * np.array(top, np.float32)
        canvas[np.arange(H) > 420] = horizon

    # Hills: hazier and bluer with distance. They don't change with the sky, so the dusk diff is the sky only.
    for r, (c_top, c_bottom), grain in (
        (FAR, ((130, 150, 175), (110, 135, 150)), 0.04),
        (MID, ((85, 125, 95), (65, 100, 75)), 0.07),
        (NEAR, ((70, 120, 60), (40, 80, 40)), 0.12),
    ):
        mask = below(r)
        layer = gradient(c_top, c_bottom, int(r.min()), H) if rendered else np.ones_like(canvas) * np.array(c_top, np.float32)
        if rendered:
            layer *= (1 - grain / 2 + grain * noise(rng, 6))[..., None]
        canvas[mask] = layer[mask]

    img = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
    d = ImageDraw.Draw(img)
    if rendered:  # grass strokes on the near hill
        for _ in range(1400):
            x = int(rng.integers(0, W))
            y = int(rng.integers(int(NEAR[x]) + 6, H))
            shade = int(rng.integers(-25, 25))
            d.line((x, y, x + int(rng.integers(-4, 5)), y - int(rng.integers(6, 16))),
                   fill=(60 + shade, 110 + shade, 50 + shade), width=2)

    # The wanderer: coat, head, hat, staff.
    fx, fy = FIGURE_X, HILLTOP_Y
    d.polygon([(fx - 34, fy), (fx + 34, fy), (fx + 18, fy - 120), (fx - 18, fy - 120)], fill=coat)
    d.ellipse((fx - 17, fy - 158, fx + 17, fy - 124), fill=(225, 190, 160))
    d.polygon([(fx - 32, fy - 146), (fx + 32, fy - 146), (fx, fy - 186)], fill=(50, 40, 35))
    d.line((fx + 46, fy + 4, fx + 92, fy - 210), fill=(90, 65, 40), width=6)
    if lantern:
        lx, ly = fx + 98, fy - 222
        glow = Image.new("L", (W, H), 0)
        ImageDraw.Draw(glow).ellipse((lx - 26, ly - 26, lx + 26, ly + 26), fill=200)
        glow = glow.filter(ImageFilter.GaussianBlur(14))
        img.paste(Image.new("RGB", (W, H), (255, 210, 120)), mask=glow)
        d.rectangle((lx - 8, ly - 11, lx + 8, ly + 11), fill=(255, 230, 160), outline=(70, 50, 30), width=2)

    if rendered:  # a little paint grain over everything
        grain = (np.random.default_rng(3).normal(0, 3, (H, W, 1))).astype(np.float32)
        img = Image.fromarray(np.clip(np.asarray(img, np.float32) + grain, 0, 255).astype(np.uint8))
    return img


VERSIONS = {
    "01-blocking.png": dict(rendered=False),
    "02-day.png": dict(),
    "03-dusk.png": dict(sky="dusk"),
    "04-lantern.png": dict(sky="dusk", lantern=True),
    "05-red-coat.png": dict(sky="dusk", coat=COAT_RED),
}

MANIFEST = {
    "name": "Hilltop wanderer",
    "steps": [
        {"image": "01-blocking.png", "message": "Blocking in the shapes"},
        {"image": "02-day.png", "notes": [
            {"kind": "client", "text": "Love the hills and the little figure. Could the sky be more dramatic, like a dusk?"},
        ]},
        {"image": "03-dusk.png", "notes": [{"kind": "artist", "text": "Dusk sky for the client, kept the hills as they were."}]},
        {"new_branch": "red-coat", "from": "v3"},
        {"image": "04-lantern.png", "message": "Lantern on the staff"},
        {"image": "05-red-coat.png", "branch": "red-coat", "message": "Trying a red coat"},
        {"merge": "red-coat", "into": "main"},
    ],
}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("folder", type=Path, nargs="?", default=Path("demo-art"))
    args = p.parse_args()
    args.folder.mkdir(parents=True, exist_ok=True)
    for name, kw in VERSIONS.items():
        paint(**kw).save(args.folder / name)
        print(f"  {name}")
    (args.folder / "kitsune-demo.json").write_text(json.dumps(MANIFEST, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(VERSIONS)} images and kitsune-demo.json to {args.folder}")


if __name__ == "__main__":
    sys.exit(main())
