"""Scheduled jobs: daily_research, weekly_review. Callers from APScheduler."""

from __future__ import annotations

import traceback
from collections.abc import Awaitable, Callable

from vnstock_bot.config import get_settings
from vnstock_bot.data.holidays import is_trading_day, iso, today_vn
from vnstock_bot.data.market_snapshot import build_snapshot
from vnstock_bot.data.watchlist import load_watchlist
from vnstock_bot.db import queries
from vnstock_bot.logging_setup import get_logger
from vnstock_bot.portfolio import reporter
from vnstock_bot.portfolio.simulator import (
    check_stop_loss,
    compute_equity,
    fill_pending_orders,
    place_order_from_decision,
    release_t2_shares,
)
from vnstock_bot.portfolio.validator import validate_batch

log = get_logger(__name__)


SendFn = Callable[[str], Awaitable[None]]


# ---------------------------------------------------------------- context builders

def _build_daily_context() -> str:
    wl = load_watchlist()
    from vnstock_bot.portfolio.simulator import load_portfolio
    p = load_portfolio()

    lines = ["# Watchlist (close + volume 5 phiên gần nhất — gọi get_price để xem thêm)"]
    for t in wl.tickers:
        rows = queries.get_ohlc(t.ticker, days=7)
        if not rows:
            lines.append(f"- {t.ticker} ({t.sector}/{t.exchange}) — no data")
            continue
        recent = rows[-5:]
        snippet = " → ".join(f"{r['close']}(v={r['volume']//1000}k)" for r in recent)
        lines.append(f"- {t.ticker} ({t.sector}/{t.exchange}): {snippet}")

    lines.append("\n# Holdings")
    if not p.holdings:
        lines.append("(none — vốn còn nguyên, đang tìm cơ hội mở vị thế)")
    else:
        for h in p.holdings:
            t2_note = "" if h.qty_available == h.qty_total else f" (T+2 locked: {h.qty_total - h.qty_available}cp)"
            lines.append(
                f"- {h.ticker}: qty={h.qty_total} avg_cost={h.avg_cost:,} "
                f"opened={h.opened_at}{t2_note}"
            )
    lines.append(f"\n# Cash available: {p.cash:,} VND")

    snap = queries.latest_market_snapshot()
    if snap:
        lines.append(f"\n# Market snapshot ({snap['date']})")
        lines.append(f"- VN-Index close: {snap['vnindex_close']}")
        fn = (snap["foreign_buy"] or 0) + (snap["foreign_sell"] or 0)
        lines.append(f"- Foreign net flow (20d aggregate): {fn:,} VND")
        if snap["top_movers_json"]:
            lines.append(f"- Top movers today: {snap['top_movers_json']}")
    else:
        lines.append("\n# Market snapshot: not built yet")
    return "\n".join(lines)


# ---------------------------------------------------------------- daily

async def daily_research_job(send: SendFn | None = None) -> dict:
    """Dispatcher — picks single-agent (v1) or swarm (v2) based on
    `DAILY_RESEARCH_MODE` env. Default: single until track record proves swarm.
    """
    settings = get_settings()
    if settings.daily_research_mode == "swarm":
        return await daily_research_swarm_job(send)
    return await daily_research_single_job(send)


async def daily_research_single_job(send: SendFn | None = None) -> dict:
    """V1 path — single Claude agent researches the watchlist sequentially.
    Kept as the production default + as the orchestrator fallback when
    the DAG runner fails."""
    today = today_vn()
    if not is_trading_day(today):
        msg = f"⏸ {iso(today)} không phải phiên giao dịch, skip daily job."
        log.info("daily_job_skip_holiday")
        if send:
            await send(msg)
        return {"skipped": "holiday"}

    try:
        log.info("daily_job_start", date=iso(today))

        # 1. Market snapshot + fill pending orders
        build_snapshot(today)
        release_t2_shares(today)
        fill_summary = fill_pending_orders(today)

        # 2. Auto stop-loss proposals → go through same validation
        auto_proposals = check_stop_loss(today)
        for p in auto_proposals:
            # still go via validator; source = simulator_auto
            did = queries.insert_decision({
                "created_at": iso(today),
                "ticker": p["ticker"],
                "action": p["action"],
                "qty": p["qty"],
                "target_price": p.get("target_price"),
                "stop_loss": p.get("stop_loss"),
                "thesis": p["thesis"],
                "evidence": p["evidence"],
                "risks": p["risks"],
                "invalidation": p["invalidation"],
                "skills_used": p["skills_used"],
                "playbook": p["playbook_used"],
                "conviction": p["conviction"],
                "source": "simulator_auto",
                "status": "pending",
            })
            place_order_from_decision(did, p, today)

        # 3. Claude research
        from vnstock_bot.research.agent import daily_research
        ctx = _build_daily_context()
        result, proposals = await daily_research(ctx)

        # 4. Validate → persist
        accepted, rejections = validate_batch(proposals)
        created_decisions: list = []
        for dec in accepted:
            did = queries.insert_decision({
                "created_at": iso(today),
                "ticker": dec.ticker,
                "action": dec.action,
                "qty": dec.qty,
                "target_price": dec.target_price,
                "stop_loss": dec.stop_loss,
                "thesis": dec.thesis,
                "evidence": dec.evidence,
                "risks": dec.risks,
                "invalidation": dec.invalidation,
                "skills_used": dec.skills_used,
                "playbook": dec.playbook_used,
                "conviction": dec.conviction,
                "source": "claude_daily",
                "status": "pending",
            })
            queries.bump_skill_uses(dec.skills_used, iso(today))
            place_order_from_decision(did, {
                "action": dec.action, "ticker": dec.ticker, "qty": dec.qty,
            }, today)
            created_decisions.append(dec)

        # 5. Equity
        snap = queries.latest_market_snapshot()
        vni = snap["vnindex_close"] if snap else None
        stats = compute_equity(today, vni)

        # 6. Report
        report_md = reporter.daily_report(today, created_decisions, rejections, fill_summary.filled, stats)
        log.info("daily_job_done",
                 decisions=len(created_decisions),
                 rejected=len(rejections),
                 fills=len(fill_summary.filled),
                 tokens=result.tokens_used)

        if send:
            await send(report_md)
            await send(
                f"✅ daily_research OK — {len(created_decisions)} decisions, "
                f"{len(rejections)} rejected, {result.turns} turns, "
                f"~{result.tokens_used} tokens"
            )
        return {
            "decisions": len(created_decisions),
            "rejected": len(rejections),
            "tokens": result.tokens_used,
            "fills": len(fill_summary.filled),
        }
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        log.error("daily_job_failed", error=str(e), traceback=tb)
        if send:
            await send(f"❌ daily_research FAILED: {e}\n```\n{tb[-800:]}\n```")
        return {"error": str(e)}


# ---------------------------------------------------------------- weekly

async def weekly_review_job(send: SendFn | None = None) -> dict:
    from vnstock_bot.bias.weekly_check import run_bot_bias_check
    from vnstock_bot.learning.skill_lifecycle import apply_all
    from vnstock_bot.learning.skill_proposer import propose
    from vnstock_bot.learning.skill_stats_compute import compute_and_persist_all
    from vnstock_bot.learning.weekly_review import run_weekly_review
    from vnstock_bot.memory import extract_patterns

    try:
        summary = await run_weekly_review()

        # v2 step 1: compute bootstrap CI + walk-forward per skill from
        # decision_outcomes. MUST run before apply_all — otherwise
        # skill_scores_v2.win_rate_ci_low stays NULL and every lifecycle
        # transition bails with 'insufficient_trades'.
        stats_rows = compute_and_persist_all(lookback_days=180)
        stats_with_ci = [r for r in stats_rows if r.win_rate_ci_low is not None]

        # v2 step 2: bias check on bot's own decisions → persist bias_reports
        bias_results = run_bot_bias_check(persist=True)
        bias_high = [r for r in bias_results if r.severity == "high"]

        # v2 step 3: skill lifecycle — auto-promote/archive per stat gate
        lifecycle_decisions = apply_all(dry_run=False)
        changes = [d for d in lifecycle_decisions if d.changed]

        # v2 step 4: extract L4 patterns from winning decisions. These feed
        # into step 5 (skill_proposer) which turns high-support patterns
        # into draft skill candidates.
        pattern_summary = extract_patterns()

        # v2 step 5: deterministic skill proposer — emit 0-2 draft proposals
        # from L4 patterns. We only *log* them; materialization is human-gated
        # via /skill promote.
        proposed_drafts = propose()

        summary["stats_computed"] = len(stats_rows)
        summary["stats_with_ci"] = len(stats_with_ci)
        summary["bias_high_count"] = len(bias_high)
        summary["lifecycle_changes"] = len(changes)
        summary["patterns"] = pattern_summary
        summary["proposed_drafts"] = len(proposed_drafts)

        if send:
            msg = (
                f"📅 *Weekly review — {iso(today_vn())}*\n"
                f"Strategy notes: +{summary['strategy_notes_applied']}\n"
                f"Skill edits: {summary['skill_edits_applied']}\n"
                f"Tokens: {summary['tokens']}\n\n"
                f"📊 Stats computed: {len(stats_rows)} skills "
                f"({len(stats_with_ci)} have CI)\n"
                f"*Top skills:* {', '.join(s['skill'] for s in summary['top_skills'])}\n"
                f"*Bottom skills:* {', '.join(s['skill'] for s in summary['bottom_skills'])}\n\n"
                f"🏴 Bias high flags: {len(bias_high)}"
                + (" (" + ", ".join(r.name for r in bias_high) + ")" if bias_high else "")
                + "\n"
                f"🔁 Lifecycle changes: {len(changes)}"
                + (" (" + ", ".join(f"{d.skill}: {d.from_status}→{d.to_status}" for d in changes) + ")" if changes else "")
                + "\n"
                f"💡 Proposed drafts: {len(proposed_drafts)}"
                + (" (" + ", ".join(d.name for d in proposed_drafts) + ")" if proposed_drafts else "")
            )
            await send(msg)
        return summary
    except Exception as e:  # noqa: BLE001
        log.error("weekly_job_failed", error=str(e))
        if send:
            await send(f"❌ weekly_review FAILED: {e}")
        return {"error": str(e)}


# ---------------------------------------------------------------- v2 daily (swarm DAG)

async def daily_research_swarm_job(send: SendFn | None = None) -> dict:
    """V2 path: run `daily_research` swarm preset via orchestrator instead
    of the single-agent loop. Both code paths remain available — config
    `DAILY_RESEARCH_MODE=swarm` switches (future enhancement).

    For now this is the opt-in entry point called by `/today_swarm` in
    Telegram or an explicit cron line; the default cron keeps using
    `daily_research_job` until we've got enough track record.
    """
    today = today_vn()
    if not is_trading_day(today):
        if send:
            await send(f"⏸ {iso(today)} không phải phiên GD, skip.")
        return {"skipped": "holiday"}

    try:
        build_snapshot(today)
        release_t2_shares(today)
        fill_summary = fill_pending_orders(today)

        ctx = _build_daily_context()

        from vnstock_bot.orchestrator import (
            make_default_agent_fn,
            run_preset,
        )

        events: list[str] = []

        async def _on_event(ev) -> None:
            if ev.type == "node_start":
                events.append(f"⏳ {ev.node_id}")
            elif ev.type == "node_end":
                events.append(f"✅ {ev.node_id} ({ev.data.get('elapsed_ms')} ms)")
            elif ev.type == "node_fail":
                events.append(f"❌ {ev.node_id}: {ev.data.get('reason','')}")

        result = await run_preset(
            "daily_research",
            variables={"watchlist_context": ctx},
            agent_fn=make_default_agent_fn(),
            listeners=[_on_event],
        )

        snap = queries.latest_market_snapshot()
        vni = snap["vnindex_close"] if snap else None
        stats = compute_equity(today, vni)

        if send:
            await send(
                f"✅ swarm daily_research {result.status} "
                f"({result.elapsed_ms} ms, trace `{result.trace_id[:12]}`)\n"
                + "\n".join(events[-10:])
                + f"\n\nNAV: {stats.total:,} VND"
            )
        return {
            "status": result.status,
            "trace_id": result.trace_id,
            "elapsed_ms": result.elapsed_ms,
            "fills": len(fill_summary.filled),
        }
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        log.error("swarm_daily_failed", error=str(e), traceback=tb)
        if send:
            await send(f"❌ swarm daily_research FAILED: {e}")
        return {"error": str(e)}
