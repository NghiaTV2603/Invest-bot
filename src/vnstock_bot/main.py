"""Entry point: telegram long-poll + APScheduler in one event loop."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from vnstock_bot.config import get_settings
from vnstock_bot.db.connection import init_db
from vnstock_bot.logging_setup import get_logger, setup_logging


async def _run_bot() -> None:
    from vnstock_bot.telegram.bot import build_application, send_to_default_chat
    from vnstock_bot.scheduler.jobs import daily_research_job, weekly_review_job

    settings = get_settings()
    log = get_logger("main")
    log.info("boot", tz=settings.tz, whitelist=list(settings.whitelist_ids))

    app = build_application()

    async def send_default(text: str):
        await send_to_default_chat(app, text)

    scheduler = AsyncIOScheduler(timezone=settings.tz)
    scheduler.add_job(
        lambda: asyncio.create_task(daily_research_job(send_default)),
        CronTrigger(
            hour=settings.daily_cron_hour,
            minute=settings.daily_cron_minute,
            day_of_week="mon-fri",
        ),
        id="daily_research",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: asyncio.create_task(weekly_review_job(send_default)),
        CronTrigger(
            day_of_week=settings.weekly_cron_day,
            hour=settings.weekly_cron_hour,
        ),
        id="weekly_review",
        replace_existing=True,
    )
    scheduler.start()
    log.info("scheduler_started",
             daily=f"{settings.daily_cron_hour}:{settings.daily_cron_minute:02d}",
             weekly=f"{settings.weekly_cron_day} {settings.weekly_cron_hour}:00")

    async with app:
        await app.initialize()
        await app.start()
        await app.updater.start_polling()
        await send_default("🤖 vnstock-bot online")

        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        finally:
            await app.updater.stop()
            await app.stop()
            scheduler.shutdown(wait=False)


async def _doctor() -> None:
    settings = get_settings()
    log = get_logger("doctor")
    print(f"• DB path: {settings.absolute_db_path}")
    print(f"• Raw dir: {settings.absolute_raw_dir}")
    print(f"• Whitelist: {settings.whitelist_ids}")
    print(f"• Model: {settings.claude_model}")

    if not settings.absolute_db_path.exists():
        print("• DB not found, initializing...")
        init_db()

    # ping claude SDK
    try:
        from claude_agent_sdk import ClaudeSDKClient  # noqa: F401
        print("✅ claude-agent-sdk import OK")
    except Exception as e:  # noqa: BLE001
        print(f"❌ claude-agent-sdk: {e}")

    # ping vnstock
    try:
        from vnstock_bot.data import vnstock_client
        bars = vnstock_client.fetch_ohlc("FPT", date.today().replace(day=1), date.today())
        print(f"✅ vnstock OK ({len(bars)} bars for FPT this month)")
    except Exception as e:  # noqa: BLE001
        print(f"❌ vnstock: {e}")

    # check DB
    try:
        from vnstock_bot.db.connection import get_connection
        row = get_connection().execute("SELECT count(*) as c FROM holdings").fetchone()
        print(f"✅ DB OK (holdings rows: {row['c']})")
    except Exception as e:  # noqa: BLE001
        print(f"❌ DB: {e}")


async def _warm_cache(days: int) -> None:
    """Fetch OHLC for every ticker in watchlist + indices; write to ohlc_cache."""
    from datetime import timedelta
    from vnstock_bot.data import vnstock_client
    from vnstock_bot.data.watchlist import load_watchlist
    from vnstock_bot.db import queries

    end = date.today()
    start = end - timedelta(days=days)
    wl = load_watchlist()
    total_ok = 0
    total_fail = 0
    failed: list[str] = []

    print(f"• Fetching {len(wl.tickers)} tickers + {len(wl.indices)} indices, {days}d")
    for t in wl.tickers:
        bars = vnstock_client.fetch_ohlc(t.ticker, start, end)
        if not bars:
            total_fail += 1
            failed.append(t.ticker)
            print(f"  ❌ {t.ticker} ({t.sector}): no data")
            continue
        for b in bars:
            queries.upsert_ohlc(t.ticker, b.date, b.open, b.high, b.low, b.close, b.volume)
        total_ok += 1
        last = bars[-1]
        print(f"  ✅ {t.ticker} ({t.sector}): {len(bars)} bars, last close {last.close:,}")

    for idx in wl.indices:
        bars = vnstock_client.fetch_index(idx, start, end)
        if not bars:
            failed.append(idx)
            print(f"  ❌ {idx}: no data")
            continue
        for b in bars:
            queries.upsert_ohlc(idx, b.date, b.open, b.high, b.low, b.close, b.volume)
        print(f"  ✅ {idx}: {len(bars)} bars")

    print(f"\nDone: {total_ok} ok, {total_fail} failed")
    if failed:
        print(f"Failed tickers: {', '.join(failed)}")


async def _backtest_cmd(months: int) -> None:
    from pathlib import Path
    from vnstock_bot.backtest.runner import run_backtest
    settings = get_settings()
    out_dir = Path(settings.absolute_raw_dir).parent / "backtest" / date.today().isoformat()
    r = run_backtest(months, out_dir)
    print(f"Strategy return: {r.strategy_return_pct:+.2f}%  VN-Index: {r.vnindex_return_pct:+.2f}%")
    print(f"Trades: {r.num_trades}  Output: {r.run_dir}")


def cli() -> None:
    parser = argparse.ArgumentParser(prog="vnstock-bot")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("run", help="Start bot + scheduler (foreground)")
    sub.add_parser("doctor", help="Health check")
    sub.add_parser("init-db", help="Create DB schema")
    bt = sub.add_parser("backtest", help="Run backtest")
    bt.add_argument("--months", type=int, default=6)
    sub.add_parser("today", help="Run daily research manually (no Telegram)")
    wc = sub.add_parser("warm-cache", help="Fetch OHLC for watchlist into DB")
    wc.add_argument("--days", type=int, default=90)

    args = parser.parse_args()
    settings = get_settings()
    setup_logging(settings.log_level, settings.absolute_log_dir)

    if args.cmd == "run":
        asyncio.run(_run_bot())
    elif args.cmd == "doctor":
        asyncio.run(_doctor())
    elif args.cmd == "init-db":
        init_db()
    elif args.cmd == "backtest":
        asyncio.run(_backtest_cmd(args.months))
    elif args.cmd == "warm-cache":
        asyncio.run(_warm_cache(args.days))
    elif args.cmd == "today":
        from vnstock_bot.scheduler.jobs import daily_research_job
        result = asyncio.run(daily_research_job())
        print(result)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    cli()
