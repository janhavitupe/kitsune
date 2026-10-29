"""Per-IP rate limits for the public demo, so the live link can't drain the model key.

Two sliding one-minute windows: "ai" for requests that may call models or render images, "write"
for every other change. Reads are never limited. In memory, which fits the single-process deploy.
"""

import re
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import settings

AI_PATHS = re.compile(
    r"^/api/(commits/\d+/(cherry-pick|explore|notes)|merges/\d+/resolve|repos/\d+/(assistant|story|merges))$"
)
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
WINDOW_S = 60.0

_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def client_ip(request: Request) -> str:
    # Behind Render's proxy the real client is the address the proxy appended last; the first
    # entry of X-Forwarded-For is whatever the client chose to send, so it can't be trusted.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def bucket(request: Request) -> str | None:
    if request.method not in WRITE_METHODS:
        return None
    return "ai" if AI_PATHS.match(request.url.path) else "write"


def limit_for(name: str) -> int:
    return settings.rate_limit_ai_per_min if name == "ai" else settings.rate_limit_writes_per_min


async def middleware(request: Request, call_next):
    name = bucket(request)
    if name is None or not settings.rate_limit_enabled:
        return await call_next(request)
    now = time.monotonic()
    hits = _hits[(client_ip(request), name)]
    while hits and now - hits[0] > WINDOW_S:
        hits.popleft()
    if len(hits) >= limit_for(name):
        retry = int(WINDOW_S - (now - hits[0])) + 1
        what = "AI requests" if name == "ai" else "changes"
        return JSONResponse(
            {"detail": f"Too many {what} in a minute; try again in {retry} s."},
            status_code=429,
            headers={"Retry-After": str(retry)},
        )
    hits.append(now)
    return await call_next(request)


def reset() -> None:
    _hits.clear()
