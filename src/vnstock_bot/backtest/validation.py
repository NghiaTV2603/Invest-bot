"""Thin wrapper: run the 3 validation methods from learning/stats.py on a
backtest run's equity curve + trade outcomes. Emits a structured report
suitable for `tool/backtest-diagnose` output shape.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from vnstock_bot.learning.stats import (
    ValidationVerdict,
    bootstrap_ci,
    combined_validation,
    monte_carlo_permutation,
    sharpe,
    walk_forward,
    win_rate,
)


@dataclass
class ValidationReport:
    verdict: str                  # pass | suspect | fail
    methods_passed: int
    ci_low: float
    ci_high: float
    ci_point: float
    mc_pvalue: float
    mc_observed_sharpe: float
    wf_pass_count: int
    wf_total_windows: int
    red_flags: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Sharpe > 2.5 with low trade count = overfit suspicion (per backtest-diagnose).
_SUSPECT_SHARPE = 2.5
_MIN_TRADES = 30


def validate_backtest(
    equity: np.ndarray,
    outcomes: np.ndarray,
    trade_count: int | None = None,
    n_bootstrap: int = 1000,
    n_permutations: int = 1000,
    n_windows: int = 5,
) -> ValidationReport:
    equity = np.asarray(equity, dtype=float)
    outcomes = np.asarray(outcomes, dtype=float)
    returns = np.diff(equity) / equity[:-1] if len(equity) >= 2 else np.zeros(0)

    verdict: ValidationVerdict = combined_validation(
        outcomes=outcomes,
        returns=returns,
        n_bootstrap=n_bootstrap,
        n_permutations=n_permutations,
        n_windows=n_windows,
    )

    red_flags: list[str] = []
    if verdict.mc.observed > _SUSPECT_SHARPE:
        tc = trade_count if trade_count is not None else len(outcomes)
        if tc < _MIN_TRADES:
            red_flags.append(
                f"RF1: Sharpe {verdict.mc.observed:.2f} with only {tc} trades "
                "(high overfit risk)"
            )
    if verdict.wf.total_windows > 0 and verdict.wf.pass_count == 0:
        red_flags.append(
            f"walk-forward: 0/{verdict.wf.total_windows} windows passed"
        )
    if verdict.ci.n_samples < 10:
        red_flags.append(f"ci: only {verdict.ci.n_samples} outcomes")

    return ValidationReport(
        verdict=verdict.verdict,
        methods_passed=verdict.methods_passed,
        ci_low=verdict.ci.ci_low,
        ci_high=verdict.ci.ci_high,
        ci_point=verdict.ci.point,
        mc_pvalue=verdict.mc.p_value,
        mc_observed_sharpe=verdict.mc.observed,
        wf_pass_count=verdict.wf.pass_count,
        wf_total_windows=verdict.wf.total_windows,
        red_flags=red_flags,
    )


__all__ = [
    "ValidationReport",
    "validate_backtest",
    # re-export primitives for direct use
    "bootstrap_ci",
    "monte_carlo_permutation",
    "walk_forward",
    "sharpe",
    "win_rate",
]
