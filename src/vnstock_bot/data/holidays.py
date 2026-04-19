from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")

# VN stock market holidays. Update yearly.
# Sources: HSX calendar + Lao Dong public holidays.
VN_HOLIDAYS: set[date] = {
    # --- 2026 ---
    date(2026, 1, 1),   # New Year
    # Lunar New Year 2026 (Feb 17 = Tuesday) — nghỉ 16-20 Feb
    date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18),
    date(2026, 2, 19), date(2026, 2, 20),
    # Giỗ tổ Hùng Vương (10/3 âm) ~ 2026-04-26 (Sunday), bù thứ 2
    date(2026, 4, 27),
    # 30/4 + 1/5
    date(2026, 4, 30), date(2026, 5, 1),
    # Quốc khánh 2/9 (Wednesday in 2026)
    date(2026, 9, 1), date(2026, 9, 2),

    # --- 2027 ---
    date(2027, 1, 1),
}


def now_vn() -> datetime:
    return datetime.now(tz=VN_TZ)


def today_vn() -> date:
    return now_vn().date()


def is_trading_day(d: date) -> bool:
    if d.weekday() >= 5:  # Sat/Sun
        return False
    return d not in VN_HOLIDAYS


def next_trading_day(d: date) -> date:
    nxt = d + timedelta(days=1)
    while not is_trading_day(nxt):
        nxt += timedelta(days=1)
    return nxt


def prev_trading_day(d: date) -> date:
    prv = d - timedelta(days=1)
    while not is_trading_day(prv):
        prv -= timedelta(days=1)
    return prv


def add_trading_days(d: date, n: int) -> date:
    """Add n trading days (can be negative)."""
    step = 1 if n > 0 else -1
    cur = d
    for _ in range(abs(n)):
        cur = next_trading_day(cur) if step > 0 else prev_trading_day(cur)
    return cur


def iso(d: date | datetime) -> str:
    if isinstance(d, datetime):
        return d.date().isoformat()
    return d.isoformat()
