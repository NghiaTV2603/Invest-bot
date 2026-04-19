from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from vnstock_bot.config import get_settings
from vnstock_bot.data.holidays import iso


def dump_ohlc_parquet(ticker: str, bars: list[dict]) -> Path:
    """Dump raw bars to parquet under data/raw/<ticker>/<date>.parquet."""
    if not bars:
        return Path()
    settings = get_settings()
    folder = settings.absolute_raw_dir / ticker
    folder.mkdir(parents=True, exist_ok=True)
    latest_date = max(b["date"] for b in bars)
    path = folder / f"{latest_date}.parquet"
    df = pd.DataFrame(bars)
    df.to_parquet(path, index=False)
    return path


def daily_snapshot_path(d: date) -> Path:
    return get_settings().absolute_raw_dir / "_snapshot" / f"{iso(d)}.parquet"
