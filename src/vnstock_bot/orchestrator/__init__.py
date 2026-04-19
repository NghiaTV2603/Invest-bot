"""V2 orchestrator — async DAG runner + swarm preset loader.

Public API. Internal modules (`dag`, `nodes`, `preset_loader`) are not meant
to be imported directly by the rest of the codebase; go through this module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

# Register built-in function-node handlers on package import.
from vnstock_bot.orchestrator import builtins as _builtins  # noqa: F401
from vnstock_bot.orchestrator.dag import load_trace, run_dag
from vnstock_bot.orchestrator.nodes import (
    NodeContext,
    make_default_agent_fn,
    register_function,
)
from vnstock_bot.orchestrator.preset_loader import (
    list_presets,
    load_preset,
    validate_variables,
)
from vnstock_bot.orchestrator.streaming import EventBus, OnEvent, StreamEvent
from vnstock_bot.orchestrator.types import (
    DagResult,
    DagSpec,
    DagStatus,
    NodeResult,
    NodeSpec,
    NodeStatus,
    NodeType,
)


async def run_preset(
    name: str,
    variables: dict[str, Any] | None = None,
    *,
    agent_fn: Callable | None = None,
    listeners: list[OnEvent] | None = None,
    trace_id: str | None = None,
    persist: bool = True,
) -> DagResult:
    """High-level: load YAML preset, resolve variables, run DAG."""
    spec = load_preset(name)
    resolved = validate_variables(spec, variables or {})
    return await run_dag(
        spec=spec,
        variables=resolved,
        agent_fn=agent_fn,
        listeners=listeners,
        trace_id=trace_id,
        persist=persist,
    )


__all__ = [
    # high-level
    "run_preset",
    "run_dag",
    "load_trace",
    "load_preset",
    "list_presets",
    "validate_variables",
    # function-node registry
    "register_function",
    "NodeContext",
    "make_default_agent_fn",
    # events
    "StreamEvent",
    "OnEvent",
    "EventBus",
    # types
    "DagSpec",
    "NodeSpec",
    "DagResult",
    "NodeResult",
    "DagStatus",
    "NodeStatus",
    "NodeType",
]
