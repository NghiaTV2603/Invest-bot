"""L4 pattern extraction — scan recent decision outcomes, emit `patterns`
rows that `skill_proposer` then reads to suggest new skills.

Runs inside weekly_review_job. Conservative: only surfaces "at least 3
winners" clusters so we don't flood L4 with noise. TTL-expired rows
(>90d old, confirmed=0) are auto-deleted at the start of each run.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from vnstock_bot.data.holidays import now_vn
from vnstock_bot.db.connection import get_connection, transaction
from vnstock_bot.logging_setup import get_logger

log = get_logger(__name__)

MIN_SUPPORT = 3
LOOKBACK_DAYS = 90
TTL_DAYS = 90


@dataclass
class PatternCandidate:
    body: str
    support_count: int
    metadata: dict[str, Any]


# ---------------------------------------------------------------- extract

def _fetch_winning_decisions(since_iso: str) -> list[dict]:
    rows = get_connection().execute(
        """SELECT d.id, d.created_at, d.ticker, d.action, d.conviction,
                  d.skills_used_json, d.playbook,
                  (SELECT pnl_pct FROM decision_outcomes
                     WHERE decision_id = d.id
                     ORDER BY days_held DESC LIMIT 1) AS pnl_pct
           FROM decisions d
           WHERE d.created_at >= ? AND d.status IN ('filled','pending')
                 AND d.action IN ('BUY','ADD')
           ORDER BY d.created_at""",
        (since_iso,),
    ).fetchall()
    out = []
    for r in rows:
        if r["pnl_pct"] is None or float(r["pnl_pct"]) <= 0:
            continue
        try:
            skills = json.loads(r["skills_used_json"] or "[]")
        except (ValueError, TypeError):
            skills = []
        out.append({
            "id": int(r["id"]),
            "ticker": r["ticker"],
            "action": r["action"],
            "conviction": int(r["conviction"]),
            "skills": list(skills),
            "playbook": r["playbook"],
            "pnl_pct": float(r["pnl_pct"]),
        })
    return out


def _extract_candidates(winners: list[dict]) -> list[PatternCandidate]:
    """Group winners by (skill_combo, playbook, conviction_bucket). Clusters
    with ≥ MIN_SUPPORT emit a pattern candidate."""
    if not winners:
        return []

    def _conv_bucket(c: int) -> str:
        return "high (4-5)" if c >= 4 else ("medium (3)" if c == 3 else "low (1-2)")

    def _skill_key(skills: list[str]) -> str:
        return "+".join(sorted(s.split("/")[-1] for s in skills[:3]))

    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for w in winners:
        key = (_skill_key(w["skills"]), w["playbook"] or "—",
               _conv_bucket(w["conviction"]))
        groups[key].append(w)

    candidates: list[PatternCandidate] = []
    for (skill_combo, playbook, conv_b), cluster in groups.items():
        if len(cluster) < MIN_SUPPORT:
            continue
        avg_pnl = sum(w["pnl_pct"] for w in cluster) / len(cluster)
        body = (
            f"Winning pattern: skills={skill_combo} · playbook={playbook} · "
            f"conviction={conv_b} · avg_pnl={avg_pnl:.1%} · "
            f"n={len(cluster)}"
        )
        candidates.append(PatternCandidate(
            body=body,
            support_count=len(cluster),
            metadata={
                "skill_combo": skill_combo,
                "playbook": playbook,
                "conviction_bucket": conv_b,
                "avg_pnl_pct": avg_pnl,
                "decision_ids": [w["id"] for w in cluster],
                "hint": skill_combo.replace("+", "-"),
            },
        ))
    return candidates


# ---------------------------------------------------------------- persist

def _delete_stale() -> int:
    cutoff = (now_vn() - timedelta(days=TTL_DAYS)).isoformat()
    with transaction() as conn:
        cur = conn.execute(
            "DELETE FROM patterns WHERE confirmed = 0 AND last_seen_at < ?",
            (cutoff,),
        )
        return cur.rowcount or 0


def _upsert(candidate: PatternCandidate) -> None:
    """Pattern is keyed by body text (cheap dedup). If the same body appears
    again, bump support_count + last_seen_at instead of duplicating."""
    now = now_vn().isoformat()
    with transaction() as conn:
        existing = conn.execute(
            "SELECT id, support_count FROM patterns WHERE body = ? AND confirmed = 0",
            (candidate.body,),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE patterns SET support_count = ?, last_seen_at = ?,
                       metadata_json = ?
                   WHERE id = ?""",
                (max(existing["support_count"], candidate.support_count),
                 now,
                 json.dumps(candidate.metadata, ensure_ascii=False, default=str),
                 existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO patterns
                    (created_at, body, support_count, confirmed,
                     last_seen_at, metadata_json)
                   VALUES (?, ?, ?, 0, ?, ?)""",
                (now, candidate.body, candidate.support_count, now,
                 json.dumps(candidate.metadata, ensure_ascii=False, default=str)),
            )


def extract_and_persist(lookback_days: int = LOOKBACK_DAYS) -> dict[str, int]:
    """Top-level — called by weekly_review_job. Returns
    {'expired': N, 'new_or_updated': M}."""
    expired = _delete_stale()
    since_iso = (now_vn() - timedelta(days=lookback_days)).isoformat()
    winners = _fetch_winning_decisions(since_iso)
    candidates = _extract_candidates(winners)
    for c in candidates:
        _upsert(c)
    log.info("patterns_extracted",
             winners=len(winners), candidates=len(candidates),
             expired=expired)
    return {"expired": expired, "new_or_updated": len(candidates),
            "winners_scanned": len(winners)}
