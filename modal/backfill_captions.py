"""Back-fill captions for every version of a piece with the open-weights model, in parallel on Modal.

The images are read from the Kitsune backend on this machine and sent to Modal, so the backend can
be local; Modal only talks to the open-weights endpoint. Captions are written back through the
backend API, which re-indexes search.

Setup (once):
    modal secret create kitsune-openweights OPENWEIGHTS_BASE_URL=... OPENWEIGHTS_API_KEY=... OPENWEIGHTS_MODEL=...

Run:
    modal run modal/backfill_captions.py --repo 1
    modal run modal/backfill_captions.py --repo 1 --backend https://kitsune-api.example.com
"""

import base64
import sys
from pathlib import Path

import modal

app = modal.App("kitsune-backfill-captions")
image = modal.Image.debian_slim(python_version="3.11").pip_install("openai==3.40.0")


@app.function(image=image, secrets=[modal.Secret.from_name("kitsune-openweights")], timeout=300, max_containers=8)
def caption(png: bytes, prompt: str) -> tuple[str, str]:
    import os

    from openai import OpenAI

    client = OpenAI(base_url=os.environ["OPENWEIGHTS_BASE_URL"], api_key=os.environ["OPENWEIGHTS_API_KEY"])
    model = os.environ["OPENWEIGHTS_MODEL"]
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}},
        ]}],
        max_tokens=120,
        temperature=0.2,
    )
    return (r.choices[0].message.content or "").strip(), model


@app.local_entrypoint()
def main(repo: int, backend: str = "http://127.0.0.1:8000"):
    import httpx

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app.ai.prompts import CAPTION  # the same prompt the backend uses

    api = httpx.Client(base_url=backend, timeout=60)
    missing = api.get(f"/api/repos/{repo}/captions/missing").raise_for_status().json()
    if not missing:
        print("Every version already has a caption.")
        return
    print(f"Captioning {len(missing)} images on Modal…")
    images = [api.get(m["image_url"]).raise_for_status().content for m in missing]
    for m, (text, model) in zip(missing, caption.starmap((png, CAPTION) for png in images), strict=True):
        api.post(f"/api/blobs/{m['blob_sha']}/captions", json={"caption": text, "model": model}).raise_for_status()
        print(f"  {m['blob_sha'][:12]}  {text[:70]}")
    print("Done.")
