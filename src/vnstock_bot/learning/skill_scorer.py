from __future__ import annotations

from vnstock_bot.db import queries


def summarize() -> list[dict]:
    """Return skill scores sorted by uses DESC."""
    rows = queries.list_skill_scores()
    return [
        {
            "skill": r["skill"],
            "uses": r["uses"],
            "wins_5d": r["wins_5d"],
            "wins_20d": r["wins_20d"],
            "win_rate_5d": round(r["win_rate_5d"], 3),
            "win_rate_20d": round(r["win_rate_20d"], 3),
            "last_used": r["last_used"],
        }
        for r in rows
    ]


def top_bottom(n: int = 3) -> tuple[list[dict], list[dict]]:
    rows = [r for r in summarize() if r["uses"] >= 5]
    if not rows:
        return [], []
    sorted_rows = sorted(rows, key=lambda x: x["win_rate_20d"], reverse=True)
    return sorted_rows[:n], sorted_rows[-n:]
