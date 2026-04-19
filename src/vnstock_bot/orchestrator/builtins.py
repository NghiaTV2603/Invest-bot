"""Built-in function-node implementations referenced by YAML presets.

Registered on module import. Tests that don't want real DB/SDK side effects
should either use their own `register_function` calls or pass programmatic
DagSpecs instead of loading YAML.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vnstock_bot.logging_setup import get_logger
from vnstock_bot.memory import record_event
from vnstock_bot.orchestrator.nodes import NodeContext, register_function

log = get_logger(__name__)


@register_function("build_market_snapshot")
async def build_market_snapshot(*, ctx: NodeContext) -> dict[str, Any]:
    """Tiny snapshot builder — pulls latest market_snapshot row from DB.

    Real regime-labeling logic lives in skills/macro_sector_desk preset (W3).
    For W2 we return a minimal summary good enough for prompting.
    """
    from vnstock_bot.db import queries

    row = queries.latest_market_snapshot()
    if not row:
        return {"regime": "unknown", "note": "no snapshot in DB"}
    close = row["vnindex_close"]
    volume = row["vnindex_volume"]
    foreign_net = (row["foreign_buy"] or 0) + (row["foreign_sell"] or 0)
    # Very rough regime label; will be replaced by a proper skill in W3.
    regime = "risk_on" if foreign_net > 0 else "risk_off"
    return {
        "regime": regime,
        "date": row["date"],
        "vnindex_close": close,
        "vnindex_volume": volume,
        "foreign_net_vnd": foreign_net,
    }


@register_function("record_research_event")
async def record_research_event(*, ctx: NodeContext) -> dict[str, Any]:
    agent_output = ctx.upstream.get("agent_output") or {}
    text = agent_output.get("text") if isinstance(agent_output, dict) else str(agent_output)
    event_id = record_event(
        kind="observation",
        summary=(text or "daily research run")[:400],
        payload={"preset": "daily_research", "tokens": agent_output.get("tokens_used")},
        trace_id=ctx.trace_id,
    )
    return {"event_id": event_id}


# ---------------------------------------------------------------- shadow_review (W5)

@register_function("parse_broker_csv_stub")
async def parse_broker_csv_stub(*, ctx: NodeContext, broker_hint: str = "auto") -> dict[str, Any]:
    """Parse broker CSV → RawTrade list + auto-detected broker."""
    from vnstock_bot.shadow import parsers

    journal_path = ctx.variables.get("journal_path")
    if not journal_path:
        raise ValueError("shadow_review: journal_path variable required")
    path = Path(str(journal_path))
    trades = parsers.parse(path, broker_hint=broker_hint or "auto")
    return {
        "broker": parsers.detect_broker(path),
        "journal_path": str(path),
        "trade_count": len(trades),
        # Serialize trades for the downstream agent node. Keep compact.
        "trades_preview": [
            {"ticker": t.ticker, "side": t.side, "qty": t.qty,
             "price": t.price, "traded_at": t.traded_at}
            for t in trades[:20]
        ],
    }


@register_function("run_shadow_backtest_stub")
async def run_shadow_backtest_stub(*, ctx: NodeContext) -> dict[str, Any]:
    """Full pipeline (parse → extract → backtest). Called after the agent
    node produces a rule preview — here we actually run the real extraction
    + backtest and return the structured result."""
    from vnstock_bot import shadow

    journal_path = ctx.variables.get("journal_path")
    if not journal_path:
        raise ValueError("shadow_review: journal_path variable required")
    ext = shadow.extract_shadow_strategy(str(journal_path))
    bt = shadow.run_shadow_backtest(ext["shadow_id"], ext)
    return {
        "shadow_id": ext["shadow_id"],
        "rule_count": len(ext["rules"]),
        "real_pnl": bt.real_pnl,
        "shadow_pnl": bt.shadow_pnl,
        "delta_pnl": bt.delta_pnl,
        "components": {
            "noise": bt.components.noise_trades_pnl,
            "early_exit": bt.components.early_exit_pnl,
            "late_exit": bt.components.late_exit_pnl,
            "overtrading": bt.components.overtrading_pnl,
            "missed": bt.components.missed_signals_pnl,
        },
    }


@register_function("render_shadow_report_stub")
async def render_shadow_report_stub(*, ctx: NodeContext) -> dict[str, Any]:
    from vnstock_bot import shadow

    journal_path = ctx.variables.get("journal_path")
    if not journal_path:
        raise ValueError("shadow_review: journal_path variable required")
    ext = shadow.extract_shadow_strategy(str(journal_path))
    bt = shadow.run_shadow_backtest(ext["shadow_id"], ext)
    html_path = shadow.render_shadow_report(ext["shadow_id"], ext, bt)
    return {
        "shadow_id": ext["shadow_id"],
        "report_path": str(html_path),
        "delta_pnl": bt.delta_pnl,
    }
