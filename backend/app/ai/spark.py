"""Muse Spark: fast multimodal calls (commit messages now; captions and query rewrites later)."""

import sqlite3

from app import storage
from app.ai import prompts
from app.ai.cache import cached
from app.ai.client import model_api
from app.config import settings

# Only what the prompt uses, so unrelated fields (polygons, bbox) don't change the cache key.
PROMPT_FIELDS = ("label", "changed_ratio", "hints")


def commit_message(conn: sqlite3.Connection, a_sha: str, b_sha: str, regions: list[dict]) -> str:
    """A one-to-two sentence, painter-voiced description of what changed from A to B."""
    top = [{k: r[k] for k in PROMPT_FIELDS} for r in regions[:6]]
    inputs = {"task": "commit_message", "v": prompts.COMMIT_MESSAGE_VERSION, "a": a_sha, "b": b_sha, "regions": top}

    def call() -> dict:
        r = model_api().chat.completions.create(
            model=settings.spark_model,
            messages=prompts.commit_message_messages(storage.data_uri(conn, a_sha), storage.data_uri(conn, b_sha), top),
            temperature=0.3,
            max_tokens=80,
        )
        return {"text": (r.choices[0].message.content or "").strip().strip('"')}

    return cached(conn, settings.spark_model, inputs, call)["text"]
