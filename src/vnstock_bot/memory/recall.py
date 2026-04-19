"""High-level memory recall API.

Combines events (FTS5) + memory files (Python-side scoring) into a single
ranked result set. This is what tools exposed to the research agent use.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from vnstock_bot.data.holidays import now_vn
from vnstock_bot.db.connection import get_connection
from vnstock_bot.memory import files, fts5
from vnstock_bot.memory.tokenizer import token_set
from vnstock_bot.memory.types import MemoryFile

HitSource = Literal["event", "file"]


@dataclass
class MemoryHit:
    source: HitSource
    score: float                    # higher = better (normalized)
    title: str
    snippet: str
    # Populated based on source:
    event_id: int | None = None
    ticker: str | None = None
    kind: str | None = None
    created_at: str | None = None
    file: MemoryFile | None = None


_METADATA_WEIGHT = 2.0


def _score_file(query_tokens: set[str], mf: MemoryFile) -> float:
    if not query_tokens:
        return 0.0
    title_desc = f"{mf.title} {mf.description}"
    meta_hits = len(query_tokens & token_set(title_desc))
    body_hits = len(query_tokens & token_set(mf.body))
    if meta_hits == 0 and body_hits == 0:
        return 0.0
    return _METADATA_WEIGHT * meta_hits + body_hits


def _normalize_fts_score(bm25_score: float) -> float:
    # bm25 returns negative numbers in SQLite (lower = better). Convert to a
    # positive relevance score for easy comparison with file scores.
    return -bm25_score


def search_memory(
    query: str,
    k: int = 5,
    include_events: bool = True,
    include_files: bool = True,
) -> list[MemoryHit]:
    hits: list[MemoryHit] = []

    if include_events:
        fts_hits = fts5.search(query, k=k * 2)  # overfetch, re-rank globally
        for h in fts_hits:
            snippet = (h.summary or "")[:200]
            hits.append(
                MemoryHit(
                    source="event",
                    score=_normalize_fts_score(h.score),
                    title=h.summary or f"event#{h.event_id}",
                    snippet=snippet,
                    event_id=h.event_id,
                    ticker=h.ticker,
                    kind=h.kind,
                    created_at=h.created_at,
                )
            )

    if include_files:
        qtokens = token_set(query)
        for mf in files.list_memory_files():
            s = _score_file(qtokens, mf)
            if s > 0:
                hits.append(
                    MemoryHit(
                        source="file",
                        score=s,
                        title=mf.title,
                        snippet=(mf.body[:200] or mf.description),
                        file=mf,
                    )
                )

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:k]


def _similar_decisions_sql(
    ticker: str,
    action: str | None,
    since_days: int,
    limit: int,
) -> list[dict[str, Any]]:
    from datetime import timedelta
    since = (now_vn() - timedelta(days=since_days)).isoformat()
    conn = get_connection()
    if action:
        rows = conn.execute(
            """SELECT id, created_at, ticker, action, thesis, invalidation,
                      conviction, status
               FROM decisions
               WHERE ticker = ? AND action = ? AND created_at >= ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (ticker.upper(), action, since, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT id, created_at, ticker, action, thesis, invalidation,
                      conviction, status
               FROM decisions
               WHERE ticker = ? AND created_at >= ?
               ORDER BY created_at DESC
               LIMIT ?""",
            (ticker.upper(), since, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def recall_similar_decision(
    ticker: str,
    action: str | None = None,
    since_days: int = 365,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Look up past decisions on the same ticker (optionally same action)."""
    return _similar_decisions_sql(ticker, action, since_days, limit)
