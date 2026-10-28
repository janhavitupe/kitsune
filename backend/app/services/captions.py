"""Captions for search (M4): one description per blob. Muse Spark normally; in private mode the
self-hosted open-weights model only, never the hosted API (M5)."""

import logging
import sqlite3

from app.ai import openweights, spark
from app.config import settings

log = logging.getLogger("kitsune.captions")


def is_private(conn: sqlite3.Connection, repo_id: int) -> bool:
    row = conn.execute("SELECT private_mode FROM repos WHERE id = ?", (repo_id,)).fetchone()
    return bool(row and row[0])


def save(conn: sqlite3.Connection, sha: str, text: str, model: str) -> None:
    conn.execute("INSERT OR REPLACE INTO captions (blob_sha, caption, model) VALUES (?, ?, ?)", (sha, text, model))


def caption_commit(conn: sqlite3.Connection, commit_id: int) -> None:
    """Analysis step: caption the commit's image if it has no caption yet."""
    c = conn.execute("SELECT blob_sha, repo_id FROM commits WHERE id = ?", (commit_id,)).fetchone()
    if conn.execute("SELECT 1 FROM captions WHERE blob_sha = ?", (c["blob_sha"],)).fetchone():
        return
    private = is_private(conn, c["repo_id"])
    try:
        if private:
            text, model = openweights.caption(conn, c["blob_sha"]), openweights.model_id()
        else:
            text, model = spark.caption(conn, c["blob_sha"]), settings.spark_model
    except Exception as e:
        # In private mode there is deliberately no fallback to the hosted model.
        log.info("caption skipped for %s (%s): %s", c["blob_sha"][:12], "private" if private else "hosted", e)
        return
    save(conn, c["blob_sha"], text, model)
