"""5-layer context compression.

Used when a DAG prompt would exceed the token budget. Produces a plain-text
block ordered from most-to-least detailed:

    L1 raw (5 latest messages)
    L2 chunked summaries (messages 6..20)
    L3 daily / session summaries (older)
    L4 pattern bullets (cross-session)
    L5 strategy.md bullets (distilled human wisdom)

Character-count heuristic is used for the budget (no tokenizer dep). Rough
rule of thumb: ~4 chars per token for English-Vietnamese mix.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from vnstock_bot.config import get_settings
from vnstock_bot.db.connection import get_connection

MessageRole = Literal["user", "assistant", "system", "tool"]


@dataclass
class Message:
    role: MessageRole
    content: str


_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


def _format_message(m: Message) -> str:
    prefix = {"user": "U", "assistant": "A", "system": "S", "tool": "T"}[m.role]
    return f"[{prefix}] {m.content.strip()}"


def _summarize_chunk(msgs: list[Message], char_cap: int = 400) -> str:
    # Simple extractive summary: first 2 + last 1 lines, truncated.
    if not msgs:
        return ""
    head = msgs[:2]
    tail = msgs[-1:] if len(msgs) > 2 else []
    picks = [_format_message(m)[:160] for m in head + tail]
    joined = " | ".join(picks)
    return joined[:char_cap]


def _load_patterns(limit: int) -> list[str]:
    rows = get_connection().execute(
        """SELECT body FROM patterns
           ORDER BY confirmed DESC, last_seen_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [r["body"] for r in rows]


def _load_strategy_bullets(limit: int) -> list[str]:
    path: Path = get_settings().strategy_path
    if not path.is_file():
        return []
    bullets: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith(("-", "*")) and len(s) > 2:
            bullets.append(s.lstrip("-*").strip())
            if len(bullets) >= limit:
                break
    return bullets


def _load_recent_summaries(limit: int) -> list[str]:
    rows = get_connection().execute(
        """SELECT body FROM summaries
           WHERE scope IN ('daily','session')
           ORDER BY created_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [r["body"] for r in rows]


def compress_context(
    messages: list[Message],
    token_budget: int = 8_000,
    keep_recent: int = 5,
    chunk_size: int = 5,
) -> str:
    """Build a compressed context string within the given token budget."""
    if not messages:
        return ""

    sections: list[str] = []

    # L1: raw latest
    recent = messages[-keep_recent:]
    sections.append("## L1 — recent")
    sections.extend(_format_message(m) for m in recent)

    # L2: chunked summaries of messages before `recent`
    older = messages[:-keep_recent]
    if older:
        sections.append("## L2 — chunks")
        for i in range(0, len(older), chunk_size):
            s = _summarize_chunk(older[i : i + chunk_size])
            if s:
                sections.append(f"- {s}")

    # L3: daily/session summaries
    l3 = _load_recent_summaries(limit=5)
    if l3:
        sections.append("## L3 — summaries")
        sections.extend(f"- {s[:200]}" for s in l3)

    # L4: confirmed patterns
    l4 = _load_patterns(limit=10)
    if l4:
        sections.append("## L4 — patterns")
        sections.extend(f"- {p[:200]}" for p in l4)

    # L5: strategy.md bullets
    l5 = _load_strategy_bullets(limit=10)
    if l5:
        sections.append("## L5 — strategy")
        sections.extend(f"- {b[:200]}" for b in l5)

    # Enforce budget by dropping from the BOTTOM up (we trust L5 > L4 > L3 >
    # L2 > L1 for long-horizon memory; but L1 recency is also important).
    # Simpler rule: always keep L1, drop lower sections until we fit.
    out = "\n".join(sections)
    if _estimate_tokens(out) <= token_budget:
        return out

    # Progressive truncation: keep L1 intact, progressively shrink L2-L5.
    cap = token_budget * _CHARS_PER_TOKEN
    if len(out) > cap:
        out = out[:cap].rsplit("\n", 1)[0] + "\n… [truncated]"
    return out
