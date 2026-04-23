"""Main CLI entry point.

Usage:
  python run.py                     # normal run
  python run.py --force             # regenerate dashboard even if no new filing
  python run.py --dry-run           # check only, write nothing
  python run.py --cik 0002045724    # override CIK
  python run.py --no-email          # skip email
  python run.py --history-quarters 8  # how many quarters of AUM to show in sparkline
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

load_dotenv()
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stderr,
)
log = logging.getLogger("run")

STATE_PATH = Path("data/state.json")
HISTORY_PATH = Path("data/aum_history.json")
DEFAULT_CIK = "0002045724"
DEFAULT_NAME = "Situational Awareness LP"


def _load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def _load_history() -> dict[str, AumHistoryPoint]:
    """Return a dict {accession: point} from the on-disk cache."""
    if not HISTORY_PATH.exists():
        return {}
    try:
        raw = json.loads(HISTORY_PATH.read_text())
        return {p["accession"]: AumHistoryPoint(**p) for p in raw}
    except Exception as exc:
        log.warning("Failed to read %s: %s. Starting fresh.", HISTORY_PATH, exc)
        return {}


def _save_history(points: dict[str, AumHistoryPoint]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    sorted_pts = sorted(points.values(), key=lambda p: p.period)
    HISTORY_PATH.write_text(json.dumps([asdict(p) for p in sorted_pts], indent=2) + "\n")


def _ensure_history(
    cik: str,
    cached: dict[str, AumHistoryPoint],
    target_quarters: int,
    prefetched: dict[str, list[edgar.Holding]] | None = None,
) -> dict[str, AumHistoryPoint]:
    """Top up `cached` so it contains up to `target_quarters` most-recent filings.

    Fetches info tables only for filings not already cached. `prefetched` lets the
    caller supply already-fetched holdings lists (to avoid refetching latest/prior).
    """
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


@click.command()
@click.option("--cik", default=DEFAULT_CIK, help="SEC CIK (zero-padded or not).")
@click.option("--name", default=DEFAULT_NAME, help="Fund display name.")
@click.option("--force", is_flag=True, help="Regenerate dashboard even if no new filing.")
@click.option("--dry-run", is_flag=True, help="Check only; no writes, no email.")
@click.option("--no-email", is_flag=True, help="Skip sending email even if a new filing is detected.")
@click.option("--history-quarters", type=int, default=8,
              help="How many quarters of history to keep for the AUM sparkline.")
def main(cik: str, name: str, force: bool, dry_run: bool, no_email: bool, history_quarters: int) -> int:
    state = _load_state()
    last_accession = state.get("last_accession")

    log.info("Checking EDGAR for %s (CIK %s)…", name, cik)
    filings = edgar.get_latest_13f_filings(cik, limit=2)
    if not filings:
        log.error("No 13F-HR filings found for CIK %s. Wrong CIK, or the fund hasn't filed yet.", cik)
        return 2

    latest = filings[0]
    prior = filings[1] if len(filings) > 1 else None
    log.info("Latest: %s filed %s (period %s)", latest.accession, latest.filing_date, latest.period_of_report)

    new_filing_detected = latest.accession != last_accession
    if not new_filing_detected and not force:
        log.info("No new filing (still %s). Nothing to do.", last_accession)
        return 0

    if dry_run:
        log.info("Dry run: would update dashboard and alert for %s.", latest.accession)
        return 0

    # Fetch info tables for latest + prior
    log.info("Fetching info table for %s…", latest.accession)
    latest_holdings = edgar.fetch_with_retry(latest)
    log.info("  %d holdings, total value $%s", len(latest_holdings), f"{sum(h.value_usd for h in latest_holdings):,}")

    prior_holdings = []
    if prior:
        log.info("Fetching info table for prior %s…", prior.accession)
        try:
            prior_holdings = edgar.fetch_with_retry(prior)
            log.info("  %d prior holdings", len(prior_holdings))
        except Exception as exc:
            log.warning("Prior fetch failed; QoQ diff will be empty. %s", exc)

    # AUM history — top up cache with older filings for the sparkline
    history_cache = _load_history()
    prefetched_holdings = {latest.accession: latest_holdings}
    if prior:
        prefetched_holdings[prior.accession] = prior_holdings
    history_cache = _ensure_history(cik, history_cache, history_quarters, prefetched=prefetched_holdings)
    _save_history(history_cache)
    aum_history = sorted(history_cache.values(), key=lambda p: p.period)[-history_quarters:]

    # CUSIP → ticker
    resolver = CusipResolver()
    all_cusips = {h.cusip for h in latest_holdings} | {h.cusip for h in prior_holdings}
    ticker_map: dict[str, str | None] = {c: resolver.resolve(c) for c in all_cusips}
    resolver.save()

    # Prices
    unique_latest_tickers = {t for t in ticker_map.values() if t}
    unique_prior_tickers = {ticker_map.get(h.cusip) for h in prior_holdings if ticker_map.get(h.cusip)}

    current_prices: dict[str, float | None] = {}
    for t in sorted(unique_latest_tickers):
        current_prices[t] = prices.get_current(t)

    # Entry price = quarterly average for the first-seen quarter
    # If present in prior filing → use prior period; else → use latest period
    prior_tickers_set: set[str] = set(unique_prior_tickers)
    entry_prices: dict[str, float | None] = {}
    for t in sorted(unique_latest_tickers):
        period = prior.period_of_report if (t in prior_tickers_set and prior) else latest.period_of_report
        entry_prices[t] = prices.get_quarterly_avg(t, period)

    payload = compute.build_dashboard_payload(
        filer_name=name,
        cik=cik.zfill(10) if cik.isdigit() else cik,
        latest_filing=latest,
        latest_holdings=latest_holdings,
        prior_filing=prior,
        prior_holdings=prior_holdings,
        ticker_map=ticker_map,
        current_prices=current_prices,
        entry_prices=entry_prices,
        prices_as_of=date.today().isoformat(),
    )

    log.info("Rendering dashboard with %d history points…", len(aum_history))
    render.write_dashboard(payload, aum_history=aum_history)

    if new_filing_detected:
        summary = compute.format_diff_summary(payload)
        log.info("Diff summary:\n%s", summary)
        if not no_email:
            subject = f"New 13F filing: {name} — {latest.period_of_report}"
            alert.send_new_filing_alert(subject=subject, body_text=summary)

    state["last_accession"] = latest.accession
    state["last_period"] = latest.period_of_report
    state["last_run"] = date.today().isoformat()
    _save_state(state)

    log.info("Done. Dashboard written to docs/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main(standalone_mode=False) or 0)
