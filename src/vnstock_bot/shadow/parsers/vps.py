"""VPS SmartOne export format.

Typical header: "Ngày","Mã","Mua/Bán","Khối lượng","Giá","Phí GD"
"""

from __future__ import annotations

from vnstock_bot.shadow.parsers.base import BaseCSVParser


class VPSParser(BaseCSVParser):
    BROKER = "vps"

    COLUMN_MAP = {
        "traded_at": ["ngày", "ngay", "thời gian"],
        "ticker":    ["mã", "ma", "mã cp"],
        "side":      ["mua/bán", "mua ban", "mua/ban"],
        "qty":       ["khối lượng", "khoi luong", "kl"],
        "price":     ["giá", "gia", "giá gd"],
        "fee":       ["phí gd", "phi gd", "phí", "phi"],
        "trade_id":  ["mã lệnh", "ma lenh"],
    }

    @classmethod
    def detect(cls, header: list[str]) -> bool:
        lower = {h.strip().lower() for h in header}
        return (
            ("mua/bán" in lower or "mua/ban" in lower or "mua ban" in lower)
            and ("mã" in lower or "ma" in lower)
            and ("khối lượng" in lower or "khoi luong" in lower or "kl" in lower)
        )
