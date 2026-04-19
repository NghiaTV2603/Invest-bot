from vnstock_bot.bias import weekly_check
from vnstock_bot.bias.detectors import detect_all
from vnstock_bot.db.connection import get_connection


def test_persist_report_inserts_seven_rows():
    results = detect_all(trades=[], decisions=[])
    n = weekly_check.persist_report(scope="bot", week_of="2026-04-13",
                                    results=results)
    assert n == 7
    rows = get_connection().execute(
        "SELECT bias_name FROM bias_reports WHERE scope='bot' AND week_of='2026-04-13'"
    ).fetchall()
    assert len(rows) == 7


def test_persist_report_upserts_existing_week():
    results1 = detect_all(trades=[], decisions=[])
    weekly_check.persist_report("bot", "2026-04-13", results1)
    # Re-run with same scope+week → should update, not duplicate
    weekly_check.persist_report("bot", "2026-04-13", results1)
    rows = get_connection().execute(
        "SELECT count(*) as n FROM bias_reports WHERE scope='bot' AND week_of='2026-04-13'"
    ).fetchone()
    assert rows["n"] == 7


def test_load_bot_trades_pairs_buy_sell_fifo():
    """Insert 2 buys + 1 sell on same ticker, verify FIFO pairing produces
    correct pnl + hold_days."""
    conn = get_connection()
    with conn:
        # decision row for FK
        cur = conn.execute(
            """INSERT INTO decisions
                (created_at, ticker, action, qty, thesis,
                 evidence_json, risks_json, invalidation,
                 skills_used_json, conviction, source, status)
               VALUES ('2026-04-01T10:00:00', 'FPT', 'BUY', 200, 't',
                       '[]', '[]', 'x', '["technical-trend"]', 4,
                       'claude_daily', 'filled')""",
        )
        did = cur.lastrowid
        conn.execute(
            """INSERT INTO orders
                (decision_id, ticker, side, qty, placed_at, expected_fill_date,
                 filled_at, fill_price, fee, status)
               VALUES (?, 'FPT', 'BUY', 100, '2026-04-01', '2026-04-02',
                       '2026-04-02T09:00:00', 100000, 150, 'filled')""",
            (did,),
        )
        conn.execute(
            """INSERT INTO orders
                (decision_id, ticker, side, qty, placed_at, expected_fill_date,
                 filled_at, fill_price, fee, status)
               VALUES (?, 'FPT', 'BUY', 100, '2026-04-03', '2026-04-04',
                       '2026-04-04T09:00:00', 105000, 150, 'filled')""",
            (did,),
        )
        conn.execute(
            """INSERT INTO orders
                (decision_id, ticker, side, qty, placed_at, expected_fill_date,
                 filled_at, fill_price, fee, status)
               VALUES (?, 'FPT', 'SELL', 150, '2026-04-10', '2026-04-11',
                       '2026-04-11T09:00:00', 115000, 200, 'filled')""",
            (did,),
        )

    trades = weekly_check.load_bot_trades(days=365)
    sells = [t for t in trades if t.side == "SELL"]
    assert len(sells) == 1
    s = sells[0]
    # Average cost of 150cp: 100 @ 100k + 50 @ 105k = 10,525,000 → avg 70_166
    # Wait: 100 cp @ 100000 + 50 cp @ 105000 = 15,250,000 VND / 150 = 101_666
    assert s.entry_price is not None
    assert 101_000 < s.entry_price < 102_000
    # pnl = (115000 - 101666) * 150 > 0
    assert s.pnl is not None and s.pnl > 0
    assert s.hold_days is not None and s.hold_days >= 7


def test_load_bot_decisions_parses_skills_json():
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO decisions
                (created_at, ticker, action, qty, thesis,
                 evidence_json, risks_json, invalidation,
                 skills_used_json, conviction, source, status)
               VALUES ('2026-04-10T10:00:00', 'VNM', 'BUY', 100, 'momentum play',
                       '[]', '[]', 'x', '["momentum","candlestick"]', 3,
                       'claude_daily', 'pending')"""
        )

    decisions = weekly_check.load_bot_decisions(days=365)
    assert len(decisions) >= 1
    d = next(d for d in decisions if d.ticker == "VNM")
    assert d.skills_used == ["momentum", "candlestick"]
    assert d.thesis == "momentum play"


def test_run_bot_bias_check_empty_db_still_produces_seven_results():
    results = weekly_check.run_bot_bias_check(persist=False)
    assert len(results) == 7
    assert all(r.severity == "low" for r in results)  # no data → all low
