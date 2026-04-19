"""Typed SQL queries. The only module issuing raw SQL."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from vnstock_bot.db.connection import get_connection, transaction

# ---------------------------------------------------------------- holdings

def upsert_holding(
    ticker: str,
    qty_total: int,
    qty_available: int,
    avg_cost: int,
    opened_at: str,
    last_buy_at: str | None = None,
) -> None:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO holdings (ticker, qty_total, qty_available, avg_cost, opened_at, last_buy_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(ticker) DO UPDATE SET
              qty_total=excluded.qty_total,
              qty_available=excluded.qty_available,
              avg_cost=excluded.avg_cost,
              last_buy_at=COALESCE(excluded.last_buy_at, holdings.last_buy_at)""",
            (ticker, qty_total, qty_available, avg_cost, opened_at, last_buy_at),
        )


def delete_holding(ticker: str) -> None:
    with transaction() as conn:
        conn.execute("DELETE FROM holdings WHERE ticker = ?", (ticker,))


def get_holding(ticker: str) -> sqlite3.Row | None:
    return get_connection().execute(
        "SELECT * FROM holdings WHERE ticker = ?", (ticker,)
    ).fetchone()


def list_holdings() -> list[sqlite3.Row]:
    return list(get_connection().execute("SELECT * FROM holdings ORDER BY ticker").fetchall())


def update_qty_available(ticker: str, qty_available: int) -> None:
    with transaction() as conn:
        conn.execute("UPDATE holdings SET qty_available = ? WHERE ticker = ?", (qty_available, ticker))


# ---------------------------------------------------------------- meta (cash)

def get_meta(key: str, default: str | None = None) -> str | None:
    row = get_connection().execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(key: str, value: str) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_cash() -> int:
    v = get_meta("cash_vnd")
    return int(v) if v is not None else 0


def set_cash(v: int) -> None:
    set_meta("cash_vnd", str(int(v)))


# ---------------------------------------------------------------- decisions

def insert_decision(d: dict[str, Any]) -> int:
    with transaction() as conn:
        cur = conn.execute(
            """INSERT INTO decisions (
                created_at, ticker, action, qty, target_price, stop_loss,
                thesis, evidence_json, risks_json, invalidation,
                skills_used_json, playbook, conviction, source, status,
                rejection_reason, trace_id,
                target_bear, target_base, target_bull, bias_flags_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                d["created_at"], d["ticker"], d["action"], d["qty"],
                d.get("target_price"), d.get("stop_loss"),
                d["thesis"],
                json.dumps(d.get("evidence", []), ensure_ascii=False),
                json.dumps(d.get("risks", []), ensure_ascii=False),
                d["invalidation"],
                json.dumps(d.get("skills_used", []), ensure_ascii=False),
                d.get("playbook"),
                d["conviction"],
                d["source"],
                d.get("status", "pending"),
                d.get("rejection_reason"),
                # v2 fields (all optional — NULL for v1 rows)
                d.get("trace_id"),
                d.get("target_bear"),
                d.get("target_base"),
                d.get("target_bull"),
                (json.dumps(d["bias_flags"], ensure_ascii=False)
                 if d.get("bias_flags") else None),
            ),
        )
        return int(cur.lastrowid)


def set_decision_status(decision_id: int, status: str, reason: str | None = None) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE decisions SET status = ?, rejection_reason = COALESCE(?, rejection_reason) WHERE id = ?",
            (status, reason, decision_id),
        )


def get_decisions_recent(days: int) -> list[sqlite3.Row]:
    return list(get_connection().execute(
        "SELECT * FROM decisions WHERE date(created_at) >= date('now', ?) ORDER BY created_at DESC",
        (f"-{days} days",),
    ).fetchall())


def get_decision(decision_id: int) -> sqlite3.Row | None:
    return get_connection().execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchone()


# ---------------------------------------------------------------- orders

def insert_order(
    decision_id: int,
    ticker: str,
    side: str,
    qty: int,
    placed_at: str,
    expected_fill_date: str,
) -> int:
    with transaction() as conn:
        cur = conn.execute(
            """INSERT INTO orders (decision_id, ticker, side, qty, placed_at, expected_fill_date, status)
            VALUES (?,?,?,?,?,?,'pending')""",
            (decision_id, ticker, side, qty, placed_at, expected_fill_date),
        )
        return int(cur.lastrowid)


def fill_order(order_id: int, filled_at: str, fill_price: int, fee: int) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE orders SET status='filled', filled_at=?, fill_price=?, fee=? WHERE id = ?",
            (filled_at, fill_price, fee, order_id),
        )


def cancel_order(order_id: int, reason: str = "") -> None:
    with transaction() as conn:
        conn.execute("UPDATE orders SET status='cancelled' WHERE id = ?", (order_id,))


def pending_orders_for_date(fill_date: str) -> list[sqlite3.Row]:
    return list(get_connection().execute(
        "SELECT * FROM orders WHERE status='pending' AND expected_fill_date <= ?",
        (fill_date,),
    ).fetchall())


# ---------------------------------------------------------------- equity

def upsert_daily_equity(d: str, cash: int, market_value: int, total: int, vnindex: float | None, notes: str | None = None) -> None:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO daily_equity (date, cash, market_value, total, vnindex, notes)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(date) DO UPDATE SET
              cash=excluded.cash, market_value=excluded.market_value,
              total=excluded.total, vnindex=excluded.vnindex,
              notes=COALESCE(excluded.notes, daily_equity.notes)""",
            (d, cash, market_value, total, vnindex, notes),
        )


def get_equity_recent(days: int) -> list[sqlite3.Row]:
    return list(get_connection().execute(
        "SELECT * FROM daily_equity WHERE date >= date('now', ?) ORDER BY date",
        (f"-{days} days",),
    ).fetchall())


# ---------------------------------------------------------------- market snapshot

def upsert_market_snapshot(d: dict[str, Any]) -> None:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO market_snapshot (date, vnindex_open, vnindex_high, vnindex_low, vnindex_close,
              vnindex_volume, foreign_buy, foreign_sell, top_movers_json)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(date) DO UPDATE SET
              vnindex_open=excluded.vnindex_open, vnindex_high=excluded.vnindex_high,
              vnindex_low=excluded.vnindex_low, vnindex_close=excluded.vnindex_close,
              vnindex_volume=excluded.vnindex_volume,
              foreign_buy=excluded.foreign_buy, foreign_sell=excluded.foreign_sell,
              top_movers_json=excluded.top_movers_json""",
            (
                d["date"], d.get("vnindex_open"), d.get("vnindex_high"),
                d.get("vnindex_low"), d.get("vnindex_close"),
                d.get("vnindex_volume"), d.get("foreign_buy"), d.get("foreign_sell"),
                json.dumps(d.get("top_movers", []), ensure_ascii=False),
            ),
        )


def latest_market_snapshot() -> sqlite3.Row | None:
    return get_connection().execute(
        "SELECT * FROM market_snapshot ORDER BY date DESC LIMIT 1"
    ).fetchone()


# ---------------------------------------------------------------- ohlc cache

def upsert_ohlc(ticker: str, d: str, o: int, h: int, l: int, c: int, v: int) -> None:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO ohlc_cache (ticker, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(ticker, date) DO UPDATE SET
              open=excluded.open, high=excluded.high, low=excluded.low,
              close=excluded.close, volume=excluded.volume""",
            (ticker, d, o, h, l, c, v),
        )


def get_ohlc(ticker: str, days: int) -> list[sqlite3.Row]:
    return list(get_connection().execute(
        "SELECT * FROM ohlc_cache WHERE ticker = ? AND date >= date('now', ?) ORDER BY date",
        (ticker, f"-{days} days"),
    ).fetchall())


def get_ohlc_on(ticker: str, d: str) -> sqlite3.Row | None:
    return get_connection().execute(
        "SELECT * FROM ohlc_cache WHERE ticker = ? AND date = ?", (ticker, d)
    ).fetchone()


# ---------------------------------------------------------------- skill scores

def bump_skill_uses(skills: list[str], when: str) -> None:
    with transaction() as conn:
        for s in skills:
            conn.execute(
                """INSERT INTO skill_scores (skill, uses, last_used) VALUES (?, 1, ?)
                ON CONFLICT(skill) DO UPDATE SET uses = uses + 1, last_used = ?""",
                (s, when, when),
            )


def update_skill_win(skill: str, window: int, add_wins: int) -> None:
    col = "wins_5d" if window == 5 else "wins_20d"
    with transaction() as conn:
        conn.execute(f"UPDATE skill_scores SET {col} = {col} + ? WHERE skill = ?", (add_wins, skill))


def list_skill_scores() -> list[sqlite3.Row]:
    return list(get_connection().execute(
        "SELECT skill, uses, wins_5d, wins_20d, last_used, "
        "CASE WHEN uses > 0 THEN 1.0*wins_5d/uses ELSE 0 END AS win_rate_5d, "
        "CASE WHEN uses > 0 THEN 1.0*wins_20d/uses ELSE 0 END AS win_rate_20d "
        "FROM skill_scores ORDER BY uses DESC"
    ).fetchall())


# ---------------------------------------------------------------- outcomes

def upsert_outcome(
    decision_id: int, days_held: int, pnl_pct: float | None,
    thesis_valid: int | None, invalidation_hit: int | None, scored_at: str,
) -> None:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO decision_outcomes (decision_id, days_held, pnl_pct, thesis_valid, invalidation_hit, scored_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(decision_id, days_held) DO UPDATE SET
              pnl_pct=excluded.pnl_pct, thesis_valid=excluded.thesis_valid,
              invalidation_hit=excluded.invalidation_hit, scored_at=excluded.scored_at""",
            (decision_id, days_held, pnl_pct, thesis_valid, invalidation_hit, scored_at),
        )


def unscored_decisions(window: int) -> list[sqlite3.Row]:
    """Decisions ≥ window days old, not yet scored at this window, and not HOLD."""
    return list(get_connection().execute(
        """SELECT d.* FROM decisions d
        WHERE d.status = 'filled' AND d.action IN ('BUY','ADD','TRIM','SELL')
          AND date(d.created_at) <= date('now', ?)
          AND NOT EXISTS (
            SELECT 1 FROM decision_outcomes o WHERE o.decision_id = d.id AND o.days_held = ?
          )""",
        (f"-{window} days", window),
    ).fetchall())


# ---------------------------------------------------------------- chat history

def insert_chat_turn(chat_id: int, role: str, content: str, created_at: str) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO chat_history (chat_id, role, content, created_at) VALUES (?,?,?,?)",
            (chat_id, role, content, created_at),
        )


def recent_chat_history(chat_id: int, limit: int = 20) -> list[sqlite3.Row]:
    rows = get_connection().execute(
        "SELECT * FROM chat_history WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
        (chat_id, limit),
    ).fetchall()
    return list(reversed(rows))
