from vnstock_bot.bias.detectors import (
    anchoring,
    chase_momentum,
    detect_all,
    disposition_effect,
    hot_hand_sizing,
    overtrading,
    recency,
    skill_dogma,
)
from vnstock_bot.bias.types import DecisionLike, TradeLike


def _buy(ticker: str, price: int, ts: str, pct_nav: float | None = None) -> TradeLike:
    return TradeLike(ticker=ticker, side="BUY", qty=100, price=price, traded_at=ts,
                     pct_nav_at_entry=pct_nav)


def _sell(ticker: str, price: int, ts: str, pnl: int, hold_days: int,
          entry_price: int = 100_000) -> TradeLike:
    return TradeLike(ticker=ticker, side="SELL", qty=100, price=price,
                     traded_at=ts, pnl=pnl, hold_days=hold_days,
                     entry_price=entry_price)


# -------------------------------------------------- disposition_effect

def test_disposition_high_when_loser_hold_2x_winner():
    trades = [
        _sell("A", 110_000, "2026-04-10T00:00:00", pnl=1_000_000, hold_days=3),
        _sell("B", 115_000, "2026-04-11T00:00:00", pnl=1_500_000, hold_days=2),
        _sell("C", 90_000, "2026-04-12T00:00:00", pnl=-1_000_000, hold_days=10),
        _sell("D", 80_000, "2026-04-13T00:00:00", pnl=-2_000_000, hold_days=14),
    ]
    r = disposition_effect(trades)
    assert r.severity == "high"
    assert r.metric > 1.5


def test_disposition_low_when_symmetric_holds():
    trades = [
        _sell("A", 110_000, "2026-04-10T00:00:00", pnl=1_000_000, hold_days=5),
        _sell("B", 90_000, "2026-04-11T00:00:00", pnl=-1_000_000, hold_days=5),
    ]
    r = disposition_effect(trades)
    assert r.severity == "low"


def test_disposition_insufficient_data():
    r = disposition_effect([])
    assert r.severity == "low"
    assert r.sample_size == 0


# -------------------------------------------------- overtrading

def test_overtrading_detected_when_busy_days_lose_money():
    trades = []
    # quiet day 1: 2 trades, +1M each
    trades.append(_sell("A", 110_000, "2026-04-01T10:00:00", pnl=1_000_000, hold_days=2))
    trades.append(_sell("B", 110_000, "2026-04-01T11:00:00", pnl=500_000, hold_days=2))
    # quiet day 2
    trades.append(_sell("C", 110_000, "2026-04-02T10:00:00", pnl=800_000, hold_days=2))
    # busy day 1: 5 trades, total -2M
    for i in range(5):
        trades.append(_sell(f"X{i}", 95_000, f"2026-04-03T{10+i:02d}:00:00",
                            pnl=-400_000, hold_days=1))
    # busy day 2: 4 trades, total -1M
    for i in range(4):
        trades.append(_sell(f"Y{i}", 95_000, f"2026-04-04T{10+i:02d}:00:00",
                            pnl=-250_000, hold_days=1))
    r = overtrading(trades)
    assert r.severity in ("medium", "high")
    assert r.metric > 0.3


# -------------------------------------------------- chase_momentum

def test_chase_momentum_high_when_buys_price_rising():
    # Sequence of buys on same ticker, each higher than previous → classic chase
    trades = [
        _buy("A", 100_000, f"2026-04-{i:02d}T10:00:00") for i in range(1, 11)
    ]
    # Bump prices upward
    for i, t in enumerate(trades):
        trades[i] = TradeLike(ticker="A", side="BUY", qty=100,
                              price=100_000 + i * 5_000,
                              traded_at=t.traded_at)
    r = chase_momentum(trades)
    assert r.severity in ("medium", "high")


def test_chase_momentum_low_when_buys_at_dips():
    # Buys alternating — no chase pattern
    trades = [
        TradeLike(ticker="A", side="BUY", qty=100, price=100_000,
                  traded_at=f"2026-04-{i:02d}T10:00:00")
        for i in range(1, 11)
    ]
    r = chase_momentum(trades)
    assert r.severity == "low"


# -------------------------------------------------- anchoring

def test_anchoring_high_when_prices_cluster():
    trades = []
    # 2 tickers, each with 6 buys at ~same price
    for ticker, base in [("A", 100_000), ("B", 50_000)]:
        for i in range(6):
            trades.append(TradeLike(
                ticker=ticker, side="BUY", qty=100,
                price=base + (i % 2) * 100,  # price varies <1%
                traded_at=f"2026-04-{i+1:02d}T10:00:00",
            ))
    r = anchoring(trades)
    assert r.severity == "high"


def test_anchoring_low_when_prices_spread():
    trades = []
    for i in range(6):
        trades.append(TradeLike(
            ticker="A", side="BUY", qty=100,
            price=100_000 + i * 10_000,  # 10% spread
            traded_at=f"2026-04-{i+1:02d}T10:00:00",
        ))
    r = anchoring(trades)
    assert r.severity == "low"


# -------------------------------------------------- hot_hand_sizing

def test_hot_hand_high_when_size_up_after_wins():
    """Pairs: after win → big size (0.2 NAV); after loss → small (0.05).
    Need ≥ 5 paired samples (detector requires 5 to compute correlation).
    """
    base_buys = [
        _buy("A", 100_000, f"2026-04-{i:02d}T09:00:00", pct_nav=0.1)
        for i in range(1, 5)
    ]
    sells = [
        _sell("A", 110_000, "2026-04-05T15:00:00", pnl=1_000_000, hold_days=4),
        _sell("A", 95_000, "2026-04-06T15:00:00", pnl=-500_000, hold_days=4),
        _sell("A", 115_000, "2026-04-07T15:00:00", pnl=1_500_000, hold_days=4),
        _sell("A", 90_000, "2026-04-08T15:00:00", pnl=-1_000_000, hold_days=4),
        _sell("A", 120_000, "2026-04-09T15:00:00", pnl=2_000_000, hold_days=4),
        _sell("A", 88_000, "2026-04-10T15:00:00", pnl=-1_500_000, hold_days=4),
    ]
    new_buys = [
        _buy("B", 100_000, "2026-04-05T16:00:00", pct_nav=0.20),
        _buy("B", 100_000, "2026-04-06T16:00:00", pct_nav=0.05),
        _buy("B", 100_000, "2026-04-07T16:00:00", pct_nav=0.22),
        _buy("B", 100_000, "2026-04-08T16:00:00", pct_nav=0.04),
        _buy("B", 100_000, "2026-04-09T16:00:00", pct_nav=0.25),
        _buy("B", 100_000, "2026-04-10T16:00:00", pct_nav=0.04),
    ]
    trades = list(base_buys)
    for s, b in zip(sells, new_buys, strict=True):
        trades.extend([s, b])
    r = hot_hand_sizing(trades)
    assert r.severity in ("medium", "high")


# -------------------------------------------------- skill_dogma

def test_skill_dogma_high_when_one_skill_dominates():
    decisions = [
        DecisionLike(decision_id=i, created_at="2026-04-01", ticker="X",
                     action="BUY", thesis="t",
                     skills_used=["technical-trend"] if i < 8 else ["momentum"])
        for i in range(10)
    ]
    r = skill_dogma(decisions)
    assert r.severity == "high"
    assert r.metric >= 0.70


def test_skill_dogma_low_when_skills_diverse():
    skills = ["technical-trend", "momentum", "smc", "ichimoku", "candlestick"]
    decisions = [
        DecisionLike(decision_id=i, created_at="2026-04-01", ticker="X",
                     action="BUY", thesis="t",
                     skills_used=[skills[i % 5]])
        for i in range(15)
    ]
    r = skill_dogma(decisions)
    assert r.severity == "low"


# -------------------------------------------------- recency

def test_recency_high_when_many_theses_mention_recent():
    theses = [
        "tuần trước FPT breakout đẹp",     # recent marker
        "hôm qua volume tăng mạnh",        # recent marker
        "gần đây mã này chạy rất tốt",     # recent marker
        "cost structure benign",           # no marker
        "last week earnings beat",         # marker
    ] * 3
    decisions = [
        DecisionLike(decision_id=i, created_at="2026-04-01", ticker="X",
                     action="BUY", thesis=t, skills_used=["technical-trend"])
        for i, t in enumerate(theses)
    ]
    r = recency(decisions)
    assert r.severity in ("medium", "high")


# -------------------------------------------------- aggregate

def test_detect_all_returns_seven_results():
    results = detect_all(trades=[], decisions=[])
    assert len(results) == 7
    names = {r.name for r in results}
    assert names == {
        "disposition_effect", "overtrading", "chase_momentum",
        "anchoring", "hot_hand", "skill_dogma", "recency",
    }
