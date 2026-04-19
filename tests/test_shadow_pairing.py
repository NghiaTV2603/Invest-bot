from vnstock_bot.shadow.pairing import pair_fifo, summarize
from vnstock_bot.shadow.types import RawTrade


def _t(ticker, side, qty, price, ts, fee=0):
    return RawTrade(traded_at=ts, ticker=ticker, side=side, qty=qty,
                    price=price, fee=fee)


def test_simple_pair_single_roundtrip():
    trades = [
        _t("FPT", "BUY",  100, 148_500, "2026-04-01T09:00:00"),
        _t("FPT", "SELL", 100, 152_000, "2026-04-05T10:00:00"),
    ]
    rts = pair_fifo(trades)
    assert len(rts) == 1
    rt = rts[0]
    assert rt.qty == 100
    assert rt.hold_days == 4
    assert rt.pnl == (152_000 - 148_500) * 100


def test_fifo_split_sell_across_two_buys():
    trades = [
        _t("FPT", "BUY",  100, 100_000, "2026-04-01T09:00:00"),
        _t("FPT", "BUY",  100, 105_000, "2026-04-03T09:00:00"),
        _t("FPT", "SELL", 150, 115_000, "2026-04-10T10:00:00"),
    ]
    rts = pair_fifo(trades)
    # 100 paired with first buy + 50 with second
    assert len(rts) == 2
    assert rts[0].qty == 100
    assert rts[0].buy_price == 100_000
    assert rts[1].qty == 50
    assert rts[1].buy_price == 105_000


def test_fifo_multiple_sells_draw_from_same_buy():
    trades = [
        _t("FPT", "BUY",  200, 100_000, "2026-04-01T09:00:00"),
        _t("FPT", "SELL", 100, 110_000, "2026-04-05T10:00:00"),
        _t("FPT", "SELL", 100, 115_000, "2026-04-10T10:00:00"),
    ]
    rts = pair_fifo(trades)
    assert len(rts) == 2
    assert rts[0].qty == 100 and rts[0].sell_price == 110_000
    assert rts[1].qty == 100 and rts[1].sell_price == 115_000


def test_fee_apportioning_sum_matches_original():
    trades = [
        _t("FPT", "BUY", 200, 100_000, "2026-04-01T09:00:00", fee=200),
        _t("FPT", "SELL", 200, 110_000, "2026-04-05T10:00:00", fee=300),
    ]
    rts = pair_fifo(trades)
    # Single full-qty pair → fees should match exactly
    assert rts[0].buy_fee == 200
    assert rts[0].sell_fee == 300


def test_fee_split_proportionally():
    trades = [
        _t("FPT", "BUY",  200, 100_000, "2026-04-01T09:00:00", fee=200),
        _t("FPT", "SELL", 100, 110_000, "2026-04-05T10:00:00", fee=100),
        _t("FPT", "SELL", 100, 115_000, "2026-04-10T10:00:00", fee=110),
    ]
    rts = pair_fifo(trades)
    # Each sell fee allocated fully (single-slice); buy fee split 100/100 = 100+100
    assert rts[0].buy_fee == 100
    assert rts[1].buy_fee == 100
    assert rts[0].sell_fee == 100
    assert rts[1].sell_fee == 110


def test_unmatched_buys_do_not_produce_roundtrips():
    trades = [
        _t("FPT", "BUY", 100, 100_000, "2026-04-01T09:00:00"),
        _t("VNM", "BUY", 50, 80_000, "2026-04-02T09:00:00"),
    ]
    assert pair_fifo(trades) == []


def test_sector_lookup_applied():
    trades = [
        _t("FPT", "BUY",  100, 100_000, "2026-04-01T09:00:00"),
        _t("FPT", "SELL", 100, 105_000, "2026-04-05T10:00:00"),
    ]
    rts = pair_fifo(trades, sector_lookup={"FPT": "Tech"})
    assert rts[0].sector == "Tech"


def test_summarize_win_rate():
    trades = [
        _t("FPT", "BUY",  100, 100_000, "2026-04-01T09:00:00"),
        _t("FPT", "SELL", 100, 110_000, "2026-04-02T09:00:00"),  # win
        _t("VNM", "BUY",  100, 100_000, "2026-04-03T09:00:00"),
        _t("VNM", "SELL", 100, 95_000, "2026-04-04T09:00:00"),   # loss
    ]
    rts = pair_fifo(trades)
    stats = summarize(rts)
    assert stats["total"] == 2
    assert stats["winners"] == 1
    assert stats["win_rate"] == 0.5


def test_summarize_empty():
    stats = summarize([])
    assert stats["total"] == 0
    assert stats["win_rate"] == 0.0
