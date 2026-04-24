"""Render the multi-fund dashboard against fixture data for local preview.

Only SA LP has real fixtures in tests/fixtures/; Appaloosa and Perceptive are
synthesized from the SA LP fixtures with different CIKs/accessions so we can
eyeball the dropdown + multi-fund layout without hitting SEC.

Usage:
  python scripts/preview.py
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.compute import AumHistoryPoint, build_dashboard_payload
from src.edgar import Filing, parse_info_table_xml
from src.funds import FUNDS, fund_by_slug
from src.render import write_dashboard


def fake_payload(fund, q4_bytes: bytes, q3_bytes: bytes, scale: float = 1.0):
    """Build a payload for `fund` using SA LP fixtures, optionally scaling values."""
    latest = Filing(
        accession=f"fake-{fund.slug}-26-000002",
        filing_date="2026-02-11",
        period_of_report="2025-12-31",
        form="13F-HR",
        cik=fund.cik,
    )
    prior = Filing(
        accession=f"fake-{fund.slug}-25-000008",
        filing_date="2025-11-14",
        period_of_report="2025-09-30",
        form="13F-HR",
        cik=fund.cik,
    )
    h4 = parse_info_table_xml(q4_bytes)
    h3 = parse_info_table_xml(q3_bytes)
    # Scale values so the three funds have visibly different AUMs in preview.
    if scale != 1.0:
        h4 = [replace(h, value_usd=int(h.value_usd * scale), shares=int(h.shares * scale)) for h in h4]
        h3 = [replace(h, value_usd=int(h.value_usd * scale), shares=int(h.shares * scale)) for h in h3]

    ticker_map = {
        "093712107": "BE", "093712AH0": "BE",
        "21873S108": "CRWV",
        "49427F108": "KRC", "456788108": "INFY",
        "67066G104": "NVDA", "92840M102": "VST",
    }
    current_prices = {"BE": 229.75, "CRWV": 122.54, "KRC": 29.18, "INFY": 13.48, "NVDA": 141.80, "VST": 167.20}
    entry_prices = {"BE": 86.89, "CRWV": 136.85, "KRC": 37.37, "INFY": 17.82, "NVDA": 115.00, "VST": 195.90}

    payload = build_dashboard_payload(
        filer_name=fund.name,
        cik=fund.cik,
        latest_filing=latest,
        latest_holdings=h4,
        prior_filing=prior,
        prior_holdings=h3,
        ticker_map=ticker_map,
        current_prices=current_prices,
        entry_prices=entry_prices,
        prices_as_of="2026-04-23",
    )

    history = [
        AumHistoryPoint(period="2024-06-30", filing_date="2024-08-14",
                        accession=f"fake-{fund.slug}-h1", total_usd=int(420_000_000 * scale)),
        AumHistoryPoint(period="2024-09-30", filing_date="2024-11-14",
                        accession=f"fake-{fund.slug}-h2", total_usd=int(560_000_000 * scale)),
        AumHistoryPoint(period="2024-12-31", filing_date="2025-02-14",
                        accession=f"fake-{fund.slug}-h3", total_usd=int(740_000_000 * scale)),
        AumHistoryPoint(period="2025-03-31", filing_date="2025-05-15",
                        accession=f"fake-{fund.slug}-h4", total_usd=int(920_000_000 * scale)),
        AumHistoryPoint(period="2025-06-30", filing_date="2025-08-14",
                        accession=f"fake-{fund.slug}-h5", total_usd=int(1_050_000_000 * scale)),
        AumHistoryPoint(period="2025-09-30", filing_date="2025-11-14",
                        accession=prior.accession, total_usd=payload.prior_total_usd or 0),
        AumHistoryPoint(period="2025-12-31", filing_date="2026-02-11",
                        accession=latest.accession, total_usd=payload.latest_total_usd),
    ]
    return payload, history


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "index.html")
    ap.add_argument("--signup-endpoint", default="/api/subscribe")
    args = ap.parse_args()

    q3 = (ROOT / "tests/fixtures/q3_2025_info_table.xml").read_bytes()
    q4 = (ROOT / "tests/fixtures/q4_2025_info_table.xml").read_bytes()

    # Scale each fund differently so the dropdown demo shows visible variation.
    scales = {"sa-lp": 1.0, "appaloosa": 3.2, "perceptive": 0.6}
    funds_data = []
    for f in FUNDS:
        payload, history = fake_payload(f, q4, q3, scale=scales.get(f.slug, 1.0))
        funds_data.append((f, payload, history))

    write_dashboard(
        funds_data,
        prices_as_of="2026-04-23",
        out_path=args.out,
        active_slug="sa-lp",
        site_name="Fundwatch",
        site_url="https://fundwatch.app",
        og_image_url=None,
        repo_url="https://github.com/Michaelpjob/sitaware",
        signup_endpoint=args.signup_endpoint,
    )
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
