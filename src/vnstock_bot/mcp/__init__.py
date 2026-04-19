"""V2 MCP server module — exposes read-only vnstock-bot tools over
MCP stdio so Claude Desktop / Cursor / OpenClaw can call into bot state.

Entry point: `vnstock-bot-mcp` CLI (registered in pyproject.toml scripts).

ALL exposed tools are READ-ONLY (enforced in the schema). Never expose
propose_trade, write_skill, or file-write tools over MCP — that would
let any connected client mutate bot state outside our validator chain.
"""

from __future__ import annotations

from vnstock_bot.mcp.server import TOOLS, handle_request, serve

__all__ = ["TOOLS", "handle_request", "serve"]
