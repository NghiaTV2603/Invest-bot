from vnstock_bot.db import queries
from vnstock_bot.portfolio.validator import validate


def _base_decision(**overrides):
    base = {
        "ticker": "FPT",
        "action": "BUY",
        "qty": 100,
        "target_price": 160_000,
        "stop_loss": 137_000,
        "thesis": "test",
        "evidence": ["e1", "e2", "e3"],
        "risks": ["r1"],
        "invalidation": "close < 143,000",
        "skills_used": ["technical-trend", "fundamental-screen"],
        "playbook_used": "new-entry",
        "conviction": 4,
    }
    base.update(overrides)
    return base


def _seed_close(ticker: str, close: int):
    queries.upsert_ohlc(ticker, "2026-04-18", close, close, close, close, 1_000_000)


def test_accepts_valid_buy():
    _seed_close("FPT", 148_000)
    outcome = validate(_base_decision())
    assert outcome.ok, outcome.errors


def test_rejects_ticker_not_in_watchlist():
    outcome = validate(_base_decision(ticker="ZZZZZ"))
    assert not outcome.ok
    assert any("watchlist" in e for e in outcome.errors)


def test_rejects_qty_not_multiple_of_100():
    _seed_close("FPT", 148_000)
    outcome = validate(_base_decision(qty=150))
    assert not outcome.ok
    assert any("multiple of" in e for e in outcome.errors)


def test_rejects_short_evidence():
    _seed_close("FPT", 148_000)
    outcome = validate(_base_decision(evidence=["only one"]))
    assert not outcome.ok
    assert any("evidence" in e for e in outcome.errors)


def test_rejects_buy_without_new_entry_playbook():
    _seed_close("FPT", 148_000)
    outcome = validate(_base_decision(playbook_used=None))
    assert not outcome.ok


def test_hold_bypasses_most_checks():
    outcome = validate({
        "ticker": "FPT",
        "action": "HOLD",
        "qty": 0,
        "thesis": "watch",
        "evidence": ["a", "b", "c"],
        "risks": ["r"],
        "invalidation": "n/a",
        "skills_used": ["technical-trend"],
        "conviction": 2,
    })
    assert outcome.ok


def test_rejects_stop_loss_too_far():
    _seed_close("FPT", 150_000)
    # stop 50_000 is way > 25% away → reject
    outcome = validate(_base_decision(stop_loss=50_000))
    assert not outcome.ok
