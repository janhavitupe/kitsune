"""Captions for search (M4): Muse Spark describes each version once per blob.
M5 adds an open-weights captioner for private mode."""

import logging
import sqlite3

from app.ai import spark
from app.config import settings

log = logging.getLogger("kitsune.captions")


def caption_commit(conn: sqlite3.Connection, commit_id: int) -> None:
    """Analysis step: caption the commit's image if it has no caption yet."""
    sha = conn.execute("SELECT blob_sha FROM commits WHERE id = ?", (commit_id,)).fetchone()[0]
    if conn.execute("SELECT 1 FROM captions WHERE blob_sha = ?", (sha,)).fetchone():
        return
    try:
        text = spark.caption(conn, sha)
    except Exception as e:
        log.info("caption skipped for %s: %s", sha[:12], e)
        return
    conn.execute(
        "INSERT OR REPLACE INTO captions (blob_sha, caption, model) VALUES (?, ?, ?)", (sha, text, settings.spark_model)
    )
