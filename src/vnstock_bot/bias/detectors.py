"""7 bias detectors — formulas per PLAN_V2.md §5.4 (user/shadow) + §5.4bis (bot).

Each detector takes a sequence of TradeLike / DecisionLike and returns one
BiasResult. Detectors are pure: no I/O, no DB, no randomness. Thresholds
match Vibe-Trading's empirical calibration.

All detectors return severity="low" with metric=0 + sample_size=0 when input
is empty/insufficient so callers can render a grid row without special-casing.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from vnstock_bot.bias.types import (
    BiasName,
    BiasResult,
    BiasSeverity,
    DecisionLike,
    TradeLike,
)


def _severity_for(
    metric: float,
    threshold_medium: float,
    threshold_high: float,
    direction: str = "up",   # "up" = higher is worse; "down" = lower is worse
) -> BiasSeverity:
    if direction == "up":
        if metric >= threshold_high:
            return "high"
        if metric >= threshold_medium:
            return "medium"
        return "low"
    # direction == "down"
    if metric <= threshold_high:
        return "high"
    if metric <= threshold_medium:
        return "medium"
    return "low"


# ------------------------------------------------------------ 1. Disposition

def disposition_effect(trades: list[TradeLike]) -> BiasResult:
    """Hold losers longer than winners. Formula:
        ratio = avg_loser_hold_days / avg_winner_hold_days
    Thresholds: medium ≥ 1.2, high ≥ 1.5 (Vibe-Trading calibration).
    """
    closed = [t for t in trades if t.side == "SELL"
              and t.pnl is not None and t.hold_days is not None]
    winners = [t for t in closed if (t.pnl or 0) > 0]
    losers = [t for t in closed if (t.pnl or 0) < 0]
    n = len(closed)

    if not winners or not losers:
        return BiasResult(
            name="disposition_effect", severity="low",
            metric=0.0, threshold_medium=1.2, threshold_high=1.5,
            evidence=f"insufficient data (winners={len(winners)}, losers={len(losers)})",
            sample_size=n,
        )

    avg_w = sum(t.hold_days or 0 for t in winners) / len(winners)
    avg_l = sum(t.hold_days or 0 for t in losers) / len(losers)
    ratio = avg_l / avg_w if avg_w > 0 else 0.0

    severity = _severity_for(ratio, 1.2, 1.5)
    return BiasResult(
        name="disposition_effect", severity=severity,
        metric=round(ratio, 3), threshold_medium=1.2, threshold_high=1.5,
        evidence=(
            f"avg_loser_hold={avg_l:.1f}d, avg_winner_hold={avg_w:.1f}d "
            f"(ratio={ratio:.2f}) — giữ loser {ratio:.1f}x dài hơn winner"
        ),
        sample_size=n,
    )


# ------------------------------------------------------------ 2. Overtrading

def overtrading(trades: list[TradeLike]) -> BiasResult:
    """Trade nhiều ngày = lỗ nhiều hơn ngày ít giao dịch. Formula:
        metric = (avg_pnl_quiet_day - avg_pnl_busy_day) / |avg_pnl_quiet_day|
    Thresholds: medium ≥ 0.3, high ≥ 1.0.
    Quiet = 1-2 trade/ngày; busy = 4+ trade/ngày.
    """
    per_day_pnl: dict[str, list[int]] = defaultdict(list)
    for t in trades:
        if t.pnl is None:
            continue
        day = t.traded_at.split("T")[0] if "T" in t.traded_at else t.traded_at[:10]
        per_day_pnl[day].append(t.pnl)

    quiet_pnl: list[float] = []
    busy_pnl: list[float] = []
    for pnls in per_day_pnl.values():
        total = float(sum(pnls))
        if len(pnls) <= 2:
            quiet_pnl.append(total)
        elif len(pnls) >= 4:
            busy_pnl.append(total)

    n = sum(len(v) for v in per_day_pnl.values())
    if not quiet_pnl or not busy_pnl:
        return BiasResult(
            name="overtrading", severity="low",
            metric=0.0, threshold_medium=0.3, threshold_high=1.0,
            evidence=f"insufficient variance (quiet={len(quiet_pnl)}d, busy={len(busy_pnl)}d)",
            sample_size=n,
        )

    quiet_avg = sum(quiet_pnl) / len(quiet_pnl)
    busy_avg = sum(busy_pnl) / len(busy_pnl)
    denom = abs(quiet_avg) if abs(quiet_avg) > 1 else 1.0
    metric = (quiet_avg - busy_avg) / denom

    severity = _severity_for(metric, 0.3, 1.0)
    return BiasResult(
        name="overtrading", severity=severity,
        metric=round(metric, 3), threshold_medium=0.3, threshold_high=1.0,
        evidence=(
            f"quiet-day avg PnL={quiet_avg:,.0f} VND, "
            f"busy-day={busy_avg:,.0f} VND — càng trade nhiều càng tệ"
        ),
        sample_size=n,
    )


# ------------------------------------------------------------ 3. Chase momentum

def chase_momentum(trades: list[TradeLike], lookback_days: int = 3, move_threshold: float = 0.03) -> BiasResult:
    """% BUY xảy ra sau 3 phiên giá tăng ≥ 3%. Cần `entry_price` + prior
    close history — vì không pass thêm OHLC, detector xấp xỉ bằng cách xem
    % BUY có giá ≥ x% giá min-20-trade-gần-nhất. Đơn giản nhưng đủ detect.

    Thresholds: medium ≥ 40%, high ≥ 60%.
    """
    buys = [t for t in trades if t.side == "BUY"]
    n = len(buys)
    if n < 5:
        return BiasResult(
            name="chase_momentum", severity="low",
            metric=0.0, threshold_medium=0.40, threshold_high=0.60,
            evidence=f"only {n} buys (need ≥5)",
            sample_size=n,
        )

    # Order buys by time; "recent high" = max price of previous 20 buys same ticker
    sorted_buys = sorted(buys, key=lambda t: t.traded_at)
    chased = 0
    for i, t in enumerate(sorted_buys):
        window_start = max(0, i - 20)
        prior = [
            p.price for p in sorted_buys[window_start:i]
            if p.ticker == t.ticker
        ]
        if not prior:
            continue
        # "chased" = current buy price ≥ (min of prior window) * (1 + move_threshold)
        if t.price >= min(prior) * (1 + move_threshold):
            chased += 1

    metric = chased / n
    severity = _severity_for(metric, 0.40, 0.60)
    return BiasResult(
        name="chase_momentum", severity=severity,
        metric=round(metric, 3), threshold_medium=0.40, threshold_high=0.60,
        evidence=f"{chased}/{n} buys ({metric:.0%}) ở giá cao hơn đáy {lookback_days*7}d",
        sample_size=n,
    )


# ------------------------------------------------------------ 4. Anchoring

def anchoring(trades: list[TradeLike], min_trades_per_symbol: int = 5, cv_threshold: float = 0.05) -> BiasResult:
    """% mã có ≥ 5 trade mà price CV < 5% (tất cả entry ở vùng giá hẹp).
    Thresholds: medium ≥ 33%, high ≥ 66%.
    """
    by_ticker: dict[str, list[int]] = defaultdict(list)
    for t in trades:
        if t.side == "BUY":
            by_ticker[t.ticker].append(t.price)

    eligible = {k: v for k, v in by_ticker.items() if len(v) >= min_trades_per_symbol}
    if not eligible:
        return BiasResult(
            name="anchoring", severity="low",
            metric=0.0, threshold_medium=0.33, threshold_high=0.66,
            evidence=f"no ticker with ≥{min_trades_per_symbol} buys",
            sample_size=sum(len(v) for v in by_ticker.values()),
        )

    anchored = 0
    for _, prices in eligible.items():
        mean_p = sum(prices) / len(prices)
        if mean_p == 0:
            continue
        var = sum((p - mean_p) ** 2 for p in prices) / len(prices)
        cv = (var ** 0.5) / mean_p
        if cv < cv_threshold:
            anchored += 1

    metric = anchored / len(eligible)
    severity = _severity_for(metric, 0.33, 0.66)
    return BiasResult(
        name="anchoring", severity=severity,
        metric=round(metric, 3), threshold_medium=0.33, threshold_high=0.66,
        evidence=(
            f"{anchored}/{len(eligible)} ticker ({metric:.0%}) "
            f"có entry price CV < {cv_threshold:.0%}"
        ),
        sample_size=sum(len(v) for v in eligible.values()),
    )


# ------------------------------------------------------------ 5. Hot-hand sizing

def hot_hand_sizing(trades: list[TradeLike]) -> BiasResult:
    """Correlation between previous-trade win and next-trade size (% NAV).
    Formula: Pearson corr(prev_win ∈ {0,1}, next_qty_pct) > 0.4.
    Thresholds: medium ≥ 0.4, high ≥ 0.6.
    """
    entries = [t for t in trades if t.side == "BUY" and t.pct_nav_at_entry is not None]
    closed = [t for t in trades if t.side == "SELL" and t.pnl is not None]
    if len(entries) < 8 or len(closed) < 4:
        return BiasResult(
            name="hot_hand", severity="low",
            metric=0.0, threshold_medium=0.4, threshold_high=0.6,
            evidence=f"need ≥8 buys + ≥4 closed (have {len(entries)}, {len(closed)})",
            sample_size=len(entries),
        )

    # Build sequence: for each BUY, look at the most recent closed trade before it
    sorted_closed = sorted(closed, key=lambda t: t.traded_at)
    sorted_entries = sorted(entries, key=lambda t: t.traded_at)

    prev_wins: list[float] = []
    next_sizes: list[float] = []
    for buy in sorted_entries:
        # find last SELL before this BUY
        prior_sells = [c for c in sorted_closed if c.traded_at < buy.traded_at]
        if not prior_sells:
            continue
        last = prior_sells[-1]
        prev_wins.append(1.0 if (last.pnl or 0) > 0 else 0.0)
        next_sizes.append(buy.pct_nav_at_entry or 0.0)

    if len(prev_wins) < 5:
        return BiasResult(
            name="hot_hand", severity="low",
            metric=0.0, threshold_medium=0.4, threshold_high=0.6,
            evidence=f"only {len(prev_wins)} paired samples",
            sample_size=len(prev_wins),
        )

    # Pearson correlation
    n = len(prev_wins)
    mean_x = sum(prev_wins) / n
    mean_y = sum(next_sizes) / n
    num = sum((prev_wins[i] - mean_x) * (next_sizes[i] - mean_y) for i in range(n))
    den_x = sum((x - mean_x) ** 2 for x in prev_wins) ** 0.5
    den_y = sum((y - mean_y) ** 2 for y in next_sizes) ** 0.5
    corr = 0.0 if den_x == 0 or den_y == 0 else num / (den_x * den_y)

    severity = _severity_for(corr, 0.4, 0.6)
    return BiasResult(
        name="hot_hand", severity=severity,
        metric=round(corr, 3), threshold_medium=0.4, threshold_high=0.6,
        evidence=f"corr(prev_win, next_qty_pct) = {corr:.2f} over {n} paired trades",
        sample_size=n,
    )


# ------------------------------------------------------------ 6. Skill dogma

def skill_dogma(decisions: list[DecisionLike]) -> BiasResult:
    """% decisions using the same top-1 skill. >70% = bot relying on a single
    skill, likely overfit.
    Thresholds: medium ≥ 0.55, high ≥ 0.70.
    """
    n = len(decisions)
    if n < 10:
        return BiasResult(
            name="skill_dogma", severity="low",
            metric=0.0, threshold_medium=0.55, threshold_high=0.70,
            evidence=f"only {n} decisions (need ≥10)",
            sample_size=n,
        )

    counts: Counter[str] = Counter()
    for d in decisions:
        for s in d.skills_used:
            counts[s] += 1
    if not counts:
        return BiasResult(
            name="skill_dogma", severity="low",
            metric=0.0, threshold_medium=0.55, threshold_high=0.70,
            evidence="no skills recorded on decisions",
            sample_size=n,
        )

    top_skill, top_count = counts.most_common(1)[0]
    metric = top_count / n
    severity = _severity_for(metric, 0.55, 0.70)
    return BiasResult(
        name="skill_dogma", severity=severity,
        metric=round(metric, 3), threshold_medium=0.55, threshold_high=0.70,
        evidence=f"top skill '{top_skill}' used in {top_count}/{n} decisions ({metric:.0%})",
        sample_size=n,
    )


# ------------------------------------------------------------ 7. Recency

def recency(decisions: list[DecisionLike]) -> BiasResult:
    """% decisions whose thesis cites "tuần trước/last week/<N> ngày trước".
    Thresholds: medium ≥ 0.30, high ≥ 0.40.
    """
    n = len(decisions)
    if n < 10:
        return BiasResult(
            name="recency", severity="low",
            metric=0.0, threshold_medium=0.30, threshold_high=0.40,
            evidence=f"only {n} decisions (need ≥10)",
            sample_size=n,
        )

    markers = ["tuần trước", "last week", "hôm qua", "yesterday",
               "vài phiên", "mấy ngày", "gần đây", "recent"]
    cnt = 0
    for d in decisions:
        low = d.thesis.lower()
        if any(m in low for m in markers):
            cnt += 1

    metric = cnt / n
    severity = _severity_for(metric, 0.30, 0.40)
    return BiasResult(
        name="recency", severity=severity,
        metric=round(metric, 3), threshold_medium=0.30, threshold_high=0.40,
        evidence=f"{cnt}/{n} decisions ({metric:.0%}) cite short-term markers",
        sample_size=n,
    )


# ------------------------------------------------------------ runner

def detect_all(
    trades: list[TradeLike] | None = None,
    decisions: list[DecisionLike] | None = None,
) -> list[BiasResult]:
    trades = trades or []
    decisions = decisions or []
    return [
        disposition_effect(trades),
        overtrading(trades),
        chase_momentum(trades),
        anchoring(trades),
        hot_hand_sizing(trades),
        skill_dogma(decisions),
        recency(decisions),
    ]


_ALL_BIASES: tuple[BiasName, ...] = (
    "disposition_effect", "overtrading", "chase_momentum",
    "anchoring", "hot_hand", "skill_dogma", "recency",
)
