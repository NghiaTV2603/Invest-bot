import pytest

from vnstock_bot.db.connection import get_connection, transaction
from vnstock_bot.learning import skill_lifecycle as lc
from vnstock_bot.research.skill_loader import read_skill_meta, write_skill


def _insert_stats(skill, **cols):
    placeholders = ",".join("?" * (len(cols) + 1))
    names = "skill," + ",".join(cols.keys())
    values = [skill] + list(cols.values())
    with transaction() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO skill_scores_v2 ({names}) VALUES ({placeholders})",
            values,
        )


def _seed_skill(name: str, status: str = "shadow") -> None:
    """Create a minimal v2 skill file in status=<status>."""
    write_skill(name, f"""---
name: {name.split('/')[-1]}
version: 1
status: {status}
category: strategy
when_to_use: test skill
inputs: []
outputs: []
parent_skill: null
uses: 0
---

## Body
test
""")


def test_shadow_promotes_on_clean_stats():
    _seed_skill("strategy/lc_promote", status="shadow")
    _insert_stats(
        "strategy/lc_promote",
        uses=40, trades_with_signal=40, wins=30, losses=10,
        win_rate_ci_low=0.55, win_rate_ci_high=0.85,
        wf_pass_count=4, wf_total_windows=5,
    )
    d = lc.evaluate_skill("strategy/lc_promote")
    assert d.changed
    assert d.to_status == "active"
    assert d.reason == "stat_gate_pass"


def test_shadow_blocked_by_low_ci():
    _seed_skill("strategy/lc_low_ci", status="shadow")
    _insert_stats(
        "strategy/lc_low_ci",
        uses=40, win_rate_ci_low=0.45, win_rate_ci_high=0.70,
        wf_pass_count=4, wf_total_windows=5,
    )
    d = lc.evaluate_skill("strategy/lc_low_ci")
    assert not d.changed
    assert d.reason == "stat_gate_fail_low_ci"


def test_shadow_blocked_by_few_uses():
    _seed_skill("strategy/lc_few", status="shadow")
    _insert_stats(
        "strategy/lc_few",
        uses=10, win_rate_ci_low=0.70, win_rate_ci_high=0.90,
        wf_pass_count=4, wf_total_windows=5,
    )
    d = lc.evaluate_skill("strategy/lc_few")
    assert not d.changed
    assert d.reason == "insufficient_trades"


def test_shadow_blocked_by_low_wf():
    _seed_skill("strategy/lc_wf", status="shadow")
    _insert_stats(
        "strategy/lc_wf",
        uses=40, win_rate_ci_low=0.55, win_rate_ci_high=0.85,
        wf_pass_count=2, wf_total_windows=5,
    )
    d = lc.evaluate_skill("strategy/lc_wf")
    assert not d.changed
    assert "gate_fail" in d.reason


def test_shadow_blocked_when_not_beating_parent():
    _seed_skill("strategy/lc_child", status="shadow")
    _insert_stats(
        "strategy/lc_child",
        uses=40, win_rate_ci_low=0.55, win_rate_ci_high=0.85,
        wf_pass_count=4, wf_total_windows=5,
        parent_skill="strategy/parent",
        shadow_vs_parent=0.005,  # only 0.5% better than parent
    )
    d = lc.evaluate_skill("strategy/lc_child")
    assert not d.changed
    assert d.reason == "parent_beat_insufficient"


def test_active_demotes_on_bad_ci():
    _seed_skill("strategy/lc_demote", status="active")
    _insert_stats(
        "strategy/lc_demote",
        uses=60, win_rate_ci_low=0.20, win_rate_ci_high=0.45,
        wf_pass_count=1, wf_total_windows=5,
    )
    d = lc.evaluate_skill("strategy/lc_demote")
    assert d.changed
    assert d.to_status == "archived"


def test_active_stays_when_ci_high():
    _seed_skill("strategy/lc_keep", status="active")
    _insert_stats(
        "strategy/lc_keep",
        uses=60, win_rate_ci_low=0.55, win_rate_ci_high=0.80,
    )
    d = lc.evaluate_skill("strategy/lc_keep")
    assert not d.changed


def test_draft_never_auto_promotes():
    _seed_skill("strategy/lc_draft", status="draft")
    _insert_stats(
        "strategy/lc_draft",
        uses=40, win_rate_ci_low=0.55, win_rate_ci_high=0.85,
        wf_pass_count=4, wf_total_windows=5,
    )
    d = lc.evaluate_skill("strategy/lc_draft")
    assert not d.changed
    assert d.reason == "human_approval"


def test_apply_decision_writes_transition_and_frontmatter():
    _seed_skill("strategy/lc_apply", status="shadow")
    _insert_stats(
        "strategy/lc_apply",
        uses=40, win_rate_ci_low=0.6, win_rate_ci_high=0.9,
        wf_pass_count=4, wf_total_windows=5,
    )
    d = lc.evaluate_skill("strategy/lc_apply")
    assert lc.apply_decision(d)
    # Frontmatter updated
    meta = read_skill_meta("strategy/lc_apply")
    assert meta.status == "active"
    # Transition audit row exists
    row = get_connection().execute(
        "SELECT * FROM skill_lifecycle_transitions WHERE skill=?",
        ("strategy/lc_apply",),
    ).fetchone()
    assert row is not None
    assert row["from_status"] == "shadow"
    assert row["to_status"] == "active"


def test_human_promote_draft_to_shadow():
    _seed_skill("strategy/lc_human", status="draft")
    d = lc.human_promote_draft_to_shadow("strategy/lc_human", note="looks good")
    assert d.to_status == "shadow"
    meta = read_skill_meta("strategy/lc_human")
    assert meta.status == "shadow"


def test_human_promote_rejects_non_draft():
    _seed_skill("strategy/lc_active", status="active")
    with pytest.raises(ValueError, match="not draft"):
        lc.human_promote_draft_to_shadow("strategy/lc_active")
