"""Thin wrapper over the vnstock library.

vnstock's API has evolved across versions. We wrap it defensively so callers
see a stable interface and failures degrade to "no data" rather than crashes.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pandas as pd

from vnstock_bot.data import _silence_vnstock  # noqa: F401  (side-effect import)
from vnstock_bot.data.holidays import iso
from vnstock_bot.logging_setup import get_logger

log = get_logger(__name__)


# vnstock Guest tier: 20 requests/minute. We throttle at ~17/min to be safe.
_THROTTLE_MIN_INTERVAL = 3.5  # seconds between calls
_last_call_ts: float = 0.0
_throttle_lock = threading.Lock()


def _throttle() -> None:
    global _last_call_ts
    with _throttle_lock:
        now = time.monotonic()
        wait = _THROTTLE_MIN_INTERVAL - (now - _last_call_ts)
        if wait > 0:
            time.sleep(wait)
        _last_call_ts = time.monotonic()


@dataclass
class OHLCBar:
    date: str            # ISO
    open: int            # VND
    high: int
    low: int
    close: int
    volume: int


def _to_int_vnd(x: float | int | None) -> int:
    """vnstock often returns price in thousands. We coerce to VND int.
    Heuristic: if value < 10000 we assume it's in 1000s (chuẩn VND sàn) -> *1000.
    Else assume already VND.
    """
    if x is None or pd.isna(x):
        return 0
    f = float(x)
    if f < 10_000:  # e.g. 148.5 -> 148,500 VND
        return int(round(f * 1000))
    return int(round(f))


def _get_quote(ticker: str, source: str = "VCI"):
    """Return a vnstock Quote instance. Bypasses the buggy Vnstock().stock()
    wrapper which eagerly inits Company and can crash on upstream API changes.
    """
    if source == "VCI":
        from vnstock.explorer.vci import Quote
    elif source == "TCBS":
        from vnstock.explorer.tcbs import Quote
    else:
        from vnstock.explorer.vci import Quote
    return Quote(symbol=ticker)


def fetch_ohlc(ticker: str, start: date, end: date, source: str = "VCI") -> list[OHLCBar]:
    """Fetch OHLC between [start, end] inclusive."""
    _throttle()
    try:
        q = _get_quote(ticker, source)
        df = q.history(start=iso(start), end=iso(end), interval="1D")
    except Exception as e:  # noqa: BLE001
        log.warning("vnstock_fetch_failed", ticker=ticker, error=str(e))
        return []

    if df is None or len(df) == 0:
        return []

    # Normalize column names (vnstock sometimes uses lowercase time/open/...)
    df = df.rename(columns={c: c.lower() for c in df.columns})
    bars: list[OHLCBar] = []
    for _, row in df.iterrows():
        d_raw = row.get("time") or row.get("date")
        try:
            d_iso = pd.to_datetime(d_raw).date().isoformat()
        except Exception:  # noqa: BLE001
            continue
        bars.append(OHLCBar(
            date=d_iso,
            open=_to_int_vnd(row.get("open")),
            high=_to_int_vnd(row.get("high")),
            low=_to_int_vnd(row.get("low")),
            close=_to_int_vnd(row.get("close")),
            volume=int(row.get("volume") or 0),
        ))
    return bars


def fetch_index(ticker: str, start: date, end: date) -> list[OHLCBar]:
    """Fetch index OHLC (VNINDEX, VN30, HNXINDEX). Price is index points, not VND."""
    _throttle()
    try:
        q = _get_quote(ticker, source="VCI")
        df = q.history(start=iso(start), end=iso(end), interval="1D")
    except Exception as e:  # noqa: BLE001
        log.warning("vnindex_fetch_failed", ticker=ticker, error=str(e))
        return []
    if df is None or len(df) == 0:
        return []
    df = df.rename(columns={c: c.lower() for c in df.columns})
    bars: list[OHLCBar] = []
    for _, row in df.iterrows():
        d_raw = row.get("time") or row.get("date")
        try:
            d_iso = pd.to_datetime(d_raw).date().isoformat()
        except Exception:  # noqa: BLE001
            continue
        # For index, keep raw float (we store open/close/etc as-is in "index" path).
        # But OHLCBar is int — we use *100 to preserve 2 decimals as int.
        def _pts(v: Any) -> int:
            try:
                return int(round(float(v) * 100))
            except Exception:  # noqa: BLE001
                return 0
        bars.append(OHLCBar(
            date=d_iso,
            open=_pts(row.get("open")),
            high=_pts(row.get("high")),
            low=_pts(row.get("low")),
            close=_pts(row.get("close")),
            volume=int(row.get("volume") or 0),
        ))
    return bars


def _extract_ratios(latest: dict[str, Any]) -> dict[str, Any]:
    """Flatten broker-specific column names into our canonical dict."""
    return {
        "roe": latest.get("roe") or latest.get("ROE"),
        "pe": latest.get("priceToEarning") or latest.get("pe") or latest.get("PE"),
        "pb": latest.get("priceToBook") or latest.get("pb") or latest.get("PB"),
        "debt_to_equity": latest.get("debtOnEquity") or latest.get("de"),
        "eps": latest.get("earningPerShare") or latest.get("eps"),
        "revenue_growth": latest.get("revenueGrowth"),
        "profit_growth": latest.get("postTaxOnEquity") or latest.get("profitGrowth"),
        "raw": {
            k: (float(v) if isinstance(v, (int, float)) else str(v))
            for k, v in latest.items()
            if v is not None
        },
    }


def fetch_fundamentals(ticker: str) -> dict[str, Any]:
    """Return a minimal dict of fundamental ratios. Best-effort — tries
    TCBS first, falls back to VCI, returns empty dict if both fail.

    BUG-2: recent vnstock versions have removed/renamed `explorer.tcbs`,
    so MWG/MSN fundamentals silently failed with 'No module named
    vnstock.explorer.tcbs'. We now swallow ImportError at the provider
    level and fall through to the next provider.
    """
    _throttle()
    errors: list[str] = []

    # Try TCBS first (historical default; richer ratio coverage when available)
    try:
        from vnstock.explorer.tcbs import Finance as TCBSFinance  # type: ignore
        fin = TCBSFinance(symbol=ticker)
        ratios = getattr(fin, "ratio", None)
        if ratios is not None:
            df = ratios(period="year", lang="en")
            if df is not None and len(df) > 0:
                return _extract_ratios(df.iloc[0].to_dict())
    except ImportError as e:
        errors.append(f"tcbs: {e}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"tcbs_runtime: {e}")

    # Fallback to VCI
    try:
        from vnstock.explorer.vci import Finance as VCIFinance  # type: ignore
        fin = VCIFinance(symbol=ticker)
        ratios = getattr(fin, "ratio", None)
        if ratios is not None:
            df = ratios(period="year", lang="en")
            if df is not None and len(df) > 0:
                return _extract_ratios(df.iloc[0].to_dict())
    except ImportError as e:
        errors.append(f"vci: {e}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"vci_runtime: {e}")

    if errors:
        log.warning("fundamentals_fetch_failed", ticker=ticker,
                    errors=errors)
    return {}


def fetch_foreign_flow(days: int = 20) -> list[dict[str, Any]]:
    """Fetch foreign net buy/sell per day across market. Best-effort."""
    _throttle()
    try:
        from vnstock.explorer.vci import Trading  # type: ignore
        end = date.today()
        start = end - timedelta(days=days * 2)
        tr = Trading(symbol="VN30")
        fn = getattr(tr, "foreign_net", None)
        if fn is None:
            return []
        df = fn(start=iso(start), end=iso(end))
        if df is None or len(df) == 0:
            return []
        df = df.rename(columns={c: c.lower() for c in df.columns})
        out: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            out.append({
                "date": pd.to_datetime(row.get("time") or row.get("date")).date().isoformat(),
                "net_vnd": int(float(row.get("net_value") or row.get("value") or 0)),
            })
        return out
    except Exception as e:  # noqa: BLE001
        log.warning("foreign_flow_fetch_failed", error=str(e))
        return []
