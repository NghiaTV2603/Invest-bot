"""FIFO pairing: list[RawTrade] → list[Roundtrip].

A BUY can be split across multiple SELLs; a SELL can draw from multiple
prior BUYs. Each resulting Roundtrip represents one matched qty slice.

Fee is apportioned by the qty fraction: a slice taking 40/100 of a
200-VND buy fee gets 80 VND.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from vnstock_bot.shadow.types import RawTrade, Roundtrip


def pair_fifo(
    trades: Iterable[RawTrade],
    sector_lookup: dict[str, str] | None = None,
) -> list[Roundtrip]:
    """Sort by traded_at, FIFO-match within ticker, return Roundtrip list."""
    sector_lookup = sector_lookup or {}
    sorted_trades = sorted(trades, key=lambda t: (t.traded_at, t.ticker))

    open_buys: dict[str, list[dict]] = defaultdict(list)
    roundtrips: list[Roundtrip] = []

    for t in sorted_trades:
        if t.side == "BUY":
            open_buys[t.ticker].append({
                "qty": t.qty,
                "orig_qty": t.qty,
                "price": t.price,
                "fee": t.fee,
                "traded_at": t.traded_at,
            })
            continue

        # SELL — drain open buys FIFO
        remaining = t.qty
        sell_fee_remaining = t.fee
        sell_qty_total = t.qty
        queue = open_buys.get(t.ticker) or []
        while remaining > 0 and queue:
            head = queue[0]
            take = min(remaining, head["qty"])
            # Apportion fees proportionally
            buy_fee_slice = int(head["fee"] * take / head["orig_qty"]) if head["orig_qty"] else 0
            sell_fee_slice = int(t.fee * take / sell_qty_total) if sell_qty_total else 0
            # Last slice gets the remainder to avoid rounding drift
            if remaining - take == 0:
                sell_fee_slice = sell_fee_remaining
            sell_fee_remaining -= sell_fee_slice
            rt = Roundtrip(
                ticker=t.ticker,
                qty=take,
                buy_at=head["traded_at"],
                sell_at=t.traded_at,
                buy_price=head["price"],
                sell_price=t.price,
                buy_fee=buy_fee_slice,
                sell_fee=sell_fee_slice,
                sector=sector_lookup.get(t.ticker),
            )
            roundtrips.append(rt)
            head["qty"] -= take
            remaining -= take
            if head["qty"] == 0:
                queue.pop(0)

    return roundtrips


def summarize(roundtrips: list[Roundtrip]) -> dict[str, int | float]:
    """Quick stats block — used by TradingProfile builder."""
    if not roundtrips:
        return {"total": 0, "winners": 0, "losers": 0,
                "total_pnl": 0, "avg_hold": 0.0, "win_rate": 0.0}
    winners = [r for r in roundtrips if r.is_winner]
    losers = [r for r in roundtrips if r.pnl < 0]
    total_pnl = sum(r.pnl for r in roundtrips)
    avg_hold = sum(r.hold_days for r in roundtrips) / len(roundtrips)
    return {
        "total": len(roundtrips),
        "winners": len(winners),
        "losers": len(losers),
        "total_pnl": int(total_pnl),
        "avg_hold": float(avg_hold),
        "win_rate": float(len(winners)) / len(roundtrips) if roundtrips else 0.0,
    }
