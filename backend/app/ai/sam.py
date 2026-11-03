"""SAM 3.1 over the Meta Model API: text-prompted segmentation.

SAM is served on /v1/responses only. One call per text prompt; the reply is text with one entry
per instance found, nothing at all when there is none:

    <0f>0<|box;x1=0;y1=0;x2=1023;y2=383;w=1024;h=640|><|mask;x=0;y=0;data=384,1024,<encoded>|>,1<|box;...

The mask data's encoding isn't documented, so regions are the boxes: x1..y2 are inclusive pixel
coordinates in the w×h image SAM was sent. The diff lets the smallest region claim its pixels
first, so a face box wins over the figure box around it.
"""

import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import numpy as np

from app import storage
from app.ai import cache
from app.ai.client import model_api
from app.config import settings

if TYPE_CHECKING:
    from app.services.segmentation import RawMask

PROMPT_VERSION = 1
BOX = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")


def boxes(text: str) -> list[list[int]]:
    """[x1, y1, x2, y2, w, h] per instance in a SAM reply."""
    return [[int(v) for v in m] for m in BOX.findall(text)]


def segment(conn: sqlite3.Connection, sha: str, prompts: dict[str, str]) -> list["RawMask"]:
    """One RawMask per instance SAM finds, for each {label: text prompt}, at the blob's resolution."""
    from app.services.segmentation import RawMask

    keys = {p: cache.cache_key(settings.sam_model, {"task": "segment", "v": PROMPT_VERSION, "blob": sha, "prompt": p})
            for p in prompts.values()}
    found = {p: hit["boxes"] for p, k in keys.items() if (hit := cache.get(conn, k)) is not None}
    missing = [p for p in keys if p not in found]
    if missing:
        if settings.ai_offline:
            raise cache.AIOffline("AI_OFFLINE is set and SAM hasn't seen this image")
        client = model_api()  # raises AIUnavailable here, before any thread starts, when there's no key
        image = storage.data_uri(conn, sha)

        def ask(prompt: str) -> list[list[int]]:
            r = client.responses.create(model=settings.sam_model, input=[{"role": "user", "content": [
                {"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": image},
            ]}])
            return boxes(r.output[0].content[0].text if r.output else "")

        # A call takes a few seconds, so ask in parallel; the cache is written on this thread's connection.
        with ThreadPoolExecutor(max_workers=6) as pool:
            for prompt, result in zip(missing, pool.map(ask, missing), strict=True):
                cache.put(conn, keys[prompt], settings.sam_model, {"boxes": result})
                found[prompt] = result

    blob = storage.get_blob(conn, sha)
    width, height = blob["width"], blob["height"]
    masks = []
    for label, prompt in prompts.items():
        for x1, y1, x2, y2, w, h in found[prompt]:
            mask = np.zeros((height, width), dtype=bool)
            sx, sy = width / w, height / h
            mask[round(y1 * sy):round((y2 + 1) * sy), round(x1 * sx):round((x2 + 1) * sx)] = True
            masks.append(RawMask(label, mask))
    return masks
