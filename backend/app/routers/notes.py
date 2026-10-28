import sqlite3

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app import storage
from app.db import get_db
from app.routers.common import get_commit_or_404
from app.schemas import Note
from app.services import notes

router = APIRouter(tags=["notes"])


def to_note(row: sqlite3.Row) -> Note:
    d = dict(row)
    audio = d.pop("audio_path")
    return Note(**d, audio_url=f"/api/notes/{row['id']}/audio" if audio else None)


@router.get("/commits/{commit_id}/notes", response_model=list[Note])
def list_notes(commit_id: int, conn: sqlite3.Connection = Depends(get_db)):
    get_commit_or_404(conn, commit_id)
    rows = conn.execute("SELECT * FROM voice_notes WHERE commit_id = ? ORDER BY id", (commit_id,)).fetchall()
    return [to_note(r) for r in rows]


@router.post("/commits/{commit_id}/notes", status_code=201, response_model=Note)
def add_note(
    commit_id: int,
    kind: str = Form("artist"),
    text: str | None = Form(None),
    audio: UploadFile | None = File(None),
    conn: sqlite3.Connection = Depends(get_db),
):
    """Pin a note to a version: typed text, a recording (transcribed), or both."""
    get_commit_or_404(conn, commit_id)
    try:
        note_id = notes.add(
            conn, commit_id, kind, text=text,
            audio=audio.file.read() if audio else None, filename=audio.filename if audio else None,
        )
    except notes.NoteError as e:
        raise HTTPException(e.status_code, str(e)) from e
    return to_note(notes.get_row(conn, note_id))


@router.post("/notes/{note_id}/transcribe", response_model=Note)
def transcribe_note(note_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        notes.transcribe_again(conn, note_id)
        return to_note(notes.get_row(conn, note_id))
    except notes.NoteError as e:
        raise HTTPException(e.status_code, str(e)) from e


@router.delete("/notes/{note_id}", status_code=204)
def delete_note(note_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        notes.delete(conn, note_id)
    except notes.NoteError as e:
        raise HTTPException(e.status_code, str(e)) from e


@router.get("/notes/{note_id}/audio")
def get_note_audio(note_id: int, conn: sqlite3.Connection = Depends(get_db)):
    try:
        row = notes.get_row(conn, note_id)
    except notes.NoteError as e:
        raise HTTPException(e.status_code, str(e)) from e
    if not row["audio_path"]:
        raise HTTPException(404, "This note has no recording")
    return FileResponse(storage.abs_path(row["audio_path"]))
