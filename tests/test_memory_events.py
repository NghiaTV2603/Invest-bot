import pytest

from vnstock_bot.memory import events, fts5


@pytest.fixture
def some_events():
    ids = [
        events.record_event(
            kind="chat",
            summary="User hỏi về FPT có nên mua không",
            ticker="FPT",
            payload={"q": "FPT có nên mua?"},
        ),
        events.record_event(
            kind="decision",
            summary="BUY FPT 100cp ở 148500 — breakout MA50",
            ticker="FPT",
            decision_id=None,
            payload={"action": "BUY", "qty": 100, "price": 148_500},
        ),
        events.record_event(
            kind="chat",
            summary="User hỏi về VNM trong xu hướng giảm",
            ticker="VNM",
            payload={"q": "VNM có nên cắt?"},
        ),
        events.record_event(
            kind="note",
            summary="Ghi chú khối ngoại mua ròng 5 phiên liên tiếp trên FPT",
            ticker="FPT",
            payload={"source": "market_snapshot"},
        ),
    ]
    return ids


def test_record_event_returns_incrementing_id(some_events):
    assert all(eid > 0 for eid in some_events)
    assert len(set(some_events)) == len(some_events)


def test_get_event_roundtrip(some_events):
    ev = events.get_event(some_events[1])
    assert ev is not None
    assert ev.kind == "decision"
    assert ev.ticker == "FPT"
    assert ev.payload["action"] == "BUY"


def test_get_timeline_filters_by_ticker(some_events):
    tl = events.get_timeline("FPT", days=30)
    tickers = {e.ticker for e in tl}
    assert tickers == {"FPT"}
    assert len(tl) == 3


def test_recent_events_filter_by_kind(some_events):
    chats = events.recent_events(days=30, kinds=("chat",))
    assert all(e.kind == "chat" for e in chats)
    assert len(chats) == 2


def test_fts5_index_populated_on_record(some_events):
    # "FPT" was normalized to lowercase in fts5 via unicode61
    hits = fts5.search("FPT", k=10)
    assert len(hits) >= 3
    assert all("fpt" in (h.summary or "").lower() or h.ticker == "FPT" for h in hits)


def test_fts5_search_diacritic_insensitive(some_events):
    # Query with diacritics should match indexed text without diacritics
    hits = fts5.search("khối ngoại", k=5)
    assert any("khoi" in h.summary.lower() or "ngoai" in h.summary.lower()
               or "khối" in h.summary for h in hits)


def test_rebuild_index_matches_table(some_events):
    count = fts5.rebuild_index()
    assert count == len(some_events)
