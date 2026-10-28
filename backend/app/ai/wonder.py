"""Muse Wonder: the long-horizon model behind the studio assistant and the process story."""

import json
import sqlite3

from app.ai.cache import cached
from app.ai.client import model_api
from app.config import settings


def chat(conn: sqlite3.Connection, messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 900) -> dict:
    """One Wonder turn: {"content": str, "tool_calls": [{"id", "name", "arguments": dict}]}.

    Tool calling is OpenAI-style; confirm with the probe that Wonder returns `tool_calls`. If it
    answers with a JSON object {"tool": ..., "arguments": ...} in its text instead, that is
    accepted too, so the agent works either way.
    """
    inputs = {"task": "chat", "messages": messages, "tools": tools or []}

    def call() -> dict:
        kwargs = {"model": settings.wonder_model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
        if tools:
            kwargs["tools"] = tools
        msg = model_api().chat.completions.create(**kwargs).choices[0].message
        calls = [
            {"id": c.id, "name": c.function.name, "arguments": json.loads(c.function.arguments or "{}")}
            for c in (getattr(msg, "tool_calls", None) or [])
        ]
        return {"content": (msg.content or "").strip(), "tool_calls": calls}

    reply = cached(conn, settings.wonder_model, inputs, call)
    if tools and not reply["tool_calls"]:
        reply = {**reply, "tool_calls": _json_tool_call(reply["content"])}
    return reply


def _json_tool_call(text: str) -> list[dict]:
    """Fallback for models without native tool calls: a {"tool": name, "arguments": {...}} object in the text."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict) and isinstance(data.get("tool"), str):
        return [{"id": "json-0", "name": data["tool"], "arguments": data.get("arguments") or {}}]
    return []
