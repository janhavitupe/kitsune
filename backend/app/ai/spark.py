"""Muse Spark: fast multimodal calls: commit messages, note summaries, captions, query rewrites."""

import json
import re
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


def _chat(messages: list[dict], max_tokens: int, temperature: float = 0.2) -> str:
    r = model_api().chat.completions.create(
        model=settings.spark_model, messages=messages, temperature=temperature, max_tokens=max_tokens
    )
    return (r.choices[0].message.content or "").strip()


def _json(text: str, opener: str, closer: str):
    """The first JSON object or list in a model reply (models sometimes wrap it in prose or fences)."""
    match = re.search(re.escape(opener) + r".*" + re.escape(closer), text, re.S)
    if not match:
        raise ValueError(f"no JSON in model reply: {text[:80]!r}")
    return json.loads(match.group(0))


def summarize_note(conn: sqlite3.Connection, text: str, kind: str) -> str:
    inputs = {"task": "note_summary", "v": prompts.NOTE_SUMMARY_VERSION, "kind": kind, "text": text}

    def call() -> dict:
        return {"text": _chat([
            {"role": "system", "content": prompts.NOTE_SUMMARY[kind]},
            {"role": "user", "content": text},
        ], max_tokens=150)}

    return cached(conn, settings.spark_model, inputs, call)["text"]


def caption(conn: sqlite3.Connection, sha: str) -> str:
    inputs = {"task": "caption", "v": prompts.CAPTION_VERSION, "blob": sha}

    def call() -> dict:
        return {"text": _chat([{"role": "user", "content": [
            {"type": "text", "text": prompts.CAPTION},
            {"type": "image_url", "image_url": {"url": storage.data_uri(conn, sha, max_side=768)}},
        ]}], max_tokens=120)}

    return cached(conn, settings.spark_model, inputs, call)["text"]


def rewrite_query(conn: sqlite3.Connection, query: str) -> dict:
    """{"relation": "before" | "after" | "when" | None, "anchor": str, "terms": str}"""
    inputs = {"task": "query_rewrite", "v": prompts.QUERY_REWRITE_VERSION, "q": query}

    def call() -> dict:
        reply = _chat([
            {"role": "system", "content": prompts.QUERY_REWRITE},
            {"role": "user", "content": f"Query: {query}"},
        ], max_tokens=80, temperature=0)
        data = _json(reply, "{", "}")
        relation = data.get("relation")
        return {
            "relation": relation if relation in ("before", "after", "when") else None,
            "anchor": str(data.get("anchor") or ""),
            "terms": str(data.get("terms") or ""),
        }

    return cached(conn, settings.spark_model, inputs, call)


def explore_directions(conn: sqlite3.Connection, prompt: str) -> list[str]:
    """Three palette/lighting directions for an explore request like "try 3 palettes for this"."""
    inputs = {"task": "explore_directions", "v": prompts.EXPLORE_VERSION, "prompt": prompt}

    def call() -> dict:
        reply = _chat([{"role": "user", "content": prompts.EXPLORE_DIRECTIONS.format(prompt=prompt)}], max_tokens=60, temperature=0.7)
        directions = [str(d).strip() for d in _json(reply, "[", "]") if str(d).strip()]
        if len(directions) < 3:
            raise ValueError(f"expected three directions, got {directions}")
        return {"directions": directions[:3]}

    return cached(conn, settings.spark_model, inputs, call)["directions"]
