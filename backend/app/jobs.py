"""Background analysis that runs after a commit has already been returned to the client.

Steps run in order: segment the image (SAM), diff against the parent and write the auto message,
caption the image, then index everything for search.
"""

import logging
import sqlite3
import threading
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


# One analysis at a time: they're CPU-bound in one process, so running them side by side only
# makes each slower, and it keeps native libraries from being entered from many threads at once.
_one_at_a_time = threading.Lock()


def run_analysis(commit_id: int) -> None:
    with _one_at_a_time:
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


def resume_unfinished() -> list[int]:
    """Analyses cut off by a restart or redeploy stay 'running' forever; queue them again."""
    conn = db.connect()
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM commits WHERE analysis_status IN ('pending', 'running') ORDER BY seq")]
    finally:
        conn.close()
    if ids:
        log.info("resuming analysis for %d version(s)", len(ids))
        threading.Thread(target=lambda: [run_analysis(i) for i in ids], name="resume-analysis", daemon=True).start()
    return ids
