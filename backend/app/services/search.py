"""Searchable history (M4): full-text search over everything said about a version, plus
"before / after / when I changed X" queries resolved against the commit graph.

The index row of a commit holds its message, auto message, caption, notes and the regions its
diff against the parent found. It is rebuilt whenever any of those change.
"""

import logging
import re
import sqlite3

from app.ai import openweights, spark
from app.services import diffing

log = logging.getLogger("kitsune.search")

STOPWORDS = {
    "a", "an", "the", "i", "we", "you", "my", "our", "it", "its", "was", "were", "is", "of", "to", "in",
    "on", "at", "and", "or", "me", "show", "find", "version", "versions", "one", "that", "this", "what",
    "did", "do", "look", "like", "made", "make", "changed", "change", "changing", "painted", "where",
}
RELATIONS = {"before": "before", "until": "before", "after": "after", "since": "after", "when": "when"}
TEMPORAL = re.compile(r"\b(before|until|after|since|when)\b", re.I)


def _text(conn: sqlite3.Connection, sql: str, *args) -> str:
    return " ".join(r[0] for r in conn.execute(sql, args).fetchall() if r[0])


def index_commit(conn: sqlite3.Connection, commit_id: int) -> None:
    c = conn.execute("SELECT * FROM commits WHERE id = ?", (commit_id,)).fetchone()
    regions = ""
    if c["parent_id"] is not None:
        diff = diffing.get_cached(conn, c["parent_id"], commit_id)
        if diff:
            regions = " ".join(f"{r['label']} {' '.join(r['hints'])}" for r in diff["regions"])
    caption = _text(conn, "SELECT caption FROM captions WHERE blob_sha = ?", c["blob_sha"])
    # Client notes are tagged so "after the client feedback" finds them even if the client never said so.
    notes = _text(
        conn,
        "SELECT CASE kind WHEN 'client' THEN 'client feedback: ' ELSE '' END"
        " || COALESCE(transcript, '') || ' ' || COALESCE(summary, '') FROM voice_notes WHERE commit_id = ?",
        commit_id,
    )
    conn.execute("DELETE FROM search_index WHERE commit_id = ?", (commit_id,))
    conn.execute(
        "INSERT INTO search_index (commit_id, message, auto_message, caption, voice, region_labels) VALUES (?, ?, ?, ?, ?, ?)",
        (commit_id, c["message"] or "", c["auto_message"] or "", caption, notes.strip(), regions),
    )


def tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


def _fts(words: list[str], any_word: bool = False) -> str:
    return (" OR " if any_word else " ").join(f'"{w}"*' for w in words)


def _match(conn: sqlite3.Connection, repo_id: int, words: list[str], limit: int, order: str = "score") -> list[sqlite3.Row]:
    if not words:
        return []
    sql = (
        "SELECT c.id AS commit_id, c.seq, c.parent_id, bm25(search_index) AS score,"
        " snippet(search_index, -1, '[', ']', '…', 10) AS snippet"
        " FROM search_index JOIN commits c ON c.id = search_index.commit_id"
        f" WHERE search_index MATCH ? AND c.repo_id = ? ORDER BY {'c.seq' if order == 'seq' else 'score'} LIMIT ?"
    )
    rows = conn.execute(sql, (_fts(words), repo_id, limit)).fetchall()
    if not rows and len(words) > 1:  # nothing has every word: fall back to any word
        rows = conn.execute(sql, (_fts(words, any_word=True), repo_id, limit)).fetchall()
    return rows


def parse(conn: sqlite3.Connection, query: str, private: bool = False) -> dict:
    """Split a query into relation / anchor / terms: a model when available (Muse Spark, or the
    open-weights model in private mode), rules otherwise."""
    if TEMPORAL.search(query):
        try:
            if private:
                return {**openweights.rewrite_query(conn, query), "parser": "open-weights"}
            return {**spark.rewrite_query(conn, query), "parser": "spark"}
        except Exception as e:
            log.info("query rewrite fell back to rules: %s", e)
    m = TEMPORAL.search(query)
    if not m:
        return {"relation": None, "anchor": "", "terms": query, "parser": "rules"}
    return {
        "relation": RELATIONS[m.group(1).lower()],
        "anchor": query[m.end():],
        "terms": query[: m.start()],
        "parser": "rules",
    }


def search(conn: sqlite3.Connection, repo_id: int, query: str, limit: int = 20) -> dict:
    private = bool(conn.execute("SELECT private_mode FROM repos WHERE id = ?", (repo_id,)).fetchone()[0])
    p = parse(conn, query, private)
    results: list[dict] = []

    if p["relation"] and (anchor_words := tokens(p["anchor"])):
        # The first version where the anchor change shows up marks the moment.
        anchor = next(iter(_match(conn, repo_id, anchor_words, 1, order="seq")), None)
        if anchor:
            where = f"v{anchor['seq']}, where {anchor['snippet']}"
            if p["relation"] == "before":
                if anchor["parent_id"] is None:
                    results.append({"commit_id": anchor["commit_id"], "seq": anchor["seq"], "snippet": anchor["snippet"],
                                    "reason": f"Nothing comes before {where}"})
                else:
                    seq = conn.execute("SELECT seq FROM commits WHERE id = ?", (anchor["parent_id"],)).fetchone()[0]
                    results.append({"commit_id": anchor["parent_id"], "seq": seq, "snippet": "",
                                    "reason": f"The version just before {where}"})
            else:
                label = "The version after the change: " if p["relation"] == "after" else "The change itself: "
                results.append({"commit_id": anchor["commit_id"], "seq": anchor["seq"], "snippet": anchor["snippet"],
                                "reason": label + where})

    seen = {r["commit_id"] for r in results}
    words = tokens(p["terms"]) or ([] if results else tokens(query))
    for row in _match(conn, repo_id, words, limit):
        if row["commit_id"] not in seen:
            results.append({"commit_id": row["commit_id"], "seq": row["seq"], "snippet": row["snippet"], "reason": "Matches the search"})
            seen.add(row["commit_id"])
    return {"query": query, "relation": p["relation"], "parser": p["parser"], "results": results[:limit]}
