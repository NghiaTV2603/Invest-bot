from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from vnstock_bot.data import vnstock_client
from vnstock_bot.data.holidays import iso
from vnstock_bot.data.watchlist import load_watchlist
from vnstock_bot.db import queries
from vnstock_bot.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class MarketSnapshot:
    date: str
    vnindex_close: float | None
    vnindex_change_pct: float | None
    top_gainers: list[dict[str, Any]]
    top_losers: list[dict[str, Any]]
    foreign_net_5d_vnd: int
    foreign_net_20d_vnd: int


def build_snapshot(today: date) -> MarketSnapshot:
    # VN-Index
    vnindex_bars = vnstock_client.fetch_index("VNINDEX", today - timedelta(days=14), today)
    vni_close = vnindex_bars[-1].close / 100.0 if vnindex_bars else None
    vni_prev = vnindex_bars[-2].close / 100.0 if len(vnindex_bars) >= 2 else None
    change_pct = ((vni_close - vni_prev) / vni_prev * 100.0) if (vni_close and vni_prev) else None

    # Top movers — compute from watchlist delta today vs prev
    wl = load_watchlist()
    movers: list[dict[str, Any]] = []
    for entry in wl.tickers:
        bars = vnstock_client.fetch_ohlc(entry.ticker, today - timedelta(days=7), today)
        if len(bars) < 2:
            continue
        last, prev = bars[-1], bars[-2]
        if prev.close <= 0:
            continue
        pct = (last.close - prev.close) / prev.close * 100.0
        movers.append({
            "ticker": entry.ticker,
            "close": last.close,
            "change_pct": round(pct, 2),
            "volume": last.volume,
        })
        # populate ohlc cache while we're at it
        for b in bars:
            queries.upsert_ohlc(entry.ticker, b.date, b.open, b.high, b.low, b.close, b.volume)

    movers_sorted = sorted(movers, key=lambda x: x["change_pct"], reverse=True)
    top_gainers = movers_sorted[:5]
    top_losers = list(reversed(movers_sorted[-5:]))

    # Foreign flow (best-effort)
    flows = vnstock_client.fetch_foreign_flow(days=25)
    flows_sorted = sorted(flows, key=lambda x: x["date"], reverse=True)
    fn5 = sum(f["net_vnd"] for f in flows_sorted[:5])
    fn20 = sum(f["net_vnd"] for f in flows_sorted[:20])

    # Also cache vnindex bars
    for b in vnindex_bars:
        queries.upsert_ohlc("VNINDEX", b.date, b.open, b.high, b.low, b.close, b.volume)

    # Persist snapshot row
    vnindex_today = vnindex_bars[-1] if vnindex_bars else None
    queries.upsert_market_snapshot({
        "date": iso(today),
        "vnindex_open": (vnindex_today.open / 100.0) if vnindex_today else None,
        "vnindex_high": (vnindex_today.high / 100.0) if vnindex_today else None,
        "vnindex_low": (vnindex_today.low / 100.0) if vnindex_today else None,
        "vnindex_close": vni_close,
        "vnindex_volume": (vnindex_today.volume if vnindex_today else 0),
        "foreign_buy": max(0, fn20),
        "foreign_sell": min(0, fn20),
        "top_movers": {"gainers": top_gainers, "losers": top_losers},
    })

    log.info("market_snapshot_built", date=iso(today), vni=vni_close, top_gainer=top_gainers[:1])
    return MarketSnapshot(
        date=iso(today),
        vnindex_close=vni_close,
        vnindex_change_pct=change_pct,
        top_gainers=top_gainers,
        top_losers=top_losers,
        foreign_net_5d_vnd=fn5,
        foreign_net_20d_vnd=fn20,
    )
