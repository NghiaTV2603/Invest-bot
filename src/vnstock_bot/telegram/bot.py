"""Telegram bot wiring: handlers + whitelist + chat agent."""

from __future__ import annotations

import json
from datetime import date

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from vnstock_bot.config import get_settings
from vnstock_bot.data.holidays import iso, now_vn, today_vn
from vnstock_bot.db import queries
from vnstock_bot.learning.skill_scorer import summarize
from vnstock_bot.logging_setup import get_logger
from vnstock_bot.portfolio import reporter
from vnstock_bot.scheduler.jobs import daily_research_job
from vnstock_bot.telegram.format import md_to_telegram_html, truncate
from vnstock_bot.telegram.v2_handlers import register_v2_handlers

log = get_logger(__name__)


def _allowed(chat_id: int) -> bool:
    return chat_id in get_settings().whitelist_ids


async def _send(bot, chat_id: int, text: str) -> None:
    """Send with HTML rendering of Claude's markdown. Fall back to plain
    text if Telegram rejects the HTML (e.g. Claude emitted an unmatched
    tag character we failed to escape)."""
    html_body = truncate(md_to_telegram_html(text))
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=html_body,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("send_html_failed_falling_back_plain", error=str(e))
        await bot.send_message(
            chat_id=chat_id,
            text=truncate(text),
            disable_web_page_preview=True,
        )


# ---------------------------------------------------------------- command handlers

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not _allowed(chat_id):
        await update.message.reply_text(
            f"Bot ở chế độ riêng tư. Chat ID của bạn: {chat_id}\n"
            "Thêm ID này vào TELEGRAM_CHAT_ID_WHITELIST trong .env."
        )
        return
    await update.message.reply_text(
        "👋 vnstock-bot sẵn sàng.\n\n"
        "*v1:* /status /portfolio /today /decisions /report /skills /backtest\n"
        "*v2:* /shadow /bias /recall /why /regime /debate /skill /export\n"
        "Hoặc nhắn text để chat với Claude có context portfolio.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    text = reporter.portfolio_status(today_vn())
    await update.message.reply_text(text)


async def cmd_portfolio(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    text = reporter.portfolio_status(today_vn())
    await update.message.reply_text(text)


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    await update.message.reply_text("⏳ Đang chạy daily research...")
    bot = ctx.bot
    chat_id = update.effective_chat.id
    async def send(msg: str):
        await _send(bot, chat_id, msg)
    await daily_research_job(send)


async def cmd_decisions(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    days = 7
    if ctx.args:
        try:
            days = int(ctx.args[0])
        except ValueError:
            pass
    rows = queries.get_decisions_recent(days)
    if not rows:
        await update.message.reply_text(f"Không có decision nào trong {days} ngày.")
        return
    lines = [f"*Decisions {days}d ({len(rows)}):*"]
    for r in rows[:25]:
        skills = json.loads(r["skills_used_json"] or "[]")
        lines.append(
            f"d#{r['id']} {r['created_at'][:10]} {r['action']} {r['ticker']} "
            f"qty={r['qty']} conv={r['conviction']} [{','.join(skills[:3])}]"
        )
    await update.message.reply_text("\n".join(lines))


async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    eq = queries.get_equity_recent(8)
    if not eq:
        await update.message.reply_text("Chưa có equity data.")
        return
    first, last = eq[0]["total"], eq[-1]["total"]
    pct = (last - first) / first * 100 if first else 0
    vni_first = eq[0]["vnindex"] or 0
    vni_last = eq[-1]["vnindex"] or 0
    vni_pct = (vni_last - vni_first) / vni_first * 100 if vni_first else 0
    lines = [
        "*Weekly report*",
        f"NAV: {first:,} → {last:,}  ({pct:+.2f}%)",
        f"VN-Index: {vni_first:.2f} → {vni_last:.2f}  ({vni_pct:+.2f}%)",
        f"Alpha: {pct - vni_pct:+.2f}%",
    ]
    await update.message.reply_text("\n".join(lines))


async def cmd_skills(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    rows = summarize()
    if not rows:
        await update.message.reply_text("Chưa có skill score nào.")
        return
    lines = ["*Skill scores:*"]
    for r in rows[:15]:
        lines.append(
            f"{r['skill']}: uses={r['uses']} wr5d={r['win_rate_5d']:.2f} wr20d={r['win_rate_20d']:.2f}"
        )
    await update.message.reply_text("\n".join(lines))


async def cmd_backtest(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update.effective_chat.id):
        return
    months = 6
    if ctx.args:
        try:
            months = int(ctx.args[0].rstrip("m").rstrip("mo"))
        except ValueError:
            pass
    await update.message.reply_text(f"⏳ Backtest {months} tháng, chạy nền...")
    from pathlib import Path

    from vnstock_bot.backtest.runner import run_backtest
    out_dir = Path(get_settings().absolute_raw_dir).parent / "backtest" / date.today().isoformat()
    r = run_backtest(months, out_dir)
    await update.message.reply_text(
        f"✅ Backtest done\n"
        f"Strategy: {r.strategy_return_pct:+.2f}%\n"
        f"VN-Index: {r.vnindex_return_pct:+.2f}%\n"
        f"Trades: {r.num_trades}\n"
        f"Output: {r.run_dir}"
    )


# ---------------------------------------------------------------- chat handler

async def on_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not _allowed(chat_id):
        return
    text = update.message.text or ""

    queries.insert_chat_turn(chat_id, "user", text, iso(now_vn()))

    from vnstock_bot.research.agent import chat as chat_agent
    history = [
        {"role": r["role"], "content": r["content"]}
        for r in queries.recent_chat_history(chat_id, limit=20)
    ]
    try:
        result = await chat_agent(text, history)
        reply = result.text or "(empty response)"
    except Exception as e:  # noqa: BLE001
        log.error("chat_failed", error=str(e))
        reply = f"❌ Lỗi: {e}"

    queries.insert_chat_turn(chat_id, "assistant", reply, iso(now_vn()))
    await _send(ctx.bot, chat_id, reply)


# ---------------------------------------------------------------- app factory

def build_application() -> Application:
    settings = get_settings()
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("decisions", cmd_decisions))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("skills", cmd_skills))
    app.add_handler(CommandHandler("backtest", cmd_backtest))
    # v2 handlers registered separately so this module stays readable
    register_v2_handlers(app)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    return app


async def send_to_default_chat(app: Application, text: str) -> None:
    settings = get_settings()
    for chat_id in settings.whitelist_ids:
        try:
            await app.bot.send_message(chat_id=chat_id, text=truncate(text))
        except Exception as e:  # noqa: BLE001
            log.warning("send_failed", chat_id=chat_id, error=str(e))
