"""Background analysis that runs after a commit has already been returned to the client.

Steps run in order: segment the image (SAM), diff against the parent and write the auto message,
caption the image, then index everything for search.
"""

import logging
import sqlite3
from collections.abc import Callable

from app import db
from app.services import captions, diffing, search, segmentation

log = logging.getLogger("kitsune.jobs")

AnalysisStep = Callable[[sqlite3.Connection, int], None]
ANALYSIS_STEPS: list[AnalysisStep] = [
    segmentation.segment_commit,
    diffing.diff_commit_with_parent,
    captions.caption_commit,
    search.index_commit,
]


def _set_status(conn: sqlite3.Connection, commit_id: int, status: str) -> None:
    conn.execute("UPDATE commits SET analysis_status = ? WHERE id = ?", (status, commit_id))


def run_analysis(commit_id: int) -> None:
    conn = db.connect()
    try:
        _set_status(conn, commit_id, "running")
        for step in ANALYSIS_STEPS:
            step(conn, commit_id)
        _set_status(conn, commit_id, "done")
    except Exception:
        log.exception("analysis failed for commit %s", commit_id)
        _set_status(conn, commit_id, "failed")
    finally:
        conn.close()
