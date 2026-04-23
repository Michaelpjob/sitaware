"""Price fetcher using yfinance.

- `get_current(ticker)` returns the most recent close/last trade.
- `get_quarterly_avg(ticker, period_date)` returns the mean closing price over the
  quarter that `period_date` falls in — used as a cost-basis proxy.

yfinance is stateless and rate-limit-tolerant, but we still cache results for a
single run to avoid repeat hits.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from functools import lru_cache

import yfinance as yf

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
