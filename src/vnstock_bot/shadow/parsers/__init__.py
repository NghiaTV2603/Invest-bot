"""Broker CSV parser factory.

`parse(path)` auto-detects which broker format the file is in by peeking
at the header row. Detection order (most specific first):
  ssi → vps → tcbs → generic fallback.
"""

from __future__ import annotations

import csv
from pathlib import Path

from vnstock_bot.shadow.parsers.base import BaseCSVParser, ParseError
from vnstock_bot.shadow.parsers.generic import GenericParser
from vnstock_bot.shadow.parsers.ssi import SSIParser
from vnstock_bot.shadow.parsers.tcbs import TCBSParser
from vnstock_bot.shadow.parsers.vps import VPSParser
from vnstock_bot.shadow.types import Broker, RawTrade

_PARSERS: tuple[type[BaseCSVParser], ...] = (
    SSIParser, VPSParser, TCBSParser, GenericParser,
)


def _peek_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        try:
            return next(reader)
        except StopIteration as e:
            raise ParseError("empty file") from e


def detect_broker(path: Path | str) -> Broker:
    header = _peek_header(Path(path))
    for parser_cls in _PARSERS:
        if parser_cls is GenericParser:
            continue
        if parser_cls.detect(header):
            return parser_cls.BROKER
    return "generic"


def parse(path: Path | str, broker_hint: Broker | str = "auto") -> list[RawTrade]:
    """Parse a broker CSV. `broker_hint` may be 'auto' or a specific broker."""
    p = Path(path)
    if broker_hint and broker_hint != "auto":
        cls = {pc.BROKER: pc for pc in _PARSERS}.get(broker_hint)  # type: ignore[arg-type]
        if cls is None:
            raise ParseError(
                f"unknown broker {broker_hint!r}; "
                f"known: {[pc.BROKER for pc in _PARSERS]}"
            )
        return cls.parse(p)

    header = _peek_header(p)
    for parser_cls in _PARSERS:
        if parser_cls.detect(header):
            return parser_cls.parse(p)
    raise ParseError(f"no parser matched header: {header}")


__all__ = [
    "parse",
    "detect_broker",
    "BaseCSVParser",
    "ParseError",
    "GenericParser",
    "SSIParser",
    "TCBSParser",
    "VPSParser",
]
