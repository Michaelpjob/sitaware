"""Tests for the EDGAR info-table parser."""
from src.edgar import parse_info_table_xml


def test_parses_all_holdings(q4_xml):
    holdings = parse_info_table_xml(q4_xml)
    # Fixture has 5 rows: BE common, BE Call, CRWV common, KRC common, INFY Put
    assert len(holdings) == 5


def test_values_are_whole_usd(q4_xml):
    holdings = parse_info_table_xml(q4_xml)
    be_common = next(h for h in holdings if h.cusip == "093712107" and h.put_call is None)
    assert be_common.value_usd == 875_505_552
    assert be_common.shares == 10_076_022


def test_put_call_detection(q4_xml):
    holdings = parse_info_table_xml(q4_xml)
    calls = [h for h in holdings if h.put_call == "Call"]
    puts = [h for h in holdings if h.put_call == "Put"]
    assert len(calls) == 1
    assert calls[0].cusip == "093712107"
    assert len(puts) == 1
    assert puts[0].cusip == "456788108"


def test_common_has_no_put_call(q4_xml):
    holdings = parse_info_table_xml(q4_xml)
    commons = [h for h in holdings if h.put_call is None]
    assert len(commons) == 3
    assert all(h.put_call is None for h in commons)


def test_issuer_and_class(q4_xml):
    holdings = parse_info_table_xml(q4_xml)
    infy = next(h for h in holdings if h.cusip == "456788108")
    assert infy.issuer == "INFOSYS LTD"
    assert "ADR" in infy.title_of_class


def test_empty_table_raises():
    import pytest
    empty = b'<?xml version="1.0"?><informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable"></informationTable>'
    with pytest.raises(RuntimeError):
        parse_info_table_xml(empty)
