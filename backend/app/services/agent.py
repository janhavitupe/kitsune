"""Studio assistant (M5): Muse Wonder plans a multi-step ask, then carries it out with Kitsune's own
features as tools, at most MAX_TOOL_CALLS of them.

    ask ──▶ plan (no tools) ──▶ tool loop ──▶ final summary
                                   │
              list_commits · get_changes · get_regions · bring_back · adjust · try_variant · set_message

Nothing is overwritten: images the assistant makes land on a new `assistant/...` branch started
from the working version. Nothing is painted either: the tools only copy the artist's own pixels
between versions or shift their colors. run() yields events for the UI as they happen.
"""

import json
import logging
import re
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
    _fn("bring_back", "Copy one region of an older version back into the working version, pixel for pixel. "
        "The label is a region name from get_changes(source_version, working version), or with drawn=true, "
        "a region from get_changes(the version before source_version, source_version): something the artist "
        "drew in that version. Anything drawn later stays as it is.",
        {"source_version": VERSION, "label": {"type": "string"},
         "drawn": {"type": "boolean", "description": "label is something drawn in source_version itself"}},
        ["source_version", "label"]),
    _fn("adjust", "Shift the colors of the whole working version: warm, cool, muted, brighter or darker.",
        {"instruction": {"type": "string"}}, ["instruction"]),
    _fn("try_variant", "Make a color-shifted copy of the working version (warm, cool, muted, brighter or darker) "
        "on its own side branch.",
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

    def bring_back(self, source_version: str, label: str, drawn: bool = False, name: str | None = None) -> dict:
        source = self.commit(source_version)
        self.ensure_branch()
        try:
            new = cherry_pick.cherry_pick(
                self.conn, self.working, source["id"], label, drawn, branch_id=self.branch_id, name=name,
            )
        except cherry_pick.CherryPickError as e:
            raise ToolError(str(e)) from e
        self.working = new
        return self.made(new)

    def adjust(self, instruction: str) -> dict:
        cur = self.conn.execute("SELECT * FROM commits WHERE id = ?", (self.working,)).fetchone()
        img = np.asarray(storage.load_rgb(self.conn, cur["blob_sha"]))
        try:
            out = explore.render(img, instruction)
        except explore.ExploreError as e:
            raise ToolError(str(e)) from e
        self.ensure_branch()
        new = commits.create(
            self.conn, repo_id=self.repo_id, branch_id=self.branch_id, blob_sha=explore.save(self.conn, out),
            message=f"Assistant: {instruction}", origin="assistant",
            origin_meta={"ask": self.ask, "instruction": instruction}, require_head=self.working,
        )
        self.working = new
        return self.made(new)

    def try_variant(self, direction: str) -> dict:
        cur = self.conn.execute("SELECT * FROM commits WHERE id = ?", (self.working,)).fetchone()
        img = np.asarray(storage.load_rgb(self.conn, cur["blob_sha"]))
        try:
            out = explore.render(img, direction)
        except explore.ExploreError as e:
            raise ToolError(str(e)) from e
        return self.made(explore.branch_variant(self.conn, cur, direction, out, origin="assistant"))

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
        log.info("Muse Wonder unavailable, following the ask with rules: %s", e)
        steps, skipped = rule_steps(ask)
        if not steps:
            examples = "; ".join(f'"{x}"' for x in RULE_EXAMPLES)
            yield {"type": "error", "message": f"Muse Wonder is unavailable right now. Without it I can follow simple asks like {examples}."}
            return
        lines = "\n".join(f"{i}. {st.describe}" for i, st in enumerate(steps, 1))
        if skipped:
            lines += "\nSkipping (needs Muse Wonder): " + "; ".join(f'"{x}"' for x in skipped)
        yield {"type": "plan", "text": f"Muse Wonder is unavailable, so I'm following your ask step by step:\n{lines}"}
        final = yield from run_rule_steps(r, steps)
        yield _final(conn, r, final)
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

    yield _final(conn, r, final)


def _final(conn: sqlite3.Connection, r: Run, text: str) -> dict:
    branch = conn.execute("SELECT name FROM branches WHERE id = ?", (r.branch_id,)).fetchone()[0] if r.branch_id else None
    return {"type": "final", "text": text, "created": r.created, "working_commit": r.working if r.created else None, "branch": branch}


def _dumps(obj) -> str:
    return json.dumps(obj, default=str)


# --- without Muse Wonder ---------------------------------------------------------------------------
# Simple asks are split into clauses and each clause becomes one tool call, so the assistant still
# works, with the same tools and the steps shown live, when the model is down or out of quota.

RULE_EXAMPLES = [
    "take the sky from v2 and warm it",
    "what changed since v3, then try a moonlit variant",
    'bring back the top-left area from v1 and call it "old patch"',
    "bring back the lantern",
]

# Without segmentation, change areas are named by position ("top area"); map common words onto them.
PLACE_WORDS = {
    "top": ("sky", "skies", "cloud", "clouds", "sun", "moon", "stars", "ceiling", "upper"),
    "bottom": ("ground", "grass", "floor", "water", "sea", "lake", "river", "road", "field", "lower"),
    "left": (),
    "right": (),
    "center": ("middle", "centre"),
}
FILLER = re.compile(r"^(?:the|my|old|original|previous|earlier|that|this)\s+")
MESSAGE = re.compile(r"\b(?:call it|name it)\s*:?\s*[\"“]([^\"”]+)[\"”]", re.I)
CLAUSE_SPLIT = re.compile(r"\s*(?:,|;|\.(?!\d)|\bthen\b|\band\b)\s*", re.I)
BRING_BACK = re.compile(r"(?:\b(?:take|bring back|bring|restore|use|get|keep|put back|reuse)\s+|^)(.+?)\s+from\s+v(\d+)\b")
BRING_BACK_NAMED = re.compile(r"\b(?:bring back|restore|put back|reuse)\s+(.+)$")
VARIANT_WORDS = re.compile(r"\b(try|a|an|variant|variation|alternative|option|version)\b")


class Step:
    def __init__(self, tool: str, args: dict, describe: str):
        self.tool, self.args, self.describe = tool, args, describe


def rule_steps(ask: str) -> tuple[list[Step], list[str]]:
    """The steps for an ask, and the parts of it the rules can't follow."""
    steps: list[Step] = []
    skipped: list[str] = []
    message = None
    if m := MESSAGE.search(ask):
        message = m.group(1).strip()
        ask = ask[: m.start()] + ask[m.end() :]
    for clause in CLAUSE_SPLIT.split(ask):
        c = clause.strip().lower()
        if not c:
            continue
        versions = re.findall(r"\bv(\d+)\b", c)
        if versions and re.search(r"\b(what changed|changes?|compare|difference|diff)\b", c):
            a = f"v{versions[0]}"
            b = f"v{versions[1]}" if len(versions) > 1 else "working"
            steps.append(Step("get_changes", {"from_version": a, "to_version": b},
                              f"See what changed between {a} and {'the working version' if b == 'working' else b}"))
        elif fm := BRING_BACK.search(c):
            what, source = FILLER.sub("", fm.group(1).strip()), f"v{fm.group(2)}"
            steps.append(Step("bring_back", {"source_version": source, "label": what}, f"Bring back the {what} from {source}"))
        elif fm := BRING_BACK_NAMED.search(c):
            what = FILLER.sub("", fm.group(1).strip())
            steps.append(Step("bring_back", {"source_version": None, "label": what}, f"Bring back the {what}"))
        elif re.search(r"\b(try|variant|variation|alternative|option)\b", c) and explore.preset_for(c):
            direction = " ".join(VARIANT_WORDS.sub(" ", c).split()) or c
            steps.append(Step("try_variant", {"direction": direction}, f"Try a {direction} variation on a side branch"))
        elif explore.preset_for(c):
            steps.append(Step("adjust", {"instruction": c}, f"Adjust the colors: {c}"))
        elif not re.match(r"(keep|leave)\b", c):  # "keep today's figure" is already the case
            skipped.append(clause.strip())
    if message:
        steps.append(Step("set_message", {"message": message}, f'Name the result "{message}"'))
    return steps[:MAX_TOOL_CALLS], skipped


def _words(text: str) -> list[str]:
    return [w for w in text.lower().replace("-", " ").split() if len(w) > 2]


def drawn_in(r: Run, what: str) -> str:
    """The version where the artist drew `what`: the newest one whose message or notes mention it."""
    for w in _words(what):
        row = r.conn.execute(
            "SELECT c.seq FROM commits c LEFT JOIN voice_notes n ON n.commit_id = c.id"
            " WHERE c.repo_id = ? AND c.origin = 'upload'"
            " AND (c.message LIKE ? OR n.transcript LIKE ? OR n.summary LIKE ?) ORDER BY c.seq DESC LIMIT 1",
            (r.repo_id, *[f"%{w}%"] * 3),
        ).fetchone()
        if row:
            return f"v{row[0]}"
    raise ToolError(f"No version's message or notes mention '{what}'. Say which one, e.g. \"bring back the {what} from v3\"")


def resolve_label(r: Run, source_version: str, what: str) -> tuple[str, bool]:
    """The region the artist means by `what`, and whether it was drawn in the source itself.

    First a region that changed since the source: one sharing a word with `what`, or the one change
    area in the place the word implies (sky -> top). Otherwise something drawn in the source version
    (its change from the version before): the one sharing a word, or the only thing drawn there.
    Never a guess between several.
    """
    labels = [x["label"] for x in r.get_changes(source_version, r.v(r.working))["regions"]]
    if not labels:
        raise ToolError(f"Nothing changed between {source_version} and the working version")
    words = _words(what)
    direct = [lb for lb in labels if any(w in _words(lb) for w in words)]
    if len(direct) == 1:
        return direct[0], False
    places = [p for p, synonyms in PLACE_WORDS.items() if p in words or any(s in words for s in synonyms)]
    near = [lb for lb in labels if any(p in _words(lb) for p in places)]
    if len(near) == 1:
        return near[0], False

    drawn = cherry_pick.drawn_labels(r.conn, r.commit(source_version)["id"])
    named = [lb for lb in drawn if any(w in _words(lb) for w in words)]
    if len(named) == 1 or len(drawn) == 1:
        return (named or drawn)[0], True
    raise ToolError(f"No changed region matches '{what}'. What changed since {source_version}: {', '.join(labels)}")


def run_rule_steps(r: Run, steps: list[Step]) -> Iterator[dict]:
    """Run the steps in order, yielding tool events. Returns the summary for the final event."""
    done = []
    for i, st in enumerate(steps, 1):
        args = dict(st.args)
        if args.get("to_version") == "working":
            args["to_version"] = r.v(r.working)
        called = False
        try:
            if st.tool == "bring_back":
                what = args["label"]
                args["source_version"] = args["source_version"] or drawn_in(r, what)
                args["label"], args["drawn"] = resolve_label(r, args["source_version"], what)
                args["name"] = what
            yield {"type": "tool_call", "step": i, "name": st.tool, "arguments": args}
            called = True
            result = r.call(st.tool, args)
        except ToolError as e:
            if not called:
                yield {"type": "tool_call", "step": i, "name": st.tool, "arguments": args}
            yield {"type": "tool_result", "step": i, "name": st.tool, "error": str(e)}
            done.append(f"couldn't {st.describe[0].lower()}{st.describe[1:]}: {e}")
            continue
        yield {"type": "tool_result", "step": i, "name": st.tool, "result": result}
        made = f" ({result['version']})" if st.tool != "set_message" and "version" in result else ""
        done.append(f"{st.describe[0].lower()}{st.describe[1:]}{made}")
    text = ("Done: " + "; then ".join(done) + ".") if done else "Nothing to do."
    if r.created:
        text += " Your original branch is untouched; the new versions are on their own branch."
    return text
