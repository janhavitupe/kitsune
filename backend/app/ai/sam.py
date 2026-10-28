"""SAM 3.1 over the Meta Model API: text-prompted segmentation.

Not wired up yet: the request and response shapes come from running scripts/probe_model_api.py
(M1). When they are known, implement segment() to return one RawMask per detected instance, cached
through app.ai.cache by (blob sha, labels). Fallback if the API can't do it: SAM 3.1 weights on a
Modal GPU behind this same function.
"""

import sqlite3
from typing import TYPE_CHECKING

from app.ai.client import AIUnavailable

if TYPE_CHECKING:
    from app.services.segmentation import RawMask


def segment(conn: sqlite3.Connection, sha: str, labels: list[str]) -> list["RawMask"]:
    raise AIUnavailable("SAM 3.1 is not connected yet (waiting on the Model API probe)")
