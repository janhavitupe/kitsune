"""Self-hosted open weights (private mode, M5): an OpenAI-compatible endpoint on Baseten, with
Fireworks as the fallback host (same code, different OPENWEIGHTS_BASE_URL).

Captioning needs a multimodal model, so use Muse Spark Open here; Muse Glimmer may be text-only
and then only suits query reading. Confirm in the host's model library.
"""

import sqlite3

from app import storage
from app.ai import prompts
from app.ai.cache import cached
from app.ai.client import openweights
from app.ai.spark import _json
from app.config import settings


def model_id() -> str:
    return settings.openweights_model or "open-weights"


def _chat(messages: list[dict], max_tokens: int, temperature: float = 0.2) -> str:
    r = openweights().chat.completions.create(
        model=settings.openweights_model, messages=messages, temperature=temperature, max_tokens=max_tokens
    )
    return (r.choices[0].message.content or "").strip()


def caption(conn: sqlite3.Connection, sha: str) -> str:
    inputs = {"task": "caption", "v": prompts.CAPTION_VERSION, "blob": sha}

    def call() -> dict:
        return {"text": _chat([{"role": "user", "content": [
            {"type": "text", "text": prompts.CAPTION},
            {"type": "image_url", "image_url": {"url": storage.data_uri(conn, sha, max_side=768)}},
        ]}], max_tokens=120)}

    return cached(conn, model_id(), inputs, call)["text"]


def rewrite_query(conn: sqlite3.Connection, query: str) -> dict:
    inputs = {"task": "query_rewrite", "v": prompts.QUERY_REWRITE_VERSION, "q": query}

    def call() -> dict:
        data = _json(_chat([
            {"role": "system", "content": prompts.QUERY_REWRITE},
            {"role": "user", "content": f"Query: {query}"},
        ], max_tokens=80, temperature=0), "{", "}")
        relation = data.get("relation")
        return {
            "relation": relation if relation in ("before", "after", "when") else None,
            "anchor": str(data.get("anchor") or ""),
            "terms": str(data.get("terms") or ""),
        }

    return cached(conn, model_id(), inputs, call)
