"""Render the dashboard HTML from one or more DashboardPayloads.

The template supports a multi-fund view: all fund payloads are embedded as JSON
and a dropdown in the header swaps which one is displayed.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.compute import AumHistoryPoint, DashboardPayload
from src.funds import Fund
from src.plays import PlayPayload


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["tojson_py"] = lambda v: json.dumps(v, default=str)
    return env


def _position_as_dict(p) -> dict:
    return {
        "issuer": p.issuer,
        "ticker": p.ticker,
        "cusip": p.cusip,
        "titleOfClass": p.title_of_class,
        "putCall": p.put_call,
        "latestShares": p.latest_shares,
        "latestValueUsd": p.latest_value_usd,
        "priorShares": p.prior_shares,
        "priorValueUsd": p.prior_value_usd,
        "pctPortfolio": p.pct_portfolio,
        "qEndPrice": p.q_end_price,
        "entryPrice": p.entry_price,
        "currentPrice": p.current_price,
        "currentValueUsd": p.current_value_usd,
        "estReturnPct": p.est_return_pct,
        "qoqSharesPct": p.qoq_shares_pct,
        "isNew": p.is_new,
        "flag": p.flag,
    }


def _play_as_dict(p: PlayPayload) -> dict:
    return {
        "name": p.name,
        "slug": p.slug,
        "thesis": p.thesis,
        "inceptionDate": p.inception_date,
        "weightsAsOf": p.weights_as_of,
        "benchmark": p.benchmark,
        "weights": p.weights,
        "hasOption": p.has_option,
        "series": p.series,
        "perTickerReturns": p.per_ticker_returns,
        "basketReturns": p.basket_returns,
        "benchmarkReturns": p.benchmark_returns,
        "droppedTickers": p.dropped_tickers,
    }


def _fund_blob(
    fund: Fund,
    payload: DashboardPayload,
    history: list[AumHistoryPoint],
    plays: list[PlayPayload],
) -> dict:
    """Serialize one fund's payload for embedding in the HTML."""
    return {
        "slug": fund.slug,
        "name": fund.name,
        "manager": fund.manager,
        "cik": fund.cik,
        "latest": {
            "accession": payload.latest.accession,
            "filing_date": payload.latest.filing_date,
            "period_of_report": payload.latest.period_of_report,
        },
        "prior": (
            {
                "accession": payload.prior.accession,
                "filing_date": payload.prior.filing_date,
                "period_of_report": payload.prior.period_of_report,
            }
            if payload.prior
            else None
        ),
        "latestTotalUsd": payload.latest_total_usd,
        "priorTotalUsd": payload.prior_total_usd,
        "positions": [_position_as_dict(p) for p in payload.positions],
        "exits": [asdict(e) for e in payload.exits],
        "aumHistory": [asdict(p) for p in (history or [])],
        "plays": [_play_as_dict(p) for p in (plays or [])],
    }


def render_dashboard(
    funds_data: list[tuple[Fund, DashboardPayload, list[AumHistoryPoint], list[PlayPayload]]],
    prices_as_of: str,
    active_slug: str | None = None,
    site_name: str | None = None,
    site_url: str | None = None,
    og_image_url: str | None = None,
    repo_url: str | None = None,
    signup_endpoint: str | None = None,
) -> str:
    """Render HTML. funds_data is a list of (Fund, payload, aum_history, plays)
    tuples. The first entry (or one matching active_slug) is shown by default.
    """
    if not funds_data:
        raise ValueError("render_dashboard: funds_data must not be empty")

    env = _env()
    tmpl = env.get_template("dashboard.html.j2")

    blobs = [_fund_blob(f, p, h, pl) for (f, p, h, pl) in funds_data]
    active = active_slug or funds_data[0][0].slug

    return tmpl.render(
        funds_json=json.dumps(blobs),
        active_slug=active,
        prices_as_of=prices_as_of,
        site_name=site_name or os.environ.get("SITE_NAME") or None,
        site_url=site_url or os.environ.get("SITE_URL") or None,
        og_image_url=og_image_url or os.environ.get("OG_IMAGE_URL") or None,
        repo_url=repo_url or os.environ.get("REPO_URL") or None,
        signup_endpoint=signup_endpoint or os.environ.get("SIGNUP_ENDPOINT") or None,
    )


def write_dashboard(
    funds_data: list[tuple[Fund, DashboardPayload, list[AumHistoryPoint], list[PlayPayload]]],
    prices_as_of: str,
    out_path: Path = Path("docs/index.html"),
    **kwargs,
) -> None:
    html = render_dashboard(funds_data, prices_as_of=prices_as_of, **kwargs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
