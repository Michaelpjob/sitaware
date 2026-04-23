"""Smoke test for HTML rendering."""
from src.edgar import Filing, parse_info_table_xml
from src.compute import build_dashboard_payload
from src.render import render_dashboard


def test_renders_valid_html(q4_xml, q3_xml):
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

    h4 = parse_info_table_xml(q4_xml)
    h3 = parse_info_table_xml(q3_xml)
    payload = build_dashboard_payload(
        filer_name="Situational Awareness LP",
        cik="0002045724",
        latest_filing=latest,
        latest_holdings=h4,
        prior_filing=prior,
        prior_holdings=h3,
        ticker_map={"093712107": "BE", "21873S108": "CRWV", "49427F108": "KRC",
                    "456788108": "INFY", "67066G104": "NVDA", "92840M102": "VST",
                    "093712AH0": "BE"},
        current_prices={"BE": 200.0, "CRWV": 150.0, "KRC": 30.0, "INFY": 15.0},
        entry_prices={"BE": 100.0, "CRWV": 120.0, "KRC": 40.0, "INFY": 20.0},
        prices_as_of="2026-04-23",
    )

    html = render_dashboard(payload)
    assert "<!DOCTYPE html>" in html
    assert "Situational Awareness LP" in html
    assert "BLOOM ENERGY" in html.upper()
    # Data must be embedded in the JSON blob for the client-side table
    assert "BLOOM ENERGY" in html.upper()
    assert "093712107" in html
    # The two script blobs must be present
    assert 'id="payload-data"' in html
    assert 'id="exits-data"' in html
