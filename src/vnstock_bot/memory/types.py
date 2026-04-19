from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

EventKind = Literal["chat", "decision", "tool_call", "note", "observation"]
SummaryScope = Literal["daily", "weekly", "ticker", "session"]
MemoryLayer = Literal["user_prefs", "project", "reference"]


class EventInput(BaseModel):
    kind: EventKind
    summary: str = Field(..., min_length=1, max_length=500)
    payload: dict[str, Any] = Field(default_factory=dict)
    ticker: str | None = None
    decision_id: int | None = None
    trace_id: str | None = None


@dataclass
class Event:
    id: int
    created_at: str
    kind: EventKind
    ticker: str | None
    decision_id: int | None
    trace_id: str | None
    summary: str
    payload: dict[str, Any]


@dataclass
class Summary:
    id: int
    created_at: str
    scope: SummaryScope
    key: str
    body: str
    event_count: int


@dataclass
class Pattern:
    id: int
    created_at: str
    body: str
    support_count: int
    confirmed: bool
    last_seen_at: str
    metadata: dict[str, Any]


@dataclass
class MemoryFile:
    """A markdown file in the memory dir with YAML frontmatter."""

    path: Path
    layer: MemoryLayer
    name: str                      # stem without .md
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""

    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title") or self.name)

    @property
    def description(self) -> str:
        return str(self.frontmatter.get("description") or "")
