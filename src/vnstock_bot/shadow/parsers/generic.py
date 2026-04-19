"""Generic CSV parser — accepts a broad set of English / Vietnamese column
names. Used as fallback when no broker-specific parser matches.
"""

from __future__ import annotations

from vnstock_bot.shadow.parsers.base import BaseCSVParser


class GenericParser(BaseCSVParser):
    BROKER = "generic"

    COLUMN_MAP = {
        "traded_at": [
            "traded_at", "trade_date", "date", "datetime", "timestamp",
            "ngày", "ngày giao dịch", "thời gian", "ngay gd",
        ],
        "ticker": [
            "ticker", "symbol", "code", "mã", "mã ck", "ma ck",
            "stock", "security",
        ],
        "side": [
            "side", "action", "type", "loại", "loại lệnh", "loai lenh",
            "mua/bán", "mua ban",
        ],
        "qty": [
            "qty", "quantity", "volume", "shares", "khối lượng", "khoi luong",
            "số lượng", "so luong", "kl", "kl khớp",
        ],
        "price": [
            "price", "fill_price", "giá", "gia", "giá khớp", "gia khop",
            "giá giao dịch", "unit_price",
        ],
        "fee": [
            "fee", "commission", "phí", "phi", "phí giao dịch",
            "phi giao dich",
        ],
        "trade_id": ["trade_id", "id", "order_id", "mã lệnh", "ma lenh"],
    }

    @classmethod
    def detect(cls, header: list[str]) -> bool:
        # Generic always matches — it's the last-resort fallback. The
        # factory calls detect() in priority order, so generic is tried last.
        return True
