"""Base class for broker CSV parsers + shared normalization helpers.

All broker-specific parsers inherit from `BaseCSVParser` and override
`COLUMN_MAP` + (optionally) `detect()` and `_transform_row()`.
"""

from __future__ import annotations

import csv
import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from vnstock_bot.shadow.types import Broker, RawTrade


class ParseError(Exception):
    pass


_NUMERIC_RE = re.compile(r"[^\d\-\.]")
_THOUSANDS_DOT_RE = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


def to_int(value: object, default: int = 0) -> int:
    """Accept '100,000', '100.000' (VN thousands), '100000', '100 000',
    int, float. VN stock prices are integer VND — never fractional — so
    a string like '148.500' is always 148,500 (not 148.5)."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    if not s:
        return default
    s = _NUMERIC_RE.sub("", s)
    if not s or s in ("-", ".", "-."):
        return default
    # Recognize VN thousands-dot format: '148.500', '1.234.567' → strip dots.
    if _THOUSANDS_DOT_RE.match(s):
        s = s.replace(".", "")
    try:
        return int(float(s))
    except ValueError:
        return default


def parse_datetime(value: str, default: str | None = None) -> str:
    """Try a handful of common VN broker formats, return ISO string."""
    if not value:
        if default is None:
            raise ParseError("empty datetime")
        return default
    value = value.strip()
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(value, fmt).isoformat()
        except ValueError:
            continue
    if default is not None:
        return default
    raise ParseError(f"unrecognized datetime format: {value!r}")


def parse_side(value: object) -> str:
    s = str(value or "").strip().upper()
    if s in {"BUY", "B", "MUA", "LONG", "MUA KHỚP"}:
        return "BUY"
    if s in {"SELL", "S", "BAN", "BÁN", "SHORT", "BAN KHOP", "BÁN KHỚP"}:
        return "SELL"
    raise ParseError(f"unrecognized side: {value!r}")


class BaseCSVParser(ABC):
    BROKER: ClassVar[Broker] = "generic"

    # Keys are RawTrade fields; values are a list of acceptable CSV header
    # names (case-insensitive, stripped). First match wins.
    COLUMN_MAP: ClassVar[dict[str, list[str]]] = {}

    @classmethod
    @abstractmethod
    def detect(cls, header: list[str]) -> bool:
        """Return True if `header` matches this parser's expected schema."""

    # ------------------------------------------------------------ shared impl

    @classmethod
    def _find_col(cls, header: list[str], aliases: list[str]) -> int | None:
        lower = [h.strip().lower() for h in header]
        for alias in aliases:
            al = alias.strip().lower()
            if al in lower:
                return lower.index(al)
        return None

    @classmethod
    def parse(cls, path: Path | str) -> list[RawTrade]:
        path = Path(path)
        with path.open("r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration as e:
                raise ParseError("empty file") from e

            col_map: dict[str, int] = {}
            for field, aliases in cls.COLUMN_MAP.items():
                idx = cls._find_col(header, aliases)
                if idx is not None:
                    col_map[field] = idx

            missing = {"traded_at", "ticker", "side", "qty", "price"} - set(col_map)
            if missing:
                raise ParseError(
                    f"{cls.BROKER}: missing required columns {sorted(missing)} "
                    f"in header {header}"
                )

            trades: list[RawTrade] = []
            for row in reader:
                if not row or all(not c for c in row):
                    continue
                try:
                    t = cls._row_to_trade(row, col_map)
                except ParseError:
                    continue
                except (ValueError, IndexError):
                    continue
                trades.append(t)
            return trades

    @classmethod
    def _row_to_trade(cls, row: list[str], col_map: dict[str, int]) -> RawTrade:
        def get(field: str, default: str = "") -> str:
            idx = col_map.get(field)
            if idx is None or idx >= len(row):
                return default
            return (row[idx] or "").strip()

        return RawTrade(
            traded_at=parse_datetime(get("traded_at")),
            ticker=get("ticker").upper(),
            side=parse_side(get("side")),  # type: ignore[arg-type]
            qty=to_int(get("qty")),
            price=to_int(get("price")),
            fee=to_int(get("fee"), default=0),
            broker=cls.BROKER,
            trade_id=get("trade_id") or None,
        )
