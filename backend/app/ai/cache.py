"""Every model result is cached by a hash of its inputs, so nothing is computed twice and the demo
can replay with AI_OFFLINE=1.

Inputs must be JSON-serializable and must reference images and audio by their sha256, never by
raw bytes, so keys stay small and stable.
"""

import hashlib
import json
import logging
import sqlite3
from collections.abc import Callable
from typing import Any

from app.config import settings
from app.db import now

log = logging.getLogger("kitsune.ai")


class AIOffline(RuntimeError):
    pass


def cache_key(model: str, inputs: dict[str, Any]) -> str:
    canonical = json.dumps(inputs, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(f"{model}\n{canonical}".encode()).hexdigest()


def get(conn: sqlite3.Connection, key: str) -> Any | None:
    row = conn.execute("SELECT response_json FROM ai_cache WHERE key = ?", (key,)).fetchone()
    return json.loads(row["response_json"]) if row else None


def put(conn: sqlite3.Connection, key: str, model: str, response: Any) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO ai_cache (key, model, response_json, created_at) VALUES (?, ?, ?, ?)",
        (key, model, json.dumps(response), now()),
    )


def cached(conn: sqlite3.Connection, model: str, inputs: dict[str, Any], call: Callable[[], Any]) -> Any:
    """Return the cached result for (model, inputs), or run `call` once and cache what it returns."""
    key = cache_key(model, inputs)
    hit = get(conn, key)
    if hit is not None:
        log.info("ai cache hit model=%s key=%s", model, key[:12])
        return hit
    if settings.ai_offline:
        raise AIOffline(f"AI_OFFLINE is set and there is no cached result for {model}")
    log.info("ai call model=%s key=%s", model, key[:12])
    result = call()
    put(conn, key, model, result)
    return result
