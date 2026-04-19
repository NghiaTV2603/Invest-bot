"""Score decisions after N trading days. Reads close prices + invalidation."""

from __future__ import annotations

import json
from datetime import date, datetime

from vnstock_bot.data.holidays import add_trading_days, iso
from vnstock_bot.db import queries
from vnstock_bot.logging_setup import get_logger

log = get_logger(__name__)


def _pnl_pct(decision_action: str, entry: int, current: int) -> float:
    if entry <= 0:
        return 0.0
    # For BUY/ADD: we're long → (cur - entry)/entry
    # For SELL/TRIM: we closed → no ongoing pnl; use 0 and rely on invalidation check
    if decision_action in ("BUY", "ADD"):
        return (current - entry) / entry * 100
    return 0.0


def _check_invalidation(invalidation_text: str, bars: list[dict]) -> bool:
    """Best-effort heuristic: look for 'close < X' patterns. Robust logic lives
    in future weekly review; here we return False by default unless explicit
    price-break obviously matched. We keep this simple: if invalidation text
    contains "close <" + a number, check latest close."""
    if not bars:
        return False
    import re

    m = re.search(r"close\s*<\s*([0-9][0-9,\.]*)", invalidation_text.lower())
    if not m:
        return False
    try:
        threshold = int(m.group(1).replace(",", "").replace(".", ""))
    except ValueError:
        return False
    last_close = bars[-1]["close"]
    return last_close < threshold


def score_window(today: date, window: int) -> int:
    """Score all unscored decisions older than `window` trading days. Returns count."""
    decisions = queries.unscored_decisions(window)
    scored = 0
    for d in decisions:
        created = datetime.fromisoformat(d["created_at"]).date()
        target_date = add_trading_days(created, window)
        if target_date > today:
            continue

        bars = queries.get_ohlc(d["ticker"], days=window + 5)
        if not bars:
            continue
        # Entry price: close at decision day (simulator fills at ATO next day,
        # but for scoring purposes close on creation is a close-enough proxy).
        entry_row = queries.get_ohlc_on(d["ticker"], iso(created))
        entry_price = int(entry_row["close"]) if entry_row else int(bars[0]["close"])

        last_close = int(bars[-1]["close"])
        pnl = _pnl_pct(d["action"], entry_price, last_close)

        bars_dicts = [dict(b) for b in bars]
        inv_hit = _check_invalidation(d["invalidation"], bars_dicts)
        thesis_valid = not inv_hit and pnl >= -5  # rough — pnl > -5% considered "still alive"

        queries.upsert_outcome(
            decision_id=int(d["id"]),
            days_held=window,
            pnl_pct=pnl,
            thesis_valid=1 if thesis_valid else 0,
            invalidation_hit=1 if inv_hit else 0,
            scored_at=iso(today),
        )

        # update skill scores — a "win" = thesis_valid AND pnl > 0 for long actions
        is_win = thesis_valid and pnl > 0
        if is_win:
            skills = json.loads(d["skills_used_json"] or "[]")
            for skill in skills:
                queries.update_skill_win(skill, window, 1)
        scored += 1
    log.info("scored_window", window=window, count=scored)
    return scored


def score_all(today: date) -> dict[str, int]:
    return {
        "5d": score_window(today, 5),
        "20d": score_window(today, 20),
    }
