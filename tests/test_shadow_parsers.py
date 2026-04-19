from pathlib import Path

import pytest

from vnstock_bot.shadow import parsers


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    path.write_text("\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")


def test_generic_parser_basic(tmp_path):
    p = tmp_path / "trades.csv"
    _write_csv(p, [
        ["date", "ticker", "side", "qty", "price", "fee"],
        ["2026-04-01 09:15:00", "FPT", "BUY", "200", "148500", "200"],
        ["2026-04-05 10:30:00", "FPT", "SELL", "200", "152000", "250"],
    ])
    trades = parsers.parse(p)
    assert len(trades) == 2
    assert trades[0].ticker == "FPT"
    assert trades[0].side == "BUY"
    assert trades[0].qty == 200
    assert trades[0].price == 148_500
    assert trades[0].fee == 200


def test_parser_accepts_vietnamese_formats(tmp_path):
    p = tmp_path / "vi.csv"
    _write_csv(p, [
        ["Ngày", "Mã", "Mua/Bán", "Khối lượng", "Giá", "Phí"],
        ["01/04/2026 09:15:00", "FPT", "Mua", "200", "148.500", "200"],
        ["05/04/2026 10:30:00", "FPT", "Bán", "200", "152.000", "250"],
    ])
    trades = parsers.parse(p)
    assert len(trades) == 2
    assert trades[0].price == 148_500
    assert trades[1].side == "SELL"


def test_ssi_broker_detected(tmp_path):
    p = tmp_path / "ssi.csv"
    _write_csv(p, [
        ["Ngày giao dịch", "Mã CK", "Loại lệnh", "Khối lượng khớp", "Giá khớp", "Phí"],
        ["2026-04-01 09:15:00", "VNM", "Mua", "100", "80000", "120"],
    ])
    assert parsers.detect_broker(p) == "ssi"
    trades = parsers.parse(p)
    assert trades[0].broker == "ssi"


def test_vps_broker_detected(tmp_path):
    p = tmp_path / "vps.csv"
    _write_csv(p, [
        ["Ngày", "Mã", "Mua/Bán", "Khối lượng", "Giá", "Phí GD"],
        ["01/04/2026 10:00:00", "HPG", "Bán", "300", "25000", "180"],
    ])
    assert parsers.detect_broker(p) == "vps"


def test_tcbs_broker_detected(tmp_path):
    p = tmp_path / "tcbs.csv"
    _write_csv(p, [
        ["Ngày GD", "Ticker", "Loại GD", "Khối lượng khớp", "Giá khớp", "Phí GD"],
        ["2026-04-01", "MWG", "Mua", "100", "45000", "100"],
    ])
    assert parsers.detect_broker(p) == "tcbs"


def test_generic_fallback_when_no_broker_match(tmp_path):
    p = tmp_path / "unknown.csv"
    _write_csv(p, [
        ["date", "ticker", "side", "qty", "price"],
        ["2026-04-01", "FPT", "BUY", "100", "148500"],
    ])
    assert parsers.detect_broker(p) == "generic"


def test_parser_rejects_missing_required_column(tmp_path):
    p = tmp_path / "bad.csv"
    _write_csv(p, [
        ["date", "qty", "price"],  # no ticker, no side
        ["2026-04-01", "100", "148500"],
    ])
    with pytest.raises(parsers.ParseError):
        parsers.parse(p)


def test_parser_skips_malformed_rows(tmp_path):
    p = tmp_path / "mixed.csv"
    _write_csv(p, [
        ["date", "ticker", "side", "qty", "price"],
        ["2026-04-01 09:00:00", "FPT", "BUY", "100", "148500"],
        ["bad-date", "FPT", "BUY", "100", "148500"],   # bad datetime → skip
        ["2026-04-02 09:00:00", "FPT", "SELL", "100", "150000"],
    ])
    trades = parsers.parse(p)
    assert len(trades) == 2


def test_explicit_broker_hint(tmp_path):
    p = tmp_path / "hinted.csv"
    _write_csv(p, [
        ["Ngày giao dịch", "Mã CK", "Loại lệnh", "Khối lượng khớp", "Giá khớp"],
        ["2026-04-01 09:15:00", "VNM", "Mua", "100", "80000"],
    ])
    trades = parsers.parse(p, broker_hint="ssi")
    assert trades[0].broker == "ssi"


def test_unknown_broker_hint_raises(tmp_path):
    p = tmp_path / "x.csv"
    _write_csv(p, [
        ["date", "ticker", "side", "qty", "price"],
        ["2026-04-01", "FPT", "BUY", "100", "150000"],
    ])
    with pytest.raises(parsers.ParseError, match="unknown broker"):
        parsers.parse(p, broker_hint="notareal")  # type: ignore[arg-type]
