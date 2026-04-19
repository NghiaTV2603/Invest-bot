"""Weekly bias check — run detectors on bot's own decisions + orders/fills.

Pulls data from DB, converts to `TradeLike` / `DecisionLike`, calls
`detectors.detect_all`, persists results to `bias_reports`.

Wired from `scheduler/jobs.py` Sunday 10:00 after weekly_review.
"""

from __future__ import annotations

import contextlib
import json
from datetime import date, datetime, timedelta

from vnstock_bot.bias.detectors import detect_all
from vnstock_bot.bias.types import BiasResult, DecisionLike, TradeLike
from vnstock_bot.data.holidays import now_vn
from vnstock_bot.db.connection import get_connection, transaction


def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def load_bot_trades(days: int = 90) -> list[TradeLike]:
    """Build TradeLike entries from filled orders.

    A filled BUY becomes side='BUY' with qty/price. The matching SELL is
    paired by FIFO within the same ticker; pnl + hold_days + entry_price
    are attached on the SELL. Qty-partial matching is supported.
    """
    since = (now_vn() - timedelta(days=days)).isoformat()
    rows = get_connection().execute(
        """SELECT id, ticker, side, qty, fill_price, filled_at
           FROM orders
           WHERE status = 'filled' AND filled_at IS NOT NULL
             AND filled_at >= ?
           ORDER BY filled_at ASC""",
        (since,),
    ).fetchall()

    open_buys: dict[str, list[dict]] = {}  # FIFO queue per ticker
    trades: list[TradeLike] = []
    for r in rows:
        ticker = r["ticker"]
        side = r["side"]
        qty = int(r["qty"])
        price = int(r["fill_price"] or 0)
        ts = r["filled_at"]
        if side == "BUY":
            q = open_buys.setdefault(ticker, [])
            q.append({"qty": qty, "price": price, "ts": ts})
            trades.append(TradeLike(ticker=ticker, side="BUY",
                                    qty=qty, price=price, traded_at=ts))
        else:  # SELL
            remaining = qty
            total_cost = 0
            total_qty = 0
            first_buy_ts: str | None = None
            q = open_buys.get(ticker, [])
            while remaining > 0 and q:
                head = q[0]
                take = min(remaining, head["qty"])
                total_cost += take * head["price"]
                total_qty += take
                if first_buy_ts is None:
                    first_buy_ts = head["ts"]
                head["qty"] -= take
                remaining -= take
                if head["qty"] == 0:
                    q.pop(0)

            pnl = None
            hold_days = None
            entry_price = None
            if total_qty > 0:
                avg_cost = total_cost // total_qty
                pnl = (price - avg_cost) * total_qty
                entry_price = avg_cost
                if first_buy_ts:
                    try:
                        d0 = datetime.fromisoformat(first_buy_ts).date()
                        d1 = datetime.fromisoformat(ts).date()
                        hold_days = (d1 - d0).days
                    except ValueError:
                        hold_days = None
            trades.append(TradeLike(
                ticker=ticker, side="SELL", qty=qty, price=price,
                traded_at=ts, pnl=pnl, hold_days=hold_days,
                entry_price=entry_price,
            ))
    return trades


def load_bot_decisions(days: int = 90) -> list[DecisionLike]:
    since = (now_vn() - timedelta(days=days)).isoformat()
    rows = get_connection().execute(
        """SELECT id, created_at, ticker, action, thesis, skills_used_json
           FROM decisions
           WHERE created_at >= ?
             AND source IN ('claude_daily','claude_chat')
           ORDER BY created_at ASC""",
        (since,),
    ).fetchall()
    out: list[DecisionLike] = []
    for r in rows:
        skills: list[str] = []
        # Legacy rows may have malformed JSON; recorded decisions go through
        # Pydantic so this is defensive rather than expected.
        with contextlib.suppress(ValueError, TypeError):
            skills = json.loads(r["skills_used_json"] or "[]")
        out.append(DecisionLike(
            decision_id=int(r["id"]),
            created_at=r["created_at"],
            ticker=r["ticker"],
            action=r["action"],
            thesis=r["thesis"] or "",
            skills_used=list(skills),
        ))
    return out


def persist_report(
    scope: str,
    week_of: str,
    results: list[BiasResult],
) -> int:
    """Upsert one row per bias for the given (scope, week_of). Returns count."""
    now = now_vn().isoformat()
    with transaction() as conn:
        for r in results:
            conn.execute(
                """INSERT INTO bias_reports
                    (scope, week_of, bias_name, severity, metric,
                     threshold_medium, threshold_high, evidence, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(scope, week_of, bias_name) DO UPDATE SET
                     severity = excluded.severity,
                     metric = excluded.metric,
                     threshold_medium = excluded.threshold_medium,
                     threshold_high = excluded.threshold_high,
                     evidence = excluded.evidence,
                     created_at = excluded.created_at""",
                (scope, week_of, r.name, r.severity, r.metric,
                 r.threshold_medium, r.threshold_high,
                 r.evidence, now),
            )
    return len(results)


def run_bot_bias_check(
    week_of: date | None = None,
    lookback_days: int = 90,
    persist: bool = True,
) -> list[BiasResult]:
    """Top-level entry — called by scheduler every Sunday after weekly review."""
    week = _monday_of(week_of or now_vn().date())
    trades = load_bot_trades(days=lookback_days)
    decisions = load_bot_decisions(days=lookback_days)
    results = detect_all(trades=trades, decisions=decisions)
    if persist:
        persist_report(scope="bot", week_of=week.isoformat(), results=results)
    return results
