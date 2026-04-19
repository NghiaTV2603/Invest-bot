"""End-to-end: CSV → extract → backtest → report. Verifies the full flow
and DB persistence."""

from pathlib import Path

from vnstock_bot import shadow
from vnstock_bot.db.connection import get_connection


def _fixture_csv(tmp_path: Path) -> Path:
    """Build a journal with obvious pattern: morning Bank buys held 3-4d win,
    afternoon Retail buys noise, plus a late-exit loser."""
    rows = [["date", "ticker", "side", "qty", "price", "fee"]]
    # 6 Bank morning winners, held 3-4 days
    for i in range(1, 7):
        rows.append([f"2026-03-{i:02d} 09:30:00", "VCB", "BUY", "100", "80000", "120"])
        rows.append([f"2026-03-{i+3:02d} 09:30:00", "VCB", "SELL", "100", "82000", "125"])
    # 2 Retail afternoon losers (noise)
    rows.append(["2026-03-15 14:00:00", "MWG", "BUY", "100", "50000", "75"])
    rows.append(["2026-03-20 14:00:00", "MWG", "SELL", "100", "48000", "72"])
    rows.append(["2026-03-17 14:00:00", "MWG", "BUY", "100", "50000", "75"])
    rows.append(["2026-03-22 14:00:00", "MWG", "SELL", "100", "47000", "71"])
    # 1 late-exit loser (Bank, held 15 days)
    rows.append(["2026-03-10 09:30:00", "CTG", "BUY", "100", "40000", "60"])
    rows.append(["2026-03-25 09:30:00", "CTG", "SELL", "100", "35000", "53"])

    path = tmp_path / "journal.csv"
    path.write_text("\n".join(",".join(r) for r in rows) + "\n",
                    encoding="utf-8")
    return path


def test_analyze_trade_journal_returns_structured(tmp_path):
    p = _fixture_csv(tmp_path)
    result = shadow.analyze_trade_journal(
        p, sector_lookup={"VCB": "Bank", "CTG": "Bank", "MWG": "Retail"},
    )
    assert result["broker"] in ("generic", "vps", "ssi", "tcbs")
    assert result["profile"].total_trades >= 10
    assert result["profile"].total_roundtrips >= 5
    assert len(result["bias"]) == 7


def test_extract_persists_shadow_and_rules(tmp_path):
    p = _fixture_csv(tmp_path)
    ext = shadow.extract_shadow_strategy(
        p, sector_lookup={"VCB": "Bank", "CTG": "Bank", "MWG": "Retail"},
    )
    sid = ext["shadow_id"]
    assert sid.startswith("shadow_")

    conn = get_connection()
    acc = conn.execute(
        "SELECT * FROM shadow_accounts WHERE shadow_id = ?", (sid,)
    ).fetchone()
    assert acc is not None
    assert acc["total_trades"] > 0

    rules = conn.execute(
        "SELECT * FROM shadow_rules WHERE shadow_id = ?", (sid,)
    ).fetchall()
    assert len(rules) >= 1


def test_run_shadow_backtest_persists_components(tmp_path):
    p = _fixture_csv(tmp_path)
    ext = shadow.extract_shadow_strategy(
        p, sector_lookup={"VCB": "Bank", "CTG": "Bank", "MWG": "Retail"},
    )
    bt = shadow.run_shadow_backtest(ext["shadow_id"], ext)
    assert bt.real_pnl is not None
    assert bt.shadow_pnl is not None
    # With morning Bank winners + afternoon Retail losers, shadow should do
    # at least as well as real (or better)
    assert bt.shadow_pnl >= bt.real_pnl - 1  # allow rounding

    row = get_connection().execute(
        "SELECT * FROM shadow_backtests WHERE shadow_id = ?",
        (ext["shadow_id"],),
    ).fetchone()
    assert row is not None
    assert row["real_pnl"] == bt.real_pnl


def test_render_report_writes_html_with_eight_sections(tmp_path):
    p = _fixture_csv(tmp_path)
    out_dir = tmp_path / "reports"
    ext = shadow.extract_shadow_strategy(
        p, sector_lookup={"VCB": "Bank", "CTG": "Bank", "MWG": "Retail"},
    )
    bt = shadow.run_shadow_backtest(ext["shadow_id"], ext)
    html_path = shadow.render_shadow_report(ext["shadow_id"], ext, bt,
                                            out_dir=out_dir)
    assert html_path.is_file()
    content = html_path.read_text(encoding="utf-8")
    # Each of the 8 sections must have an id marker
    for sid in ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8"):
        assert f'id="{sid}"' in content, f"missing section {sid}"
    # Sanity: contains shadow_id
    assert ext["shadow_id"] in content


def test_load_shadow_summary_roundtrip(tmp_path):
    p = _fixture_csv(tmp_path)
    ext = shadow.extract_shadow_strategy(p)
    shadow.run_shadow_backtest(ext["shadow_id"], ext)
    summary = shadow.load_shadow_summary(ext["shadow_id"])
    assert summary is not None
    assert summary["account"]["shadow_id"] == ext["shadow_id"]
    assert summary["latest_backtest"] is not None


def test_load_shadow_summary_unknown_returns_none():
    assert shadow.load_shadow_summary("shadow_nonexistent") is None
