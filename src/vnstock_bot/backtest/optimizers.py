"""Portfolio optimizers (PLAN_V2 §6.4).

3 deterministic optimizers:
- `equal_volatility`: w_i ∝ 1/σ_i → equal per-asset volatility contribution
- `risk_parity`: w_i ∝ 1/σ_i² → equal marginal risk contribution
- `max_diversification`: maximize (Σ w_i σ_i) / σ_portfolio → iterative closed
  form (no scipy.optimize dep).

Mean-variance (Markowitz) requires `scipy.optimize` + risk_free; deferred until
we add scipy as a dep. Caller can pick one of the 3 above for now.

All optimizers take:
  - `returns`: (T, N) numpy array of per-asset returns
  - returns: (N,) weight array summing to 1, all ≥ 0
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

OptimizerName = Literal[
    "equal_weight",
    "equal_volatility",
    "risk_parity",
    "max_diversification",
]


@dataclass
class OptimizerResult:
    weights: np.ndarray
    method: OptimizerName
    diagnostics: dict[str, float]


def _validate(returns: np.ndarray) -> None:
    if returns.ndim != 2:
        raise ValueError("returns must be 2D (T, N)")
    if returns.shape[0] < 2 or returns.shape[1] < 1:
        raise ValueError(f"returns too small: shape {returns.shape}")


def _normalize(w: np.ndarray) -> np.ndarray:
    w = np.clip(w, 0.0, None)
    s = w.sum()
    return w / s if s > 0 else np.full_like(w, 1.0 / len(w))


def equal_weight(returns: np.ndarray) -> OptimizerResult:
    _validate(returns)
    n = returns.shape[1]
    w = np.full(n, 1.0 / n)
    return OptimizerResult(weights=w, method="equal_weight", diagnostics={})


def equal_volatility(returns: np.ndarray) -> OptimizerResult:
    _validate(returns)
    sigma = np.std(returns, axis=0, ddof=1)
    # guard against zero-vol assets
    sigma = np.where(sigma > 0, sigma, np.finfo(float).eps)
    w = 1.0 / sigma
    w = _normalize(w)
    return OptimizerResult(
        weights=w, method="equal_volatility",
        diagnostics={"mean_sigma": float(sigma.mean())},
    )


def risk_parity(returns: np.ndarray) -> OptimizerResult:
    """Inverse-variance weighting → each asset contributes equal marginal
    risk at the portfolio level (under the diagonal-cov simplification)."""
    _validate(returns)
    sigma = np.std(returns, axis=0, ddof=1)
    sigma = np.where(sigma > 0, sigma, np.finfo(float).eps)
    w = 1.0 / (sigma ** 2)
    w = _normalize(w)
    return OptimizerResult(
        weights=w, method="risk_parity",
        diagnostics={"mean_sigma": float(sigma.mean())},
    )


def max_diversification(
    returns: np.ndarray,
    n_iter: int = 200,
    tol: float = 1e-8,
) -> OptimizerResult:
    """Maximize diversification ratio = (w · σ) / sqrt(w' Σ w).

    Projected gradient: at each step, move weights toward ∇DR and project
    onto the simplex (non-negative, sum-to-1). Converges quickly for small N.
    No scipy dep.
    """
    _validate(returns)
    n = returns.shape[1]
    cov = np.cov(returns, rowvar=False, ddof=1)
    sigma = np.sqrt(np.diag(cov))
    sigma = np.where(sigma > 0, sigma, np.finfo(float).eps)

    w = np.full(n, 1.0 / n)
    lr = 0.02
    prev_dr = -np.inf
    iterations = 0

    for it in range(n_iter):
        iterations = it + 1
        port_var = float(w @ cov @ w)
        if port_var <= 0:
            break
        port_vol = np.sqrt(port_var)
        dr = float(w @ sigma / port_vol)
        if abs(dr - prev_dr) < tol:
            break
        prev_dr = dr

        # Gradient: d(DR)/dw = σ/port_vol - (w σ) * (cov w) / port_vol^3
        grad = sigma / port_vol - (w @ sigma) * (cov @ w) / (port_vol ** 3)
        w = w + lr * grad
        w = _normalize(w)

    port_var = float(w @ cov @ w)
    port_vol = np.sqrt(max(port_var, 0.0))
    dr = float(w @ sigma / port_vol) if port_vol > 0 else 0.0

    return OptimizerResult(
        weights=w,
        method="max_diversification",
        diagnostics={"diversification_ratio": dr, "iterations": iterations},
    )


_IMPL = {
    "equal_weight": equal_weight,
    "equal_volatility": equal_volatility,
    "risk_parity": risk_parity,
    "max_diversification": max_diversification,
}


def optimize(method: OptimizerName, returns: np.ndarray) -> OptimizerResult:
    if method not in _IMPL:
        raise ValueError(f"unknown optimizer {method!r}; known: {list(_IMPL)}")
    return _IMPL[method](returns)
