"""Render the dashboard HTML from a DashboardPayload using Jinja2."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from src.compute import AumHistoryPoint, DashboardPayload


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["tojson_py"] = lambda v: json.dumps(v, default=str)
    return env


def render_dashboard(
    payload: DashboardPayload,
    aum_history: list[AumHistoryPoint] | None = None,
    site_name: str | None = None,
    site_url: str | None = None,
    og_image_url: str | None = None,
    repo_url: str | None = None,
    signup_endpoint: str | None = None,
) -> str:
    """Render HTML. Optional site/branding/signup hooks come from env or kwargs."""
    env = _env()
    tmpl = env.get_template("dashboard.html.j2")

    positions_json = [_position_as_dict(p) for p in payload.positions]
    exits_json = [asdict(e) for e in payload.exits]
    history_json = [asdict(p) for p in (aum_history or [])]

    return tmpl.render(
        filer_name=payload.filer_name,
        cik=payload.cik,
        latest=payload.latest,
        prior=payload.prior,
        latest_total_usd=payload.latest_total_usd,
        prior_total_usd=payload.prior_total_usd,
        prices_as_of=payload.prices_as_of,
        positions_json=json.dumps(positions_json),
        exits_json=json.dumps(exits_json),
        aum_history_json=json.dumps(history_json),
        site_name=site_name or os.environ.get("SITE_NAME") or None,
        site_url=site_url or os.environ.get("SITE_URL") or None,
        og_image_url=og_image_url or os.environ.get("OG_IMAGE_URL") or None,
        repo_url=repo_url or os.environ.get("REPO_URL") or None,
        signup_endpoint=signup_endpoint or os.environ.get("SIGNUP_ENDPOINT") or None,
    )


def _position_as_dict(p) -> dict:
    """Convert an EnrichedPosition to a JSON-serializable dict."""
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


def write_dashboard(
    payload: DashboardPayload,
    aum_history: list[AumHistoryPoint] | None = None,
    out_path: Path = Path("docs/index.html"),
    **kwargs,
) -> None:
    html = render_dashboard(payload, aum_history=aum_history, **kwargs)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
