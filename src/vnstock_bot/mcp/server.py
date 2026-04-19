"""Minimal JSON-RPC 2.0 stdio MCP-like server.

This is NOT a full MCP spec implementation — we implement a compatible
subset (initialize + list_tools + call_tool) that covers what Claude
Desktop / Cursor / OpenClaw actually use. Upgrading to the official
`mcp` pypi package is a drop-in later when it becomes a hard dep.

Tools exposed — READ-ONLY ONLY (enforced via `read_only: True` in the
schema + a check in `handle_request`):

  get_price            — OHLC history for a ticker
  get_portfolio        — current cash + holdings snapshot
  search_memory        — FTS5 + file memory search
  get_timeline         — event timeline for a ticker
  recall_similar_decision — historical decisions matching (ticker, action)

NEVER add:
  - propose_trade
  - write_skill
  - append_strategy_note
  - any function that writes to DB or filesystem.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from vnstock_bot.logging_setup import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------- tool impls

def _get_price(args: dict[str, Any]) -> dict[str, Any]:
    from vnstock_bot.db import queries

    ticker = str(args.get("ticker", "")).upper()
    days = int(args.get("days", 60))
    rows = queries.get_ohlc(ticker, days=days)
    return {
        "ticker": ticker,
        "days": days,
        "bars": [
            {"date": r["date"], "o": r["open"], "h": r["high"],
             "l": r["low"], "c": r["close"], "v": r["volume"]}
            for r in rows
        ],
    }


def _get_portfolio(_args: dict[str, Any]) -> dict[str, Any]:
    from vnstock_bot.portfolio.simulator import load_portfolio
    p = load_portfolio()
    return {
        "cash_vnd": p.cash,
        "holdings": [
            {"ticker": h.ticker, "qty_total": h.qty_total,
             "qty_available": h.qty_available, "avg_cost": h.avg_cost,
             "opened_at": h.opened_at}
            for h in p.holdings
        ],
        "num_positions": len(p.holdings),
    }


def _search_memory(args: dict[str, Any]) -> dict[str, Any]:
    from vnstock_bot.memory import search_memory

    query = str(args.get("query", ""))
    k = int(args.get("k", 5))
    hits = search_memory(query, k=k)
    return {
        "query": query,
        "hits": [
            {"source": h.source, "score": h.score, "title": h.title,
             "snippet": h.snippet, "ticker": h.ticker,
             "created_at": h.created_at}
            for h in hits
        ],
    }


def _get_timeline(args: dict[str, Any]) -> dict[str, Any]:
    from vnstock_bot.memory import get_timeline

    ticker = str(args.get("ticker", "")).upper()
    days = int(args.get("days", 90))
    events = get_timeline(ticker=ticker, days=days)
    return {
        "ticker": ticker,
        "days": days,
        "events": [
            {"id": e.id, "created_at": e.created_at, "kind": e.kind,
             "summary": e.summary}
            for e in events
        ],
    }


def _recall_similar_decision(args: dict[str, Any]) -> dict[str, Any]:
    from vnstock_bot.memory import recall_similar_decision

    ticker = str(args.get("ticker", "")).upper()
    action = args.get("action")
    since_days = int(args.get("since_days", 365))
    decisions = recall_similar_decision(ticker, action=action, since_days=since_days)
    return {"ticker": ticker, "decisions": decisions}


# ---------------------------------------------------------------- registry

@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]
    read_only: bool = True              # Invariant — never flip this to False


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="get_price",
        description="OHLC history for a VN ticker (cached from vnstock).",
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "days": {"type": "integer", "default": 60},
            },
            "required": ["ticker"],
        },
        handler=_get_price,
    ),
    ToolSpec(
        name="get_portfolio",
        description="Current cash + holdings snapshot (T+2 qty_available).",
        input_schema={"type": "object", "properties": {}},
        handler=_get_portfolio,
    ),
    ToolSpec(
        name="search_memory",
        description="FTS5 search over bot memory (events + memory files).",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
        handler=_search_memory,
    ),
    ToolSpec(
        name="get_timeline",
        description="All events about a ticker in the last N days (newest first).",
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "days": {"type": "integer", "default": 90},
            },
            "required": ["ticker"],
        },
        handler=_get_timeline,
    ),
    ToolSpec(
        name="recall_similar_decision",
        description="Past bot decisions on the same ticker (+optional action).",
        input_schema={
            "type": "object",
            "properties": {
                "ticker": {"type": "string"},
                "action": {"type": "string",
                           "enum": ["BUY", "ADD", "TRIM", "SELL", "HOLD"]},
                "since_days": {"type": "integer", "default": 365},
            },
            "required": ["ticker"],
        },
        handler=_recall_similar_decision,
    ),
)


_BY_NAME = {t.name: t for t in TOOLS}


# ---------------------------------------------------------------- JSON-RPC

def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id,
            "error": {"code": code, "message": message}}


def _result(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    """Single-message handler. Used by `serve()` loop + tests."""
    msg_id = request.get("id")
    method = request.get("method", "")

    if method == "initialize":
        return _result(msg_id, {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "vnstock-bot", "version": "0.2.0"},
            "capabilities": {"tools": {}},
        })

    if method == "tools/list":
        return _result(msg_id, {
            "tools": [
                {
                    "name": t.name,
                    "description": t.description,
                    "inputSchema": t.input_schema,
                }
                for t in TOOLS
            ],
        })

    if method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        spec = _BY_NAME.get(name)
        if not spec:
            return _error(msg_id, -32601, f"unknown tool: {name}")
        if not spec.read_only:
            # Defense in depth. No exposed tool should be write-capable.
            return _error(msg_id, -32603,
                          f"tool {name!r} rejected: writes not allowed over MCP")
        try:
            output = spec.handler(args)
            return _result(msg_id, {
                "content": [{
                    "type": "text",
                    "text": json.dumps(output, ensure_ascii=False, default=str),
                }],
            })
        except Exception as e:  # noqa: BLE001
            log.warning("mcp_tool_error", tool=name, error=str(e))
            return _error(msg_id, -32000, f"tool {name} failed: {e}")

    return _error(msg_id, -32601, f"unknown method: {method}")


def serve(stdin=None, stdout=None) -> None:
    """Stdin/stdout line-based JSON-RPC loop. Designed for Claude Desktop
    which spawns the process + talks over stdio."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            err = _error(None, -32700, f"parse error: {e}")
            stdout.write(json.dumps(err) + "\n")
            stdout.flush()
            continue
        resp = handle_request(req)
        stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        stdout.flush()


def cli() -> None:
    """Entry point for `vnstock-bot-mcp`."""
    serve()
