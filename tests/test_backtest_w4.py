import numpy as np

from vnstock_bot.backtest import metrics, optimizers, validation

# ---------------------------------------------------------------- metrics

def test_metrics_on_constant_equity():
    equity = np.array([100.0] * 50)
    m = metrics.compute(equity)
    assert m.total_return == 0.0
    assert m.max_drawdown == 0.0
    assert m.sharpe == 0.0


def test_metrics_detect_drawdown():
    equity = np.array([100.0, 110.0, 120.0, 90.0, 95.0, 100.0])
    m = metrics.compute(equity)
    # Peak 120 → trough 90 → DD = -25%
    assert -0.26 < m.max_drawdown < -0.24


def test_metrics_benchmark_excess():
    equity = np.linspace(100, 130, 50)
    bench = np.linspace(100, 120, 50)
    m = metrics.compute(equity, benchmark_equity=bench)
    assert 0.09 < m.excess_return < 0.11


def test_metrics_trade_level():
    pnls = np.array([100, -50, 200, -30, 80, -100], dtype=float)
    holds = np.array([3, 5, 2, 7, 4, 6], dtype=float)
    equity = np.array([1000.0, 1100.0, 1050.0, 1250.0])  # dummy
    m = metrics.compute(equity, trade_pnls=pnls, trade_hold_days=holds)
    assert m.trade_count == 6
    assert 0.4 < m.win_rate < 0.6      # 3 wins / 6
    assert m.profit_factor > 1.0
    assert m.max_consec_loss == 1      # no back-to-back losses here


def test_metrics_all_15_fields_present():
    m = metrics.compute(np.linspace(100, 120, 30))
    d = m.as_dict()
    expected = {
        "final_value", "total_return", "annual_return", "max_drawdown",
        "sharpe", "calmar", "sortino", "win_rate", "profit_loss_ratio",
        "profit_factor", "max_consec_loss", "avg_holding_days", "trade_count",
        "benchmark_return", "excess_return", "information_ratio",
    }
    assert set(d) == expected


# ---------------------------------------------------------------- optimizers

def test_equal_weight_sums_to_one():
    returns = np.random.default_rng(1).normal(0, 0.01, (100, 5))
    r = optimizers.equal_weight(returns)
    assert abs(r.weights.sum() - 1.0) < 1e-9
    assert np.allclose(r.weights, 0.2)


def test_equal_volatility_lower_weight_to_high_vol():
    rng = np.random.default_rng(0)
    low_vol = rng.normal(0, 0.005, 200)
    high_vol = rng.normal(0, 0.05, 200)
    returns = np.column_stack([low_vol, high_vol])
    r = optimizers.equal_volatility(returns)
    assert r.weights[0] > r.weights[1]  # lower vol asset gets higher weight
    assert abs(r.weights.sum() - 1.0) < 1e-9


def test_risk_parity_similar_shape_to_equal_vol():
    rng = np.random.default_rng(2)
    returns = rng.normal(0, np.array([0.005, 0.01, 0.02]), (200, 3))
    r = optimizers.risk_parity(returns)
    # Low vol → high weight; high vol → low weight
    assert r.weights[0] > r.weights[1] > r.weights[2]
    assert abs(r.weights.sum() - 1.0) < 1e-9


def test_max_diversification_yields_valid_simplex():
    rng = np.random.default_rng(3)
    returns = rng.normal(0, 0.01, (200, 4))
    r = optimizers.max_diversification(returns)
    assert abs(r.weights.sum() - 1.0) < 1e-6
    assert (r.weights >= -1e-12).all()
    assert "diversification_ratio" in r.diagnostics


def test_optimize_dispatcher():
    returns = np.random.default_rng(4).normal(0, 0.01, (100, 3))
    for name in ["equal_weight", "equal_volatility", "risk_parity",
                 "max_diversification"]:
        r = optimizers.optimize(name, returns)  # type: ignore[arg-type]
        assert r.method == name


# ---------------------------------------------------------------- validation

def test_validate_backtest_with_noise_returns_fail_or_suspect():
    rng = np.random.default_rng(5)
    equity = 100 + np.cumsum(rng.normal(0, 0.005, 300))
    outcomes = (rng.random(300) < 0.5).astype(float)
    report = validation.validate_backtest(
        equity, outcomes,
        n_bootstrap=200, n_permutations=200, n_windows=5,
    )
    assert report.verdict in ("fail", "suspect")
    assert 0.4 < report.ci_point < 0.6


def test_validate_backtest_flags_overfit_sharpe():
    # Engineered high-sharpe short equity curve → should trigger red flag
    equity = np.linspace(100.0, 200.0, 20)  # smooth linear up → very high sharpe
    outcomes = np.ones(10)
    report = validation.validate_backtest(
        equity, outcomes, trade_count=10,
        n_bootstrap=100, n_permutations=100, n_windows=5,
    )
    # With trade_count < 30 and engineered sharpe, either red flag or
    # insufficient-sample warning must fire
    assert report.red_flags
