"""Simulator: fill pending orders, track T+2, compute equity, stop-loss scan."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from vnstock_bot.config import get_settings
from vnstock_bot.data.holidays import add_trading_days, iso, next_trading_day
from vnstock_bot.db import queries
from vnstock_bot.logging_setup import get_logger
from vnstock_bot.portfolio.types import FillResult, Holding, Portfolio

log = get_logger(__name__)


LOT_SIZE = 100  # HSX lô chẵn


# ----------------------------------------------------------------- helpers

def round_down_lot(qty: int) -> int:
    return (qty // LOT_SIZE) * LOT_SIZE


def compute_fee(side: str, notional_vnd: int) -> int:
    s = get_settings()
    bps = s.fee_buy_bps if side == "BUY" else s.fee_sell_bps
    return int(round(notional_vnd * bps / 10_000))


def load_portfolio() -> Portfolio:
    cash = queries.get_cash()
    if cash == 0 and not queries.list_holdings():
        cash = get_settings().initial_capital_vnd
        queries.set_cash(cash)
    holdings = [
        Holding(
            ticker=r["ticker"],
            qty_total=r["qty_total"],
            qty_available=r["qty_available"],
            avg_cost=r["avg_cost"],
            opened_at=r["opened_at"],
            last_buy_at=r["last_buy_at"],
        )
        for r in queries.list_holdings()
    ]
    return Portfolio(cash=cash, holdings=holdings)


def _ohlc_on(ticker: str, d: date) -> dict[str, int] | None:
    row = queries.get_ohlc_on(ticker, iso(d))
    if not row:
        return None
    return {
        "open": row["open"] or 0,
        "high": row["high"] or 0,
        "low": row["low"] or 0,
        "close": row["close"] or 0,
        "volume": row["volume"] or 0,
    }


# ----------------------------------------------------------------- fill

@dataclass
class FillSummary:
    filled: list[FillResult]
    cancelled: list[tuple[int, str]]  # (order_id, reason)


def fill_pending_orders(today: date) -> FillSummary:
    """Fill orders whose expected_fill_date <= today at today's ATO (open) price."""
    filled: list[FillResult] = []
    cancelled: list[tuple[int, str]] = []

    portfolio = load_portfolio()
    cash = portfolio.cash
    holdings_map = {h.ticker: h for h in portfolio.holdings}

    pending = queries.pending_orders_for_date(iso(today))
    if not pending:
        return FillSummary([], [])

    for order in pending:
        ticker = order["ticker"]
        side = order["side"]
        qty = int(order["qty"])
        ohlc = _ohlc_on(ticker, today)
        if not ohlc or ohlc["open"] <= 0:
            queries.cancel_order(order["id"])
            cancelled.append((order["id"], "no_ato_price"))
            log.warning("order_cancelled_no_price", order_id=order["id"], ticker=ticker)
            continue

        fill_price = ohlc["open"]
        notional = fill_price * qty
        fee = compute_fee(side, notional)

        if side == "BUY":
            total_cost = notional + fee
            if cash < total_cost:
                queries.cancel_order(order["id"])
                cancelled.append((order["id"], "insufficient_cash"))
                log.warning("buy_cancelled_no_cash", order_id=order["id"], need=total_cost, have=cash)
                continue
            cash -= total_cost
            existing = holdings_map.get(ticker)
            if existing is None:
                new_avg = (notional + fee) // qty
                h = Holding(
                    ticker=ticker, qty_total=qty, qty_available=0,
                    avg_cost=new_avg,
                    opened_at=iso(today), last_buy_at=iso(today),
                )
                holdings_map[ticker] = h
                queries.upsert_holding(ticker, qty, 0, new_avg, iso(today), iso(today))
            else:
                new_total_qty = existing.qty_total + qty
                new_avg_cost = (existing.avg_cost * existing.qty_total + notional + fee) // new_total_qty
                holdings_map[ticker] = Holding(
                    ticker=ticker,
                    qty_total=new_total_qty,
                    qty_available=existing.qty_available,  # newly bought qty locked for T+2
                    avg_cost=new_avg_cost,
                    opened_at=existing.opened_at,
                    last_buy_at=iso(today),
                )
                queries.upsert_holding(
                    ticker, new_total_qty, existing.qty_available, new_avg_cost,
                    existing.opened_at, iso(today),
                )
        else:  # SELL
            existing = holdings_map.get(ticker)
            if existing is None or existing.qty_available < qty:
                queries.cancel_order(order["id"])
                cancelled.append((order["id"], "insufficient_available_qty"))
                log.warning("sell_cancelled_t2", order_id=order["id"], ticker=ticker, have=existing.qty_available if existing else 0, need=qty)
                continue
            proceeds = notional - fee
            cash += proceeds
            new_total = existing.qty_total - qty
            new_avail = existing.qty_available - qty
            if new_total <= 0:
                queries.delete_holding(ticker)
                holdings_map.pop(ticker, None)
            else:
                holdings_map[ticker] = Holding(
                    ticker=ticker, qty_total=new_total, qty_available=new_avail,
                    avg_cost=existing.avg_cost, opened_at=existing.opened_at,
                    last_buy_at=existing.last_buy_at,
                )
                queries.upsert_holding(
                    ticker, new_total, new_avail, existing.avg_cost,
                    existing.opened_at, existing.last_buy_at,
                )

        queries.fill_order(order["id"], iso(today), fill_price, fee)
        queries.set_decision_status(int(order["decision_id"]), "filled")
        filled.append(FillResult(
            order_id=int(order["id"]),
            ticker=ticker, side=side, qty=qty,
            fill_price=fill_price, fee=fee, date=iso(today),
        ))

    queries.set_cash(cash)
    return FillSummary(filled=filled, cancelled=cancelled)


# ----------------------------------------------------------------- T+2

def release_t2_shares(today: date) -> None:
    """After fill_pending_orders, release qty bought on or before T-2 into available."""
    holdings = queries.list_holdings()
    for h in holdings:
        if not h["last_buy_at"]:
            continue
        last_buy = datetime.fromisoformat(h["last_buy_at"]).date()
        # T+2 means: bought on X, available starting close of X+2 → tradable from X+2 onwards.
        # We release qty_available = qty_total once today >= last_buy + 2 trading days.
        released_on = add_trading_days(last_buy, 2)
        if today >= released_on and h["qty_available"] < h["qty_total"]:
            queries.update_qty_available(h["ticker"], h["qty_total"])
            log.info("t2_released", ticker=h["ticker"], qty=h["qty_total"])


# ----------------------------------------------------------------- equity

def compute_equity(today: date, vnindex_close: float | None = None) -> dict[str, int]:
    """Compute and persist daily_equity row."""
    portfolio = load_portfolio()
    prices: dict[str, int] = {}
    for h in portfolio.holdings:
        ohlc = _ohlc_on(h.ticker, today)
        prices[h.ticker] = ohlc["close"] if ohlc and ohlc["close"] > 0 else h.avg_cost
    mv = portfolio.market_value(prices)
    total = portfolio.cash + mv
    queries.upsert_daily_equity(iso(today), portfolio.cash, mv, total, vnindex_close)
    return {"cash": portfolio.cash, "market_value": mv, "total": total}


# ----------------------------------------------------------------- stop-loss scan

def check_stop_loss(today: date) -> list[dict[str, Any]]:
    """Return auto-sell proposals for holdings violating stop rules.

    Rules (subset of cut-loser playbook):
      (1) close ≤ decision.stop_loss  (hard stop hit)
      (2) close ≤ avg_cost × 0.92      (fallback -8% if no stop set)
    """
    proposals: list[dict[str, Any]] = []
    holdings = load_portfolio().holdings
    for h in holdings:
        if h.qty_available <= 0:
            continue  # still locked T+2
        ohlc = _ohlc_on(h.ticker, today)
        if not ohlc or ohlc["close"] <= 0:
            continue
        close = ohlc["close"]

        # find latest BUY/ADD decision on this ticker to read stop_loss
        # simple heuristic: if close < avg_cost × 0.92 → auto SELL
        threshold = int(h.avg_cost * 0.92)
        if close <= threshold:
            proposals.append({
                "ticker": h.ticker,
                "action": "SELL",
                "qty": h.qty_available,
                "target_price": None,
                "stop_loss": None,
                "thesis": f"Stop-loss hit: close {close} ≤ 92% avg_cost ({h.avg_cost})",
                "evidence": [
                    f"close_today={close}",
                    f"avg_cost={h.avg_cost}",
                    f"pnl_pct={(close - h.avg_cost)/h.avg_cost*100:.2f}%",
                ],
                "risks": ["Có thể hồi sau khi cắt — chấp nhận rủi ro false signal"],
                "invalidation": "N/A (exit)",
                "skills_used": ["stop-loss-rules"],
                "playbook_used": "cut-loser",
                "conviction": 5,
            })
            log.info("auto_sell_proposed", ticker=h.ticker, close=close, avg=h.avg_cost)
    return proposals


# ----------------------------------------------------------------- place order from decision

def place_order_from_decision(decision_id: int, decision: dict[str, Any], today: date) -> int | None:
    """Create a pending order for next trading day's ATO. HOLD → no order."""
    action = decision["action"]
    if action == "HOLD":
        return None
    side = "BUY" if action in ("BUY", "ADD") else "SELL"
    qty = int(decision["qty"])
    if qty <= 0:
        return None
    fill_date = next_trading_day(today)
    return queries.insert_order(
        decision_id=decision_id,
        ticker=decision["ticker"],
        side=side,
        qty=qty,
        placed_at=iso(today),
        expected_fill_date=iso(fill_date),
    )
