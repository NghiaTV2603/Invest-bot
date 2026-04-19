"""L1 raw event log. Every chat turn, tool call, decision lands here."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from vnstock_bot.data.holidays import now_vn
from vnstock_bot.db.connection import get_connection, transaction
from vnstock_bot.memory import fts5
from vnstock_bot.memory.types import Event, EventInput, EventKind


def _row_to_event(row: sqlite3.Row) -> Event:
    return Event(
        id=row["id"],
        created_at=row["created_at"],
        kind=row["kind"],
        ticker=row["ticker"],
        decision_id=row["decision_id"],
        trace_id=row["trace_id"],
        summary=row["summary"],
        payload=json.loads(row["payload_json"]),
    )


def record_event(
    kind: EventKind,
    summary: str,
    payload: dict[str, Any] | None = None,
    ticker: str | None = None,
    decision_id: int | None = None,
    trace_id: str | None = None,
) -> int:
    inp = EventInput(
        kind=kind,
        summary=summary,
        payload=payload or {},
        ticker=ticker.upper() if ticker else None,
        decision_id=decision_id,
        trace_id=trace_id,
    )
    created_at = now_vn().isoformat()
    payload_json = json.dumps(inp.payload, ensure_ascii=False)

    with transaction() as conn:
        cur = conn.execute(
            """INSERT INTO events (created_at, kind, ticker, decision_id,
                                   trace_id, summary, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                created_at,
                inp.kind,
                inp.ticker,
                inp.decision_id,
                inp.trace_id,
                inp.summary,
                payload_json,
            ),
        )
        event_id = int(cur.lastrowid or 0)

    # Index separately — keeps FTS write out of the main txn, so an FTS
    # corruption won't block business writes.
    fts5.add_to_index(
        event_id=event_id,
        created_at=created_at,
        kind=inp.kind,
        ticker=inp.ticker,
        summary=inp.summary,
        payload_text=payload_json,
    )
    return event_id


def get_event(event_id: int) -> Event | None:
    row = get_connection().execute(
        "SELECT * FROM events WHERE id = ?", (event_id,)
    ).fetchone()
    return _row_to_event(row) if row else None


def get_timeline(
    ticker: str,
    days: int = 90,
    limit: int = 200,
) -> list[Event]:
    """All events mentioning one ticker within the last N days, newest first."""
    from datetime import timedelta
    since = (now_vn() - timedelta(days=days)).isoformat()
    rows = get_connection().execute(
        """SELECT * FROM events
           WHERE ticker = ? AND created_at >= ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (ticker.upper(), since, limit),
    ).fetchall()
    return [_row_to_event(r) for r in rows]


def recent_events(
    days: int = 7,
    kinds: tuple[EventKind, ...] | None = None,
    limit: int = 200,
) -> list[Event]:
    from datetime import timedelta
    since = (now_vn() - timedelta(days=days)).isoformat()
    conn = get_connection()
    if kinds:
        placeholders = ",".join("?" * len(kinds))
        rows = conn.execute(
            f"""SELECT * FROM events
                WHERE created_at >= ? AND kind IN ({placeholders})
                ORDER BY created_at DESC
                LIMIT ?""",
            (since, *kinds, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT * FROM events
               WHERE created_at >= ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (since, limit),
        ).fetchall()
    return [_row_to_event(r) for r in rows]
