"""SSI iBoard export format.

Header observed:
  "Ngày giao dịch","Mã CK","Loại lệnh","Khối lượng khớp","Giá khớp","Phí"
"""

from __future__ import annotations

from vnstock_bot.shadow.parsers.base import BaseCSVParser


class SSIParser(BaseCSVParser):
    BROKER = "ssi"

    COLUMN_MAP = {
        "traded_at": ["ngày giao dịch", "ngay giao dich", "trade_date"],
        "ticker":    ["mã ck", "ma ck", "mã ck/sản phẩm"],
        "side":      ["loại lệnh", "loai lenh"],
        "qty":       ["khối lượng khớp", "kl khớp", "khoi luong khop"],
        "price":     ["giá khớp", "gia khop"],
        "fee":       ["phí", "phi"],
        "trade_id":  ["mã lệnh", "ma lenh", "số lệnh"],
    }

    @classmethod
    def detect(cls, header: list[str]) -> bool:
        lower = {h.strip().lower() for h in header}
        # SSI has all these three in combination
        return (
            "mã ck" in lower
            and ("loại lệnh" in lower or "loai lenh" in lower)
            and ("khối lượng khớp" in lower or "kl khớp" in lower
                 or "khoi luong khop" in lower)
        )
