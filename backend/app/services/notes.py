"""Notes pinned to a version (M4): typed or recorded, the artist's own or a client's feedback.

Audio is transcribed by Muse Voice Transcribe. Without the model the note is still saved with its
audio, and can be transcribed later. Long notes get a one-line (artist) or bullet-list (client)
summary from Muse Spark.
"""

import hashlib
import logging
import re
import sqlite3
from pathlib import PurePath

from app import storage
from app.ai import spark, voice
from app.db import now
from app.services import search

log = logging.getLogger("kitsune.notes")

KINDS = ("artist", "client")
AUDIO_EXTENSIONS = {"webm", "ogg", "oga", "mp3", "m4a", "mp4", "wav", "flac", "aac"}
MAX_AUDIO_MB = 20
SUMMARY_AFTER_SENTENCES = 3


class NoteError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _sentences(text: str) -> int:
    return len([s for s in re.split(r"[.!?]+(?:\s|$)", text) if s.strip()])


def _summary(conn: sqlite3.Connection, text: str | None, kind: str) -> str | None:
    if not text or _sentences(text) <= SUMMARY_AFTER_SENTENCES:
        return None
    try:
        return spark.summarize_note(conn, text, kind)
    except Exception as e:
        log.info("note summary skipped: %s", e)
        return None


def _transcribe(conn: sqlite3.Connection, audio: bytes, filename: str) -> str | None:
    try:
        return voice.transcribe(conn, audio, filename) or None
    except Exception as e:
        log.info("transcription skipped: %s", e)
        return None


def add(
    conn: sqlite3.Connection, commit_id: int, kind: str, text: str | None = None,
    audio: bytes | None = None, filename: str | None = None,
) -> int:
    if kind not in KINDS:
        raise NoteError(f"kind must be one of {', '.join(KINDS)}")
    text = (text or "").strip() or None
    if not text and not audio:
        raise NoteError("Add some text or a recording")

    audio_path = None
    if audio:
        if len(audio) > MAX_AUDIO_MB * 1024 * 1024:
            raise NoteError(f"Recording is larger than {MAX_AUDIO_MB} MB", 413)
        ext = PurePath(filename or "").suffix.lower().lstrip(".")
        if ext not in AUDIO_EXTENSIONS:
            raise NoteError(f"Unsupported audio type '{ext or '?'}'. Use one of: {', '.join(sorted(AUDIO_EXTENSIONS))}", 415)
        audio_path = f"audio/{hashlib.sha256(audio).hexdigest()}.{ext}"
        path = storage.abs_path(audio_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        # A typed note that comes with audio keeps the typed text.
        text = text or _transcribe(conn, audio, PurePath(audio_path).name)

    note_id = conn.execute(
        "INSERT INTO voice_notes (commit_id, kind, audio_path, transcript, summary, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (commit_id, kind, audio_path, text, _summary(conn, text, kind), now()),
    ).lastrowid
    search.index_commit(conn, commit_id)
    return note_id


def transcribe_again(conn: sqlite3.Connection, note_id: int) -> None:
    """Retry transcription of a recorded note (e.g. once the model key is configured)."""
    note = get_row(conn, note_id)
    if not note["audio_path"]:
        raise NoteError("This note has no recording")
    path = storage.abs_path(note["audio_path"])
    text = _transcribe(conn, path.read_bytes(), path.name)
    if text is None:
        raise NoteError("Transcription is unavailable right now", 503)
    conn.execute(
        "UPDATE voice_notes SET transcript = ?, summary = ? WHERE id = ?",
        (text, _summary(conn, text, note["kind"]), note_id),
    )
    search.index_commit(conn, note["commit_id"])


def get_row(conn: sqlite3.Connection, note_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM voice_notes WHERE id = ?", (note_id,)).fetchone()
    if row is None:
        raise NoteError(f"Note {note_id} not found", 404)
    return row


def delete(conn: sqlite3.Connection, note_id: int) -> None:
    note = get_row(conn, note_id)
    conn.execute("DELETE FROM voice_notes WHERE id = ?", (note_id,))
    search.index_commit(conn, note["commit_id"])
