"""Skill stats compute loop — unblocks skill_lifecycle (PLAN_V2 §2.3).

Without this loop, `skill_scores_v2.win_rate_ci_low/high` stays NULL and
every skill gets 'insufficient_trades' from `skill_lifecycle.evaluate_skill`.

Called from weekly_review_job BEFORE `apply_all`. For each skill with ≥ N
recent decision_outcomes, compute bootstrap CI + walk-forward and UPSERT.

Design:
  - "outcome" per decision = (pnl_pct_20d > 0). Uses 20-day scored outcome;
    skills that haven't had 20d to season get skipped.
  - "return" per decision = pnl_pct_20d (float). Used for walk-forward on
    chronological trade sequence.
  - Skills used in < MIN_USES_TO_COMPUTE decisions are recorded but CI is
    left NULL (lifecycle gate will then still say insufficient_trades, which
    is correct).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta

import numpy as np

from vnstock_bot.data.holidays import now_vn
from vnstock_bot.db.connection import get_connection, transaction
from vnstock_bot.learning.stats import (
    bootstrap_ci,
    monte_carlo_permutation,
    walk_forward,
    win_rate,
)
from vnstock_bot.logging_setup import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------- config

OUTCOME_HORIZON_DAYS = 20
MIN_USES_TO_COMPUTE = 5        # below this, skip bootstrap (too noisy)
WF_THRESHOLD = 0.5             # win_rate window must exceed this to "pass"


@dataclass
class SkillStatsRow:
    skill: str
    uses: int
    trades_with_signal: int
    wins: int
    losses: int
    win_rate_point: float | None
    win_rate_ci_low: float | None
    win_rate_ci_high: float | None
    mc_pvalue: float | None
    wf_pass_count: int | None
    wf_total_windows: int | None


# ---------------------------------------------------------------- queries

def _fetch_outcomes_for_skill(skill: str, since_iso: str) -> list[dict]:
    """All scored decisions using this skill. One row per decision (longest
    horizon scored, up to OUTCOME_HORIZON_DAYS)."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT d.id, d.created_at, d.skills_used_json,
                  (SELECT pnl_pct FROM decision_outcomes
                     WHERE decision_id = d.id AND days_held <= ?
                     ORDER BY days_held DESC LIMIT 1) AS pnl_pct
           FROM decisions d
           WHERE d.created_at >= ?
             AND d.skills_used_json LIKE ?
             AND d.status IN ('filled','pending')
           ORDER BY d.created_at""",
        (OUTCOME_HORIZON_DAYS, since_iso, f'%"{skill}"%'),
    ).fetchall()
    out = []
    for r in rows:
        # LIKE may false-positive on skill substrings; verify by parsing JSON.
        try:
            skills = json.loads(r["skills_used_json"] or "[]")
        except (ValueError, TypeError):
            continue
        if skill not in skills:
            continue
        if r["pnl_pct"] is None:
            continue  # outcome not scored yet
        out.append({
            "decision_id": int(r["id"]),
            "created_at": r["created_at"],
            "pnl_pct": float(r["pnl_pct"]),
        })
    return out


def _distinct_skills_seen(since_iso: str) -> list[str]:
    rows = get_connection().execute(
        """SELECT DISTINCT skills_used_json FROM decisions
           WHERE created_at >= ? AND skills_used_json IS NOT NULL""",
        (since_iso,),
    ).fetchall()
    seen: set[str] = set()
    for r in rows:
        try:
            seen.update(json.loads(r["skills_used_json"] or "[]"))
        except (ValueError, TypeError):
            continue
    return sorted(seen)


def _resolve_skill_name(raw: str) -> str:
    """Decisions may log skills as either bare name ('momentum') or path-
    style ('strategy/momentum'). skill_lifecycle reads by path, so we
    normalize here: if the bare name matches exactly one file, return the
    path; otherwise return the raw name. This lets stats_compute write to
    skill_scores_v2 with the SAME key the lifecycle FSM reads with.
    """
    if "/" in raw:
        return raw
    from vnstock_bot.research.skill_loader import list_all_skills
    matches = [s for s in list_all_skills() if s.split("/")[-1] == raw]
    return matches[0] if len(matches) == 1 else raw


# ---------------------------------------------------------------- compute

def compute_skill_stats(skill: str, since_iso: str | None = None) -> SkillStatsRow:
    if since_iso is None:
        since_iso = (now_vn() - timedelta(days=180)).isoformat()
    records = _fetch_outcomes_for_skill(skill, since_iso)
    uses = len(records)
    pnl_pct = np.array([r["pnl_pct"] for r in records], dtype=float)
    outcomes = (pnl_pct > 0).astype(float)
    wins = int(outcomes.sum())
    losses = uses - wins

    if uses < MIN_USES_TO_COMPUTE:
        return SkillStatsRow(
            skill=skill, uses=uses, trades_with_signal=uses,
            wins=wins, losses=losses,
            win_rate_point=float(wins / uses) if uses else None,
            win_rate_ci_low=None, win_rate_ci_high=None,
            mc_pvalue=None,
            wf_pass_count=None, wf_total_windows=None,
        )

    # Bootstrap CI for win-rate. Reduced n_bootstrap for speed — CI width
    # is dominated by sample size, not n_bootstrap after ~500.
    ci = bootstrap_ci(outcomes, stat_fn=win_rate, n_bootstrap=500)

    # Monte Carlo permutation on the pnl sequence (path-dependent via
    # cumulative return). Keep n=500 for speed.
    mc = monte_carlo_permutation(
        pnl_pct, stat_fn=win_rate, n_permutations=500,
    )

    # Walk-forward: split chronologically into N windows. Use N=3 for small
    # samples, up to 5 when we have plenty.
    n_windows = 3 if uses < 20 else 5
    wf = walk_forward(
        pnl_pct, n_windows=n_windows,
        stat_fn=win_rate, threshold=WF_THRESHOLD,
    )

    return SkillStatsRow(
        skill=skill,
        uses=uses,
        trades_with_signal=uses,
        wins=wins,
        losses=losses,
        win_rate_point=float(ci.point),
        win_rate_ci_low=float(ci.ci_low),
        win_rate_ci_high=float(ci.ci_high),
        mc_pvalue=float(mc.p_value),
        wf_pass_count=int(wf.pass_count),
        wf_total_windows=int(wf.total_windows),
    )


# ---------------------------------------------------------------- persist

def _upsert(row: SkillStatsRow) -> None:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO skill_scores_v2
                (skill, uses, trades_with_signal, wins, losses,
                 win_rate_point, win_rate_ci_low, win_rate_ci_high,
                 mc_pvalue, wf_pass_count, wf_total_windows,
                 last_computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(skill) DO UPDATE SET
                 uses = excluded.uses,
                 trades_with_signal = excluded.trades_with_signal,
                 wins = excluded.wins,
                 losses = excluded.losses,
                 win_rate_point = excluded.win_rate_point,
                 win_rate_ci_low = excluded.win_rate_ci_low,
                 win_rate_ci_high = excluded.win_rate_ci_high,
                 mc_pvalue = excluded.mc_pvalue,
                 wf_pass_count = excluded.wf_pass_count,
                 wf_total_windows = excluded.wf_total_windows,
                 last_computed_at = excluded.last_computed_at""",
            (
                row.skill, row.uses, row.trades_with_signal,
                row.wins, row.losses,
                row.win_rate_point, row.win_rate_ci_low, row.win_rate_ci_high,
                row.mc_pvalue, row.wf_pass_count, row.wf_total_windows,
                now_vn().isoformat(),
            ),
        )


def compute_and_persist_all(lookback_days: int = 180) -> list[SkillStatsRow]:
    """For every skill seen in recent decisions, compute + UPSERT stats.
    Returns list of computed rows. Safe to call multiple times — idempotent."""
    since_iso = (now_vn() - timedelta(days=lookback_days)).isoformat()
    skills = _distinct_skills_seen(since_iso)
    results: list[SkillStatsRow] = []
    # Deduplicate after resolution (two different decision forms may point
    # at the same skill file).
    seen_resolved: set[str] = set()
    for raw in skills:
        row = compute_skill_stats(raw, since_iso=since_iso)
        # Re-key under the resolved skill path so lifecycle FSM can find it
        resolved = _resolve_skill_name(raw)
        if resolved in seen_resolved:
            continue
        seen_resolved.add(resolved)
        row.skill = resolved
        _upsert(row)
        results.append(row)
        log.info(
            "skill_stats_computed",
            skill=resolved, uses=row.uses,
            wr=row.win_rate_point,
            ci_low=row.win_rate_ci_low,
            ci_high=row.win_rate_ci_high,
            wf=f"{row.wf_pass_count}/{row.wf_total_windows}"
                if row.wf_total_windows else None,
        )
    return results
