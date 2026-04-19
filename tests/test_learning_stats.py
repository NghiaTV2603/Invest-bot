import numpy as np

from vnstock_bot.learning.stats import (
    bootstrap_ci,
    combined_validation,
    max_drawdown_from_returns,
    monte_carlo_permutation,
    sharpe,
    walk_forward,
    win_rate,
)


def test_sharpe_on_constant_returns_is_zero():
    # Zero std → sharpe defined as 0 by our code (not NaN)
    assert sharpe(np.ones(10) * 0.01) == 0.0


def test_sharpe_positive_on_trending_returns():
    rng = np.random.default_rng(0)
    r = rng.normal(0.001, 0.01, 252)  # ~25% drift
    assert sharpe(r) > 0.5


def test_bootstrap_ci_brackets_point_estimate():
    # 100 Bernoulli outcomes with true p=0.6
    rng = np.random.default_rng(7)
    wins = rng.random(200) < 0.6
    out = bootstrap_ci(wins.astype(float), stat_fn=win_rate, n_bootstrap=500)
    assert 0.5 < out.point < 0.7
    assert out.ci_low < out.point < out.ci_high
    # 95% CI should roughly span true value
    assert out.ci_low < 0.6 < out.ci_high


def test_bootstrap_ci_handles_tiny_input():
    out = bootstrap_ci(np.array([1.0]), stat_fn=win_rate)
    # Only 1 sample → point defined, CI degenerate
    assert out.n_bootstrap == 0


def test_monte_carlo_sharpe_neutral_because_order_invariant():
    # Sharpe is order-invariant → shuffling doesn't change it → p ≈ 0.5.
    # This test documents the limitation; use a path-dependent stat for
    # meaningful results.
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.01, 200)
    out = monte_carlo_permutation(r, stat_fn=sharpe, n_permutations=300)
    assert 0.1 < out.p_value < 0.9


def test_monte_carlo_max_drawdown_is_path_dependent():
    # MaxDD IS path-dependent — shuffling genuinely changes the distribution.
    rng = np.random.default_rng(2)
    # Engineered clustered loss sequence: all losses bunched at start
    # produces a much worse MaxDD than random ordering.
    losses = rng.normal(-0.02, 0.01, 50)
    gains = rng.normal(0.02, 0.01, 150)
    r = np.concatenate([losses, gains])  # bad-order first
    out = monte_carlo_permutation(
        r, stat_fn=max_drawdown_from_returns, n_permutations=300,
    )
    # Observed (bad-order) DD should be near the worst percentile of the
    # null distribution → p is high (we count stat >= observed; DD is ≤ 0
    # so "worst observed" = smallest number; most permutations have less
    # severe DD → more permutations have stat >= observed → high p).
    assert out.p_value > 0.5


def test_walk_forward_enough_windows():
    rng = np.random.default_rng(3)
    r = rng.normal(0.001, 0.01, 260)
    wf = walk_forward(r, n_windows=5)
    assert wf.total_windows == 5
    # Each window must have train_stat + test_stat populated
    assert all(w.test_stat is not None for w in wf.windows)


def test_walk_forward_tiny_input_returns_empty():
    wf = walk_forward(np.array([0.01, 0.02]), n_windows=5)
    assert wf.total_windows == 0


def test_combined_validation_verdict_pass_on_clean_signal():
    rng = np.random.default_rng(42)
    n = 500
    outcomes = (rng.random(n) < 0.65).astype(float)
    # paired returns that trend up (create pass case)
    returns = np.where(outcomes > 0, 0.02, -0.01) + rng.normal(0, 0.005, n)
    v = combined_validation(outcomes, returns=returns,
                            n_bootstrap=300, n_permutations=300, n_windows=5)
    assert v.verdict in ("pass", "suspect")
    assert v.methods_passed >= 1


def test_combined_validation_fail_on_pure_noise():
    rng = np.random.default_rng(99)
    outcomes = (rng.random(200) < 0.5).astype(float)  # 50/50
    returns = rng.normal(0, 0.01, 200)
    v = combined_validation(outcomes, returns=returns,
                            n_bootstrap=300, n_permutations=300, n_windows=5)
    assert v.verdict in ("fail", "suspect")
    # CI of 50/50 should NOT have low > 0.5
    assert v.ci.ci_low <= 0.55
