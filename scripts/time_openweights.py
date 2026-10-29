"""Time caption calls against an open-weights endpoint (Baseten vs Fireworks, for the write-up).

    backend/.venv/Scripts/python scripts/time_openweights.py
    backend/.venv/Scripts/python scripts/time_openweights.py --base-url https://api.fireworks.ai/inference/v1 \
        --api-key fw_... --model accounts/.../models/... --runs 10

Defaults come from OPENWEIGHTS_* in .env. Each run sends a fresh image so nothing is cached.
"""

import argparse
import base64
import io
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from openai import OpenAI  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app.ai.prompts import CAPTION  # noqa: E402
from app.config import settings  # noqa: E402


def image(i: int) -> str:
    img = Image.new("RGB", (768, 512), (90 + i * 10, 140, 210))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 340, 768, 512), fill=(60, 95, 70))
    d.ellipse((350, 200, 410, 260), fill=(235, 200, 170))
    d.polygon([(340, 260), (420, 260), (440, 420), (320, 420)], fill=(150, 40, 50))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # model text on a Windows console
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", default=settings.openweights_base_url)
    p.add_argument("--api-key", default=settings.openweights_api_key)
    p.add_argument("--model", default=settings.openweights_model)
    p.add_argument("--runs", type=int, default=10)
    args = p.parse_args()
    if not (args.base_url and args.api_key and args.model):
        sys.exit("Set OPENWEIGHTS_BASE_URL, OPENWEIGHTS_API_KEY and OPENWEIGHTS_MODEL in .env, or pass them.")

    client = OpenAI(base_url=args.base_url, api_key=args.api_key, timeout=120, max_retries=0)
    times = []
    for i in range(args.runs):
        t = time.perf_counter()
        r = client.chat.completions.create(
            model=args.model, max_tokens=120,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": CAPTION}, {"type": "image_url", "image_url": {"url": image(i)}},
            ]}],
        )
        times.append(time.perf_counter() - t)
        print(f"{i + 1:2d}  {times[-1]:5.2f}s  {(r.choices[0].message.content or '')[:60]!r}")
    print(f"\n{args.base_url}\nmean {statistics.mean(times):.2f}s · median {statistics.median(times):.2f}s · max {max(times):.2f}s")


if __name__ == "__main__":
    main()
