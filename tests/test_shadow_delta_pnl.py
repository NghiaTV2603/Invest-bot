from datetime import datetime, timedelta

from vnstock_bot.shadow import delta_pnl
from vnstock_bot.shadow.types import Roundtrip, ShadowRule


def _rt(ticker, sector, buy_at, hold_days, pnl):
    buy = datetime.fromisoformat(buy_at)
    sell = buy + timedelta(days=hold_days)
    return Roundtrip(
        ticker=ticker, qty=100,
        buy_at=buy.isoformat(), sell_at=sell.isoformat(),
        buy_price=100_000,
        sell_price=100_000 + (pnl // 100),
        sector=sector,
    )


def _rule(sector="Bank", hour="sáng sớm", hold_min=2, hold_max=5):
    return ShadowRule(
        rule_id="rule-1",
        human_text=f"{sector} {hour}, {hold_min}-{hold_max}d",
        support_count=5,
        coverage_rate=0.5,
        sector=sector,
        hour_bucket=hour,
        holding_min=hold_min,
        holding_max=hold_max,
        win_rate=0.7,
    )


def test_noise_trade_without_rule_match():
    # Trade in Retail sector, no rule for it → noise
    roundtrips = [_rt("MWG", "Retail", "2026-04-01T09:30:00", 3, pnl=-200_000)]
    rules = [_rule(sector="Bank")]
    result = delta_pnl.compute(roundtrips, rules)
    assert result.components.noise_trades_pnl == -200_000
    assert result.components.early_exit_pnl == 0


def test_early_exit_of_winner():
    # Winner held 1 day but rule says 2-5 → early exit cost
    rt = _rt("VCB", "Bank", "2026-04-01T09:30:00", 1, pnl=500_000)
    rules = [_rule(sector="Bank", hold_min=2, hold_max=5)]
    result = delta_pnl.compute([rt], rules)
    assert result.components.early_exit_pnl > 0
    # Shadow PnL should be > real PnL (rule-conforming + early exit uplift)
    assert result.shadow_pnl > result.real_pnl


def test_late_exit_of_loser():
    # Loser held 10 days but rule says 2-5 → late exit savings
    rt = _rt("VCB", "Bank", "2026-04-01T09:30:00", 10, pnl=-1_000_000)
    rules = [_rule(sector="Bank", hold_min=2, hold_max=5)]
    result = delta_pnl.compute([rt], rules)
    assert result.components.late_exit_pnl > 0   # savings = positive
    # Shadow should beat real (we "would have cut" earlier)
    assert result.shadow_pnl > result.real_pnl


def test_overtrading_detects_third_plus_on_same_day():
    # 4 trades on same day → 3rd and 4th are overtrading
    day = "2026-04-01T"
    roundtrips = [
        _rt("A", "Bank", day + "09:00:00", 3, 100_000),
        _rt("B", "Bank", day + "09:30:00", 3, 100_000),
        _rt("C", "Bank", day + "10:00:00", 3, -500_000),  # 3rd
        _rt("D", "Bank", day + "10:30:00", 3, -300_000),  # 4th
    ]
    rules = [_rule(sector="Bank")]
    result = delta_pnl.compute(roundtrips, rules)
    assert result.components.overtrading_pnl != 0
    # The overtraded trades contribute their PnL sign
    assert result.components.overtrading_pnl <= 0


def test_rule_conforming_trade_contributes_to_shadow():
    # A perfect trade: Bank sector, morning, 3 day hold, profitable
    rt = _rt("VCB", "Bank", "2026-04-01T09:30:00", 3, pnl=500_000)
    rules = [_rule(sector="Bank", hold_min=2, hold_max=5)]
    result = delta_pnl.compute([rt], rules)
    assert result.shadow_pnl == result.real_pnl == 500_000
    assert result.components.noise_trades_pnl == 0
    assert result.components.early_exit_pnl == 0
    assert result.components.late_exit_pnl == 0


def test_equity_curves_have_same_length_as_roundtrips():
    rts = [
        _rt("A", "Bank", "2026-04-01T09:30:00", 3, 100_000),
        _rt("B", "Bank", "2026-04-02T09:30:00", 3, -50_000),
        _rt("C", "Retail", "2026-04-03T10:30:00", 3, 200_000),
    ]
    rules = [_rule(sector="Bank")]
    result = delta_pnl.compute(rts, rules)
    assert len(result.real_equity) == len(rts)
    assert len(result.shadow_equity) == len(rts)


def test_counterfactuals_top5():
    # Mix of trades, expect counterfactuals to include biggest early_exit/late_exit
    rts = [
        _rt("A", "Bank", "2026-04-01T09:30:00", 1, pnl=2_000_000),   # big winner, early
        _rt("B", "Bank", "2026-04-02T09:30:00", 10, pnl=-3_000_000), # big loser, late
        _rt("C", "Retail", "2026-04-03T09:30:00", 3, pnl=1_000_000), # noise winner
    ]
    rules = [_rule(sector="Bank", hold_min=3, hold_max=5)]
    result = delta_pnl.compute(rts, rules)
    assert len(result.counterfactuals) <= 5
    assert result.counterfactuals  # non-empty


def test_per_sector_tracks_trades():
    rts = [
        _rt("A", "Bank", "2026-04-01T09:30:00", 3, 100_000),
        _rt("B", "Bank", "2026-04-02T09:30:00", 3, -50_000),
        _rt("C", "Tech", "2026-04-03T10:30:00", 3, 200_000),
    ]
    result = delta_pnl.compute(rts, [_rule(sector="Bank")])
    assert "Bank" in result.per_sector
    assert "Tech" in result.per_sector
    assert result.per_sector["Bank"]["count"] == 2
    assert result.per_sector["Tech"]["count"] == 1
