"""Tests for the compute layer (diff, returns, QoQ)."""
from src.edgar import Filing, parse_info_table_xml
from src.compute import build_dashboard_payload, format_diff_summary


def _filings():
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
    return latest, prior


def test_totals(q4_xml, q3_xml):
    latest, prior = _filings()
    h4 = parse_info_table_xml(q4_xml)
    h3 = parse_info_table_xml(q3_xml)
    payload = build_dashboard_payload(
        filer_name="Situational Awareness LP",
        cik="0002045724",
        latest_filing=latest,
        latest_holdings=h4,
        prior_filing=prior,
        prior_holdings=h3,
        ticker_map={h.cusip: "XXX" for h in h4 + h3},
        current_prices={"XXX": 100.0},
        entry_prices={"XXX": 50.0},
        prices_as_of="2026-04-23",
    )
    # Q4 fixture total: 875505552 + 35494565 + 436735927 + 49616149 + 8910000 = 1,406,262,193
    assert payload.latest_total_usd == 1_406_262_193
    # Q3 fixture total: 43890344 + 563200154 + 298528000 + 252327327 = 1,157,945,825
    assert payload.prior_total_usd == 1_157_945_825


def test_identifies_new_positions(q4_xml, q3_xml):
    latest, prior = _filings()
    h4 = parse_info_table_xml(q4_xml)
    h3 = parse_info_table_xml(q3_xml)
    payload = build_dashboard_payload(
        "SA LP", "0002045724", latest, h4, prior, h3,
        ticker_map={h.cusip: None for h in h4 + h3},
        current_prices={},
        entry_prices={},
        prices_as_of="2026-04-23",
    )
    new_buys = [p for p in payload.positions if p.is_new]
    # KRC and BE Call and INFY Put are all new in Q4
    new_cusips = {p.cusip for p in new_buys}
    assert "49427F108" in new_cusips  # KRC
    assert "456788108" in new_cusips  # INFY Put


def test_exits_detected(q4_xml, q3_xml):
    latest, prior = _filings()
    h4 = parse_info_table_xml(q4_xml)
    h3 = parse_info_table_xml(q3_xml)
    payload = build_dashboard_payload(
        "SA LP", "0002045724", latest, h4, prior, h3,
        ticker_map={}, current_prices={}, entry_prices={},
        prices_as_of="2026-04-23",
    )
    exit_cusips = {e.cusip for e in payload.exits}
    assert "67066G104" in exit_cusips  # NVDA Put
    assert "92840M102" in exit_cusips  # VST


def test_bloom_cusip_canonicalization(q4_xml, q3_xml):
    """Q3 BE was filed under 093712AH0 (conv. CUSIP); Q4 under 093712107 (common).
    The canonicalization should recognize these as the same position."""
    latest, prior = _filings()
    h4 = parse_info_table_xml(q4_xml)
    h3 = parse_info_table_xml(q3_xml)
    payload = build_dashboard_payload(
        "SA LP", "0002045724", latest, h4, prior, h3,
        ticker_map={}, current_prices={}, entry_prices={},
        prices_as_of="2026-04-23",
    )
    be_common = next(p for p in payload.positions if p.cusip == "093712107" and p.put_call is None)
    # Should NOT be flagged as new; should have prior values pulled from the AH0 row
    assert not be_common.is_new
    assert be_common.prior_shares == 3_048_002
    # And the AH0 CUSIP should NOT show up as an exit
    assert not any(e.cusip == "093712AH0" for e in payload.exits)


def test_return_computation(q4_xml):
    latest, _ = _filings()
    h4 = parse_info_table_xml(q4_xml)
    ticker_map = {"093712107": "BE", "21873S108": "CRWV", "49427F108": "KRC", "456788108": "INFY"}
    payload = build_dashboard_payload(
        "SA LP", "0002045724", latest, h4, None, [],
        ticker_map=ticker_map,
        current_prices={"BE": 200.0, "CRWV": 150.0, "KRC": 30.0, "INFY": 15.0},
        entry_prices={"BE": 100.0, "CRWV": 120.0, "KRC": 40.0, "INFY": 20.0},
        prices_as_of="2026-04-23",
    )
    be = next(p for p in payload.positions if p.cusip == "093712107" and p.put_call is None)
    assert abs(be.est_return_pct - 100.0) < 0.01  # 100% return


def test_diff_summary_formats(q4_xml, q3_xml):
    latest, prior = _filings()
    h4 = parse_info_table_xml(q4_xml)
    h3 = parse_info_table_xml(q3_xml)
    payload = build_dashboard_payload(
        "SA LP", "0002045724", latest, h4, prior, h3,
        ticker_map={}, current_prices={}, entry_prices={},
        prices_as_of="2026-04-23",
    )
    summary = format_diff_summary(payload)
    assert "NEW 13F FILING" in summary
    assert "NEW BUYS" in summary
    assert "EXITS" in summary
    assert "KILROY" in summary.upper()
