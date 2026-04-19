"""5-component PnL attribution (PLAN_V2 §5.3).

Classifies each real roundtrip against the extracted rules, then computes
how much PnL came from each of 5 reasons. Sum of components + shadow_pnl
should reconcile with real_pnl (within rounding).

Simplified model for W5 (no OHLC access for full path simulation):
- `noise_trades_pnl`: trades matching NO rule (emotion trades)
- `early_exit_pnl`: winner hold < rule.holding_min → counterfactual
  uplift assuming hold extended would have captured rule avg extra return
- `late_exit_pnl`: loser hold > rule.holding_max → counterfactual savings
  assuming cut at rule.holding_max would have capped the loss
- `overtrading_pnl`: trades beyond the day's most recent rule-conforming
  trade (1 rule-conforming trade/day baseline)
- `missed_signals_pnl`: residual = shadow_pnl − (rule-conforming real PnL)

Full backtest with OHLC + strict rule replay is deferred (requires
historical price access for every shadow-day, not just trade days).
"""

from __future__ import annotations

from collections import defaultdict

from vnstock_bot.shadow.types import (
    DeltaComponents,
    Roundtrip,
    ShadowBacktestResult,
    ShadowRule,
)


def _matches_setup(rt: Roundtrip, rule: ShadowRule) -> bool:
    """Sector + hour only — 'this trade is the kind of setup the rule
    addresses'. Hold-range mismatch becomes early/late exit, NOT noise."""
    from vnstock_bot.shadow.rule_extractor import _hour_bucket
    if (rule.sector and rule.sector != "đa ngành"
            and (rt.sector or "đa ngành") != rule.sector):
        return False
    return not (
        rule.hour_bucket
        and rule.hour_bucket not in ("không rõ", "ngoài phiên")
        and _hour_bucket(rt.buy_at) != rule.hour_bucket
    )


def _matches_full(rt: Roundtrip, rule: ShadowRule) -> bool:
    if not _matches_setup(rt, rule):
        return False
    return not (
        rule.holding_min is not None and rule.holding_max is not None
        and not (rule.holding_min <= rt.hold_days <= rule.holding_max)
    )


def _match_any(rt: Roundtrip, rules: list[ShadowRule]) -> ShadowRule | None:
    """Return first rule whose SETUP matches (sector + hour). Hold mismatch
    is handled as early/late exit attribution, not as noise."""
    for r in rules:
        if _matches_setup(rt, r):
            return r
    return None


def _late_exit_savings(rt: Roundtrip, rule: ShadowRule) -> int:
    """If rt is a loser and held past rule.holding_max, estimate savings
    from cutting at rule.holding_max. We don't have intermediate prices,
    so fall back to proportional attribution: assume linear loss accrual."""
    if rt.pnl >= 0:
        return 0
    if rule.holding_max <= 0 or rt.hold_days <= rule.holding_max:
        return 0
    # Fraction of the hold that was over-budget
    overshoot_ratio = (rt.hold_days - rule.holding_max) / rt.hold_days
    # Attribute that fraction of the loss as "amplified by holding too long"
    return int(-rt.pnl * overshoot_ratio)   # positive number = dollars saved


def _early_exit_cost(rt: Roundtrip, rule: ShadowRule) -> int:
    """If rt is a winner and held less than rule.holding_min, estimate the
    opportunity cost. Proportional: early_exit_ratio × actual_win."""
    if rt.pnl <= 0:
        return 0
    if rule.holding_min <= 0 or rt.hold_days >= rule.holding_min:
        return 0
    shortfall_ratio = (rule.holding_min - rt.hold_days) / rule.holding_min
    # Opportunity cost = win could have been X% larger
    return int(rt.pnl * shortfall_ratio)   # positive = dollars left on table


def _overtrading_overhead(
    rt: Roundtrip, same_day_count: int
) -> int:
    """If user made ≥ 3 trades on the same entry day, flag the 3rd+ as
    overtrading. Return absolute PnL (positive or negative) of that slice
    for attribution (sign preserved: overtrading losses attributed, gains
    attributed as "unnecessary wins")."""
    if same_day_count < 3:
        return 0
    return rt.pnl


def compute(
    roundtrips: list[Roundtrip],
    rules: list[ShadowRule],
) -> ShadowBacktestResult:
    real_pnl = sum(r.pnl for r in roundtrips)

    components = DeltaComponents()
    rule_conforming_pnl = 0

    # Same-day grouping for overtrading detection (by buy_at date)
    per_day: dict[str, list[Roundtrip]] = defaultdict(list)
    for rt in roundtrips:
        day = rt.buy_at.split("T")[0] if "T" in rt.buy_at else rt.buy_at[:10]
        per_day[day].append(rt)
    day_order: dict[str, dict[str, int]] = {}
    for day, trs in per_day.items():
        day_order[day] = {id(tr): i + 1 for i, tr in enumerate(
            sorted(trs, key=lambda t: t.buy_at)
        )}

    counterfactuals: list[dict[str, object]] = []

    for rt in roundtrips:
        matched = _match_any(rt, rules)
        day = rt.buy_at.split("T")[0] if "T" in rt.buy_at else rt.buy_at[:10]
        same_day_count = day_order[day][id(rt)]
        overtrade_pnl = _overtrading_overhead(rt, same_day_count)

        if overtrade_pnl != 0:
            components.overtrading_pnl += overtrade_pnl
            # Overtrading exclusion — don't count this roundtrip in other buckets
            continue

        if matched is None:
            # No rule matches → noise trade. Attribute full PnL to noise.
            components.noise_trades_pnl += rt.pnl
            if abs(rt.pnl) >= 500_000:
                counterfactuals.append({
                    "ticker": rt.ticker,
                    "buy_at": rt.buy_at,
                    "sell_at": rt.sell_at,
                    "pnl": rt.pnl,
                    "type": "noise_trade",
                    "advice": "would NOT have taken this trade",
                })
            continue

        # Rule-conforming trade
        rule_conforming_pnl += rt.pnl

        early = _early_exit_cost(rt, matched)
        late = _late_exit_savings(rt, matched)
        if early > 0:
            components.early_exit_pnl += early
            counterfactuals.append({
                "ticker": rt.ticker,
                "buy_at": rt.buy_at,
                "sell_at": rt.sell_at,
                "pnl": rt.pnl,
                "type": "early_exit",
                "missed_vnd": early,
                "advice": f"could have held to rule min ({matched.holding_min} days)",
                "rule": matched.human_text,
            })
        if late > 0:
            components.late_exit_pnl += late
            counterfactuals.append({
                "ticker": rt.ticker,
                "buy_at": rt.buy_at,
                "sell_at": rt.sell_at,
                "pnl": rt.pnl,
                "type": "late_exit",
                "saved_vnd": late,
                "advice": f"should have cut at rule max ({matched.holding_max} days)",
                "rule": matched.human_text,
            })

    # Shadow PnL model: user keeps rule-conforming trades, PLUS recovers
    # `early_exit_pnl` (winners held longer) AND `late_exit_pnl` (losers cut),
    # MINUS noise + overtrade trades (user wouldn't have taken them).
    shadow_pnl = (
        rule_conforming_pnl
        + components.early_exit_pnl
        + components.late_exit_pnl
    )
    delta = shadow_pnl - real_pnl

    # Missed signals = residual that doesn't fit other buckets
    accounted = (
        components.noise_trades_pnl
        + components.overtrading_pnl
        + components.early_exit_pnl
        + components.late_exit_pnl
    )
    # residual such that accounted + shadow_pnl = real + delta; by construction
    # this is 0 up to same-day-exclusion quirks. Keep 0 for now.
    components.missed_signals_pnl = real_pnl - rule_conforming_pnl - accounted + (
        components.early_exit_pnl + components.late_exit_pnl
    )

    # Per-sector comparison
    per_sector: dict[str, dict[str, int]] = defaultdict(
        lambda: {"count": 0, "real_pnl": 0, "rule_conforming_pnl": 0}
    )
    for rt in roundtrips:
        sec = rt.sector or "đa ngành"
        per_sector[sec]["count"] += 1
        per_sector[sec]["real_pnl"] += rt.pnl
        if _match_any(rt, rules):
            per_sector[sec]["rule_conforming_pnl"] += rt.pnl

    # Rank counterfactuals: biggest missed_vnd first, then biggest noise loss
    def _sort_key(c: dict[str, object]) -> int:
        if c["type"] == "early_exit":
            return -int(c.get("missed_vnd", 0) or 0)
        if c["type"] == "late_exit":
            return -int(c.get("saved_vnd", 0) or 0)
        return -abs(int(c.get("pnl", 0) or 0))
    counterfactuals.sort(key=_sort_key)

    # Equity curves (cumulative PnL over trade sequence)
    real_eq: list[tuple[str, int]] = []
    shadow_eq: list[tuple[str, int]] = []
    cum_real, cum_shadow = 0, 0
    for rt in sorted(roundtrips, key=lambda t: t.sell_at):
        cum_real += rt.pnl
        real_eq.append((rt.sell_at, cum_real))
        if _match_any(rt, rules):
            cum_shadow += rt.pnl
        shadow_eq.append((rt.sell_at, cum_shadow))
    # Bake in early/late "uplift" at the end so final equity equals shadow_pnl
    if shadow_eq:
        uplift = shadow_pnl - cum_shadow
        if uplift != 0:
            shadow_eq[-1] = (shadow_eq[-1][0], shadow_eq[-1][1] + uplift)

    return ShadowBacktestResult(
        shadow_id="",                  # filled by caller
        real_pnl=int(real_pnl),
        shadow_pnl=int(shadow_pnl),
        delta_pnl=int(delta),
        components=components,
        real_equity=real_eq,
        shadow_equity=shadow_eq,
        counterfactuals=counterfactuals[:5],
        per_sector=dict(per_sector),
    )


