from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import yaml

from vnstock_bot.config import get_settings


@dataclass(frozen=True)
class WatchlistEntry:
    ticker: str
    exchange: str
    sector: str


@dataclass(frozen=True)
class Watchlist:
    tickers: tuple[WatchlistEntry, ...]
    indices: tuple[str, ...]

    def has(self, ticker: str) -> bool:
        return any(t.ticker == ticker for t in self.tickers)

    def get(self, ticker: str) -> WatchlistEntry | None:
        return next((t for t in self.tickers if t.ticker == ticker), None)

    def sector_of(self, ticker: str) -> str | None:
        entry = self.get(ticker)
        return entry.sector if entry else None

    def exchange_of(self, ticker: str) -> str | None:
        entry = self.get(ticker)
        return entry.exchange if entry else None


@lru_cache(maxsize=1)
def load_watchlist() -> Watchlist:
    path = get_settings().watchlist_path
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    tickers = tuple(
        WatchlistEntry(ticker=t["ticker"], exchange=t["exchange"], sector=t["sector"])
        for t in raw.get("tickers", [])
    )
    indices = tuple(raw.get("indices", []))
    return Watchlist(tickers=tickers, indices=indices)
