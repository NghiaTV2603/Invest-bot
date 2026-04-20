"""MCP-style tools exposed to Claude Agent SDK.

We use claude_agent_sdk's @tool + create_sdk_mcp_server pattern.
Tools validate input, hit DB/vnstock, and return structured JSON.
"""

from __future__ import annotations

import json
from typing import Any

from vnstock_bot.data.watchlist import load_watchlist
from vnstock_bot.db import queries
from vnstock_bot.logging_setup import get_logger
from vnstock_bot.portfolio.simulator import load_portfolio
from vnstock_bot.research.skill_loader import list_all_skills, read_skill

log = get_logger(__name__)


# ---------------------------------------------------------------- tool impls

def tool_load_skill(args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name", "")
    try:
        content = read_skill(name)
        return {"content": [{"type": "text", "text": content}]}
    except Exception as e:  # noqa: BLE001
        return {"content": [{"type": "text", "text": f"ERROR: {e}"}], "is_error": True}


def tool_list_skills(args: dict[str, Any]) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": "\n".join(list_all_skills())}]}


def tool_get_price(args: dict[str, Any]) -> dict[str, Any]:
    ticker = args["ticker"].upper()
    days = int(args.get("days", 60))
    rows = queries.get_ohlc(ticker, days=days)
    if not rows:
        return {"content": [{"type": "text", "text": f"no data for {ticker}"}]}
    payload = [
        {"date": r["date"], "o": r["open"], "h": r["high"], "l": r["low"], "c": r["close"], "v": r["volume"]}
        for r in rows
    ]
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}]}


def tool_get_fundamentals(args: dict[str, Any]) -> dict[str, Any]:
    from vnstock_bot.data import vnstock_client

    ticker = args["ticker"].upper()
    data = vnstock_client.fetch_fundamentals(ticker)
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}]}


def tool_market_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    row = queries.latest_market_snapshot()
    if not row:
        return {"content": [{"type": "text", "text": "no snapshot yet"}]}
    snap = {
        "date": row["date"],
        "vnindex_close": row["vnindex_close"],
        "vnindex_volume": row["vnindex_volume"],
        "foreign_net_vnd": (row["foreign_buy"] or 0) + (row["foreign_sell"] or 0),
        "top_movers": json.loads(row["top_movers_json"] or "{}"),
    }
    return {"content": [{"type": "text", "text": json.dumps(snap, ensure_ascii=False)}]}


def tool_get_portfolio_status(args: dict[str, Any]) -> dict[str, Any]:
    p = load_portfolio()
    wl = load_watchlist()
    holdings = [
        {
            "ticker": h.ticker,
            "qty_total": h.qty_total,
            "qty_available": h.qty_available,
            "avg_cost": h.avg_cost,
            "opened_at": h.opened_at,
            "sector": wl.sector_of(h.ticker),
        }
        for h in p.holdings
    ]
    return {"content": [{"type": "text", "text": json.dumps({
        "cash_vnd": p.cash,
        "holdings": holdings,
        "num_positions": len(p.holdings),
    }, ensure_ascii=False)}]}


# Side-effect tools — these write to DB via a buffer so we can validate before persist.
# The agent runner reads this buffer after the query loop ends.

_proposal_buffer: list[dict[str, Any]] = []
_strategy_append_buffer: list[str] = []
_skill_write_buffer: list[tuple[str, str]] = []


def reset_buffers() -> None:
    _proposal_buffer.clear()
    _strategy_append_buffer.clear()
    _skill_write_buffer.clear()


def get_proposals() -> list[dict[str, Any]]:
    return list(_proposal_buffer)


def get_strategy_notes() -> list[str]:
    return list(_strategy_append_buffer)


def get_skill_writes() -> list[tuple[str, str]]:
    return list(_skill_write_buffer)


def tool_propose_trade(args: dict[str, Any]) -> dict[str, Any]:
    _proposal_buffer.append(args)
    return {"content": [{"type": "text",
        "text": f"buffered proposal #{len(_proposal_buffer)}: {args.get('action')} {args.get('ticker')} {args.get('qty')}"}]}


def tool_append_strategy_note(args: dict[str, Any]) -> dict[str, Any]:
    _strategy_append_buffer.append(args["note"])
    return {"content": [{"type": "text", "text": "strategy note buffered"}]}


def tool_write_skill(args: dict[str, Any]) -> dict[str, Any]:
    _skill_write_buffer.append((args["name"], args["content"]))
    return {"content": [{"type": "text", "text": f"skill write buffered: {args['name']}"}]}


# ---------------------------------------------------------------- registry for SDK

TOOLS_SCHEMA = [
    {
        "name": "load_skill",
        "description": "Load full content of a skill markdown by name (e.g. 'analysis/technical-trend').",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        "handler": tool_load_skill,
    },
    {
        "name": "list_skills",
        "description": "List all available skill names.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_list_skills,
    },
    {
        "name": "get_price",
        "description": "Get OHLC for a ticker over the last N days.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}, "days": {"type": "integer", "default": 60}},
            "required": ["ticker"],
        },
        "handler": tool_get_price,
    },
    {
        "name": "get_fundamentals",
        "description": "Get basic financial ratios (ROE, P/E, P/B, D/E, EPS) for a ticker.",
        "input_schema": {
            "type": "object",
            "properties": {"ticker": {"type": "string"}},
            "required": ["ticker"],
        },
        "handler": tool_get_fundamentals,
    },
    {
        "name": "market_snapshot",
        "description": "Latest market snapshot: VN-Index close/volume, foreign flow, top movers.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_market_snapshot,
    },
    {
        "name": "get_portfolio_status",
        "description": "Current cash + holdings (with qty_available for T+2 tracking).",
        "input_schema": {"type": "object", "properties": {}},
        "handler": tool_get_portfolio_status,
    },
    {
        "name": "propose_trade",
        "description": (
            "Submit a decision (BUY/ADD/TRIM/SELL/HOLD). Buffered for validation; "
            "MUST include all required fields per schema."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "action": {"type": "string", "enum": ["BUY", "ADD", "TRIM", "SELL", "HOLD"]},
                "qty": {"type": "integer"},
                "target_price": {"type": ["integer", "null"]},
                "stop_loss": {"type": ["integer", "null"]},
                "thesis": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}},
                "risks": {"type": "array", "items": {"type": "string"}},
                "invalidation": {"type": "string"},
                "skills_used": {"type": "array", "items": {"type": "string"}},
                "playbook_used": {"type": ["string", "null"]},
                "conviction": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["ticker", "action", "qty", "thesis", "evidence", "risks",
                        "invalidation", "skills_used", "conviction"],
        },
        "handler": tool_propose_trade,
    },
    {
        "name": "append_strategy_note",
        "description": "Append a short bullet to strategy.md (weekly review only).",
        "input_schema": {
            "type": "object",
            "properties": {"note": {"type": "string"}},
            "required": ["note"],
        },
        "handler": tool_append_strategy_note,
    },
    {
        "name": "write_skill",
        "description": "Overwrite a skill/playbook markdown file (weekly review only).",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string"}, "content": {"type": "string"}},
            "required": ["name", "content"],
        },
        "handler": tool_write_skill,
    },
]


ALL_TOOL_NAMES = [t["name"] for t in TOOLS_SCHEMA]
DAILY_TOOL_NAMES = [
    "load_skill", "list_skills", "get_price", "get_fundamentals",
    "market_snapshot", "get_portfolio_status", "propose_trade",
]
CHAT_TOOL_NAMES = [
    "load_skill", "get_price", "market_snapshot", "get_portfolio_status",
]
WEEKLY_TOOL_NAMES = [
    "list_skills", "load_skill", "get_price",
    "append_strategy_note", "write_skill",
]
