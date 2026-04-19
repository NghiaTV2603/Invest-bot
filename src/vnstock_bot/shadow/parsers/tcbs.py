"""TCBS (Techcom Securities) export format."""

from __future__ import annotations

from vnstock_bot.shadow.parsers.base import BaseCSVParser


class TCBSParser(BaseCSVParser):
    BROKER = "tcbs"

    COLUMN_MAP = {
        "traded_at": ["ngày gd", "ngay gd", "trade date"],
        "ticker":    ["ticker", "mã chứng khoán", "ma ck"],
        "side":      ["loại gd", "loai gd", "side"],
        "qty":       ["khối lượng khớp", "kl khớp", "qty matched"],
        "price":     ["giá khớp", "gia khop", "match price"],
        "fee":       ["phí gd", "phi gd", "fee"],
        "trade_id":  ["order id", "mã lệnh"],
    }

    @classmethod
    def detect(cls, header: list[str]) -> bool:
        lower = {h.strip().lower() for h in header}
        return (
            ("loại gd" in lower or "loai gd" in lower)
            and ("ticker" in lower or "mã chứng khoán" in lower or "ma ck" in lower)
        )
