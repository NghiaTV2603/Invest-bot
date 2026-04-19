from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Broker = Literal["ssi", "vps", "tcbs", "mbs", "generic"]


@dataclass
class RawTrade:
    """One row from a broker CSV, normalized.

    Money is VND int (same convention as the rest of the codebase)."""
    traded_at: str                   # ISO datetime (Asia/Ho_Chi_Minh)
    ticker: str
    side: Literal["BUY", "SELL"]
    qty: int
    price: int                       # VND
    fee: int = 0                     # VND
    broker: Broker = "generic"
    trade_id: str | None = None


@dataclass
class Roundtrip:
    """FIFO-matched buy→sell pair. A BUY can be split across multiple SELLs
    (and vice-versa). Each Roundtrip represents one matched slice."""
    ticker: str
    qty: int
    buy_at: str
    sell_at: str
    buy_price: int
    sell_price: int
    buy_fee: int = 0
    sell_fee: int = 0
    sector: str | None = None

    @property
    def hold_days(self) -> int:
        from datetime import datetime
        try:
            d0 = datetime.fromisoformat(self.buy_at).date()
            d1 = datetime.fromisoformat(self.sell_at).date()
            return (d1 - d0).days
        except ValueError:
            return 0

    @property
    def pnl(self) -> int:
        gross = (self.sell_price - self.buy_price) * self.qty
        return gross - self.buy_fee - self.sell_fee

    @property
    def pnl_pct(self) -> float:
        if self.buy_price == 0:
            return 0.0
        return (self.sell_price - self.buy_price) / self.buy_price

    @property
    def is_winner(self) -> bool:
        return self.pnl > 0


@dataclass
class ShadowRule:
    """A rule extracted from profitable roundtrips. Human_text ≤ 30 chars
    per PLAN_V2 §5.2."""
    rule_id: str                     # 'rule-1'
    human_text: str                  # 'Mua NH sáng, giữ 3-5d'
    support_count: int               # # roundtrips matching
    coverage_rate: float             # support / total_winners
    sector: str | None = None
    hour_bucket: str | None = None   # '09:15-10:30' etc.
    holding_min: int = 0
    holding_max: int = 0
    win_rate: float = 0.0            # within cluster
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass
class DeltaComponents:
    """5-component PnL attribution (PLAN_V2 §5.3)."""
    noise_trades_pnl: int = 0        # trades matching NO rule (emotion trades)
    early_exit_pnl: int = 0          # winner cắt sớm — opportunity cost
    late_exit_pnl: int = 0           # loser giữ lâu — amplified loss
    overtrading_pnl: int = 0         # trade vượt rule frequency
    missed_signals_pnl: int = 0      # residual


@dataclass
class ShadowBacktestResult:
    shadow_id: str
    real_pnl: int
    shadow_pnl: int
    delta_pnl: int                   # shadow - real (positive = shadow better)
    components: DeltaComponents
    # Equity curves for the side-by-side chart (list of (date, pnl_cumulative))
    real_equity: list[tuple[str, int]] = field(default_factory=list)
    shadow_equity: list[tuple[str, int]] = field(default_factory=list)
    counterfactuals: list[dict[str, object]] = field(default_factory=list)
    per_sector: dict[str, dict[str, int]] = field(default_factory=dict)


@dataclass
class TradingProfile:
    total_trades: int
    total_roundtrips: int
    winners: int
    losers: int
    win_rate: float
    total_pnl: int
    avg_hold_days: float
    avg_win_pnl: int
    avg_loss_pnl: int
    top_tickers_by_trades: list[tuple[str, int]] = field(default_factory=list)
    top_sectors: list[tuple[str, int]] = field(default_factory=list)
    start_date: str | None = None
    end_date: str | None = None
