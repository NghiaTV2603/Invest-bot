from vnstock_bot.db import queries
from vnstock_bot.memory import events, files, recall


def test_search_memory_events_only():
    events.record_event(
        kind="note",
        summary="FPT bứt phá MA50 sau 3 phiên volume cao",
        ticker="FPT",
    )
    events.record_event(
        kind="chat",
        summary="User hỏi VNM có nên bán",
        ticker="VNM",
    )
    hits = recall.search_memory("FPT breakout", include_files=False)
    assert hits
    assert hits[0].source == "event"
    assert hits[0].ticker == "FPT"


def test_search_memory_files_scored_by_metadata():
    files.write_memory_file(
        layer="reference",
        key="fpt_thesis",
        body="Detail body about trend",
        frontmatter={"title": "FPT long-term thesis",
                     "description": "growth + tech sector"},
    )
    hits = recall.search_memory("FPT thesis", include_events=False)
    assert hits
    assert hits[0].source == "file"
    assert hits[0].file is not None
    assert hits[0].file.name == "fpt_thesis"


def test_search_memory_combines_and_ranks():
    events.record_event(
        kind="note", summary="FPT technical breakout", ticker="FPT"
    )
    files.write_memory_file(
        "project", "fpt_plan", "Mua FPT ở vùng 148-150",
        frontmatter={"title": "FPT trading plan"},
    )
    hits = recall.search_memory("FPT", k=5)
    sources = {h.source for h in hits}
    assert "event" in sources
    assert "file" in sources


def test_recall_similar_decision_filters_by_ticker():
    queries.insert_decision({
        "created_at": "2026-04-10T15:31:00",
        "ticker": "FPT",
        "action": "BUY",
        "qty": 100,
        "target_price": 160_000,
        "stop_loss": 137_000,
        "thesis": "breakout",
        "evidence": ["a", "b", "c"],
        "risks": ["r"],
        "invalidation": "close < 140k",
        "skills_used": ["technical-trend"],
        "playbook": "new-entry",
        "conviction": 4,
        "source": "claude_daily",
        "status": "pending",
    })
    queries.insert_decision({
        "created_at": "2026-04-15T15:31:00",
        "ticker": "VNM",
        "action": "BUY",
        "qty": 100,
        "target_price": 90_000,
        "stop_loss": 78_000,
        "thesis": "mean revert",
        "evidence": ["a", "b", "c"],
        "risks": ["r"],
        "invalidation": "close < 80k",
        "skills_used": ["mean-reversion"],
        "playbook": "new-entry",
        "conviction": 3,
        "source": "claude_daily",
        "status": "pending",
    })

    fpt_only = recall.recall_similar_decision("FPT", since_days=365)
    assert len(fpt_only) == 1
    assert fpt_only[0]["ticker"] == "FPT"

    buys_only = recall.recall_similar_decision("VNM", action="BUY", since_days=365)
    assert len(buys_only) == 1
    assert buys_only[0]["action"] == "BUY"


def test_search_memory_returns_empty_on_empty_db():
    hits = recall.search_memory("anything")
    assert hits == []
