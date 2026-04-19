"""Extract 3-5 rules from profitable roundtrips (PLAN_V2 §5.2).

Algorithm:
  1. Filter to winners (pnl > 0).
  2. Group by (sector, hour_bucket, hold_days_bucket).
  3. Any cluster with support ≥ min_support → emit a ShadowRule.
  4. Rank clusters by support × (cluster_win_rate - global_win_rate), take top N.
  5. Render human_text ≤ 30 chars.

Hour buckets are coarse (5 slots) because Vietnamese equities only trade
morning + afternoon sessions — finer buckets produce noise.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from vnstock_bot.shadow.types import Roundtrip, ShadowRule

MIN_SUPPORT = 3
MAX_RULES = 5

# Hour buckets tuned to HSX session structure.
HOUR_BUCKETS: list[tuple[int, int, str]] = [
    (9, 10, "sáng sớm"),        # 9:00-10:00 ATO + early morning
    (10, 11, "sáng muộn"),      # 10:00-11:30 mid-morning
    (13, 14, "chiều sớm"),      # 13:00-14:00 afternoon start
    (14, 15, "chiều muộn"),     # 14:00-14:45 close + ATC
]

HOLD_BUCKETS: list[tuple[int, int, str]] = [
    (0, 1, "1 ngày"),
    (2, 5, "2-5 ngày"),
    (6, 10, "6-10 ngày"),
    (11, 30, "11-30 ngày"),
    (31, 999, "dài hạn"),
]


def _hour_bucket(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return "không rõ"
    h = dt.hour
    for lo, hi, label in HOUR_BUCKETS:
        if lo <= h < hi:
            return label
    return "ngoài phiên"


def _hold_bucket(days: int) -> tuple[str, int, int]:
    for lo, hi, label in HOLD_BUCKETS:
        if lo <= days <= hi:
            return label, lo, hi
    return "dài hạn", 31, 999


def _sector_label(sector: str | None) -> str:
    return sector or "đa ngành"


def _render_text(sector: str, hour: str, hold: str, max_len: int = 30) -> str:
    # Prefer short forms; strip when too long.
    parts = []
    if sector and sector != "đa ngành":
        parts.append(sector[:8])
    if hour and hour != "không rõ":
        parts.append(hour)
    if hold:
        parts.append(hold)
    text = ", ".join(parts)
    if not text:
        return "(chưa rõ pattern)"
    if len(text) <= max_len:
        return text
    # Truncate gracefully
    return text[: max_len - 1] + "…"


def extract(
    roundtrips: list[Roundtrip],
    min_support: int = MIN_SUPPORT,
    max_rules: int = MAX_RULES,
) -> list[ShadowRule]:
    if not roundtrips:
        return []

    winners = [r for r in roundtrips if r.is_winner]
    all_n = len(roundtrips)
    win_n = len(winners)
    if win_n == 0:
        return []

    global_win_rate = win_n / all_n

    # Group by (sector, hour_bucket, hold_bucket). Key tracks bucket metadata.
    groups: dict[tuple[str, str, str], list[Roundtrip]] = defaultdict(list)
    winner_groups: dict[tuple[str, str, str], list[Roundtrip]] = defaultdict(list)
    for r in roundtrips:
        sector = _sector_label(r.sector)
        hour = _hour_bucket(r.buy_at)
        hold_label, _, _ = _hold_bucket(r.hold_days)
        key = (sector, hour, hold_label)
        groups[key].append(r)
        if r.is_winner:
            winner_groups[key].append(r)

    # Build candidates from clusters with enough winner support
    candidates: list[ShadowRule] = []
    for key, group_winners in winner_groups.items():
        if len(group_winners) < min_support:
            continue
        sector, hour, hold_label = key
        cluster_all = groups[key]
        cluster_win_rate = len(group_winners) / len(cluster_all) if cluster_all else 0.0
        lift = cluster_win_rate - global_win_rate
        # Drop clusters that perform WORSE than the user's global baseline
        # (those aren't patterns worth emulating). Equal-to-baseline clusters
        # are kept when support is high — the pattern is at least consistent.
        if lift < 0:
            continue

        # Resolve actual hold range from the winners in this cluster
        hold_days = [w.hold_days for w in group_winners]
        hold_min = max(0, min(hold_days))
        hold_max = max(hold_days)

        rule_id = f"rule-{len(candidates)+1}"
        human = _render_text(sector, hour, hold_label)

        # Score: support × (1 + lift). Adding 1 keeps equal-lift clusters
        # ranked by raw support count (patterns with 10 winners beat 3
        # winners even when both are at the global baseline).
        score = len(group_winners) * (1.0 + lift)

        candidates.append(ShadowRule(
            rule_id=rule_id,
            human_text=human,
            support_count=len(group_winners),
            coverage_rate=len(group_winners) / win_n,
            sector=sector,
            hour_bucket=hour,
            holding_min=hold_min,
            holding_max=hold_max,
            win_rate=cluster_win_rate,
            metadata={
                "lift": lift,
                "cluster_size": len(cluster_all),
                "score": score,
            },
        ))

    # Rank by score (support × (1+lift)), take top max_rules
    candidates.sort(
        key=lambda r: float(r.metadata.get("score", 0)),
        reverse=True,
    )
    return candidates[:max_rules]


def new_shadow_id() -> str:
    return f"shadow_{uuid.uuid4().hex[:12]}"
