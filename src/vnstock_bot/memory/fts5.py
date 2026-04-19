"""Thin wrapper over the events_fts virtual table.

Write path is called from memory/events.py on every insert. Read path is
called from memory/recall.py. No other module should import this directly —
go through memory/recall.py for queries.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from vnstock_bot.db.connection import get_connection, transaction
from vnstock_bot.memory.tokenizer import normalize


@dataclass
class FtsHit:
    event_id: int
    created_at: str
    kind: str
    ticker: str | None
    summary: str
    payload_text: str
    score: float                    # lower = better (bm25 convention)


def fts5_available() -> bool:
    try:
        get_connection().execute("SELECT count(*) FROM events_fts").fetchone()
        return True
    except sqlite3.DatabaseError:
        return False


def add_to_index(
    event_id: int,
    created_at: str,
    kind: str,
    ticker: str | None,
    summary: str,
    payload_text: str,
) -> None:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO events_fts
               (rowid, summary, payload_text, ticker, kind, event_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (event_id, summary, payload_text, ticker, kind, event_id, created_at),
        )


def delete_from_index(event_id: int) -> None:
    with transaction() as conn:
        conn.execute("DELETE FROM events_fts WHERE rowid = ?", (event_id,))


def _sanitize_query(query: str) -> str:
    # FTS5 MATCH uses special chars (AND/OR/NEAR/", etc). Feeding user input
    # raw risks fts5 syntax errors. We normalize to lowercase-ascii tokens and
    # OR them — matches FTS5's own unicode61 output, so queries like "tăng
    # trưởng FPT" → "tang OR truong OR fpt".
    from vnstock_bot.memory.tokenizer import tokenize
    tokens = tokenize(query)
    if not tokens:
        return ""
    return " OR ".join(tokens)


def search(
    query: str,
    k: int = 5,
    kind: str | None = None,
    ticker: str | None = None,
) -> list[FtsHit]:
    fts_query = _sanitize_query(query)
    if not fts_query:
        return []

    sql = (
        "SELECT event_id, created_at, kind, ticker, summary, payload_text, "
        "       bm25(events_fts, 2.0, 1.0) AS score "
        "FROM events_fts "
        "WHERE events_fts MATCH ? "
    )
    params: list[object] = [fts_query]
    if kind:
        sql += "AND kind = ? "
        params.append(kind)
    if ticker:
        sql += "AND ticker = ? "
        params.append(normalize(ticker).upper())
    sql += "ORDER BY score LIMIT ?"
    params.append(k)

    rows = get_connection().execute(sql, params).fetchall()
    return [
        FtsHit(
            event_id=r["event_id"],
            created_at=r["created_at"],
            kind=r["kind"],
            ticker=r["ticker"],
            summary=r["summary"],
            payload_text=r["payload_text"],
            score=float(r["score"]),
        )
        for r in rows
    ]


def rebuild_index() -> int:
    """Drop + repopulate events_fts from events. Returns row count."""
    conn = get_connection()
    with transaction():
        conn.execute("DELETE FROM events_fts")
        conn.execute(
            """INSERT INTO events_fts
               (rowid, summary, payload_text, ticker, kind, event_id, created_at)
               SELECT id, summary, payload_json, ticker, kind, id, created_at
               FROM events"""
        )
    return conn.execute("SELECT count(*) AS n FROM events_fts").fetchone()["n"]
