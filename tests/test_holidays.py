from datetime import date

from vnstock_bot.data.holidays import (
    add_trading_days,
    is_trading_day,
    next_trading_day,
    prev_trading_day,
)


def test_weekend_not_trading():
    assert not is_trading_day(date(2026, 4, 18))  # Saturday
    assert not is_trading_day(date(2026, 4, 19))  # Sunday
    assert is_trading_day(date(2026, 4, 20))       # Monday


def test_holiday_not_trading():
    assert not is_trading_day(date(2026, 4, 30))   # 30/4
    assert not is_trading_day(date(2026, 5, 1))    # 1/5
    assert not is_trading_day(date(2026, 9, 2))    # 2/9


def test_next_trading_day_skips_weekend():
    assert next_trading_day(date(2026, 4, 17)) == date(2026, 4, 20)
    assert next_trading_day(date(2026, 4, 30)) == date(2026, 5, 4)  # 30/4 + 1/5 holidays → Mon


def test_add_trading_days_t2():
    # Buy Mon 2026-04-20, T+2 = Wed 2026-04-22
    assert add_trading_days(date(2026, 4, 20), 2) == date(2026, 4, 22)
    # Buy Thu 2026-04-23: +1=Fri(24), +2=Mon(27) but 27 is Giỗ Tổ bù → Tue(28)
    assert add_trading_days(date(2026, 4, 23), 2) == date(2026, 4, 28)


def test_prev_trading_day():
    # From Monday, prev = Friday
    assert prev_trading_day(date(2026, 4, 20)) == date(2026, 4, 17)
