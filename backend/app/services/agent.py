"""Studio assistant (M5): Muse Wonder plans a multi-step ask, then carries it out with Kitsune's own
features as tools, at most MAX_TOOL_CALLS of them.

    ask ──▶ plan (no tools) ──▶ tool loop ──▶ final summary
                                   │
              list_commits · get_changes · get_regions · bring_back · adjust · try_variant · set_message

Nothing is overwritten: images the assistant makes land on a new `assistant/...` branch started
from the working version. run() yields events for the UI as they happen.
"""

import json
import logging
import sqlite3
import time
from collections.abc import Iterator

import numpy as np

from app import jobs, storage
from app.ai import prompts, wonder
from app.db import now
from app.services import cherry_pick, commits, diffing, explore

log = logging.getLogger("kitsune.agent")

MAX_TOOL_CALLS = 6
TIMEOUT_S = 90


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}


VERSION = {"type": "string", "description": "A version like \"v4\""}
TOOLS = [
    _fn("list_commits", "List the versions, oldest first, with branch, message and notes.", {}, []),
    _fn("get_changes", "What changed between two versions, as named regions with how they changed.",
        {"from_version": VERSION, "to_version": VERSION}, ["from_version", "to_version"]),
    _fn("get_regions", "The named regions (sky, figure, ...) of one version, if segmentation has run.",
        {"version": VERSION}, ["version"]),
    _fn("bring_back", "Bring one changed region of an older version back into the working version. "
        "The label must be a region name from get_changes(source_version, working version).",
        {"source_version": VERSION, "label": {"type": "string"}}, ["source_version", "label"]),
    _fn("adjust", "Recolor or relight the whole working version, e.g. \"warm it to match the sky\".",
        {"instruction": {"type": "string"}}, ["instruction"]),
    _fn("try_variant", "Make a palette variation of the working version on its own side branch.",
        {"direction": {"type": "string", "description": "e.g. \"cool moonlit night\""}}, ["direction"]),
    _fn("set_message", "Set the message of the newest version you made.", {"message": {"type": "string"}}, ["message"]),
]


class ToolError(ValueError):
    pass


class Run:
    def __init__(self, conn: sqlite3.Connection, repo_id: int, ask: str, start: int):
        self.conn, self.repo_id, self.ask = conn, repo_id, ask
        self.working = start
        self.branch_id: int | None = None  # the assistant branch, made on the first image
        self.created: list[int] = []

    # --- helpers ---------------------------------------------------------------------------

    def commit(self, ref: str | int) -> sqlite3.Row:
        s = str(ref).strip().lower().lstrip("v")
        row = self.conn.execute(
            "SELECT * FROM commits WHERE repo_id = ? AND seq = ?", (self.repo_id, int(s) if s.isdigit() else -1)
        ).fetchone()
        if row is None:
            raise ToolError(f"There is no version {ref}")
        return row

    def v(self, commit_id: int) -> str:
        return "v" + str(self.conn.execute("SELECT seq FROM commits WHERE id = ?", (commit_id,)).fetchone()[0])

    def ensure_branch(self) -> None:
        """Move the working version onto an assistant branch, so the original branch is untouched."""
        if self.branch_id is not None:
            return
        base = "assistant/" + explore.slug(self.ask)[:32]
        name, n = base, 1
        while self.conn.execute("SELECT 1 FROM branches WHERE repo_id = ? AND name = ?", (self.repo_id, name)).fetchone():
            n += 1
            name = f"{base}-{n}"
        self.branch_id = self.conn.execute(
            "INSERT INTO branches (repo_id, name, head_commit_id, kind, created_at) VALUES (?, ?, ?, 'normal', ?)",
            (self.repo_id, name, self.working, now()),
        ).lastrowid

    def made(self, commit_id: int) -> dict:
        jobs.run_analysis(commit_id)  # regions + auto message now, so the next step can use them
        self.created.append(commit_id)
        row = self.conn.execute("SELECT seq, message, blob_sha FROM commits WHERE id = ?", (commit_id,)).fetchone()
        return {"version": f"v{row['seq']}", "commit_id": commit_id, "message": row["message"],
                "thumb_url": f"/api/blobs/{row['blob_sha']}/thumb"}

    # --- tools -----------------------------------------------------------------------------

    def list_commits(self) -> dict:
        rows = self.conn.execute(
            "SELECT c.id, c.seq, b.name AS branch, COALESCE(c.message, c.auto_message, '') AS message,"
            " (SELECT group_concat(COALESCE(summary, transcript), ' | ') FROM voice_notes v WHERE v.commit_id = c.id) AS notes"
            " FROM commits c JOIN branches b ON b.id = c.branch_id"
            " WHERE c.repo_id = ? AND b.kind != 'discarded' ORDER BY c.seq",
            (self.repo_id,),
        ).fetchall()
        return {"working_version": self.v(self.working), "versions": [
            {"version": f"v{r['seq']}", "branch": r["branch"], "message": r["message"], "notes": r["notes"] or ""} for r in rows
        ]}

    def get_changes(self, from_version: str, to_version: str) -> dict:
        a, b = self.commit(from_version), self.commit(to_version)
        try:
            d = diffing.get_or_compute(self.conn, a["id"], b["id"])
        except diffing.DiffError as e:
            raise ToolError(str(e)) from e
        return {"summary": d["summary"], "regions": [
            {"label": r["label"], "changed": f"{round(r['changed_ratio'] * 100)}%", "how": r["hints"]} for r in d["regions"]
        ]}

    def get_regions(self, version: str) -> dict:
        c = self.commit(version)
        labels = [r[0] for r in self.conn.execute("SELECT label FROM regions WHERE blob_sha = ?", (c["blob_sha"],))]
        if not labels:
            return {"regions": [], "note": "Regions aren't named for this version yet; use get_changes instead."}
        return {"regions": labels}

    def bring_back(self, source_version: str, label: str) -> dict:
        source = self.commit(source_version)
        self.ensure_branch()
        try:
            new = cherry_pick.cherry_pick(self.conn, self.working, source["id"], label, branch_id=self.branch_id)
        except cherry_pick.CherryPickError as e:
            raise ToolError(str(e)) from e
        self.working = new
        return self.made(new)

    def adjust(self, instruction: str) -> dict:
        cur = self.conn.execute("SELECT * FROM commits WHERE id = ?", (self.working,)).fetchone()
        img = np.asarray(storage.load_rgb(self.conn, cur["blob_sha"]))
        try:
            out, used = explore.render(self.conn, img, cur["blob_sha"], instruction)
        except explore.ExploreError as e:
            raise ToolError(str(e)) from e
        self.ensure_branch()
        new = commits.create(
            self.conn, repo_id=self.repo_id, branch_id=self.branch_id, blob_sha=explore.save(self.conn, out),
            message=f"Assistant: {instruction}", origin="assistant",
            origin_meta={"ask": self.ask, "instruction": instruction, "method": used}, require_head=self.working,
        )
        self.working = new
        return self.made(new)

    def try_variant(self, direction: str) -> dict:
        cur = self.conn.execute("SELECT * FROM commits WHERE id = ?", (self.working,)).fetchone()
        img = np.asarray(storage.load_rgb(self.conn, cur["blob_sha"]))
        try:
            out, used = explore.render(self.conn, img, cur["blob_sha"], direction)
        except explore.ExploreError as e:
            raise ToolError(str(e)) from e
        return self.made(explore.branch_variant(self.conn, cur, direction, out, used, origin="assistant"))

    def set_message(self, message: str) -> dict:
        if not self.created:
            raise ToolError("You haven't made a version yet")
        self.conn.execute("UPDATE commits SET message = ? WHERE id = ?", (message.strip()[:200], self.created[-1]))
        return {"version": self.v(self.created[-1]), "message": message.strip()[:200]}

    def call(self, name: str, args: dict) -> dict:
        tool = getattr(self, name, None) if name in {t["function"]["name"] for t in TOOLS} else None
        if tool is None:
            raise ToolError(f"Unknown tool {name}")
        try:
            return tool(**args)
        except TypeError as e:
            raise ToolError(f"Bad arguments for {name}: {e}") from e


def run(conn: sqlite3.Connection, repo_id: int, ask: str, start_commit: int | None = None) -> Iterator[dict]:
    """Events: plan, tool_call, tool_result, final, error."""
    if start_commit is None:
        start_commit = conn.execute(
            "SELECT head_commit_id FROM branches WHERE repo_id = ? AND name = 'main'", (repo_id,)
        ).fetchone()[0]
    if start_commit is None:
        yield {"type": "error", "message": "Upload a version first"}
        return
    r = Run(conn, repo_id, ask, start_commit)
    deadline = time.monotonic() + TIMEOUT_S
    context = f"Working version: {r.v(start_commit)}\nHistory: {r.list_commits()['versions']}\n\nAsk: {ask}"
    messages = [{"role": "system", "content": prompts.ASSISTANT_SYSTEM}, {"role": "user", "content": context}]

    try:
        plan = wonder.chat(conn, messages + [{"role": "user", "content": prompts.ASSISTANT_PLAN}])["content"]
    except Exception as e:
        yield {"type": "error", "message": f"The assistant needs Muse Wonder, which is unavailable: {e}"}
        return
    yield {"type": "plan", "text": plan}
    messages += [{"role": "assistant", "content": plan}, {"role": "user", "content": prompts.ASSISTANT_GO}]

    calls, final = 0, None
    while final is None:
        if calls >= MAX_TOOL_CALLS or time.monotonic() > deadline:
            final = f"Stopped after {calls} steps to stay within the limit."
            break
        try:
            reply = wonder.chat(conn, messages, tools=TOOLS)
        except Exception as e:
            yield {"type": "error", "message": f"Muse Wonder stopped responding: {e}"}
            return
        if not reply["tool_calls"]:
            final = reply["content"] or "Done."
            break
        messages.append({"role": "assistant", "content": reply["content"], "tool_calls": [
            {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": _dumps(c["arguments"])}}
            for c in reply["tool_calls"]
        ]})
        for c in reply["tool_calls"]:
            if calls >= MAX_TOOL_CALLS:
                result = {"error": "Tool call limit reached"}
            else:
                calls += 1
                yield {"type": "tool_call", "step": calls, "name": c["name"], "arguments": c["arguments"]}
                try:
                    result = r.call(c["name"], c["arguments"])
                    yield {"type": "tool_result", "step": calls, "name": c["name"], "result": result}
                except ToolError as e:
                    result = {"error": str(e)}
                    yield {"type": "tool_result", "step": calls, "name": c["name"], "error": str(e)}
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": _dumps(result)})

    branch = conn.execute("SELECT name FROM branches WHERE id = ?", (r.branch_id,)).fetchone()[0] if r.branch_id else None
    yield {"type": "final", "text": final, "created": r.created, "working_commit": r.working if r.created else None, "branch": branch}


def _dumps(obj) -> str:
    return json.dumps(obj, default=str)
