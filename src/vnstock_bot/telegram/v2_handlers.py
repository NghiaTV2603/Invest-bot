"""Telegram v2 handlers — shadow, bias, recall, why, regime, debate, skill,
export. Registered from `telegram.bot.build_application`.

Kept in a separate file so v1 `bot.py` stays readable.
"""

from __future__ import annotations

import json

from telegram import Update
from telegram.ext import ContextTypes

from vnstock_bot.config import get_settings
from vnstock_bot.data.holidays import now_vn
from vnstock_bot.db.connection import get_connection
from vnstock_bot.logging_setup import get_logger

log = get_logger(__name__)


def _allowed(chat_id: int) -> bool:
    return chat_id in get_settings().whitelist_ids


# ---------------------------------------------------------------- /shadow

_SHADOW_UPLOAD_INSTRUCTIONS = (
    "📎 *Shadow Account — Upload broker CSV*\n\n"
    "1. Export lịch sử giao dịch từ broker:\n"
    "   - SSI iBoard → Thống kê → Lịch sử lệnh\n"
    "   - VPS SmartOne → Sổ lệnh → Export\n"
    "   - TCBS → Lịch sử đặt lệnh → XLSX (save as CSV)\n"
    "   - Hoặc CSV generic (cột: date, ticker, side, qty, price).\n\n"
    "2. Gửi file CSV vào chat này (attach document).\n"
    "3. Bot sẽ parse → extract rule → Delta-PnL report HTML.\n\n"
    "Kết quả không được gửi ngoài chat này. Dữ liệu giữ trong "
    "`data/shadow/` local."
)


async def cmd_shadow(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    sub = (ctx.args[0] if ctx.args else "upload").lower()

    if sub == "upload":
        await update.message.reply_text(
            _SHADOW_UPLOAD_INSTRUCTIONS, parse_mode="Markdown",
        )
        return

    if sub == "report":
        rows = get_connection().execute(
            """SELECT a.shadow_id, a.broker, a.uploaded_at, a.total_trades,
                      a.real_pnl, b.shadow_pnl, b.delta_pnl, b.report_html_path
               FROM shadow_accounts a
               LEFT JOIN shadow_backtests b ON b.shadow_id = a.shadow_id
               ORDER BY a.uploaded_at DESC LIMIT 5"""
        ).fetchall()
        if not rows:
            await update.message.reply_text(
                "Chưa có shadow account nào. Dùng `/shadow upload` để bắt đầu."
            )
            return
        lines = ["*Shadow Accounts (gần nhất):*"]
        for r in rows:
            delta = r["delta_pnl"]
            emoji = "📈" if (delta or 0) > 0 else "📉"
            lines.append(
                f"{emoji} `{r['shadow_id'][:20]}` {r['broker']} "
                f"trades={r['total_trades']} Δ={delta or 0:,} VND\n"
                f"  report: {r['report_html_path'] or '(not rendered)'}"
            )
        await update.message.reply_text(
            "\n".join(lines), parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        "Dùng: `/shadow upload` | `/shadow report`", parse_mode="Markdown",
    )


async def on_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle CSV upload → run full shadow pipeline → send report."""
    chat_id = update.effective_chat.id
    if not _allowed(chat_id):
        return
    doc = update.message.document
    if not doc:
        return
    filename = (doc.file_name or "journal.csv").strip()
    if not filename.lower().endswith(".csv"):
        await update.message.reply_text(
            "⚠️ Chỉ chấp nhận file CSV. Vui lòng convert Excel → CSV trước."
        )
        return

    # Download to data/shadow/<timestamp>_<filename>
    shadow_dir = get_settings().absolute_raw_dir.parent / "shadow"
    shadow_dir.mkdir(parents=True, exist_ok=True)
    stem = now_vn().strftime("%Y%m%d_%H%M%S")
    target = shadow_dir / f"{stem}_{filename}"
    tg_file = await doc.get_file()
    await tg_file.download_to_drive(custom_path=str(target))

    await update.message.reply_text(
        f"⏳ Parsing {filename} ({doc.file_size or 0:,} bytes)..."
    )

    from vnstock_bot import shadow
    try:
        ext = shadow.extract_shadow_strategy(target)
        bt = shadow.run_shadow_backtest(ext["shadow_id"], ext)
        html_path = shadow.render_shadow_report(ext["shadow_id"], ext, bt)
    except Exception as e:  # noqa: BLE001
        log.error("shadow_upload_failed", error=str(e), file=str(target))
        await update.message.reply_text(f"❌ Parse thất bại: {e}")
        return

    profile = ext["profile"]
    sign = "+" if bt.delta_pnl >= 0 else ""
    summary = (
        f"✅ Shadow `{ext['shadow_id']}`\n"
        f"Trades: {profile.total_trades:,} ({profile.total_roundtrips} "
        f"roundtrip), win-rate {profile.win_rate:.0%}\n"
        f"Rules extracted: {len(ext['rules'])}\n"
        f"Real PnL: {bt.real_pnl:,} VND\n"
        f"Shadow PnL: {bt.shadow_pnl:,} VND\n"
        f"Δ: {sign}{bt.delta_pnl:,} VND\n\n"
        f"Report: `{html_path}`"
    )
    await update.message.reply_text(summary, parse_mode="Markdown")


# ---------------------------------------------------------------- /bias

async def cmd_bias(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    # Run detector on last 90d bot decisions + return grid
    from vnstock_bot.bias.weekly_check import run_bot_bias_check
    results = run_bot_bias_check(persist=False)
    emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}
    lines = ["*Bias check — bot's own decisions (90d):*"]
    for r in results:
        lines.append(
            f"{emoji.get(r.severity, '⚪')} `{r.name}` "
            f"metric={r.metric} n={r.sample_size}\n  {r.evidence}"
        )
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
    )


# ---------------------------------------------------------------- /recall

async def cmd_recall(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    if not ctx.args:
        await update.message.reply_text("Dùng: `/recall <TICKER>`", parse_mode="Markdown")
        return
    ticker = ctx.args[0].upper()
    from vnstock_bot.memory import get_timeline, recall_similar_decision

    events = get_timeline(ticker, days=365, limit=15)
    decisions = recall_similar_decision(ticker, since_days=365)

    lines = [f"*Recall {ticker}:*"]
    if decisions:
        lines.append(f"\n*Decisions ({len(decisions)}):*")
        for d in decisions[:5]:
            lines.append(
                f"- d#{d['id']} {d['created_at'][:10]} {d['action']} "
                f"qty={d.get('qty','?')} conv={d.get('conviction','?')}"
            )
    if events:
        lines.append(f"\n*Timeline events ({len(events)}):*")
        for e in events[:10]:
            lines.append(f"- {e.created_at[:10]} [{e.kind}] {e.summary[:80]}")
    if not decisions and not events:
        lines.append(f"Không tìm thấy dữ liệu cho {ticker}.")
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
    )


# ---------------------------------------------------------------- /why

async def cmd_why(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Dùng: `/why <trace_id>` hoặc `/why d<decision_id>`.",
            parse_mode="Markdown",
        )
        return
    arg = ctx.args[0]
    # Accept 'd42' or bare '42' as decision_id → look up trace_id via DB
    trace_id: str | None = arg
    if arg.lstrip("d").isdigit():
        did = int(arg.lstrip("d"))
        row = get_connection().execute(
            "SELECT trace_id FROM decisions WHERE id = ?", (did,),
        ).fetchone()
        if row and row["trace_id"]:
            trace_id = row["trace_id"]
        else:
            await update.message.reply_text(
                f"Decision d#{did} không có trace_id liên kết "
                "(có thể là decision v1 single-agent).",
            )
            return

    from vnstock_bot.orchestrator import load_trace
    trace = load_trace(trace_id)
    if not trace:
        await update.message.reply_text(f"Không tìm thấy trace `{trace_id}`.",
                                         parse_mode="Markdown")
        return
    lines = [
        f"*Trace `{trace['trace_id'][:12]}`*",
        f"Preset: {trace['preset']} · Status: {trace['status']} · "
        f"{trace['elapsed_ms']} ms",
    ]
    for n in trace["nodes"]:
        emoji = {"success": "✅", "failed": "❌",
                 "timeout": "⌛", "skipped": "⏭"}.get(n["status"], "·")
        lines.append(
            f"{emoji} `{n['node_id']}` ({n['elapsed_ms']} ms) {n['status']}"
        )
        if n.get("error"):
            lines.append(f"   error: {n['error'][:100]}")
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
    )


# ---------------------------------------------------------------- /regime

async def cmd_regime(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    row = get_connection().execute(
        """SELECT trace_id, started_at, final_output_json
           FROM dag_traces
           WHERE preset = 'macro_sector_desk' AND status = 'success'
           ORDER BY started_at DESC LIMIT 1"""
    ).fetchone()
    if not row:
        await update.message.reply_text(
            "Chưa có regime label nào (chạy `macro_sector_desk` preset cuối tuần)."
        )
        return
    try:
        out = json.loads(row["final_output_json"] or "{}")
    except (ValueError, TypeError):
        out = {}
    label = out.get("regime") if isinstance(out, dict) else None
    body = (
        f"*Regime hiện tại:* `{label or 'unknown'}`\n"
        f"Cập nhật: {row['started_at'][:16]}\n"
        f"Trace: `{row['trace_id'][:12]}`"
    )
    await update.message.reply_text(body, parse_mode="Markdown")


# ---------------------------------------------------------------- /debate

async def cmd_debate(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Dùng: `/debate <TICKER>` — chạy bull↔bear debate swarm.",
            parse_mode="Markdown",
        )
        return
    ticker = ctx.args[0].upper()
    await update.message.reply_text(
        f"⏳ Chạy `new_entry_debate` cho {ticker}...", parse_mode="Markdown",
    )
    from vnstock_bot.orchestrator import make_default_agent_fn, run_preset

    try:
        result = await run_preset(
            "new_entry_debate",
            variables={"ticker": ticker},
            agent_fn=make_default_agent_fn(),
        )
    except Exception as e:  # noqa: BLE001
        log.error("debate_failed", ticker=ticker, error=str(e))
        await update.message.reply_text(f"❌ Debate thất bại: {e}")
        return

    lines = [
        f"*Debate {ticker}* ({result.status}, {result.elapsed_ms} ms)",
        f"Trace: `{result.trace_id[:12]}` (dùng `/why` xem chi tiết)",
    ]
    for node_id in ["bull_advocate", "bear_advocate",
                    "risk_officer", "portfolio_manager"]:
        n = result.node(node_id)
        if not n:
            continue
        emoji = "✅" if n.status == "success" else "⚠️"
        lines.append(f"{emoji} {node_id}: {n.status} ({n.elapsed_ms} ms)")
    if result.final_output and isinstance(result.final_output, dict):
        txt = result.final_output.get("text") or ""
        lines.append(f"\n*PM verdict:*\n{txt[:500]}")
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
    )


# ---------------------------------------------------------------- /skill

async def cmd_skill(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Dùng:\n"
            "• `/skill status <name>` — v2 frontmatter + CI\n"
            "• `/skill promote <draft-name>` — approve draft → shadow",
            parse_mode="Markdown",
        )
        return
    sub = ctx.args[0].lower()

    if sub == "status":
        if len(ctx.args) < 2:
            await update.message.reply_text(
                "`/skill status <name>`", parse_mode="Markdown",
            )
            return
        name = ctx.args[1]
        from vnstock_bot.research.skill_loader import (
            SkillNotFound,
            read_skill_meta,
        )
        try:
            meta = read_skill_meta(name)
        except SkillNotFound:
            await update.message.reply_text(f"Không thấy skill `{name}`.",
                                             parse_mode="Markdown")
            return
        row = get_connection().execute(
            "SELECT * FROM skill_scores_v2 WHERE skill = ?", (name,),
        ).fetchone()
        ci_low = row["win_rate_ci_low"] if row else None
        ci_high = row["win_rate_ci_high"] if row else None
        wf = (
            f"{row['wf_pass_count']}/{row['wf_total_windows']}"
            if row and row["wf_pass_count"] is not None else "—"
        )
        await update.message.reply_text(
            f"*Skill `{name}`*\n"
            f"Version: {meta.version} · Status: `{meta.status}`\n"
            f"Category: {meta.category} · Parent: {meta.parent_skill or '—'}\n"
            f"Uses: {meta.uses} · Trades with signal: {meta.trades_with_signal}\n"
            f"CI95: [{ci_low}, {ci_high}]\n"
            f"Walk-forward: {wf}",
            parse_mode="Markdown",
        )
        return

    if sub == "promote":
        if len(ctx.args) < 2:
            await update.message.reply_text(
                "`/skill promote <draft-name>`", parse_mode="Markdown",
            )
            return
        name = ctx.args[1]
        from vnstock_bot.learning.skill_lifecycle import (
            human_promote_draft_to_shadow,
        )
        try:
            d = human_promote_draft_to_shadow(name, note="telegram")
        except ValueError as e:
            await update.message.reply_text(f"❌ {e}")
            return
        await update.message.reply_text(
            f"✅ `{name}`: {d.from_status} → {d.to_status}",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        "Unknown subcommand. `/skill status <name>` hoặc `/skill promote <name>`.",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------- /review

async def cmd_review(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Kick `position_review` swarm preset on a holding."""
    if not _allowed(update.effective_chat.id):
        return
    if not ctx.args:
        await update.message.reply_text(
            "Dùng: `/review <TICKER>` — chạy position_review swarm.",
            parse_mode="Markdown",
        )
        return
    ticker = ctx.args[0].upper()
    await update.message.reply_text(
        f"⏳ Chạy `position_review` cho {ticker}...", parse_mode="Markdown",
    )
    from vnstock_bot.orchestrator import make_default_agent_fn, run_preset

    try:
        result = await run_preset(
            "position_review",
            variables={"ticker": ticker},
            agent_fn=make_default_agent_fn(),
        )
    except Exception as e:  # noqa: BLE001
        log.error("review_failed", ticker=ticker, error=str(e))
        await update.message.reply_text(f"❌ Review thất bại: {e}")
        return

    lines = [
        f"*Review {ticker}* ({result.status}, {result.elapsed_ms} ms)",
        f"Trace: `{result.trace_id[:12]}`",
    ]
    for node_id in ["fundamental_check", "technical_check",
                    "invalidation_check", "decider"]:
        n = result.node(node_id)
        if not n:
            continue
        emoji = "✅" if n.status == "success" else "⚠️"
        lines.append(f"{emoji} {node_id}: {n.status} ({n.elapsed_ms} ms)")
    if result.final_output and isinstance(result.final_output, dict):
        txt = result.final_output.get("text") or ""
        lines.append(f"\n*Decision:*\n{txt[:500]}")
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
    )


# ---------------------------------------------------------------- /today_swarm

async def cmd_today_swarm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Explicit swarm daily_research (bypasses DAILY_RESEARCH_MODE default)."""
    if not _allowed(update.effective_chat.id):
        return
    await update.message.reply_text("⏳ Chạy swarm daily_research...")

    from vnstock_bot.scheduler.jobs import daily_research_swarm_job

    async def _send(msg: str) -> None:
        await ctx.bot.send_message(
            chat_id=update.effective_chat.id, text=msg[:4000],
        )

    result = await daily_research_swarm_job(_send)
    await update.message.reply_text(
        f"✅ done: {result}", parse_mode="Markdown",
    )


# ---------------------------------------------------------------- /export

async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    if not ctx.args or ctx.args[0].lower() != "pine":
        from vnstock_bot.export import TEMPLATES
        await update.message.reply_text(
            f"Dùng: `/export pine <template>`\nTemplate: {', '.join(TEMPLATES)}",
            parse_mode="Markdown",
        )
        return
    tpl = ctx.args[1].lower() if len(ctx.args) > 1 else ""
    from vnstock_bot.export import TEMPLATES, PineParams, write_to_file

    if tpl not in TEMPLATES:
        await update.message.reply_text(
            f"Template không hợp lệ. Có: {', '.join(TEMPLATES)}",
        )
        return
    strategy_name = " ".join(ctx.args[2:]) or f"vnstock-bot {tpl}"
    path = write_to_file(
        tpl,  # type: ignore[arg-type]
        PineParams(strategy_name=strategy_name),
    )
    await update.message.reply_text(
        f"✅ Pine script generated:\n`{path}`\n\n"
        f"Mở file, copy nội dung, paste vào TradingView Pine Editor → "
        f"*Add to Chart*.",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------- registration

def register_v2_handlers(app) -> None:
    from telegram.ext import CommandHandler, MessageHandler, filters

    app.add_handler(CommandHandler("shadow", cmd_shadow))
    app.add_handler(CommandHandler("bias", cmd_bias))
    app.add_handler(CommandHandler("recall", cmd_recall))
    app.add_handler(CommandHandler("why", cmd_why))
    app.add_handler(CommandHandler("regime", cmd_regime))
    app.add_handler(CommandHandler("debate", cmd_debate))
    app.add_handler(CommandHandler("review", cmd_review))
    app.add_handler(CommandHandler("today_swarm", cmd_today_swarm))
    app.add_handler(CommandHandler("skill", cmd_skill))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(
        MessageHandler(filters.Document.FileExtension("csv"), on_document)
    )
