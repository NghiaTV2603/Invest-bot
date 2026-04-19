from __future__ import annotations

import subprocess
from pathlib import Path

from vnstock_bot.config import get_settings
from vnstock_bot.data.holidays import iso, today_vn
from vnstock_bot.db import queries
from vnstock_bot.learning.scorer import score_all
from vnstock_bot.learning.skill_scorer import summarize, top_bottom
from vnstock_bot.logging_setup import get_logger
from vnstock_bot.research.agent import weekly_review
from vnstock_bot.research.skill_loader import write_skill as write_skill_file

log = get_logger(__name__)

MAX_SKILL_EDITS_PER_WEEK = 2


def _recent_decisions_summary(days: int = 7) -> str:
    rows = queries.get_decisions_recent(days)
    lines = [f"# Decisions {days}d ({len(rows)} rows)"]
    for r in rows[:50]:
        lines.append(
            f"- d#{r['id']} {r['created_at'][:10]} {r['action']} {r['ticker']} qty={r['qty']} "
            f"conv={r['conviction']} status={r['status']} skills={r['skills_used_json']}"
        )
    return "\n".join(lines)


def _outcomes_summary() -> str:
    rows = summarize()
    lines = ["# Skill scores"]
    for r in rows:
        lines.append(
            f"- {r['skill']}: uses={r['uses']} wr5d={r['win_rate_5d']:.2f} "
            f"wr20d={r['win_rate_20d']:.2f}"
        )
    return "\n".join(lines)


def _equity_summary(days: int = 7) -> str:
    rows = queries.get_equity_recent(days)
    if not rows:
        return "# Equity: no data"
    first = rows[0]["total"]
    last = rows[-1]["total"]
    return f"# Equity: {first} → {last} ({(last-first)/first*100:+.2f}%)"


def _git_commit(repo: Path, message: str) -> None:
    try:
        subprocess.run(["git", "add", "skills/", "strategy.md"], cwd=repo, check=False)
        r = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo, capture_output=True, text=True,
        )
        if r.returncode != 0:
            log.info("git_commit_skip", stdout=r.stdout[:200], stderr=r.stderr[:200])
    except FileNotFoundError:
        log.warning("git_not_found")


async def run_weekly_review() -> dict:
    """Run the weekly review job. Returns summary dict for Telegram."""
    settings = get_settings()
    today = today_vn()

    score_stats = score_all(today)
    log.info("weekly_review_start", **score_stats)

    context = "\n\n".join([
        _recent_decisions_summary(7),
        _outcomes_summary(),
        _equity_summary(7),
    ])

    result, strategy_notes, skill_writes = await weekly_review(context)

    # Apply buffered writes
    applied_notes = 0
    applied_skills = 0

    if strategy_notes:
        existing = settings.strategy_path.read_text(encoding="utf-8") if settings.strategy_path.exists() else ""
        today_iso = iso(today)
        new_section = f"\n\n### {today_iso}\n" + "\n".join(f"- {n}" for n in strategy_notes)
        settings.strategy_path.write_text(existing + new_section, encoding="utf-8")
        applied_notes = len(strategy_notes)

    # enforce MAX_SKILL_EDITS_PER_WEEK
    for name, content in skill_writes[:MAX_SKILL_EDITS_PER_WEEK]:
        write_skill_file(name, content)
        applied_skills += 1
    if len(skill_writes) > MAX_SKILL_EDITS_PER_WEEK:
        log.warning("skill_edits_capped", attempted=len(skill_writes), applied=applied_skills)

    # git commit
    repo_root = settings.strategy_path.parent
    _git_commit(repo_root, f"weekly review {iso(today)}: +{applied_notes} notes, {applied_skills} skill edits")

    top, bottom = top_bottom(3)
    return {
        "scored": score_stats,
        "strategy_notes_applied": applied_notes,
        "skill_edits_applied": applied_skills,
        "top_skills": top,
        "bottom_skills": bottom,
        "tokens": result.tokens_used,
    }
