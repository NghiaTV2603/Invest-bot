"""Shadow Account — upload broker CSV → rule extraction → Delta-PnL report.

Public API matches the 4 tools described in PLAN_V2 §5.1:
  - analyze_trade_journal  -> profile + 4 bias score
  - extract_shadow_strategy -> 3-5 rules
  - run_shadow_backtest     -> Delta-PnL components + counterfactuals
  - render_shadow_report    -> 8-section HTML at data/reports/

Persistence: shadow_accounts + shadow_rules + shadow_backtests tables.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from vnstock_bot.bias import detect_all
from vnstock_bot.bias.types import TradeLike
from vnstock_bot.config import get_settings
from vnstock_bot.data.holidays import now_vn
from vnstock_bot.db.connection import get_connection, transaction
from vnstock_bot.shadow import backtester, parsers, report
from vnstock_bot.shadow.pairing import pair_fifo, summarize
from vnstock_bot.shadow.rule_extractor import extract, new_shadow_id
from vnstock_bot.shadow.types import (
    Broker,
    DeltaComponents,
    RawTrade,
    Roundtrip,
    ShadowBacktestResult,
    ShadowRule,
    TradingProfile,
)

# ---------------------------------------------------------------- profile

def _build_profile(
    trades: list[RawTrade], roundtrips: list[Roundtrip]
) -> TradingProfile:
    stats = summarize(roundtrips)
    winners = [r for r in roundtrips if r.is_winner]
    losers = [r for r in roundtrips if r.pnl < 0]
    avg_win = int(sum(r.pnl for r in winners) / len(winners)) if winners else 0
    avg_loss = int(sum(r.pnl for r in losers) / len(losers)) if losers else 0

    ticker_counts = Counter(t.ticker for t in trades).most_common(10)
    sector_counts = Counter(
        r.sector or "đa ngành" for r in roundtrips
    ).most_common(10)

    start = min((t.traded_at for t in trades), default=None)
    end = max((t.traded_at for t in trades), default=None)

    return TradingProfile(
        total_trades=len(trades),
        total_roundtrips=len(roundtrips),
        winners=len(winners),
        losers=len(losers),
        win_rate=float(stats["win_rate"]),
        total_pnl=int(stats["total_pnl"]),
        avg_hold_days=float(stats["avg_hold"]),
        avg_win_pnl=avg_win,
        avg_loss_pnl=avg_loss,
        top_tickers_by_trades=ticker_counts,
        top_sectors=sector_counts,
        start_date=(start or "")[:10] or None,
        end_date=(end or "")[:10] or None,
    )


# ---------------------------------------------------------------- bias bridge

def _trades_to_biaslike(
    trades: list[RawTrade], roundtrips: list[Roundtrip]
) -> list[TradeLike]:
    """Convert for bias detectors. SELL rows get pnl/hold_days/entry from
    matching roundtrips; BUY rows pass through without pnl."""
    # Build per-SELL lookup by (ticker, sell_at) → weighted avg entry + sum pnl
    sells_agg: dict[tuple[str, str], dict[str, int]] = {}
    for rt in roundtrips:
        key = (rt.ticker, rt.sell_at)
        acc = sells_agg.setdefault(
            key, {"qty": 0, "cost": 0, "pnl": 0, "hold": 0, "first_buy": rt.buy_at}
        )
        acc["qty"] += rt.qty
        acc["cost"] += rt.buy_price * rt.qty
        acc["pnl"] += rt.pnl
        # use longest-held slice for hold_days
        acc["hold"] = max(acc["hold"], rt.hold_days)
        if rt.buy_at < acc["first_buy"]:
            acc["first_buy"] = rt.buy_at

    out: list[TradeLike] = []
    for t in trades:
        if t.side == "BUY":
            out.append(TradeLike(
                ticker=t.ticker, side="BUY", qty=t.qty, price=t.price,
                traded_at=t.traded_at,
            ))
        else:
            agg = sells_agg.get((t.ticker, t.traded_at))
            pnl = agg["pnl"] if agg else None
            hold = agg["hold"] if agg else None
            entry = (agg["cost"] // agg["qty"]) if agg and agg["qty"] > 0 else None
            out.append(TradeLike(
                ticker=t.ticker, side="SELL", qty=t.qty, price=t.price,
                traded_at=t.traded_at, pnl=pnl, hold_days=hold,
                entry_price=entry,
            ))
    return out


# ---------------------------------------------------------------- tools

def analyze_trade_journal(
    journal_path: str | Path,
    broker_hint: Broker | str = "auto",
    sector_lookup: dict[str, str] | None = None,
) -> dict[str, Any]:
    path = Path(journal_path)
    trades = parsers.parse(path, broker_hint=broker_hint)
    roundtrips = pair_fifo(trades, sector_lookup=sector_lookup)
    profile = _build_profile(trades, roundtrips)

    bias_like = _trades_to_biaslike(trades, roundtrips)
    bias_results = detect_all(trades=bias_like, decisions=[])

    return {
        "broker": parsers.detect_broker(path),
        "profile": profile,
        "roundtrips": roundtrips,
        "trades": trades,
        "bias": bias_results,
    }


def extract_shadow_strategy(
    journal_path: str | Path,
    broker_hint: Broker | str = "auto",
    sector_lookup: dict[str, str] | None = None,
    min_support: int = 3,
    max_rules: int = 5,
) -> dict[str, Any]:
    result = analyze_trade_journal(
        journal_path, broker_hint=broker_hint, sector_lookup=sector_lookup,
    )
    rules = extract(result["roundtrips"],
                    min_support=min_support, max_rules=max_rules)
    shadow_id = new_shadow_id()

    # Persist shadow + rules
    broker = result["broker"]
    profile: TradingProfile = result["profile"]
    with transaction() as conn:
        conn.execute(
            """INSERT INTO shadow_accounts
                (shadow_id, broker, journal_path, uploaded_at,
                 total_trades, roundtrips, start_date, end_date, real_pnl)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (shadow_id, broker, str(journal_path), now_vn().isoformat(),
             profile.total_trades, profile.total_roundtrips,
             profile.start_date, profile.end_date, profile.total_pnl),
        )
        for r in rules:
            conn.execute(
                """INSERT INTO shadow_rules
                    (shadow_id, rule_id, human_text, support_count,
                     coverage_rate, sector, hour_bucket,
                     holding_min, holding_max, win_rate, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (shadow_id, r.rule_id, r.human_text, r.support_count,
                 r.coverage_rate, r.sector, r.hour_bucket,
                 r.holding_min, r.holding_max, r.win_rate,
                 json.dumps(r.metadata, ensure_ascii=False, default=str)),
            )

    return {
        "shadow_id": shadow_id,
        "rules": rules,
        "profile": profile,
        "roundtrips": result["roundtrips"],
        "trades": result["trades"],
        "bias": result["bias"],
    }


def run_shadow_backtest(shadow_id: str, extraction: dict[str, Any]) -> ShadowBacktestResult:
    rules: list[ShadowRule] = extraction["rules"]
    roundtrips: list[Roundtrip] = extraction["roundtrips"]
    result = backtester.run(shadow_id, roundtrips, rules)

    with transaction() as conn:
        c = result.components
        conn.execute(
            """INSERT INTO shadow_backtests
                (shadow_id, run_at, real_pnl, shadow_pnl, delta_pnl,
                 noise_trades_pnl, early_exit_pnl, late_exit_pnl,
                 overtrading_pnl, missed_signals_pnl, metrics_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (shadow_id, now_vn().isoformat(),
             result.real_pnl, result.shadow_pnl, result.delta_pnl,
             c.noise_trades_pnl, c.early_exit_pnl, c.late_exit_pnl,
             c.overtrading_pnl, c.missed_signals_pnl,
             json.dumps({"per_sector": result.per_sector},
                        ensure_ascii=False, default=str)),
        )
    return result


def render_shadow_report(
    shadow_id: str,
    extraction: dict[str, Any],
    backtest_result: ShadowBacktestResult,
    out_dir: Path | None = None,
) -> Path:
    profile: TradingProfile = extraction["profile"]
    rules: list[ShadowRule] = extraction["rules"]
    out_dir = out_dir or (get_settings().absolute_raw_dir.parent / "reports" / "shadow")
    out_path = Path(out_dir) / f"{shadow_id}.html"
    report.write_html(profile, rules, backtest_result, out_path)

    with transaction() as conn:
        conn.execute(
            "UPDATE shadow_backtests SET report_html_path = ? "
            "WHERE shadow_id = ? AND run_at = ("
            "  SELECT max(run_at) FROM shadow_backtests WHERE shadow_id = ?)",
            (str(out_path), shadow_id, shadow_id),
        )
    return out_path


def load_shadow_summary(shadow_id: str) -> dict[str, Any] | None:
    conn = get_connection()
    acc = conn.execute(
        "SELECT * FROM shadow_accounts WHERE shadow_id = ?", (shadow_id,)
    ).fetchone()
    if not acc:
        return None
    rules = conn.execute(
        "SELECT * FROM shadow_rules WHERE shadow_id = ? ORDER BY support_count DESC",
        (shadow_id,),
    ).fetchall()
    latest_bt = conn.execute(
        "SELECT * FROM shadow_backtests WHERE shadow_id = ? "
        "ORDER BY run_at DESC LIMIT 1",
        (shadow_id,),
    ).fetchone()
    return {
        "account": dict(acc),
        "rules": [dict(r) for r in rules],
        "latest_backtest": dict(latest_bt) if latest_bt else None,
    }


__all__ = [
    "analyze_trade_journal",
    "extract_shadow_strategy",
    "run_shadow_backtest",
    "render_shadow_report",
    "load_shadow_summary",
    "RawTrade", "Roundtrip", "ShadowRule", "ShadowBacktestResult",
    "DeltaComponents", "TradingProfile",
]
