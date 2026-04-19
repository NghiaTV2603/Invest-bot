from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BiasName = Literal[
    "disposition_effect",
    "overtrading",
    "chase_momentum",
    "anchoring",
    "hot_hand",
    "skill_dogma",
    "recency",
]
BiasSeverity = Literal["low", "medium", "high"]


@dataclass
class TradeLike:
    """Minimal shape a detector needs. Shadow account parsers emit this,
    weekly_check builds it from DB decisions + fills."""
    ticker: str
    side: Literal["BUY", "SELL"]
    qty: int
    price: int                  # VND int
    traded_at: str              # ISO datetime
    pnl: int | None = None      # filled when pair (BUY→SELL) closed
    hold_days: int | None = None
    entry_price: int | None = None  # filled on SELL
    pct_nav_at_entry: float | None = None  # for hot-hand sizing


@dataclass
class DecisionLike:
    """Used by skill_dogma + recency detectors on bot's own decisions."""
    decision_id: int
    created_at: str
    ticker: str
    action: str
    thesis: str
    skills_used: list[str]


@dataclass
class BiasResult:
    name: BiasName
    severity: BiasSeverity
    metric: float                 # raw number (formula output)
    threshold_medium: float
    threshold_high: float
    evidence: str                 # human-readable 1-line
    sample_size: int

    @property
    def is_actionable(self) -> bool:
        return self.severity in ("medium", "high")
