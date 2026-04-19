from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ActionType = Literal["BUY", "ADD", "TRIM", "SELL", "HOLD"]
SourceType = Literal["claude_daily", "claude_chat", "user_manual", "simulator_auto"]


class DecisionInput(BaseModel):
    """Claude proposes this; validator + simulator consume."""

    ticker: str
    action: ActionType
    qty: int
    target_price: int | None = None
    stop_loss: int | None = None
    thesis: str = Field(..., min_length=1)
    evidence: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    invalidation: str = Field(..., min_length=1)
    skills_used: list[str] = Field(default_factory=list)
    playbook_used: str | None = None
    conviction: int = Field(..., ge=1, le=5)

    @field_validator("ticker")
    @classmethod
    def upper_ticker(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("qty")
    @classmethod
    def qty_nonneg(cls, v: int, info):
        if v < 0:
            raise ValueError("qty must be >= 0")
        return v


@dataclass
class Holding:
    ticker: str
    qty_total: int
    qty_available: int
    avg_cost: int
    opened_at: str
    last_buy_at: str | None


@dataclass
class FillResult:
    order_id: int
    ticker: str
    side: Literal["BUY", "SELL"]
    qty: int
    fill_price: int
    fee: int
    date: str


@dataclass
class Portfolio:
    cash: int
    holdings: list[Holding]

    def market_value(self, prices: dict[str, int]) -> int:
        total = 0
        for h in self.holdings:
            p = prices.get(h.ticker, h.avg_cost)
            total += p * h.qty_total
        return total

    def total(self, prices: dict[str, int]) -> int:
        return self.cash + self.market_value(prices)

    def holding_of(self, ticker: str) -> Holding | None:
        return next((h for h in self.holdings if h.ticker == ticker), None)
