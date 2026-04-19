"""Deterministic skill proposer: pattern → draft skill markdown.

W4 scope: read `patterns` table (L4 memory), group by confidence, emit
0-N SkillDraft objects. Creating the actual file is an explicit step
(`materialize_draft`) so the weekly review can preview first.

The LLM-driven proposer (where Claude reads decision outcomes + suggests
net-new skills from scratch) lives in `research/weekly_review.py` and is
out of scope for W4 — this module is the deterministic floor.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

import yaml

from vnstock_bot.config import get_settings
from vnstock_bot.data.holidays import now_vn
from vnstock_bot.db.connection import get_connection
from vnstock_bot.research.skill_loader import list_all_skills

# minimum signal strength before a pattern is worth materializing as a skill
MIN_SUPPORT = 3
MAX_DRAFTS_PER_WEEK = 2


@dataclass
class SkillDraft:
    name: str                        # "strategy/volume-surge-v1"
    category: str                    # "strategy" | "analysis" | ...
    body_markdown: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    source_pattern_ids: list[int] = field(default_factory=list)


_NAME_SAFE = re.compile(r"[^a-z0-9-]+")


def _sanitize_name(candidate: str) -> str:
    base = _NAME_SAFE.sub("-", candidate.lower().strip()).strip("-")
    return base[:48] or "untitled"


def _load_candidate_patterns(days: int = 30) -> list[dict[str, Any]]:
    since = (now_vn() - timedelta(days=days)).isoformat()
    rows = get_connection().execute(
        """SELECT id, body, support_count, confirmed, last_seen_at, metadata_json
           FROM patterns
           WHERE last_seen_at >= ? AND support_count >= ? AND confirmed = 0
           ORDER BY support_count DESC, last_seen_at DESC
           LIMIT 20""",
        (since, MIN_SUPPORT),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            meta = json.loads(r["metadata_json"] or "{}")
        except (ValueError, TypeError):
            meta = {}
        out.append({
            "id": int(r["id"]),
            "body": r["body"],
            "support_count": int(r["support_count"]),
            "metadata": meta,
        })
    return out


def _render_draft_body(pattern: dict[str, Any]) -> str:
    body_text = pattern["body"]
    support = pattern["support_count"]
    meta = pattern.get("metadata") or {}
    md_metadata = "\n".join(f"- {k}: {v}" for k, v in meta.items()) or "- (none)"
    return f"""## Mục tiêu

Skill được đề xuất tự động từ observed pattern L4 memory (support ≥ {MIN_SUPPORT}).

**Pattern gốc:** {body_text}

## Rules (cần human confirm trước khi promote)

1. {body_text}
2. Phải confirm thêm bằng ≥ 1 skill active khác (technical-trend, momentum, hoặc
   catalyst-check) trước khi entry.

## Evidence required

- Số phiên/trade liên quan (support count: {support})
- Setup cụ thể matching pattern

## Metadata gốc

{md_metadata}

## Trạng thái

Đây là **draft** được sinh tự động. Không được dùng trong live decision. Cần
chuyển sang shadow (via `/skill promote <name>`) để gather stats, rồi mới active.
"""


def _build_draft(pattern: dict[str, Any], idx: int) -> SkillDraft:
    hint = pattern.get("metadata", {}).get("hint") or pattern["body"].split(".")[0]
    safe = _sanitize_name(hint)
    name = f"strategy/{safe}-draft-{idx}"

    frontmatter = {
        "name": safe + f"-draft-{idx}",
        "version": 1,
        "status": "draft",
        "category": "strategy",
        "when_to_use": pattern["body"][:200],
        "inputs": ["ohlc_60d"],
        "outputs": ["signal"],
        "parent_skill": None,
        "uses": 0,
        "trades_with_signal": 0,
        "win_rate_20d": None,
        "win_rate_ci_95": None,
        "walk_forward_stable": None,
        "shadow_vs_parent": None,
    }
    body = _render_draft_body(pattern)
    return SkillDraft(
        name=name,
        category="strategy",
        body_markdown=body,
        frontmatter=frontmatter,
        source_pattern_ids=[pattern["id"]],
    )


def propose(days: int = 30, max_drafts: int = MAX_DRAFTS_PER_WEEK) -> list[SkillDraft]:
    """Return up to `max_drafts` new skill drafts. Does NOT write files —
    caller (weekly_review) decides what to materialize."""
    existing = set(list_all_skills())
    patterns = _load_candidate_patterns(days=days)
    drafts: list[SkillDraft] = []
    for idx, p in enumerate(patterns, start=1):
        d = _build_draft(p, idx)
        if d.name in existing:
            continue
        drafts.append(d)
        if len(drafts) >= max_drafts:
            break
    return drafts


def materialize_draft(draft: SkillDraft) -> Path:
    """Write the draft to skills/<category>/<name>.md. Returns written path.
    Caller should git-add + commit afterwards.
    """
    root = get_settings().skills_dir
    path = root / f"{draft.name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    fm_yaml = yaml.safe_dump(draft.frontmatter, allow_unicode=True, sort_keys=False).strip()
    path.write_text(f"---\n{fm_yaml}\n---\n\n{draft.body_markdown}\n",
                    encoding="utf-8")
    return path
