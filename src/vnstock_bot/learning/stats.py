"""Statistical validation library for v2 skill lifecycle + backtest validation.

Three methods (per PLAN_V2 §6.3):

1. Bootstrap CI: resample outcomes w/ replacement → 95% CI for win-rate/Sharpe.
2. Monte Carlo permutation: shuffle trade order N times → p-value for Sharpe.
3. Walk-forward: split series into N windows, train/test split, count
   windows where strategy outperforms threshold.

Pure numpy. scipy.stats is NOT imported — we compute quantiles with
np.quantile and don't need parametric tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TRADING_DAYS_PER_YEAR = 252


# ---------------------------------------------------------------- primitives

def sharpe(returns: np.ndarray, rf: float = 0.0, periods_per_year: int = TRADING_DAYS_PER_YEAR) -> float:
    if len(returns) < 2:
        return 0.0
    excess = returns - rf / periods_per_year
    std = float(np.std(excess, ddof=1))
    # Floating-point: constant returns give std ≈ 1e-18, not exactly 0.
    if std < 1e-12:
        return 0.0
    return float(np.mean(excess) / std * np.sqrt(periods_per_year))


def win_rate(outcomes: np.ndarray) -> float:
    """outcomes: 1 for win, 0 for loss (or -1)."""
    if len(outcomes) == 0:
        return 0.0
    wins = np.sum(outcomes > 0)
    return float(wins) / len(outcomes)


def max_drawdown_from_returns(returns: np.ndarray) -> float:
    """Path-dependent: -max(peak-trough) of the cumulative return curve.
    Returns a non-positive number (0 = no drawdown). Used as the MC
    permutation default because Sharpe is order-invariant on i.i.d. returns
    (so MC with Sharpe has p≈0.5 by construction, not useful)."""
    if len(returns) == 0:
        return 0.0
    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    return float(dd.min())


# ---------------------------------------------------------------- bootstrap

@dataclass
class BootstrapResult:
    point: float
    ci_low: float
    ci_high: float
    n_samples: int
    n_bootstrap: int

    @property
    def ci_excludes_zero(self) -> bool:
        return self.ci_low > 0 or self.ci_high < 0

    @property
    def ci_lower_bound_above(self) -> float:
        return self.ci_low


def bootstrap_ci(
    data: np.ndarray,
    stat_fn=win_rate,
    n_bootstrap: int = 1000,
    alpha: float = 0.05,
    seed: int | None = 42,
) -> BootstrapResult:
    """95% bootstrap CI (percentile method) for an arbitrary statistic.

    Default alpha=0.05 → 95% CI. stat_fn defaults to win_rate; pass `sharpe`
    for Sharpe CI on return series.
    """
    arr = np.asarray(data, dtype=float)
    n = len(arr)
    if n < 2:
        point = float(stat_fn(arr)) if n == 1 else 0.0
        return BootstrapResult(point, point, point, n, 0)

    rng = np.random.default_rng(seed)
    point = float(stat_fn(arr))
    stats = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        sample = rng.choice(arr, size=n, replace=True)
        stats[i] = stat_fn(sample)

    lo = float(np.quantile(stats, alpha / 2))
    hi = float(np.quantile(stats, 1 - alpha / 2))
    return BootstrapResult(point, lo, hi, n, n_bootstrap)


# ---------------------------------------------------------------- Monte Carlo

@dataclass
class PermutationResult:
    observed: float
    mean_null: float
    p_value: float
    n_permutations: int

    @property
    def significant_95(self) -> bool:
        return self.p_value < 0.05


def monte_carlo_permutation(
    returns: np.ndarray,
    stat_fn=sharpe,
    n_permutations: int = 1000,
    seed: int | None = 42,
) -> PermutationResult:
    """Shuffle the order of returns; under H0 (order is random) any time-
    dependent structure should be destroyed. p-value = proportion of
    permutations with stat >= observed (one-sided, upper tail).

    Caveat: permutation of i.i.d. returns is a weaker null than needed for
    strategy validation — still useful to detect "stat inflated by ordering"
    bugs (lookahead).
    """
    arr = np.asarray(returns, dtype=float)
    if len(arr) < 2:
        return PermutationResult(0.0, 0.0, 1.0, 0)

    rng = np.random.default_rng(seed)
    observed = float(stat_fn(arr))

    ge_count = 0
    null_sum = 0.0
    for _ in range(n_permutations):
        shuffled = rng.permutation(arr)
        s = stat_fn(shuffled)
        null_sum += s
        if s >= observed:
            ge_count += 1

    p = ge_count / n_permutations
    mean_null = null_sum / n_permutations
    return PermutationResult(observed, mean_null, p, n_permutations)


# ---------------------------------------------------------------- walk-forward

@dataclass
class WalkForwardWindow:
    window_idx: int
    train_start: int
    train_end: int
    test_start: int
    test_end: int
    train_stat: float
    test_stat: float
    passes: bool


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow]
    pass_count: int
    total_windows: int
    threshold: float

    @property
    def stable(self) -> bool:
        return self.pass_count / self.total_windows >= 0.6

    @property
    def pass_ratio(self) -> float:
        return self.pass_count / self.total_windows if self.total_windows else 0.0


def walk_forward(
    returns: np.ndarray,
    n_windows: int = 5,
    train_ratio: float = 0.7,
    stat_fn=sharpe,
    threshold: float = 0.5,
) -> WalkForwardResult:
    """Partition returns into N non-overlapping windows. In each window,
    split the first `train_ratio` as in-sample, the remainder as
    out-of-sample. A window "passes" if test_stat ≥ `threshold`.
    """
    arr = np.asarray(returns, dtype=float)
    n = len(arr)
    if n_windows < 1 or n < n_windows * 4:
        return WalkForwardResult(windows=[], pass_count=0, total_windows=0,
                                 threshold=threshold)

    bounds = np.linspace(0, n, n_windows + 1, dtype=int)
    windows: list[WalkForwardWindow] = []
    passes = 0

    for i in range(n_windows):
        w_start, w_end = bounds[i], bounds[i + 1]
        w_len = w_end - w_start
        if w_len < 4:
            continue
        split = w_start + max(1, int(w_len * train_ratio))

        train = arr[w_start:split]
        test = arr[split:w_end]
        if len(train) < 2 or len(test) < 2:
            continue

        train_stat = float(stat_fn(train))
        test_stat = float(stat_fn(test))
        ok = test_stat >= threshold

        windows.append(WalkForwardWindow(
            window_idx=i,
            train_start=int(w_start),
            train_end=int(split),
            test_start=int(split),
            test_end=int(w_end),
            train_stat=train_stat,
            test_stat=test_stat,
            passes=ok,
        ))
        if ok:
            passes += 1

    return WalkForwardResult(
        windows=windows,
        pass_count=passes,
        total_windows=len(windows),
        threshold=threshold,
    )


# ---------------------------------------------------------------- combined gate

@dataclass
class ValidationVerdict:
    ci: BootstrapResult
    mc: PermutationResult
    wf: WalkForwardResult
    methods_passed: int          # out of 3
    verdict: str                 # "pass" | "suspect" | "fail"


def combined_validation(
    outcomes: np.ndarray,
    returns: np.ndarray | None = None,
    n_bootstrap: int = 1000,
    n_permutations: int = 1000,
    n_windows: int = 5,
    ci_low_threshold: float = 0.5,
    wf_threshold: float = 0.5,
) -> ValidationVerdict:
    """Run all three methods and return a combined verdict.

    - `outcomes` is the win/loss series (1/0) — used by bootstrap for win-rate CI.
    - `returns` is the per-period returns — used by MC + walk-forward for Sharpe.
      If None, we treat outcomes − 0.5 as a crude return proxy so a caller
      without return series still gets 3 numbers.
    """
    ci = bootstrap_ci(outcomes, stat_fn=win_rate, n_bootstrap=n_bootstrap)

    ret = returns if returns is not None else (np.asarray(outcomes, dtype=float) - 0.5)
    mc = monte_carlo_permutation(ret, stat_fn=sharpe, n_permutations=n_permutations)
    wf = walk_forward(ret, n_windows=n_windows, stat_fn=sharpe,
                      threshold=wf_threshold)

    passed = 0
    if ci.ci_low > ci_low_threshold:
        passed += 1
    if mc.p_value < 0.05:
        passed += 1
    if wf.pass_ratio >= 0.6:
        passed += 1

    if passed >= 2:
        verdict = "pass"
    elif passed == 1:
        verdict = "suspect"
    else:
        verdict = "fail"

    return ValidationVerdict(ci=ci, mc=mc, wf=wf,
                             methods_passed=passed, verdict=verdict)
