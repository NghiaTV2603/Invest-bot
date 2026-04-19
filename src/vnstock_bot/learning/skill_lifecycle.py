"""Skill lifecycle FSM + statistical gate (PLAN_V2.md §2.3).

States: draft → shadow → active → archived (+ archived → shadow via human revive).

Transitions happen in weekly review. Only automated transitions:
- shadow → active: pass stat gate (≥30 trades, CI95_low > 0.5, wf_pass ≥ 3/5)
- active → archived: ≥30 trades AND CI95_high < 0.5 (win-rate below 50% with confidence)

draft → shadow requires human approval (Telegram `/skill promote <name>`).
archived → shadow (revive) requires human approval.

Every transition writes to `skill_lifecycle_transitions` + updates the skill
file's frontmatter `status` field (via skill_loader.write_skill). Git commit
happens in the caller (weekly_review).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from vnstock_bot.data.holidays import now_vn
from vnstock_bot.db.connection import get_connection, transaction
from vnstock_bot.research.skill_loader import (
    SkillStatus,
    list_all_skills,
    read_skill,
    read_skill_meta,
    write_skill,
)

# ---------------------------------------------------------------- thresholds

MIN_USES_FOR_PROMOTION = 30
MIN_USES_FOR_ARCHIVAL = 30
CI_LOW_THRESHOLD_PROMOTE = 0.50        # CI95 lower bound > this → eligible
CI_HIGH_THRESHOLD_ARCHIVE = 0.50       # CI95 upper bound < this → archive
WF_PASS_MIN = 3                        # out of 5 windows
MIN_BEAT_PARENT_PCT = 0.02             # 2% absolute win-rate delta


# ---------------------------------------------------------------- data types

TransitionReason = Literal[
    "stat_gate_pass",
    "stat_gate_fail_low_ci",
    "human_approval",
    "parent_beat_insufficient",
    "insufficient_trades",
    "manual_override",
    "no_change_needed",
]


@dataclass
class LifecycleDecision:
    skill: str
    from_status: SkillStatus
    to_status: SkillStatus
    reason: TransitionReason
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return self.from_status != self.to_status


# ---------------------------------------------------------------- stat fetch

def _load_stats_row(skill: str) -> dict[str, Any] | None:
    row = get_connection().execute(
        "SELECT * FROM skill_scores_v2 WHERE skill = ?", (skill,)
    ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- evaluation

def _evaluate_shadow_to_active(
    skill: str, current: SkillStatus, stats: dict[str, Any] | None
) -> LifecycleDecision:
    """Shadow → active promotion rule."""
    if stats is None:
        return LifecycleDecision(skill, current, current,
                                 "insufficient_trades",
                                 {"reason_detail": "no stats row"})

    uses = int(stats.get("uses") or 0)
    if uses < MIN_USES_FOR_PROMOTION:
        return LifecycleDecision(skill, current, current,
                                 "insufficient_trades",
                                 {"uses": uses, "min_required": MIN_USES_FOR_PROMOTION})

    ci_low = stats.get("win_rate_ci_low")
    if ci_low is None or float(ci_low) <= CI_LOW_THRESHOLD_PROMOTE:
        return LifecycleDecision(skill, current, current,
                                 "stat_gate_fail_low_ci",
                                 {"ci_low": ci_low,
                                  "threshold": CI_LOW_THRESHOLD_PROMOTE})

    wf_pass = stats.get("wf_pass_count")
    if wf_pass is None or int(wf_pass) < WF_PASS_MIN:
        return LifecycleDecision(skill, current, current,
                                 "stat_gate_fail_low_ci",
                                 {"wf_pass_count": wf_pass,
                                  "min_required": WF_PASS_MIN})

    # beat parent (if parent exists)
    parent = stats.get("parent_skill")
    if parent:
        delta = stats.get("shadow_vs_parent")
        if delta is None or float(delta) < MIN_BEAT_PARENT_PCT:
            return LifecycleDecision(skill, current, current,
                                     "parent_beat_insufficient",
                                     {"shadow_vs_parent": delta,
                                      "min_required": MIN_BEAT_PARENT_PCT})

    return LifecycleDecision(
        skill, current, "active", "stat_gate_pass",
        evidence={"uses": uses, "ci_low": ci_low, "wf_pass": wf_pass,
                  "parent_delta": stats.get("shadow_vs_parent")},
    )


def _evaluate_active_to_archived(
    skill: str, current: SkillStatus, stats: dict[str, Any] | None
) -> LifecycleDecision:
    """Active → archived demotion rule."""
    if stats is None:
        return LifecycleDecision(skill, current, current,
                                 "no_change_needed",
                                 {"reason_detail": "no stats row"})

    uses = int(stats.get("uses") or 0)
    if uses < MIN_USES_FOR_ARCHIVAL:
        return LifecycleDecision(skill, current, current,
                                 "no_change_needed",
                                 {"uses": uses,
                                  "min_required": MIN_USES_FOR_ARCHIVAL})

    ci_high = stats.get("win_rate_ci_high")
    if ci_high is None or float(ci_high) >= CI_HIGH_THRESHOLD_ARCHIVE:
        return LifecycleDecision(skill, current, current, "no_change_needed",
                                 {"ci_high": ci_high,
                                  "threshold": CI_HIGH_THRESHOLD_ARCHIVE})

    return LifecycleDecision(
        skill, current, "archived", "stat_gate_fail_low_ci",
        evidence={"uses": uses, "ci_high": ci_high},
    )


def evaluate_skill(skill_name: str) -> LifecycleDecision:
    """Return the transition decision for one skill."""
    meta = read_skill_meta(skill_name)
    current = meta.status
    stats = _load_stats_row(skill_name)

    if current == "shadow":
        return _evaluate_shadow_to_active(skill_name, current, stats)
    if current == "active":
        return _evaluate_active_to_archived(skill_name, current, stats)
    if current in ("draft", "archived"):
        return LifecycleDecision(skill_name, current, current, "human_approval",
                                 {"note": f"{current} transitions need human approval"})

    return LifecycleDecision(skill_name, current, current, "no_change_needed")


def evaluate_all() -> list[LifecycleDecision]:
    return [evaluate_skill(n) for n in list_all_skills()]


# ---------------------------------------------------------------- apply

_FRONTMATTER_RE = re.compile(r"^---\s*\n(?P<fm>.*?)\n---\s*\n(?P<rest>.*)$",
                             re.DOTALL)


def _bump_frontmatter_status(skill_name: str, new_status: SkillStatus) -> None:
    """Rewrite the skill file's frontmatter `status:` line. Keep everything
    else byte-identical. Raises if file doesn't have v2 frontmatter."""
    text = read_skill(skill_name)
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"skill {skill_name!r}: no frontmatter to update")
    fm_text = m.group("fm")
    rest = m.group("rest")

    new_fm, hit = re.subn(
        r"^status:\s*\w+\s*$",
        f"status: {new_status}",
        fm_text,
        count=1,
        flags=re.MULTILINE,
    )
    if hit == 0:
        new_fm = fm_text.rstrip() + f"\nstatus: {new_status}\n"

    write_skill(skill_name, f"---\n{new_fm}\n---\n\n{rest}")


def _record_transition(d: LifecycleDecision) -> None:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO skill_lifecycle_transitions
                (skill, from_status, to_status, reason, evidence_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (d.skill, d.from_status, d.to_status, d.reason,
             json.dumps(d.evidence, ensure_ascii=False, default=str),
             now_vn().isoformat()),
        )
        # Also update status in skill_scores_v2 if row exists
        conn.execute(
            """UPDATE skill_scores_v2
               SET status = ?, last_computed_at = ?
               WHERE skill = ?""",
            (d.to_status, now_vn().isoformat(), d.skill),
        )


def apply_decision(d: LifecycleDecision, *, write_file: bool = True) -> bool:
    """Apply one decision: bump frontmatter + record transition. Returns True
    when state actually changed. No-op when `d.changed` is False.
    """
    if not d.changed:
        return False
    if write_file:
        _bump_frontmatter_status(d.skill, d.to_status)
    _record_transition(d)
    return True


def apply_all(decisions: list[LifecycleDecision] | None = None,
              *, dry_run: bool = False) -> list[LifecycleDecision]:
    """Evaluate + apply for every skill. Caller is expected to git-commit
    the resulting skill file changes in weekly review. Returns the list of
    decisions (both changed + unchanged — caller can filter `.changed`).
    """
    decisions = decisions or evaluate_all()
    if dry_run:
        return decisions
    for d in decisions:
        if d.changed:
            apply_decision(d)
    return decisions


# ---------------------------------------------------------------- human commands

def human_promote_draft_to_shadow(skill: str, note: str = "") -> LifecycleDecision:
    """Called from Telegram `/skill promote <name>`. No stat check — the
    whole point of shadow phase is to *gather* stats."""
    current = read_skill_meta(skill).status
    if current != "draft":
        raise ValueError(f"skill {skill!r} is {current!r}, not draft")
    d = LifecycleDecision(skill, "draft", "shadow", "human_approval",
                          evidence={"note": note})
    apply_decision(d)
    return d


def human_revive_archived(skill: str, note: str = "") -> LifecycleDecision:
    current = read_skill_meta(skill).status
    if current != "archived":
        raise ValueError(f"skill {skill!r} is {current!r}, not archived")
    d = LifecycleDecision(skill, "archived", "shadow", "human_approval",
                          evidence={"note": note})
    apply_decision(d)
    return d
