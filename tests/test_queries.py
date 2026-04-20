from vnstock_bot.db import queries


def test_cash_default():
    queries.set_cash(100_000_000)
    assert queries.get_cash() == 100_000_000


def test_upsert_holding_roundtrip():
    queries.upsert_holding("FPT", 200, 100, 148_500, "2026-04-18", "2026-04-18")
    h = queries.get_holding("FPT")
    assert h is not None
    assert h["qty_total"] == 200
    assert h["qty_available"] == 100
    assert h["avg_cost"] == 148_500


def test_decision_insert_and_recent():
    from vnstock_bot.data.holidays import now_vn
    did = queries.insert_decision({
        "created_at": now_vn().isoformat(),
        "ticker": "FPT",
        "action": "BUY",
        "qty": 100,
        "target_price": 160_000,
        "stop_loss": 137_000,
        "thesis": "test",
        "evidence": ["a", "b", "c"],
        "risks": ["r"],
        "invalidation": "x",
        "skills_used": ["technical-trend"],
        "playbook": "new-entry",
        "conviction": 4,
        "source": "claude_daily",
        "status": "pending",
    })
    assert did > 0
    rows = queries.get_decisions_recent(days=1)
    assert len(rows) == 1
    assert rows[0]["id"] == did


def test_ohlc_cache():
    queries.upsert_ohlc("VNM", "2026-04-18", 80_000, 82_000, 79_500, 81_500, 2_000_000)
    row = queries.get_ohlc_on("VNM", "2026-04-18")
    assert row is not None
    assert row["close"] == 81_500
    rows = queries.get_ohlc("VNM", days=30)
    assert len(rows) == 1


def test_skill_scores_bump():
    queries.bump_skill_uses(["technical-trend", "fundamental-screen"], "2026-04-18")
    queries.bump_skill_uses(["technical-trend"], "2026-04-19")
    rows = {r["skill"]: r for r in queries.list_skill_scores()}
    assert rows["technical-trend"]["uses"] == 2
    assert rows["fundamental-screen"]["uses"] == 1
