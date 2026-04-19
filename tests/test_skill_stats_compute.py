from datetime import timedelta

from vnstock_bot.data.holidays import now_vn
from vnstock_bot.db import queries
from vnstock_bot.db.connection import get_connection
from vnstock_bot.learning.skill_stats_compute import (
    MIN_USES_TO_COMPUTE,
    compute_and_persist_all,
    compute_skill_stats,
)


def _seed_decision(created_at: str, skills: list[str], ticker: str = "FPT") -> int:
    return queries.insert_decision({
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
        "playbook": "new-entry",
        "conviction": 4,
        "source": "claude_daily",
        "status": "filled",
    })


def _seed_outcome(did: int, pnl_pct: float, days_held: int = 20) -> None:
    queries.upsert_outcome(
        decision_id=did, days_held=days_held,
        pnl_pct=pnl_pct,
        thesis_valid=1 if pnl_pct > 0 else 0,
        invalidation_hit=0 if pnl_pct > 0 else 1,
        scored_at=now_vn().isoformat(),
    )


def test_too_few_uses_returns_null_ci():
    for i in range(3):
        did = _seed_decision(
            (now_vn() - timedelta(days=40 - i)).isoformat(),
            ["test-skill"],
        )
        _seed_outcome(did, pnl_pct=0.05)

    row = compute_skill_stats("test-skill")
    assert row.uses == 3
    assert row.wins == 3
    assert row.win_rate_point == 1.0
    # Below MIN_USES_TO_COMPUTE → no CI populated
    assert row.win_rate_ci_low is None
    assert row.win_rate_ci_high is None


def test_enough_uses_produces_bootstrap_ci():
    # 12 decisions on same skill, mix of winners/losers
    for i in range(12):
        did = _seed_decision(
            (now_vn() - timedelta(days=60 - i * 2)).isoformat(),
            ["bootstrap-skill"],
        )
        # 8 winners, 4 losers
        pnl = 0.06 if i < 8 else -0.04
        _seed_outcome(did, pnl_pct=pnl)

    row = compute_skill_stats("bootstrap-skill")
    assert row.uses >= MIN_USES_TO_COMPUTE
    assert row.wins == 8
    assert row.losses == 4
    assert row.win_rate_ci_low is not None
    assert row.win_rate_ci_high is not None
    assert row.win_rate_ci_low <= row.win_rate_point <= row.win_rate_ci_high
    assert row.wf_total_windows is not None and row.wf_total_windows > 0


def test_substring_skill_name_not_matched_falsely():
    # Skill A is a prefix of Skill B. LIKE '%"A"%' would also match 'AB'.
    # Our JSON-parse guard must filter correctly.
    for i in range(8):
        did = _seed_decision(
            (now_vn() - timedelta(days=40 - i)).isoformat(),
            ["momentum-long"],   # shouldn't match "momentum"
        )
        _seed_outcome(did, pnl_pct=0.02)

    row = compute_skill_stats("momentum")
    assert row.uses == 0


def test_unscored_decisions_are_ignored():
    # Decisions without outcome rows should NOT count toward uses
    for i in range(5):
        _seed_decision(
            (now_vn() - timedelta(days=10 + i)).isoformat(),
            ["unscored-skill"],
        )
    row = compute_skill_stats("unscored-skill")
    assert row.uses == 0


def test_compute_and_persist_all_upserts_rows():
    for i in range(8):
        did = _seed_decision(
            (now_vn() - timedelta(days=40 - i)).isoformat(),
            ["persist-skill"],
        )
        _seed_outcome(did, pnl_pct=0.05 if i < 5 else -0.03)

    rows = compute_and_persist_all()
    assert any(r.skill == "persist-skill" for r in rows)

    # Verify DB row exists with CI
    db_row = get_connection().execute(
        "SELECT * FROM skill_scores_v2 WHERE skill = ?", ("persist-skill",),
    ).fetchone()
    assert db_row is not None
    assert db_row["win_rate_ci_low"] is not None
    assert db_row["uses"] == 8


def test_compute_and_persist_idempotent():
    """Running twice should UPDATE, not INSERT duplicate rows."""
    for i in range(6):
        did = _seed_decision(
            (now_vn() - timedelta(days=30 - i)).isoformat(),
            ["idempotent-skill"],
        )
        _seed_outcome(did, pnl_pct=0.04)

    compute_and_persist_all()
    compute_and_persist_all()

    count = get_connection().execute(
        "SELECT count(*) AS n FROM skill_scores_v2 WHERE skill = ?",
        ("idempotent-skill",),
    ).fetchone()["n"]
    assert count == 1


def test_stats_unblocks_skill_lifecycle():
    """Integration: if stats get populated properly, a shadow skill with
    ≥30 winning uses + high CI should be promoted by apply_all."""
    # Seed 35 winning decisions for 'lc-integration'
    for i in range(35):
        did = _seed_decision(
            (now_vn() - timedelta(days=60 - i)).isoformat(),
            ["lc-integration"],
        )
        _seed_outcome(did, pnl_pct=0.06)   # all winners

    # Create a shadow-status skill file
    from vnstock_bot.research.skill_loader import write_skill
    write_skill("strategy/lc-integration", """---
name: lc-integration
version: 1
status: shadow
category: strategy
when_to_use: test
inputs: []
outputs: []
parent_skill: null
uses: 0
---

## Body
""")

    # Run the full weekly chain: compute → apply
    compute_and_persist_all()

    from vnstock_bot.learning.skill_lifecycle import apply_all
    decisions = apply_all(dry_run=False)
    changed = {d.skill: d for d in decisions if d.changed}
    assert "strategy/lc-integration" in changed
    assert changed["strategy/lc-integration"].to_status == "active"
