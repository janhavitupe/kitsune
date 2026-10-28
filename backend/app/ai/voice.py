"""Muse Voice Transcribe: speech to text for voice notes and client voice feedback."""

import hashlib
import sqlite3

from app.ai.cache import cached
from app.ai.client import model_api
from app.config import settings


def transcribe(conn: sqlite3.Connection, audio: bytes, filename: str) -> str:
    """Transcript of an audio file. The format is passed through as uploaded; confirm with the probe
    which formats the API accepts (browser recordings are webm/opus)."""
    inputs = {"task": "transcribe", "audio": hashlib.sha256(audio).hexdigest()}

    def call() -> dict:
        r = model_api().audio.transcriptions.create(model=settings.voice_model, file=(filename, audio))
        return {"text": (r.text or "").strip()}

    return cached(conn, settings.voice_model, inputs, call)["text"]
