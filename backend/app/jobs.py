"""Background analysis that runs after a commit has already been returned to the client.

M1 only moves the status through pending -> running -> done. Later milestones append steps:
M2 segmentation + diff + auto message, M4 caption + search index.
"""

import logging
import sqlite3
from collections.abc import Callable

from app import db

log = logging.getLogger("kitsune.jobs")

AnalysisStep = Callable[[sqlite3.Connection, int], None]
ANALYSIS_STEPS: list[AnalysisStep] = []


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
