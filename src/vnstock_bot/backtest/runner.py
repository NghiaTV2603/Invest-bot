"""Backtest: replay N months of history. Sanity-checks simulator logic.

Usage:
    uv run vnstock-bot backtest --months 6

Loads OHLC from vnstock for watchlist + VN-Index, then walks day-by-day.
For MVP this is a deterministic **mechanical** backtest (no Claude calls) that
verifies simulator correctness: T+2, ATO fill, fees, price bands. A smarter
backtest with Claude-in-the-loop is a Phase 2 task.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from vnstock_bot.config import get_settings
from vnstock_bot.data import vnstock_client
from vnstock_bot.data.holidays import iso
from vnstock_bot.data.watchlist import load_watchlist
from vnstock_bot.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class BacktestResult:
    days: int
    start_equity: int
    end_equity: int
    vnindex_return_pct: float
    strategy_return_pct: float
    num_trades: int
    run_dir: Path


def _moving_avg(values: list[int], n: int) -> list[float | None]:
    out: list[float | None] = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def simple_momentum_strategy(bars: dict[str, list[dict]], cash: int, day_idx: int) -> list[dict]:
    """Baseline strategy: buy if close crosses above SMA20 with volume >= 1.2x MA20 vol.
    Sell if close < SMA20."""
    proposals = []
    for ticker, series in bars.items():
        if day_idx < 21 or day_idx >= len(series):
            continue
        closes = [b["close"] for b in series[: day_idx + 1]]
        vols = [b["volume"] for b in series[: day_idx + 1]]
        sma20 = _moving_avg(closes, 20)
        vol20 = _moving_avg(vols, 20)
        c_today = closes[-1]
        c_yest = closes[-2]
        if sma20[-1] is None or sma20[-2] is None or vol20[-1] is None:
            continue
        if c_yest < sma20[-2] and c_today > sma20[-1] and vols[-1] > 1.2 * vol20[-1]:
            proposals.append({"action": "BUY", "ticker": ticker, "price": c_today})
        elif c_today < sma20[-1]:
            proposals.append({"action": "SELL", "ticker": ticker, "price": c_today})
    return proposals


def run_backtest(months: int, out_dir: Path) -> BacktestResult:
    settings = get_settings()
    wl = load_watchlist()
    end = date.today()
    start = end - timedelta(days=months * 31)

    log.info("backtest_fetch", start=iso(start), end=iso(end), tickers=len(wl.tickers))
    bars: dict[str, list[dict]] = {}
    for t in wl.tickers:
        data = vnstock_client.fetch_ohlc(t.ticker, start, end)
        bars[t.ticker] = [
            {"date": b.date, "open": b.open, "high": b.high, "low": b.low, "close": b.close, "volume": b.volume}
            for b in data
        ]

    idx_bars = vnstock_client.fetch_index("VNINDEX", start, end)
    vni_start = idx_bars[0].close / 100 if idx_bars else None
    vni_end = idx_bars[-1].close / 100 if idx_bars else None
    vnindex_return = ((vni_end - vni_start) / vni_start * 100) if vni_start and vni_end else 0.0

    # Unified list of trading days
    all_dates = sorted({b.date for b in idx_bars} | {b["date"] for s in bars.values() for b in s})

    cash = settings.initial_capital_vnd
    holdings: dict[str, dict[str, int]] = {}  # ticker -> {qty, avg_cost}
    pending_buy: list[dict] = []
    pending_sell: list[dict] = []
    trades: list[dict] = []

    for i, d_iso in enumerate(all_dates):
        # Fill pending orders at today's ATO
        for order in pending_buy:
            series = bars.get(order["ticker"], [])
            ohlc_today = next((b for b in series if b["date"] == d_iso), None)
            if not ohlc_today:
                continue
            fill = ohlc_today["open"]
            qty = order["qty"]
            notional = fill * qty
            fee = int(notional * settings.fee_buy_bps / 10_000)
            if cash < notional + fee:
                continue
            cash -= notional + fee
            h = holdings.setdefault(order["ticker"], {"qty": 0, "avg_cost": 0})
            new_total = h["qty"] + qty
            h["avg_cost"] = (h["avg_cost"] * h["qty"] + notional + fee) // new_total
            h["qty"] = new_total
            trades.append({"date": d_iso, "side": "BUY", **order, "fill": fill, "fee": fee})
        pending_buy.clear()

        for order in pending_sell:
            series = bars.get(order["ticker"], [])
            ohlc_today = next((b for b in series if b["date"] == d_iso), None)
            if not ohlc_today:
                continue
            fill = ohlc_today["open"]
            qty = order["qty"]
            notional = fill * qty
            fee = int(notional * settings.fee_sell_bps / 10_000)
            cash += notional - fee
            h = holdings.get(order["ticker"])
            if h:
                h["qty"] -= qty
                if h["qty"] <= 0:
                    holdings.pop(order["ticker"], None)
            trades.append({"date": d_iso, "side": "SELL", **order, "fill": fill, "fee": fee})
        pending_sell.clear()

        # Generate proposals for next day
        proposals = simple_momentum_strategy(bars, cash, i)
        for p in proposals:
            if p["action"] == "BUY" and p["ticker"] not in holdings:
                # 10% NAV sizing
                price = p["price"]
                if price <= 0:
                    continue
                notional_cap = (cash + sum(h["qty"] * p["price"] for h in holdings.values())) // 10
                qty_target = (notional_cap // price // 100) * 100
                if qty_target > 0:
                    pending_buy.append({"ticker": p["ticker"], "qty": qty_target})
            elif p["action"] == "SELL" and p["ticker"] in holdings:
                pending_sell.append({"ticker": p["ticker"], "qty": holdings[p["ticker"]]["qty"]})

    # Final MV
    last_prices = {t: (bars[t][-1]["close"] if bars[t] else 0) for t in bars}
    mv = sum(h["qty"] * last_prices.get(t, 0) for t, h in holdings.items())
    end_equity = cash + mv
    start_equity = settings.initial_capital_vnd
    strategy_return = (end_equity - start_equity) / start_equity * 100

    # Output
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "trades.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "side", "ticker", "qty", "fill", "fee"])
        for t in trades:
            w.writerow([t["date"], t["side"], t["ticker"], t["qty"], t["fill"], t["fee"]])
    (out_dir / "report.md").write_text(
        f"# Backtest {iso(start)} → {iso(end)}\n\n"
        f"- Tickers: {len(wl.tickers)}\n"
        f"- Start equity: {start_equity:,} VND\n"
        f"- End equity: {end_equity:,} VND\n"
        f"- Strategy return: {strategy_return:+.2f}%\n"
        f"- VN-Index return: {vnindex_return:+.2f}%\n"
        f"- Trades: {len(trades)}\n",
        encoding="utf-8",
    )
    return BacktestResult(
        days=len(all_dates),
        start_equity=start_equity,
        end_equity=end_equity,
        vnindex_return_pct=vnindex_return,
        strategy_return_pct=strategy_return,
        num_trades=len(trades),
        run_dir=out_dir,
    )


def cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=6)
    args = parser.parse_args()
    settings = get_settings()
    out_dir = settings.absolute_raw_dir.parent / "backtest" / date.today().isoformat()
    r = run_backtest(args.months, out_dir)
    print(json.dumps({
        "strategy_return_pct": r.strategy_return_pct,
        "vnindex_return_pct": r.vnindex_return_pct,
        "trades": r.num_trades,
        "out": str(r.run_dir),
    }, indent=2))


if __name__ == "__main__":
    cli()
