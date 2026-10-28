"""Probe the Meta Model API once per model and save the raw responses.

Purpose (M1): confirm model ids and request/response shapes before coding against them.
Each probe is one guess at the request format. If a probe fails, read the saved error, check the
Model API docs, adjust that probe, and run it again with --only.

    backend/.venv/Scripts/python scripts/probe_model_api.py
    backend/.venv/Scripts/python scripts/probe_model_api.py --only sam,image
    backend/.venv/Scripts/python scripts/probe_model_api.py --audio note.webm

Output: scripts/probe_out/<probe>.json (gitignored), plus any images returned.
"""

import argparse
import base64
import io
import json
import math
import struct
import sys
import traceback
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from openai import OpenAI  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from app.config import settings  # noqa: E402

OUT = ROOT / "scripts" / "probe_out"


def test_image(sky: tuple[int, int, int]) -> bytes:
    """A tiny 'painting': sky, ground, and a figure. Only the sky color changes between A and B."""
    img = Image.new("RGB", (512, 384), sky)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 260, 512, 384), fill=(70, 110, 60))
    d.ellipse((230, 140, 280, 190), fill=(235, 200, 170))
    d.rectangle((240, 190, 270, 280), fill=(160, 40, 50))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def data_uri(png: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png).decode()


def silent_wav() -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", int(800 * math.sin(i / 20))) for i in range(16000)))
    return out.getvalue()


def dump(obj) -> object:
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj


SKY_DAY = test_image((120, 170, 230))
SKY_DUSK = test_image((230, 140, 90))


def probe_models(client: OpenAI, _args):
    return [m.id for m in client.models.list()]


def probe_spark(client: OpenAI, _args):
    r = client.chat.completions.create(
        model=settings.spark_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Image 1 is before, image 2 is after. In one sentence, what changed?"},
                {"type": "image_url", "image_url": {"url": data_uri(SKY_DAY)}},
                {"type": "image_url", "image_url": {"url": data_uri(SKY_DUSK)}},
            ],
        }],
    )
    return dump(r)


def probe_sam(client: OpenAI, _args):
    # Guess: SAM exposed through chat completions with an image and a text prompt.
    # The answer we need: how masks come back (RLE? PNG? polygons?) and whether labels are included.
    r = client.chat.completions.create(
        model=settings.sam_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "sky"},
                {"type": "image_url", "image_url": {"url": data_uri(SKY_DAY)}},
            ],
        }],
    )
    return dump(r)


def probe_image(client: OpenAI, _args):
    # Guess: OpenAI-style image edit. Also tells us whether a mask parameter is accepted.
    r = client.images.edit(
        model=settings.image_model,
        image=("a.png", SKY_DAY, "image/png"),
        prompt="Make the sky a warm dusk orange. Do not change anything else.",
    )
    result = dump(r)
    for i, item in enumerate(result.get("data") or []):
        if item.get("b64_json"):
            (OUT / f"image_{i}.png").write_bytes(base64.b64decode(item["b64_json"]))
            item["b64_json"] = f"<saved to image_{i}.png>"
    return result


def probe_voice(client: OpenAI, args):
    audio = Path(args.audio).read_bytes() if args.audio else silent_wav()
    name = Path(args.audio).name if args.audio else "tone.wav"
    r = client.audio.transcriptions.create(model=settings.voice_model, file=(name, audio))
    return dump(r)


def probe_wonder(client: OpenAI, _args):
    # Does Wonder return OpenAI-style tool calls? M5's agent design depends on it.
    r = client.chat.completions.create(
        model=settings.wonder_model,
        messages=[{"role": "user", "content": "List the commits in this repo."}],
        tools=[{
            "type": "function",
            "function": {
                "name": "list_commits",
                "description": "List the commits of the current repo.",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }],
    )
    return dump(r)


PROBES = {
    "models": probe_models,
    "spark": probe_spark,
    "sam": probe_sam,
    "image": probe_image,
    "voice": probe_voice,
    "wonder": probe_wonder,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="comma-separated: " + ",".join(PROBES))
    parser.add_argument("--audio", help="audio file for the voice probe (default: generated 1 s tone)")
    args = parser.parse_args()

    if not settings.model_api_key:
        sys.exit("MODEL_API_KEY is not set. Add it to .env at the repo root.")
    client = OpenAI(base_url=settings.model_api_base_url, api_key=settings.model_api_key, timeout=120, max_retries=0)

    names = args.only.split(",") if args.only else list(PROBES)
    OUT.mkdir(parents=True, exist_ok=True)
    for name in names:
        try:
            result = {"ok": True, "response": PROBES[name](client, args)}
            print(f"[ok]   {name}")
        except Exception as e:
            result = {"ok": False, "error": repr(e), "body": getattr(e, "body", None), "trace": traceback.format_exc()}
            print(f"[fail] {name}: {e}")
        (OUT / f"{name}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(f"\nRaw responses saved in {OUT}")


if __name__ == "__main__":
    main()
