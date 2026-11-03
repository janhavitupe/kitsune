"""Muse Voice Transcribe: speech to text for voice notes and client voice feedback.

The model isn't on the OpenAI-style /audio/transcriptions route: it's served at /v1/asr/transcribe,
a multipart POST with a JSON "request" part and the audio, which must be a mono 16-bit WAV at
16 or 24 kHz. The browser converts recordings to that before uploading (frontend/src/lib/wav.ts).
"""

import hashlib
import json
import sqlite3

import httpx

from app.ai.cache import cached
from app.ai.client import AIUnavailable
from app.config import settings


def transcribe(conn: sqlite3.Connection, audio: bytes, filename: str) -> str:
    """Transcript of a WAV recording."""
    if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise AIUnavailable("Voice Transcribe only reads WAV; this recording wasn't converted in the browser")
    inputs = {"task": "transcribe", "audio": hashlib.sha256(audio).hexdigest()}
    return cached(conn, settings.voice_model, inputs, lambda: {"text": _request(audio, filename)})["text"]


def _request(audio: bytes, filename: str) -> str:
    if not settings.model_api_key:
        raise AIUnavailable("MODEL_API_KEY is not set")
    request = {"mode": "PUSH_TO_TALK", "model": settings.voice_model, "audioEncoding": "WAV"}
    r = httpx.post(
        settings.model_api_base_url.rstrip("/") + "/asr/transcribe",
        headers={"Authorization": f"Bearer {settings.model_api_key}"},
        files={"request": (None, json.dumps(request), "application/json"), "audio": (filename, audio, "audio/wav")},
        timeout=120,
    )
    r.raise_for_status()
    return (r.json().get("transcript") or "").strip()
