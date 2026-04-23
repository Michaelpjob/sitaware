"""Render the dashboard template against fixture data so we can preview
locally without running the full pipeline (no yfinance, no network).

Usage:
  python scripts/preview.py                 # writes docs/index.html
  python scripts/preview.py --out tmp.html  # writes somewhere else
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.compute import AumHistoryPoint, build_dashboard_payload
from src.edgar import Filing, parse_info_table_xml
from src.render import write_dashboard


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "index.html")
    ap.add_argument("--signup-endpoint", default="https://example.com/subscribe",
                    help="Placeholder endpoint so the signup form renders.")
    args = ap.parse_args()

    q3 = (ROOT / "tests/fixtures/q3_2025_info_table.xml").read_bytes()
    q4 = (ROOT / "tests/fixtures/q4_2025_info_table.xml").read_bytes()

    latest = Filing(
        accession="0002045724-26-000002",
        filing_date="2026-02-11",
        period_of_report="2025-12-31",
        form="13F-HR",
        cik="0002045724",
    )
    prior = Filing(
        accession="0002045724-25-000008",
        filing_date="2025-11-14",
        period_of_report="2025-09-30",
        form="13F-HR",
        cik="0002045724",
    )

    h4 = parse_info_table_xml(q4)
    h3 = parse_info_table_xml(q3)

    ticker_map = {
        "093712107": "BE", "093712AH0": "BE",
        "21873S108": "CRWV",
        "49427F108": "KRC", "456788108": "INFY",
        "67066G104": "NVDA", "92840M102": "VST",
    }
    # Canned prices (no network). Invent entry + current so the returns look sensible.
    current_prices = {"BE": 229.75, "CRWV": 122.54, "KRC": 29.18, "INFY": 13.48, "NVDA": 141.80, "VST": 167.20}
    entry_prices = {"BE": 86.89, "CRWV": 136.85, "KRC": 37.37, "INFY": 17.82, "NVDA": 115.00, "VST": 195.90}

    payload = build_dashboard_payload(
        filer_name="Situational Awareness LP",
        cik="0002045724",
        latest_filing=latest,
        latest_holdings=h4,
        prior_filing=prior,
        prior_holdings=h3,
        ticker_map=ticker_map,
        current_prices=current_prices,
        entry_prices=entry_prices,
        prices_as_of="2026-04-23",
    )

    # Fake AUM history so we can verify the sparkline renders.
    history = [
        AumHistoryPoint(period="2024-06-30", filing_date="2024-08-14", accession="fake1", total_usd=420_000_000),
        AumHistoryPoint(period="2024-09-30", filing_date="2024-11-14", accession="fake2", total_usd=560_000_000),
        AumHistoryPoint(period="2024-12-31", filing_date="2025-02-14", accession="fake3", total_usd=740_000_000),
        AumHistoryPoint(period="2025-03-31", filing_date="2025-05-15", accession="fake4", total_usd=920_000_000),
        AumHistoryPoint(period="2025-06-30", filing_date="2025-08-14", accession="fake5", total_usd=1_050_000_000),
        AumHistoryPoint(period="2025-09-30", filing_date="2025-11-14", accession=prior.accession, total_usd=payload.prior_total_usd or 0),
        AumHistoryPoint(period="2025-12-31", filing_date="2026-02-11", accession=latest.accession, total_usd=payload.latest_total_usd),
    ]

    write_dashboard(
        payload,
        aum_history=history,
        out_path=args.out,
        site_name="Situational Awareness Tracker",
        site_url="https://example.com",
        og_image_url="https://example.com/og.png",
        repo_url="https://github.com/yourname/situational-awareness-tracker",
        signup_endpoint=args.signup_endpoint,
    )
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
