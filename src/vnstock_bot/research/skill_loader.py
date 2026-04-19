"""Skill file loader + v2 frontmatter parsing.

V1 skills have: name, when_to_use, inputs, outputs, version.
V2 adds: status (draft|shadow|active|archived), category, parent_skill, uses,
win_rate_* + CI fields (populated by learning/stats.py — never hand-edited).

Reader works on either format; writers always emit v2 frontmatter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

from vnstock_bot.config import get_settings

SkillStatus = Literal["draft", "shadow", "active", "archived"]
SkillCategory = Literal[
    "analysis", "strategy", "risk", "flow", "tool", "playbook"
]

_FRONTMATTER_RE = re.compile(
    r"^---\s*\n(?P<fm>.*?)\n---\s*\n(?P<body>.*)$", re.DOTALL
)


class SkillNotFound(Exception):
    pass


@dataclass
class SkillMeta:
    name: str
    path: Path
    body: str
    # Frontmatter fields (v1 + v2)
    version: int = 1
    when_to_use: str = ""
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    # v2 additions
    status: SkillStatus = "active"
    category: SkillCategory | None = None
    parent_skill: str | None = None
    uses: int = 0
    trades_with_signal: int = 0
    win_rate_20d: float | None = None
    win_rate_ci_95: tuple[float, float] | None = None
    walk_forward_stable: bool | None = None
    shadow_vs_parent: float | None = None
    raw_frontmatter: dict[str, Any] = field(default_factory=dict)


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm = yaml.safe_load(m.group("fm")) or {}
    if not isinstance(fm, dict):
        fm = {}
    return fm, m.group("body").lstrip("\n")


def _category_from_path(name: str) -> SkillCategory | None:
    # "analysis/foo" → "analysis"; "playbooks/bar" → "playbook"
    parts = name.split("/")
    if len(parts) < 2:
        return None
    head = parts[0]
    if head == "playbooks":
        return "playbook"
    if head in ("analysis", "strategy", "risk", "flow", "tool"):
        return head  # type: ignore[return-value]
    return None


@lru_cache(maxsize=64)
def read_skill(name: str) -> str:
    root = get_settings().skills_dir
    path = root / f"{name}.md"
    if not path.exists():
        raise SkillNotFound(f"skill not found: {name} (looked at {path})")
    return path.read_text(encoding="utf-8")


def read_skill_meta(name: str) -> SkillMeta:
    text = read_skill(name)
    fm, body = _parse_frontmatter(text)
    path = get_settings().skills_dir / f"{name}.md"

    ci_raw = fm.get("win_rate_ci_95")
    ci: tuple[float, float] | None = None
    if isinstance(ci_raw, (list, tuple)) and len(ci_raw) == 2:
        ci = (float(ci_raw[0]), float(ci_raw[1]))

    return SkillMeta(
        name=name,
        path=path,
        body=body,
        version=int(fm.get("version", 1) or 1),
        when_to_use=str(fm.get("when_to_use") or ""),
        inputs=list(fm.get("inputs") or []),
        outputs=list(fm.get("outputs") or []),
        status=fm.get("status", "active"),
        category=fm.get("category") or _category_from_path(name),
        parent_skill=fm.get("parent_skill"),
        uses=int(fm.get("uses", 0) or 0),
        trades_with_signal=int(fm.get("trades_with_signal", 0) or 0),
        win_rate_20d=fm.get("win_rate_20d"),
        win_rate_ci_95=ci,
        walk_forward_stable=fm.get("walk_forward_stable"),
        shadow_vs_parent=fm.get("shadow_vs_parent"),
        raw_frontmatter=fm,
    )


def read_index() -> str:
    root = get_settings().skills_dir
    idx = root / "README.md"
    return idx.read_text(encoding="utf-8") if idx.exists() else ""


def list_all_skills() -> list[str]:
    root: Path = get_settings().skills_dir
    out: list[str] = []
    for p in root.rglob("*.md"):
        if p.name == "README.md":
            continue
        rel = p.relative_to(root).with_suffix("")
        out.append(str(rel).replace("\\", "/"))
    return sorted(out)


def list_skills_by_status(status: SkillStatus = "active") -> list[SkillMeta]:
    return [
        m for m in (read_skill_meta(n) for n in list_all_skills())
        if m.status == status
    ]


def list_skills_by_category(category: SkillCategory) -> list[SkillMeta]:
    return [
        m for m in (read_skill_meta(n) for n in list_all_skills())
        if m.category == category
    ]


def write_skill(name: str, content: str) -> Path:
    """Weekly review entry point. Caller must git-commit afterwards."""
    root = get_settings().skills_dir
    path = root / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    read_skill.cache_clear()
    return path
