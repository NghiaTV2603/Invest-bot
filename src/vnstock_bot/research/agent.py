"""Claude Agent SDK wrapper — only this module imports claude_agent_sdk."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vnstock_bot.config import get_settings
from vnstock_bot.logging_setup import get_logger
from vnstock_bot.research import tools as tmod

log = get_logger(__name__)


@dataclass
class AgentResult:
    text: str               # final assistant message
    turns: int
    tokens_used: int


# Guarded import so other modules don't crash when SDK absent during tests.
def _import_sdk():
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient, create_sdk_mcp_server, tool
    return ClaudeSDKClient, ClaudeAgentOptions, tool, create_sdk_mcp_server


def _build_mcp_server(tool_names: list[str]):
    """Bundle our tool handlers as an in-process MCP server for the SDK."""
    _, _, tool, create_sdk_mcp_server = _import_sdk()

    tool_defs = []
    for spec in tmod.TOOLS_SCHEMA:
        if spec["name"] not in tool_names:
            continue
        # Construct an SDK @tool at runtime
        name = spec["name"]
        desc = spec["description"]
        schema = spec["input_schema"]
        handler = spec["handler"]

        async def _wrapper(args, _handler=handler):
            return _handler(args)

        tool_defs.append(tool(name, desc, schema)(_wrapper))
    return create_sdk_mcp_server(name="vnstock_bot_tools", version="0.1.0", tools=tool_defs)


async def run_agent(
    user_prompt: str,
    system_prompt: str,
    tool_names: list[str],
    max_turns: int | None = None,
) -> AgentResult:
    """Run a Claude agent turn-loop and return final text + buffered side effects."""
    ClaudeSDKClient, ClaudeAgentOptions, _tool, _mcp = _import_sdk()
    settings = get_settings()

    tmod.reset_buffers()

    mcp = _build_mcp_server(tool_names)
    allowed = [f"mcp__vnstock_bot_tools__{name}" for name in tool_names]

    opts = ClaudeAgentOptions(
        system_prompt=system_prompt,
        mcp_servers={"vnstock_bot_tools": mcp},
        allowed_tools=allowed,
        model=settings.claude_model,
        max_turns=max_turns or settings.claude_max_turns,
        permission_mode="bypassPermissions",
    )

    from claude_agent_sdk import (
        AssistantMessage,
        ResultMessage,
        TextBlock,
    )

    text_parts: list[str] = []
    turns = 0
    tokens_used = 0
    final_text = ""

    def _extract_tokens(usage) -> int:
        if usage is None:
            return 0
        if isinstance(usage, dict):
            return int(usage.get("input_tokens", 0) or 0) + int(usage.get("output_tokens", 0) or 0)
        return int(getattr(usage, "input_tokens", 0) or 0) + int(getattr(usage, "output_tokens", 0) or 0)

    async with ClaudeSDKClient(options=opts) as client:
        await client.query(user_prompt)
        async for msg in client.receive_response():
            turns += 1
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        text_parts.append(block.text)
                tokens_used += _extract_tokens(getattr(msg, "usage", None))
            elif isinstance(msg, ResultMessage):
                # Final aggregate usage
                tokens_used = max(tokens_used, _extract_tokens(getattr(msg, "usage", None)))
                # Some SDK versions surface a `.result` string
                result_str = getattr(msg, "result", None)
                if isinstance(result_str, str) and result_str.strip():
                    text_parts.append(result_str)

    final_text = "\n".join(p for p in text_parts if p).strip()
    log.info("agent_done", turns=turns, tokens=tokens_used, proposals=len(tmod.get_proposals()), text_len=len(final_text))
    return AgentResult(text=final_text, turns=turns, tokens_used=tokens_used)


# ---------------------------------------------------------------- high-level entry points

async def daily_research(watchlist_context: str) -> tuple[AgentResult, list[dict[str, Any]]]:
    from vnstock_bot.research.prompts import daily_system_prompt

    settings = get_settings()
    strategy = settings.strategy_path.read_text(encoding="utf-8") if settings.strategy_path.exists() else ""
    sys_prompt = daily_system_prompt(strategy)

    user_prompt = (
        "Hãy research thị trường hôm nay dựa trên snapshot + watchlist + holdings "
        "dưới đây. Với mỗi ticker quan tâm, gọi đúng tools, follow playbook, rồi "
        "`propose_trade`. Kết thúc bằng tóm tắt tiếng Việt ≤ 8 dòng.\n\n"
        + watchlist_context
    )

    result = await run_agent(user_prompt, sys_prompt, tmod.DAILY_TOOL_NAMES)
    return result, tmod.get_proposals()


async def weekly_review(context: str) -> tuple[AgentResult, list[str], list[tuple[str, str]]]:
    from vnstock_bot.research.prompts import weekly_review_system_prompt

    settings = get_settings()
    strategy = settings.strategy_path.read_text(encoding="utf-8") if settings.strategy_path.exists() else ""
    sys_prompt = weekly_review_system_prompt(strategy)

    user_prompt = (
        "Weekly review. Dữ liệu tuần qua:\n\n" + context +
        "\n\nYêu cầu: (1) append ≥ 1 bullet strategy.md. "
        "(2) nếu có skill win-rate < 40% và uses ≥ 10 → sửa skill đó qua write_skill."
    )
    result = await run_agent(user_prompt, sys_prompt, tmod.WEEKLY_TOOL_NAMES, max_turns=30)
    return result, tmod.get_strategy_notes(), tmod.get_skill_writes()


async def chat(user_message: str, history: list[dict[str, str]]) -> AgentResult:
    from vnstock_bot.research.prompts import chat_system_prompt

    history_text = "\n".join(f"{t['role'].upper()}: {t['content']}" for t in history[-10:])
    user_prompt = f"Lịch sử gần đây:\n{history_text}\n\nUSER: {user_message}"
    return await run_agent(user_prompt, chat_system_prompt(), tmod.CHAT_TOOL_NAMES, max_turns=10)
