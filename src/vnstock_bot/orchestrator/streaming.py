"""Streaming event emitter for long-running DAG runs.

The Telegram bot subscribes to these events to show progress
(`✅ researcher (8s) → ⏳ technical_panel…`). Orchestrator emits events
regardless; having no subscriber is a valid default.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from vnstock_bot.data.holidays import now_vn

EventType = Literal[
    "dag_start",
    "dag_end",
    "node_start",
    "node_end",
    "node_fail",
]


@dataclass
class StreamEvent:
    trace_id: str
    type: EventType
    timestamp: str
    node_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


# Async callback signature. Sync callbacks allowed via lambda wrappers.
OnEvent = Callable[[StreamEvent], Awaitable[None]]


async def _noop_listener(_: StreamEvent) -> None:
    return None


class EventBus:
    """Fan-out with per-listener isolation — one listener's exception must
    not prevent other listeners from receiving the event, and must not
    crash the DAG runner."""

    def __init__(self, listeners: list[OnEvent] | None = None) -> None:
        self._listeners: list[OnEvent] = list(listeners or [])

    def add(self, listener: OnEvent) -> None:
        self._listeners.append(listener)

    async def emit(
        self,
        trace_id: str,
        type_: EventType,
        node_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        if not self._listeners:
            return
        event = StreamEvent(
            trace_id=trace_id,
            type=type_,
            timestamp=now_vn().isoformat(),
            node_id=node_id,
            data=data or {},
        )
        # Streaming must never break the run. Listeners are best-effort —
        # a crashing listener is isolated so the others still receive the
        # event and the DAG continues.
        for listener in self._listeners:
            with contextlib.suppress(Exception):
                await listener(event)
