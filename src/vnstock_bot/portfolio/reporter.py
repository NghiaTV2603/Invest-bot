"""Render markdown reports for Telegram."""

from __future__ import annotations

from datetime import date

from vnstock_bot.data.holidays import iso
from vnstock_bot.db import queries
from vnstock_bot.portfolio.simulator import _ohlc_on, load_portfolio
from vnstock_bot.telegram.format import fmt_pct as _fmt_pct
from vnstock_bot.telegram.format import fmt_vnd as _fmt_vnd


def portfolio_status(today: date) -> str:
    p = load_portfolio()
    prices: dict[str, int] = {}
    for h in p.holdings:
        o = _ohlc_on(h.ticker, today)
        prices[h.ticker] = o["close"] if o and o["close"] > 0 else h.avg_cost

    mv = p.market_value(prices)
    total = p.cash + mv
    initial = queries.get_equity_recent(days=400)
    first_total = initial[0]["total"] if initial else total
    pnl_total_pct = (total - first_total) / first_total * 100 if first_total else 0

    lines = [
        f"*Portfolio — {iso(today)}*",
        f"NAV: {_fmt_vnd(total)}   ({_fmt_pct(pnl_total_pct)} so với ban đầu)",
        f"Cash: {_fmt_vnd(p.cash)}   MV: {_fmt_vnd(mv)}",
        "",
    ]
    if not p.holdings:
        lines.append("_Không có holding_")
    else:
        lines.append("*Holdings:*")
        for h in p.holdings:
            px = prices[h.ticker]
            pnl_pct = (px - h.avg_cost) / h.avg_cost * 100 if h.avg_cost else 0
            t2_note = "" if h.qty_available == h.qty_total else f"  (T+2: {h.qty_available}/{h.qty_total})"
            lines.append(
                f"• {h.ticker}: {h.qty_total}cp  "
                f"vốn {_fmt_vnd(h.avg_cost)}  giá {_fmt_vnd(px)}  {_fmt_pct(pnl_pct)}{t2_note}"
            )
    return "\n".join(lines)


def daily_report(today: date, decisions: list, rejections: list, fills: list, stats: dict) -> str:
    lines = [f"📊 *Daily report — {iso(today)}*", ""]

    # Fills (from prev day's pending)
    if fills:
        lines.append("*Đã khớp hôm nay:*")
        for f in fills:
            lines.append(
                f"• {f.side} {f.ticker} {f.qty}cp @ {_fmt_vnd(f.fill_price)}  phí {_fmt_vnd(f.fee)}"
            )
        lines.append("")

    # New decisions
    if decisions:
        lines.append("*Quyết định mới (khớp phiên kế tiếp):*")
        for d in decisions:
            tgt = _fmt_vnd(d.target_price) if d.target_price else "—"
            stp = _fmt_vnd(d.stop_loss) if d.stop_loss else "—"
            lines.append(
                f"• *{d.action}* {d.ticker} {d.qty}cp  (conv {d.conviction}/5)\n"
                f"  Thesis: {d.thesis}\n"
                f"  Target {tgt} / Stop {stp}"
            )
        lines.append("")

    if rejections:
        lines.append(f"⚠️ *{len(rejections)} proposal bị reject:*")
        for r in rejections[:5]:
            err_short = "; ".join(r["errors"][:2])
            lines.append(f"• {r['ticker']}: {err_short}")
        lines.append("")

    lines.append(f"*NAV:* {_fmt_vnd(stats.get('total', 0))}   "
                 f"Cash: {_fmt_vnd(stats.get('cash', 0))}")
    return "\n".join(lines)
