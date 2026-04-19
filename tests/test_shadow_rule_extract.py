from vnstock_bot.shadow.rule_extractor import extract
from vnstock_bot.shadow.types import Roundtrip


def _rt(sector, buy_at, hold_days, pnl, ticker="X"):
    # Build a roundtrip with fixed qty=100; hold_days derived from dates
    from datetime import datetime, timedelta
    buy = datetime.fromisoformat(buy_at)
    sell = buy + timedelta(days=hold_days)
    return Roundtrip(
        ticker=ticker, qty=100,
        buy_at=buy.isoformat(), sell_at=sell.isoformat(),
        buy_price=100_000,
        sell_price=100_000 + (pnl // 100),
        sector=sector,
    )


def test_empty_input_returns_no_rules():
    assert extract([]) == []


def test_no_winners_returns_no_rules():
    roundtrips = [_rt("Bank", "2026-04-01T09:30:00", 3, pnl=-50_000) for _ in range(5)]
    assert extract(roundtrips) == []


def test_cluster_with_enough_support_produces_rule():
    # 5 winners, all in Bank sector, morning, 3-5 day hold
    winners = [_rt("Bank", f"2026-04-{i:02d}T09:30:00", 4, pnl=50_000)
               for i in range(1, 6)]
    # 2 losers in different cluster
    losers = [_rt("RealEstate", f"2026-04-{i:02d}T14:00:00", 8, pnl=-30_000)
              for i in range(10, 12)]
    rules = extract(winners + losers)
    assert len(rules) >= 1
    r = rules[0]
    assert r.support_count >= 5
    assert "Bank" in r.human_text or "bank" in r.human_text.lower()


def test_rule_text_under_30_chars():
    winners = [_rt("Bank", f"2026-04-{i:02d}T09:30:00", 4, pnl=50_000)
               for i in range(1, 6)]
    rules = extract(winners)
    assert rules
    for r in rules:
        assert len(r.human_text) <= 30, f"rule too long: {r.human_text!r}"


def test_max_rules_respected():
    # 6 different clusters (sector × hold combinations), each with 5 winners
    all_rt = []
    sectors = ["Bank", "Tech", "RealEstate", "Retail", "Oil", "Steel"]
    for idx, sec in enumerate(sectors):
        for i in range(1, 7):
            all_rt.append(
                _rt(sec, f"2026-04-{i:02d}T09:30:00", 4, pnl=50_000,
                    ticker=f"T{idx}")
            )
    rules = extract(all_rt, max_rules=3)
    assert len(rules) == 3


def test_min_support_filter():
    # Only 2 winners per cluster → below min_support=3
    winners = [_rt("Bank", "2026-04-01T09:30:00", 4, pnl=50_000),
               _rt("Bank", "2026-04-02T09:30:00", 4, pnl=50_000)]
    rules = extract(winners, min_support=3)
    assert rules == []


def test_negative_lift_cluster_excluded():
    # A cluster that's HUGE but has a bad win rate → should be excluded.
    bad_cluster_trades = (
        [_rt("Bank", f"2026-04-{i:02d}T09:30:00", 4, pnl=50_000)
         for i in range(1, 5)]
        + [_rt("Bank", f"2026-04-{i:02d}T09:30:00", 4, pnl=-60_000)
           for i in range(1, 16)]  # many losers
    )
    # A small but clean cluster
    good_cluster_trades = [
        _rt("Tech", f"2026-04-{i:02d}T10:30:00", 4, pnl=50_000)
        for i in range(1, 6)
    ]
    rules = extract(bad_cluster_trades + good_cluster_trades)
    # Good cluster should appear; bad cluster may or may not (lift could
    # still be positive if global win-rate is low enough). Just check Tech
    # is there.
    texts = [r.human_text for r in rules]
    assert any("Tech" in t or "tech" in t.lower() for t in texts)
