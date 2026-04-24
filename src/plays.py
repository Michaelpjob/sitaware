"""Compute basket performance for a Play.

A Play is a curated subset of a fund's 13F holdings that expresses a headline
thesis. Weights come from the latest filing, normalized to 1.0 within the
basket. Returns are weighted daily returns of the basket, rebased to 100 at
each window's start so the chart is comparable to the benchmark.

Simplifications (V1):
  - Current weights, historical prices — no quarterly rebalancing.
  - Call-option rows contribute at notional value (weight) but use the
    underlying stock's price return (not option P&L).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import pandas as pd

from src import prices
from src.edgar import Holding
from src.funds import Fund, Play

log = logging.getLogger(__name__)

WINDOWS = ("1D", "7D", "30D", "YTD", "1Y", "INCEPTION")


@dataclass
class PlayPayload:
    name: str
    slug: str
    thesis: str
    inception_date: str
    weights_as_of: str              # latest filing date — for footnote
    benchmark: str
    weights: dict[str, float]       # ticker → normalized weight (sum = 1.0)
    has_option: dict[str, bool]     # ticker → True if position was held via options
    # Time-series per window. Each: {dates: [ISO], basket: [float], benchmark: [float]}
    # Values rebased to 100 at window start.
    series: dict[str, dict]
    # Per-ticker return for each window. {ticker: {window: pct}}
    per_ticker_returns: dict[str, dict[str, float | None]]
    # Whole-basket return per window (for summary chip above the chart).
    basket_returns: dict[str, float | None]
    benchmark_returns: dict[str, float | None]
    dropped_tickers: list[str]      # configured but not found in the 13F


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(weights.values())
    if total <= 0:
        return {}
    return {t: v / total for t, v in weights.items()}


def _basket_weights(
    play: Play,
    latest_holdings: list[Holding],
    ticker_map: dict[str, str | None],
) -> tuple[dict[str, float], dict[str, bool], list[str]]:
    """Compute raw ticker weights (in dollars) and option flags from the 13F.

    Returns (normalized_weights, has_option_flags, dropped_tickers).
    """
    wanted = {t.upper() for t in play.tickers}
    raw: dict[str, float] = {t: 0.0 for t in wanted}
    opt_value: dict[str, float] = {t: 0.0 for t in wanted}  # dollars held in options

    for h in latest_holdings:
        ticker = (ticker_map.get(h.cusip) or "").upper()
        if ticker not in wanted:
            continue
        v = float(h.value_usd)
        raw[ticker] += v
        if h.put_call:
            opt_value[ticker] += v

    # Flag with CALL/PUT badge only if the majority of the ticker's dollar
    # weight comes from options — avoids a misleading badge when a fund holds
    # mostly common stock plus a small hedge/call.
    has_opt: dict[str, bool] = {
        t: raw[t] > 0 and (opt_value[t] / raw[t]) >= 0.5 for t in wanted
    }

    dropped = [t for t in play.tickers if raw.get(t.upper(), 0) <= 0]
    present = {t: v for t, v in raw.items() if v > 0}
    return _normalize(present), {t: has_opt[t] for t in present}, dropped


def _window_start(window: str, today: date, inception: date) -> date | None:
    if window == "1D":
        return today - timedelta(days=1)
    if window == "7D":
        return today - timedelta(days=7)
    if window == "30D":
        return today - timedelta(days=30)
    if window == "YTD":
        return date(today.year, 1, 1)
    if window == "1Y":
        return today - timedelta(days=365)
    if window == "INCEPTION":
        return inception
    return None


def _pct_change(s: pd.Series) -> pd.Series:
    return s.pct_change().fillna(0.0)


def _index_series(daily_returns: pd.Series) -> pd.Series:
    """Convert a daily-return series to a 100-rebased index."""
    return (1.0 + daily_returns).cumprod() * 100.0


def compute_play_payload(
    fund: Fund,
    play: Play,
    latest_holdings: list[Holding],
    ticker_map: dict[str, str | None],
    weights_as_of: str,
    today: date | None = None,
) -> PlayPayload:
    """Build a fully-populated PlayPayload for the template."""
    today = today or date.today()
    inception = datetime.fromisoformat(play.inception_date).date()

    weights, has_option, dropped = _basket_weights(play, latest_holdings, ticker_map)

    if not weights:
        log.warning("Play %s/%s: no basket tickers present in 13F; skipping.", fund.slug, play.slug)
        return PlayPayload(
            name=play.name, slug=play.slug, thesis=play.thesis,
            inception_date=play.inception_date, weights_as_of=weights_as_of,
            benchmark=play.benchmark,
            weights={}, has_option={}, series={}, per_ticker_returns={},
            basket_returns={w: None for w in WINDOWS},
            benchmark_returns={w: None for w in WINDOWS},
            dropped_tickers=list(play.tickers),
        )

    # Fetch price history for basket + benchmark over the whole window.
    # Start slightly before inception so the first daily-return at inception is valid.
    fetch_start = inception - timedelta(days=10)
    all_tickers = list(weights.keys()) + [play.benchmark]
    prices_df = prices.get_price_history(all_tickers, fetch_start, today)

    if prices_df.empty:
        log.warning("Play %s/%s: price history empty.", fund.slug, play.slug)
        return PlayPayload(
            name=play.name, slug=play.slug, thesis=play.thesis,
            inception_date=play.inception_date, weights_as_of=weights_as_of,
            benchmark=play.benchmark,
            weights=weights, has_option=has_option,
            series={}, per_ticker_returns={},
            basket_returns={w: None for w in WINDOWS},
            benchmark_returns={w: None for w in WINDOWS},
            dropped_tickers=dropped,
        )

    prices_df = prices_df.sort_index().ffill()
    # Daily returns per ticker (NaN fills to 0 so newly-listed tickers contribute 0 pre-IPO).
    daily_rets = prices_df.apply(_pct_change)

    # Weighted basket daily return.
    basket_daily = pd.Series(0.0, index=daily_rets.index)
    for t, w in weights.items():
        if t in daily_rets.columns:
            basket_daily = basket_daily + daily_rets[t].fillna(0.0) * w
    basket_index = _index_series(basket_daily)

    benchmark_index = _index_series(
        daily_rets[play.benchmark].fillna(0.0)
        if play.benchmark in daily_rets.columns
        else pd.Series(0.0, index=daily_rets.index)
    )

    # Build series per window, rebased to 100 at window start.
    series: dict[str, dict] = {}
    basket_returns: dict[str, float | None] = {}
    benchmark_returns: dict[str, float | None] = {}

    for window in WINDOWS:
        start = _window_start(window, today, inception)
        if start is None:
            continue
        start_ts = pd.Timestamp(start)
        # Find the first trading-day index >= start.
        candidates = basket_index.index[basket_index.index >= start_ts]
        if len(candidates) == 0:
            series[window] = {"dates": [], "basket": [], "benchmark": []}
            basket_returns[window] = None
            benchmark_returns[window] = None
            continue
        start_idx = candidates[0]
        slice_basket = basket_index.loc[start_idx:]
        slice_bench = benchmark_index.loc[start_idx:]
        if slice_basket.empty:
            series[window] = {"dates": [], "basket": [], "benchmark": []}
            basket_returns[window] = None
            benchmark_returns[window] = None
            continue
        # Rebase to 100 at the window's start so ratio comparisons line up.
        rebase_basket = (slice_basket / slice_basket.iloc[0]) * 100.0
        rebase_bench = (slice_bench / slice_bench.iloc[0]) * 100.0 if not slice_bench.empty else slice_bench
        series[window] = {
            "dates": [d.date().isoformat() for d in rebase_basket.index],
            "basket": [None if math.isnan(v) else round(float(v), 4) for v in rebase_basket.values],
            "benchmark": [
                None if (i >= len(rebase_bench) or math.isnan(rebase_bench.iloc[i])) else round(float(rebase_bench.iloc[i]), 4)
                for i in range(len(rebase_basket))
            ],
        }
        basket_returns[window] = round(float(rebase_basket.iloc[-1]) / 100.0 - 1.0, 4)
        benchmark_returns[window] = (
            round(float(rebase_bench.iloc[-1]) / 100.0 - 1.0, 4)
            if not rebase_bench.empty else None
        )

    # Per-ticker returns across windows.
    per_ticker_returns: dict[str, dict[str, float | None]] = {}
    for t in weights.keys():
        per_ticker_returns[t] = {}
        if t not in prices_df.columns:
            for w in WINDOWS:
                per_ticker_returns[t][w] = None
            continue
        col = prices_df[t].dropna()
        for window in WINDOWS:
            start = _window_start(window, today, inception)
            if start is None:
                per_ticker_returns[t][window] = None
                continue
            start_ts = pd.Timestamp(start)
            candidates = col.index[col.index >= start_ts]
            if len(candidates) == 0 or col.empty:
                per_ticker_returns[t][window] = None
                continue
            start_idx = candidates[0]
            start_val = float(col.loc[start_idx])
            end_val = float(col.iloc[-1])
            if start_val <= 0:
                per_ticker_returns[t][window] = None
            else:
                per_ticker_returns[t][window] = round(end_val / start_val - 1.0, 4)

    return PlayPayload(
        name=play.name,
        slug=play.slug,
        thesis=play.thesis,
        inception_date=play.inception_date,
        weights_as_of=weights_as_of,
        benchmark=play.benchmark,
        weights=weights,
        has_option=has_option,
        series=series,
        per_ticker_returns=per_ticker_returns,
        basket_returns=basket_returns,
        benchmark_returns=benchmark_returns,
        dropped_tickers=dropped,
    )
