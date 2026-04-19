import pytest

from vnstock_bot.research.skill_loader import (
    SkillNotFound,
    list_all_skills,
    list_skills_by_category,
    list_skills_by_status,
    read_skill,
    read_skill_meta,
)


def test_list_all_skills_contains_v1_and_v2():
    skills = list_all_skills()
    # v1 holdovers
    assert "analysis/top-down-macro" in skills
    assert "risk/position-sizing" in skills
    assert "playbooks/new-entry" in skills
    # v2 new categories
    assert "strategy/candlestick" in skills
    assert "strategy/smc" in skills
    assert "strategy/ichimoku" in skills
    assert "flow/foreign-flow" in skills
    assert "flow/liquidity-check" in skills
    assert "tool/backtest-diagnose" in skills
    assert "tool/pine-script" in skills
    assert "analysis/sector-rotation" in skills
    assert "analysis/factor-research" in skills
    assert "analysis/multi-factor" in skills
    assert "analysis/valuation-model" in skills
    assert "risk/drawdown-budget" in skills
    assert "risk/regime-filter" in skills


def test_read_skill_returns_frontmatter():
    content = read_skill("analysis/technical-trend")
    assert content.startswith("---")
    assert "name: technical-trend" in content


def test_read_skill_missing():
    with pytest.raises(SkillNotFound):
        read_skill("nope/missing")


def test_skill_meta_parses_v2_frontmatter():
    meta = read_skill_meta("strategy/candlestick")
    assert meta.name == "strategy/candlestick"  # lookup key, not FM name
    assert meta.raw_frontmatter["name"] == "candlestick"
    assert meta.version == 1
    assert meta.status == "active"
    assert meta.category == "strategy"
    assert meta.parent_skill is None
    assert meta.uses == 0
    assert meta.body.startswith("## Mục tiêu")


def test_skill_meta_falls_back_to_path_category():
    # playbooks/ folder → category "playbook"
    meta = read_skill_meta("playbooks/new-entry")
    assert meta.category == "playbook"


def test_list_skills_by_status_active_counts():
    actives = list_skills_by_status("active")
    # We expect at least 20 active skills in v2
    assert len(actives) >= 20


def test_list_skills_by_category_strategy():
    strategy_skills = list_skills_by_category("strategy")
    names = {s.name for s in strategy_skills}
    assert "strategy/candlestick" in names
    assert "strategy/ichimoku" in names
    assert "strategy/smc" in names
    assert "strategy/momentum" in names
    assert "strategy/breakout" in names
    assert "strategy/mean-reversion" in names


def test_every_skill_has_v2_frontmatter_fields():
    """Every skill file must carry the v2 frontmatter fields so learning/
    stats.py can write CI numbers back without guessing."""
    required = {"name", "version", "status", "category"}
    for name in list_all_skills():
        meta = read_skill_meta(name)
        missing = required - set(meta.raw_frontmatter)
        assert not missing, f"{name} missing v2 fields: {missing}"
