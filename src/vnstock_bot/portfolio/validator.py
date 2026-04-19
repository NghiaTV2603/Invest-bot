"""Validator chain for Claude's proposed decisions. Rejected → not persisted."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from vnstock_bot.data.watchlist import load_watchlist
from vnstock_bot.db import queries
from vnstock_bot.logging_setup import get_logger
from vnstock_bot.portfolio.simulator import LOT_SIZE, load_portfolio
from vnstock_bot.portfolio.types import DecisionInput

log = get_logger(__name__)


# Biên độ sàn (phiên thường)
PRICE_BAND = {
    "HSX": 0.07,
    "HNX": 0.10,
    "UPCOM": 0.15,
}


@dataclass
class ValidationOutcome:
    ok: bool
    errors: list[str]
    decision: DecisionInput | None


def _last_close(ticker: str) -> int | None:
    rows = queries.get_ohlc(ticker, days=5)
    if not rows:
        return None
    return int(rows[-1]["close"])


def validate(raw: dict) -> ValidationOutcome:
    """Run validation chain. Returns ValidationOutcome with normalized decision."""
    errors: list[str] = []

    # 1. Schema
    try:
        d = DecisionInput.model_validate(raw)
    except ValidationError as e:
        return ValidationOutcome(False, [f"schema: {e.errors()[0]['msg']}"], None)

    # 2. Ticker in watchlist
    wl = load_watchlist()
    if not wl.has(d.ticker):
        errors.append(f"ticker {d.ticker} not in watchlist")
        return ValidationOutcome(False, errors, d)

    # 3. HOLD short-circuit
    if d.action == "HOLD":
        return ValidationOutcome(True, [], d)

    # 4. Qty multiple of LOT_SIZE
    if d.qty % LOT_SIZE != 0:
        errors.append(f"qty {d.qty} not multiple of {LOT_SIZE}")
    if d.qty <= 0:
        errors.append("qty must be > 0 for non-HOLD")

    # 5. Price band check
    exchange = wl.exchange_of(d.ticker) or "HSX"
    band = PRICE_BAND.get(exchange, 0.07)
    last_close = _last_close(d.ticker)
    if last_close and last_close > 0:
        lo = int(last_close * (1 - band))
        hi = int(last_close * (1 + band))
        if d.target_price is not None and not (lo <= d.target_price <= hi * 4):
            # target may be longer-horizon — don't enforce band hard here, only sanity (≤ 4x)
            errors.append(f"target_price {d.target_price} out of sanity range")
        if d.stop_loss is not None:
            # stop should be within 20% of last_close (otherwise nonsensical)
            diff_pct = abs(d.stop_loss - last_close) / last_close
            if diff_pct > 0.25:
                errors.append(f"stop_loss {d.stop_loss} too far from close {last_close} ({diff_pct:.1%})")

    # 6. Portfolio feasibility
    portfolio = load_portfolio()
    holding = portfolio.holding_of(d.ticker)
    nav_snapshot = portfolio.total({h.ticker: h.avg_cost for h in portfolio.holdings}) or 1

    if d.action == "BUY":
        if holding is not None:
            errors.append(f"BUY not allowed: {d.ticker} already held (use ADD)")
        if last_close:
            cost = last_close * d.qty
            if cost > portfolio.cash * 0.95:
                errors.append("BUY exceeds 95% of cash (needs buffer)")
            if cost > nav_snapshot * 0.20:
                errors.append(f"BUY > 20% NAV: {cost}/{nav_snapshot}")
    elif d.action == "ADD":
        if holding is None:
            errors.append(f"ADD not allowed: no existing position on {d.ticker}")
        elif last_close:
            new_notional = last_close * (holding.qty_total + d.qty)
            if new_notional > nav_snapshot * 0.20:
                errors.append(f"ADD makes position > 20% NAV")
    elif d.action in ("TRIM", "SELL"):
        if holding is None:
            errors.append(f"{d.action} not allowed: no position on {d.ticker}")
        else:
            if d.qty > holding.qty_available:
                errors.append(
                    f"{d.action} qty {d.qty} > qty_available {holding.qty_available} (T+2 locked)"
                )

    # 7. Required skill/playbook per action
    if d.action in ("BUY", "ADD") and d.playbook_used != "new-entry":
        errors.append("BUY/ADD requires playbook_used='new-entry'")
    if d.action in ("TRIM", "SELL") and d.playbook_used != "cut-loser":
        # relax: allow TRIM without cut-loser if it's a target-hit trim
        if d.action == "SELL":
            errors.append("SELL requires playbook_used='cut-loser'")
    if not d.skills_used:
        errors.append("skills_used must be non-empty")
    if len(d.evidence) < 3:
        errors.append(f"evidence has only {len(d.evidence)} bullets, need ≥ 3")
    if not d.invalidation.strip():
        errors.append("invalidation must be specified")

    if errors:
        return ValidationOutcome(False, errors, d)
    return ValidationOutcome(True, [], d)


def validate_batch(raws: list[dict]) -> tuple[list[DecisionInput], list[dict]]:
    """Returns (accepted, rejections[])."""
    accepted: list[DecisionInput] = []
    rejections: list[dict] = []
    for raw in raws:
        outcome = validate(raw)
        if outcome.ok and outcome.decision is not None:
            accepted.append(outcome.decision)
        else:
            rejections.append({
                "raw": raw,
                "errors": outcome.errors,
                "ticker": (outcome.decision.ticker if outcome.decision else raw.get("ticker", "?")),
            })
    return accepted, rejections
