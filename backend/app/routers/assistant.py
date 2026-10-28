import json
import sqlite3

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import db
from app.db import get_db
from app.routers.common import get_repo_or_404
from app.services import agent, story

router = APIRouter(tags=["assistant"])


class AssistantRequest(BaseModel):
    ask: str = Field(min_length=1, max_length=500)
    start_commit: int | None = None  # the working version; defaults to the head of main


@router.post("/repos/{repo_id}/assistant")
def run_assistant(repo_id: int, body: AssistantRequest, conn: sqlite3.Connection = Depends(get_db)):
    """Stream the assistant's run as server-sent events: plan, tool_call, tool_result, final, error."""
    get_repo_or_404(conn, repo_id)

    def events():
        # Its own connection: the request's is closed once the response starts streaming.
        run_conn = db.connect()
        try:
            for event in agent.run(run_conn, repo_id, body.ask, body.start_commit):
                yield f"data: {json.dumps(event, default=str)}\n\n"
        finally:
            run_conn.close()

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


class Story(BaseModel):
    markdown: str
    source: str  # wonder | template


@router.post("/repos/{repo_id}/story", response_model=Story)
def make_story(repo_id: int, conn: sqlite3.Connection = Depends(get_db)):
    """The history as a narrated process breakdown, in markdown with [v3]-style version references."""
    get_repo_or_404(conn, repo_id)
    return story.tell(conn, repo_id)
