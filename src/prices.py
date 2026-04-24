"""Price fetcher using yfinance.

- `get_current(ticker)` returns the most recent close/last trade.
- `get_quarterly_avg(ticker, period_date)` returns the mean closing price over the
  quarter that `period_date` falls in — used as a cost-basis proxy.
- `get_price_history(tickers, start, end)` returns a daily-close DataFrame for a
  whole basket, disk-cached at data/price_cache/<ticker>.csv so repeat runs only
  fetch the tail.

yfinance is stateless and rate-limit-tolerant, but we still cache results for a
single run to avoid repeat hits.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yfinance as yf

PRICE_CACHE_DIR = Path("data/price_cache")
STALE_DAYS = 1  # refresh cache tail if latest cached date is > this many calendar days old

log = logging.getLogger(__name__)


def _quarter_bounds(d: date) -> tuple[date, date]:
    """Return (start, end) dates for the calendar quarter containing d."""
    q = (d.month - 1) // 3
    start_month = q * 3 + 1
    start = date(d.year, start_month, 1)
    end_month = start_month + 2
    if end_month == 12:
        end = date(d.year, 12, 31)
    else:
        end = date(d.year, end_month + 1, 1) - timedelta(days=1)
    return start, end


@lru_cache(maxsize=256)
def get_current(ticker: str) -> float | None:
    """Most recent daily close for a ticker. Returns None if unknown."""
    if not ticker:
        return None
    try:
        hist = yf.Ticker(ticker).history(period="5d", auto_adjust=False)
        if hist.empty:
            log.warning("No recent history for %s", ticker)
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as exc:
        log.warning("yfinance failed for %s: %s", ticker, exc)
        return None


@lru_cache(maxsize=512)
def get_quarterly_avg(ticker: str, period_date_iso: str) -> float | None:
    """Mean daily close over the quarter containing `period_date_iso` (YYYY-MM-DD)."""
    if not ticker:
        return None
    try:
        d = datetime.fromisoformat(period_date_iso).date()
        start, end = _quarter_bounds(d)
        # yfinance end is exclusive; pad by a day.
        hist = yf.Ticker(ticker).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=False,
        )
        if hist.empty:
            return None
        return float(hist["Close"].mean())
    except Exception as exc:
        log.warning("yfinance quarterly avg failed for %s: %s", ticker, exc)
        return None


@lru_cache(maxsize=256)
def get_quarter_end_close(ticker: str, period_date_iso: str) -> float | None:
    """Closing price on the last trading day of the quarter ending period_date_iso."""
    if not ticker:
        return None
    try:
        d = datetime.fromisoformat(period_date_iso).date()
        start = d - timedelta(days=7)
        end = d + timedelta(days=2)
        hist = yf.Ticker(ticker).history(
            start=start.isoformat(), end=end.isoformat(), auto_adjust=False
        )
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception as exc:
        log.warning("yfinance Q-end close failed for %s: %s", ticker, exc)
        return None


def clear_cache() -> None:
    get_current.cache_clear()
    get_quarterly_avg.cache_clear()
    get_quarter_end_close.cache_clear()


def _cache_path(ticker: str) -> Path:
    return PRICE_CACHE_DIR / f"{ticker.upper()}.csv"


def _load_cached_series(ticker: str) -> pd.Series | None:
    p = _cache_path(ticker)
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p, parse_dates=["date"], index_col="date")
        s = df["close"].astype(float)
        s.name = ticker
        return s
    except Exception as exc:
        log.warning("Failed to read price cache for %s: %s. Ignoring.", ticker, exc)
        return None


def _save_cached_series(ticker: str, s: pd.Series) -> None:
    PRICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df = s.to_frame("close").reset_index().rename(columns={"index": "date", s.index.name or "Date": "date"})
    # Some index names come through as "Date" from yfinance; normalize.
    if "date" not in df.columns:
        df = df.rename(columns={df.columns[0]: "date"})
    df.to_csv(_cache_path(ticker), index=False)


def _fetch_one(ticker: str, start: date, end: date) -> pd.Series:
    """Raw yfinance download for a single ticker → daily Close series."""
    hist = yf.Ticker(ticker).history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=False,
    )
    if hist.empty:
        return pd.Series(dtype="float64", name=ticker)
    s = hist["Close"].astype(float)
    s.index = pd.DatetimeIndex(s.index.date)  # drop intraday TZ, keep calendar date
    s.name = ticker
    return s


def get_price_history(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    """Daily close prices as a DataFrame indexed by date, columns = tickers.

    Uses a disk cache at `data/price_cache/<ticker>.csv`. Only the tail (from
    the latest cached date forward) is fetched on subsequent runs — so repeat
    CI runs for unchanged baskets are fast and free.
    """
    unique_tickers = list(dict.fromkeys(t.upper() for t in tickers if t))
    today = date.today()
    columns = {}

    for t in unique_tickers:
        cached = _load_cached_series(t)
        if cached is None or cached.empty:
            fetched = _fetch_one(t, start, end)
            if not fetched.empty:
                _save_cached_series(t, fetched)
            columns[t] = fetched
            continue

        cached_end = cached.index.max().date()
        if cached_end >= today - timedelta(days=STALE_DAYS):
            columns[t] = cached
            continue

        # Refresh the tail.
        tail_start = cached_end + timedelta(days=1)
        tail = _fetch_one(t, tail_start, end)
        merged = pd.concat([cached, tail])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        _save_cached_series(t, merged)
        columns[t] = merged

    if not columns:
        return pd.DataFrame()

    df = pd.concat(columns.values(), axis=1, keys=columns.keys())
    # Trim to the requested window.
    mask = (df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))
    return df.loc[mask]
