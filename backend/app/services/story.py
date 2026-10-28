"""Process story (M5): the whole history turned into a narrated breakdown for a portfolio or post.

Muse Wonder writes it from the history; without Wonder, a plain story is assembled from the same
facts (messages, measured changes, notes), so the button always produces something true.
"""

import logging
import re
import sqlite3

from app.ai import prompts, wonder

log = logging.getLogger("kitsune.story")


def history(conn: sqlite3.Connection, repo_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT c.id, c.seq, c.origin, c.message, c.auto_message, c.created_at, b.name AS branch"
        " FROM commits c JOIN branches b ON b.id = c.branch_id"
        " WHERE c.repo_id = ? AND b.kind NOT IN ('discarded', 'explore') ORDER BY c.seq",
        (repo_id,),
    ).fetchall()
    out = []
    for r in rows:
        notes = conn.execute(
            "SELECT kind, COALESCE(summary, transcript) AS text FROM voice_notes"
            " WHERE commit_id = ? AND COALESCE(summary, transcript) IS NOT NULL ORDER BY id",
            (r["id"],),
        ).fetchall()
        out.append({
            "version": f"v{r['seq']}", "branch": r["branch"], "origin": r["origin"],
            "what": r["message"] or r["auto_message"] or "", "measured": r["auto_message"] or "",
            "notes": [{"from": n["kind"], "text": n["text"]} for n in notes], "date": r["created_at"][:10],
        })
    return out


def _history_text(items: list[dict]) -> str:
    lines = []
    for i in items:
        lines.append(f"{i['version']} ({i['branch']}, {i['date']}, {i['origin']}): {i['what']}")
        lines += [f"   {n['from']} note: {n['text']}" for n in i["notes"]]
    return "\n".join(lines)


def template(name: str, items: list[dict]) -> str:
    """A plain process story from the history alone."""
    branches = sorted({i["branch"] for i in items})
    md = [f"# {name}: the process", ""]
    if items:
        span = items[0]["date"] if items[0]["date"] == items[-1]["date"] else f"{items[0]['date']} to {items[-1]['date']}"
        md += [
            f"{len(items)} versions on {len(branches)} branch{'es' if len(branches) != 1 else ''} ({', '.join(branches)}), {span}.",
            "",
        ]
    for i in items:
        md += [f"## [{i['version']}] {i['what'] or 'A new version'}", ""]
        if i["origin"] == "cherry_pick":
            md.append("An area from an earlier version was brought back here.")
        elif i["origin"] == "merge":
            md.append("Two directions came together here.")
        for n in i["notes"]:
            who = "The client asked" if n["from"] == "client" else "Why"
            md.append(f"> {who}: {n['text']}")
        md.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(md)).strip() + "\n"


def tell(conn: sqlite3.Connection, repo_id: int) -> dict:
    name = conn.execute("SELECT name FROM repos WHERE id = ?", (repo_id,)).fetchone()[0]
    items = history(conn, repo_id)
    if not items:
        return {"markdown": f"# {name}\n\nNo versions yet.\n", "source": "template"}
    try:
        text = wonder.chat(conn, [{"role": "user", "content": prompts.STORY.format(history=_history_text(items))}],
                           max_tokens=1200)["content"]
        if text.strip():
            return {"markdown": text.strip() + "\n", "source": "wonder"}
    except Exception as e:
        log.info("story fell back to the template: %s", e)
    return {"markdown": template(name, items), "source": "template"}
