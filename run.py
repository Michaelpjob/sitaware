"""Main CLI entry point — multi-fund tracker.

Iterates over the funds configured in `src/funds.py`, fetches each fund's
13F filings, renders a single dashboard HTML with a fund dropdown.

Usage:
  python run.py                     # normal run (all funds)
  python run.py --force             # regenerate dashboard even if no new filings
  python run.py --dry-run           # check EDGAR only, write nothing
  python run.py --fund sa-lp        # run only one fund
  python run.py --no-email          # skip email alerts
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

import click
from dotenv import load_dotenv

from src import alert, compute, edgar, prices, render
from src.compute import AumHistoryPoint
from src.cusip_map import CusipResolver
from src.funds import FUNDS, Fund, fund_by_slug

load_dotenv()
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stderr,
)
log = logging.getLogger("run")

STATE_PATH = Path("data/state.json")
HISTORY_PATH = Path("data/aum_history.json")


def _load_state() -> dict:
    """State is { "version": 2, "funds": { <cik>: {...} } }.

    Migrates a v1 single-fund flat file (with top-level last_accession) into
    v2 under the SA LP CIK so existing installs don't re-alert.
    """
    if not STATE_PATH.exists():
        return {"version": 2, "funds": {}}
    raw = json.loads(STATE_PATH.read_text())
    if raw.get("version") == 2:
        return raw
    # v1 → v2 migration: move top-level fields under SA LP's CIK.
    if "last_accession" in raw:
        log.info("Migrating state.json v1 → v2 (single-fund flat → per-CIK).")
        return {
            "version": 2,
            "funds": {"0002045724": {
                "last_accession": raw.get("last_accession"),
                "last_period": raw.get("last_period"),
                "last_run": raw.get("last_run"),
            }},
        }
    return {"version": 2, "funds": {}}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def _load_history_all() -> dict[str, dict[str, AumHistoryPoint]]:
    """AUM history is keyed by CIK: { cik: { accession: point } }.

    Migrates old flat format (just a list of points for SA LP) into the per-CIK
    dict the multi-fund pipeline uses.
    """
    if not HISTORY_PATH.exists():
        return {}
    try:
        raw = json.loads(HISTORY_PATH.read_text())
    except Exception as exc:
        log.warning("Failed to read %s: %s. Starting fresh.", HISTORY_PATH, exc)
        return {}
    # v1 flat list → migrate to SA LP.
    if isinstance(raw, list):
        log.info("Migrating aum_history.json list → per-CIK map.")
        return {
            "0002045724": {p["accession"]: AumHistoryPoint(**p) for p in raw},
        }
    # v2 is already a dict keyed by CIK.
    out: dict[str, dict[str, AumHistoryPoint]] = {}
    for cik, points in raw.items():
        out[cik] = {p["accession"]: AumHistoryPoint(**p) for p in points}
    return out


def _save_history_all(by_cik: dict[str, dict[str, AumHistoryPoint]]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = {}
    for cik, points in by_cik.items():
        out[cik] = [asdict(p) for p in sorted(points.values(), key=lambda p: p.period)]
    HISTORY_PATH.write_text(json.dumps(out, indent=2) + "\n")


def _ensure_history(
    cik: str,
    cached: dict[str, AumHistoryPoint],
    target_quarters: int,
    prefetched: dict[str, list[edgar.Holding]] | None = None,
) -> dict[str, AumHistoryPoint]:
    prefetched = prefetched or {}
    filings = edgar.get_latest_13f_filings(cik, limit=target_quarters)
    for f in filings:
        if f.accession in cached:
            continue
        if f.accession in prefetched:
            holdings = prefetched[f.accession]
        else:
            log.info("Fetching history info table for %s (period %s)…", f.accession, f.period_of_report)
            try:
                holdings = edgar.fetch_with_retry(f)
            except Exception as exc:
                log.warning("Skipping history for %s: %s", f.accession, exc)
                continue
        total = sum(h.value_usd for h in holdings)
        cached[f.accession] = AumHistoryPoint(
            period=f.period_of_report,
            filing_date=f.filing_date,
            accession=f.accession,
            total_usd=total,
        )
    return cached


def _run_one_fund(
    fund: Fund,
    state: dict,
    history_by_cik: dict[str, dict[str, AumHistoryPoint]],
    dry_run: bool,
    history_quarters: int,
    resolver: CusipResolver,
) -> tuple[compute.DashboardPayload | None, list[AumHistoryPoint], bool]:
    """Fetch + compute payload for one fund. Always fetches so the fund stays
    in the multi-fund dashboard. Returns (payload, history, new_filing_detected).
    """
    log.info("▶ %s (CIK %s)", fund.name, fund.cik)
    filings = edgar.get_latest_13f_filings(fund.cik, limit=2)
    if not filings:
        log.warning("No 13F-HR filings for %s — skipping.", fund.slug)
        return None, [], False

    latest = filings[0]
    prior = filings[1] if len(filings) > 1 else None
    last_accession = state["funds"].get(fund.cik, {}).get("last_accession")
    new_filing_detected = latest.accession != last_accession

    if dry_run:
        log.info("  dry-run: latest %s (new=%s)", latest.accession, new_filing_detected)
        return None, [], new_filing_detected

    log.info("  fetching info table for %s…", latest.accession)
    latest_holdings = edgar.fetch_with_retry(latest)
    log.info("    %d holdings, total $%s", len(latest_holdings), f"{sum(h.value_usd for h in latest_holdings):,}")

    prior_holdings: list[edgar.Holding] = []
    if prior:
        try:
            log.info("  fetching info table for prior %s…", prior.accession)
            prior_holdings = edgar.fetch_with_retry(prior)
            log.info("    %d prior holdings", len(prior_holdings))
        except Exception as exc:
            log.warning("  prior fetch failed; QoQ will be empty: %s", exc)

    # AUM history
    cached = history_by_cik.setdefault(fund.cik, {})
    prefetched = {latest.accession: latest_holdings}
    if prior:
        prefetched[prior.accession] = prior_holdings
    cached = _ensure_history(fund.cik, cached, history_quarters, prefetched=prefetched)
    history_by_cik[fund.cik] = cached
    aum_history = sorted(cached.values(), key=lambda p: p.period)[-history_quarters:]

    # CUSIP → ticker
    all_cusips = {h.cusip for h in latest_holdings} | {h.cusip for h in prior_holdings}
    ticker_map: dict[str, str | None] = {c: resolver.resolve(c) for c in all_cusips}

    # Prices
    latest_tickers = {t for t in ticker_map.values() if t}
    prior_tickers = {ticker_map.get(h.cusip) for h in prior_holdings if ticker_map.get(h.cusip)}

    current_prices: dict[str, float | None] = {t: prices.get_current(t) for t in sorted(latest_tickers)}
    entry_prices: dict[str, float | None] = {}
    for t in sorted(latest_tickers):
        period = prior.period_of_report if (t in prior_tickers and prior) else latest.period_of_report
        entry_prices[t] = prices.get_quarterly_avg(t, period)

    payload = compute.build_dashboard_payload(
        filer_name=fund.name,
        cik=fund.cik,
        latest_filing=latest,
        latest_holdings=latest_holdings,
        prior_filing=prior,
        prior_holdings=prior_holdings,
        ticker_map=ticker_map,
        current_prices=current_prices,
        entry_prices=entry_prices,
        prices_as_of=date.today().isoformat(),
    )
    return payload, aum_history, new_filing_detected


@click.command()
@click.option("--force", is_flag=True, help="Regenerate dashboard even if no new filings.")
@click.option("--dry-run", is_flag=True, help="Check only; no writes, no email.")
@click.option("--no-email", is_flag=True, help="Skip sending email.")
@click.option("--fund", default=None, help="Run a single fund by slug.")
@click.option("--history-quarters", type=int, default=8,
              help="Quarters of AUM history to keep for each fund's sparkline.")
def main(force: bool, dry_run: bool, no_email: bool, fund: str | None, history_quarters: int) -> int:
    state = _load_state()
    history_by_cik = _load_history_all()

    funds_to_run: list[Fund] = FUNDS
    if fund:
        chosen = fund_by_slug(fund)
        if not chosen:
            log.error("Unknown fund slug: %s (known: %s)", fund, ", ".join(f.slug for f in FUNDS))
            return 2
        funds_to_run = [chosen]

    resolver = CusipResolver()

    funds_data: list[tuple[Fund, compute.DashboardPayload, list[AumHistoryPoint]]] = []
    new_filings: list[tuple[Fund, compute.DashboardPayload]] = []

    for f in funds_to_run:
        try:
            payload, history, new_filing = _run_one_fund(
                f, state, history_by_cik, dry_run, history_quarters, resolver
            )
        except Exception as exc:
            log.exception("Pipeline failed for %s: %s", f.slug, exc)
            continue
        if payload is not None:
            funds_data.append((f, payload, history))
            if new_filing:
                new_filings.append((f, payload))
            state["funds"].setdefault(f.cik, {})
            state["funds"][f.cik].update({
                "last_accession": payload.latest.accession,
                "last_period": payload.latest.period_of_report,
                "last_run": date.today().isoformat(),
            })

    resolver.save()

    if dry_run:
        log.info("Dry run complete — %d fund(s) checked.", len(funds_to_run))
        return 0

    if not funds_data:
        log.info("No fund data to render.")
        return 0

    # Decide whether to render & commit. If no fund has a new filing and
    # --force wasn't passed, skip — nothing visibly changed.
    if not new_filings and not force:
        log.info("No new filings across %d fund(s). Nothing to render.", len(funds_data))
        return 0

    log.info("Rendering dashboard for %d fund(s)…", len(funds_data))
    render.write_dashboard(funds_data, prices_as_of=date.today().isoformat())

    _save_history_all(history_by_cik)
    _save_state(state)

    # Email + log per-fund diff summaries for any new filings.
    for f, payload in new_filings:
        summary = compute.format_diff_summary(payload)
        # Marker lets the workflow extract per-fund summaries and file issues.
        log.info("::NEW_FILING:: %s :: %s", f.slug, payload.latest.period_of_report)
        log.info("Diff summary:\n%s", summary)
        if not no_email:
            subject = f"New 13F filing: {f.name} — {payload.latest.period_of_report}"
            alert.send_new_filing_alert(subject=subject, body_text=summary)

    log.info("Done. Dashboard → docs/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main(standalone_mode=False) or 0)
