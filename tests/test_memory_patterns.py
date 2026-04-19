from datetime import timedelta

from vnstock_bot.data.holidays import now_vn
from vnstock_bot.db import queries
from vnstock_bot.db.connection import get_connection
from vnstock_bot.memory.patterns import extract_and_persist


def _seed(created_at: str, skills: list[str], pnl_pct: float,
          conviction: int = 4, playbook: str = "new-entry",
          ticker: str = "FPT") -> int:
    did = queries.insert_decision({
        "created_at": created_at,
        "ticker": ticker,
        "action": "BUY",
        "qty": 100,
        "target_price": 160_000,
        "stop_loss": 137_000,
        "thesis": "t",
        "evidence": ["a", "b", "c"],
        "risks": ["r"],
        "invalidation": "close < 140k",
        "skills_used": skills,
        "playbook": playbook,
        "conviction": conviction,
        "source": "claude_daily",
        "status": "filled",
    })
    queries.upsert_outcome(
        decision_id=did, days_held=20, pnl_pct=pnl_pct,
        thesis_valid=1 if pnl_pct > 0 else 0,
        invalidation_hit=0 if pnl_pct > 0 else 1,
        scored_at=now_vn().isoformat(),
    )
    return did


def test_pattern_emitted_when_three_winners_share_signature():
    # 4 winners with same (skills, playbook, conviction-bucket)
    for i in range(4):
        _seed(
            (now_vn() - timedelta(days=30 - i)).isoformat(),
            skills=["momentum", "candlestick"],
            pnl_pct=0.05,
            conviction=5,
        )
    summary = extract_and_persist()
    assert summary["winners_scanned"] == 4
    assert summary["new_or_updated"] >= 1

    rows = get_connection().execute(
        "SELECT body, support_count FROM patterns ORDER BY support_count DESC"
    ).fetchall()
    assert len(rows) >= 1
    assert rows[0]["support_count"] >= 4


def test_no_pattern_below_min_support():
    for i in range(2):
        _seed(
            (now_vn() - timedelta(days=20 - i)).isoformat(),
            skills=["breakout"], pnl_pct=0.05,
        )
    summary = extract_and_persist()
    assert summary["new_or_updated"] == 0
    rows = get_connection().execute(
        "SELECT count(*) AS n FROM patterns"
    ).fetchone()
    assert rows["n"] == 0


def test_losers_do_not_emit_pattern():
    # 5 losers with same signature → no pattern
    for i in range(5):
        _seed(
            (now_vn() - timedelta(days=20 - i)).isoformat(),
            skills=["mean-reversion"], pnl_pct=-0.05,
        )
    summary = extract_and_persist()
    assert summary["winners_scanned"] == 0
    assert summary["new_or_updated"] == 0


def test_pattern_idempotent_upsert():
    for i in range(4):
        _seed(
            (now_vn() - timedelta(days=20 - i)).isoformat(),
            skills=["ichimoku"], pnl_pct=0.04,
        )
    extract_and_persist()
    extract_and_persist()
    count = get_connection().execute(
        "SELECT count(*) AS n FROM patterns WHERE confirmed=0"
    ).fetchone()["n"]
    assert count == 1


def test_stale_unconfirmed_patterns_get_deleted():
    # Insert a stale pattern manually (>90 days old, unconfirmed)
    stale_date = (now_vn() - timedelta(days=120)).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO patterns
                (created_at, body, support_count, confirmed,
                 last_seen_at, metadata_json)
               VALUES (?, ?, 5, 0, ?, '{}')""",
            (stale_date, "stale pattern", stale_date),
        )
    summary = extract_and_persist()
    assert summary["expired"] >= 1
    rows = get_connection().execute(
        "SELECT count(*) AS n FROM patterns WHERE body = 'stale pattern'"
    ).fetchone()
    assert rows["n"] == 0
