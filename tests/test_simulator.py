from datetime import date

from vnstock_bot.db import queries
from vnstock_bot.portfolio.simulator import (
    compute_fee,
    fill_pending_orders,
    load_portfolio,
    release_t2_shares,
    round_down_lot,
)


def test_round_down_lot():
    assert round_down_lot(250) == 200
    assert round_down_lot(99) == 0
    assert round_down_lot(100) == 100


def test_fee_calculation():
    # 15bps on 10,000,000 = 15,000
    assert compute_fee("BUY", 10_000_000) == 15_000
    # 25bps sell
    assert compute_fee("SELL", 10_000_000) == 25_000


def test_initial_cash_seeded():
    p = load_portfolio()
    assert p.cash == 100_000_000
    assert p.holdings == []


def _seed_ohlc(ticker: str, d: str, open_px: int, close_px: int):
    queries.upsert_ohlc(ticker, d, open_px, close_px, open_px, close_px, 1_000_000)


def _place_decision_and_order(ticker: str, action: str, qty: int, when: str, fill_date: str) -> int:
    did = queries.insert_decision({
        "created_at": when, "ticker": ticker, "action": action, "qty": qty,
        "target_price": None, "stop_loss": None,
        "thesis": "test", "evidence": ["a", "b", "c"], "risks": ["x"],
        "invalidation": "close < 0",
        "skills_used": ["technical-trend"], "playbook": "new-entry",
        "conviction": 4, "source": "user_manual", "status": "pending",
    })
    side = "BUY" if action in ("BUY", "ADD") else "SELL"
    queries.insert_order(did, ticker, side, qty, when, fill_date)
    return did


def test_buy_fill_updates_cash_and_holding():
    # OHLC on fill day
    _seed_ohlc("FPT", "2026-04-20", open_px=150_000, close_px=152_000)
    _place_decision_and_order("FPT", "BUY", 100, "2026-04-17", "2026-04-20")

    summary = fill_pending_orders(date(2026, 4, 20))
    assert len(summary.filled) == 1
    f = summary.filled[0]
    assert f.fill_price == 150_000
    assert f.fee == 15 * 100 * 150_000 // 10_000  # 15bps

    p = load_portfolio()
    assert p.cash == 100_000_000 - (150_000 * 100) - f.fee
    assert len(p.holdings) == 1
    h = p.holdings[0]
    assert h.ticker == "FPT"
    assert h.qty_total == 100
    assert h.qty_available == 0  # locked until T+2


def test_sell_blocked_before_t2():
    _seed_ohlc("FPT", "2026-04-20", 150_000, 152_000)
    _place_decision_and_order("FPT", "BUY", 100, "2026-04-17", "2026-04-20")
    fill_pending_orders(date(2026, 4, 20))

    # try to sell next day while qty_available = 0
    _seed_ohlc("FPT", "2026-04-21", 151_000, 151_000)
    _place_decision_and_order("FPT", "SELL", 100, "2026-04-20", "2026-04-21")
    summary = fill_pending_orders(date(2026, 4, 21))
    assert summary.filled == []
    assert summary.cancelled[0][1] == "insufficient_available_qty"


def test_t2_release_allows_sell():
    _seed_ohlc("FPT", "2026-04-20", 150_000, 152_000)
    _place_decision_and_order("FPT", "BUY", 100, "2026-04-17", "2026-04-20")
    fill_pending_orders(date(2026, 4, 20))

    # advance 2 trading days: 2026-04-22 Wed
    _seed_ohlc("FPT", "2026-04-22", 155_000, 155_000)
    release_t2_shares(date(2026, 4, 22))

    p = load_portfolio()
    h = p.holdings[0]
    assert h.qty_available == 100  # released

    # now sell
    _place_decision_and_order("FPT", "SELL", 100, "2026-04-22", "2026-04-23")
    _seed_ohlc("FPT", "2026-04-23", 156_000, 156_000)
    summary = fill_pending_orders(date(2026, 4, 23))
    assert len(summary.filled) == 1
    assert summary.filled[0].side == "SELL"
    assert summary.filled[0].fill_price == 156_000

    p = load_portfolio()
    assert p.holdings == []
    # BUY cost = 15_000_000 + 15bps fee 22_500 = 15_022_500
    # SELL proceeds = 15_600_000 - 25bps fee 39_000 = 15_561_000
    assert p.cash == 100_000_000 - 15_022_500 + 15_561_000


def test_buy_cancelled_if_insufficient_cash():
    # Put cash to almost zero via big buy
    _seed_ohlc("VNM", "2026-04-20", 80_000, 80_000)
    _place_decision_and_order("VNM", "BUY", 1500, "2026-04-17", "2026-04-20")
    # 80k * 1500 = 120M > 100M seed cash → should cancel
    summary = fill_pending_orders(date(2026, 4, 20))
    assert summary.filled == []
    assert any(r[1] == "insufficient_cash" for r in summary.cancelled)
