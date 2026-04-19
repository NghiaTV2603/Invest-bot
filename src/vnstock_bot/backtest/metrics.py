"""15 backtest performance metrics (PLAN_V2.md §6.2).

Pure numpy; no DB access. The backtest runner + validation wrapper pull
equity/return series out of their working state and call these here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

TRADING_DAYS_PER_YEAR = 252


@dataclass
class Metrics:
    # Equity-curve based
    final_value: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe: float
    calmar: float
    sortino: float
    # Trade-based
    win_rate: float
    profit_loss_ratio: float
    profit_factor: float
    max_consec_loss: int
    avg_holding_days: float
    trade_count: int
    # Benchmark
    benchmark_return: float
    excess_return: float
    information_ratio: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------- helpers

def _safe(value: float, default: float = 0.0) -> float:
    if np.isnan(value) or np.isinf(value):
        return default
    return float(value)


def _to_returns(equity: np.ndarray) -> np.ndarray:
    if len(equity) < 2:
        return np.zeros(0)
    return np.diff(equity) / equity[:-1]


def _max_drawdown(equity: np.ndarray) -> float:
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    return float(dd.min())


def _downside_std(returns: np.ndarray) -> float:
    neg = returns[returns < 0]
    if len(neg) < 2:
        return 0.0
    return float(np.std(neg, ddof=1))


# ---------------------------------------------------------------- main

def compute(
    equity: np.ndarray,
    trade_pnls: np.ndarray | None = None,
    trade_hold_days: np.ndarray | None = None,
    benchmark_equity: np.ndarray | None = None,
    periods_per_year: int = TRADING_DAYS_PER_YEAR,
) -> Metrics:
    """Compute all 15 metrics.

    - `equity`: daily NAV (or similar) series.
    - `trade_pnls`: per-trade pnl (VND int or float). None → trade metrics are 0.
    - `trade_hold_days`: per-trade holding days, parallel to trade_pnls.
    - `benchmark_equity`: VN-Index levels aligned with `equity`. None → benchmark
      metrics are 0.
    """
    equity = np.asarray(equity, dtype=float)
    n = len(equity)
    returns = _to_returns(equity)
    periods = len(returns)

    initial = float(equity[0]) if n > 0 else 0.0
    final = float(equity[-1]) if n > 0 else 0.0
    total_ret = (final / initial - 1.0) if initial else 0.0
    annual_ret = 0.0
    if initial and periods > 0:
        # annualize by period count, not calendar days
        annual_ret = (final / initial) ** (periods_per_year / periods) - 1.0

    max_dd = _max_drawdown(equity)

    if periods >= 2:
        mean_r = float(np.mean(returns))
        std_r = float(np.std(returns, ddof=1))
        sharpe = (mean_r / std_r * np.sqrt(periods_per_year)) if std_r else 0.0
        d_std = _downside_std(returns)
        sortino = (mean_r / d_std * np.sqrt(periods_per_year)) if d_std else 0.0
    else:
        sharpe = 0.0
        sortino = 0.0

    calmar = (annual_ret / abs(max_dd)) if max_dd < 0 else 0.0

    # ---- trade-based
    if trade_pnls is not None and len(trade_pnls) > 0:
        pnls = np.asarray(trade_pnls, dtype=float)
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        trade_count = int(len(pnls))
        win_rate = float(len(wins)) / trade_count if trade_count else 0.0
        avg_win = float(np.mean(wins)) if len(wins) else 0.0
        avg_loss = float(np.mean(losses)) if len(losses) else 0.0
        pl_ratio = (avg_win / abs(avg_loss)) if avg_loss else 0.0
        gross_profit = float(wins.sum())
        gross_loss = float(abs(losses.sum()))
        profit_factor = (gross_profit / gross_loss) if gross_loss else 0.0
        # Longest losing streak
        consec = 0
        max_consec = 0
        for p in pnls:
            if p < 0:
                consec += 1
                max_consec = max(max_consec, consec)
            else:
                consec = 0
        avg_hold = float(np.mean(trade_hold_days)) if trade_hold_days is not None and len(trade_hold_days) else 0.0
    else:
        trade_count = 0
        win_rate = 0.0
        pl_ratio = 0.0
        profit_factor = 0.0
        max_consec = 0
        avg_hold = 0.0

    # ---- benchmark
    if benchmark_equity is not None and len(benchmark_equity) >= 2:
        bench = np.asarray(benchmark_equity, dtype=float)
        b0 = float(bench[0])
        bN = float(bench[-1])
        bench_ret = (bN / b0 - 1.0) if b0 else 0.0
        # Align lengths for tracking error
        m = min(len(returns), len(bench) - 1)
        bench_returns = np.diff(bench[-m - 1:]) / bench[-m - 1:-1]
        stgy_r = returns[-m:]
        if m >= 2:
            excess = stgy_r - bench_returns
            te = float(np.std(excess, ddof=1))
            info_ratio = (float(np.mean(excess)) / te * np.sqrt(periods_per_year)) if te else 0.0
        else:
            info_ratio = 0.0
        excess_ret = total_ret - bench_ret
    else:
        bench_ret = 0.0
        excess_ret = 0.0
        info_ratio = 0.0

    return Metrics(
        final_value=_safe(final),
        total_return=_safe(total_ret),
        annual_return=_safe(annual_ret),
        max_drawdown=_safe(max_dd),
        sharpe=_safe(sharpe),
        calmar=_safe(calmar),
        sortino=_safe(sortino),
        win_rate=_safe(win_rate),
        profit_loss_ratio=_safe(pl_ratio),
        profit_factor=_safe(profit_factor),
        max_consec_loss=max_consec,
        avg_holding_days=_safe(avg_hold),
        trade_count=trade_count,
        benchmark_return=_safe(bench_ret),
        excess_return=_safe(excess_ret),
        information_ratio=_safe(info_ratio),
    )
