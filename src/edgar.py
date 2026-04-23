"""SEC EDGAR client.

Fetches 13F-HR filings for a given CIK and parses the information-table XML.

SEC requires clients to identify themselves via User-Agent header and rate-limits
to 10 req/sec. See https://www.sec.gov/os/webmaster-faq#code-support.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Iterator

import requests
from lxml import etree

log = logging.getLogger(__name__)

# SEC URLs
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}"
INDEX_JSON_URL = ARCHIVES_BASE + "/index.json"

DEFAULT_UA = "Situational Awareness Tracker (contact@example.com)"

# Courtesy throttle between SEC requests (SEC limit is 10 req/sec; we do ~9).
MIN_REQUEST_INTERVAL_S = 0.11
_last_request_at = 0.0


@dataclass(frozen=True)
class Filing:
    accession: str            # e.g. "0002045724-26-000002"
    filing_date: str          # ISO date "YYYY-MM-DD"
    period_of_report: str     # ISO date "YYYY-MM-DD" (quarter end)
    form: str                 # "13F-HR" or "13F-HR/A"
    cik: str                  # zero-padded 10-digit CIK


@dataclass(frozen=True)
class Holding:
    issuer: str               # nameOfIssuer
    cusip: str
    title_of_class: str
    value_usd: int            # reported value in whole US dollars (post-2022)
    shares: int               # sshPrnAmt
    put_call: str | None      # "Call", "Put", or None for common
    investment_discretion: str = ""


def _user_agent() -> str:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua:
        log.warning("SEC_USER_AGENT not set; using default. SEC may rate-limit or 403.")
        return DEFAULT_UA
    return ua


def _get(url: str, accept: str = "application/json") -> requests.Response:
    """Throttled GET to sec.gov with required headers."""
    global _last_request_at
    wait = MIN_REQUEST_INTERVAL_S - (time.monotonic() - _last_request_at)
    if wait > 0:
        time.sleep(wait)
    headers = {
        "User-Agent": _user_agent(),
        "Accept": accept,
        "Accept-Encoding": "gzip, deflate",
        "Host": url.split("/")[2],
    }
    resp = requests.get(url, headers=headers, timeout=30)
    _last_request_at = time.monotonic()
    resp.raise_for_status()
    return resp


def _normalize_cik(cik: str | int) -> str:
    """Zero-pad CIK to 10 digits."""
    return str(cik).lstrip("0").zfill(10) or "0000000000"


def _accession_nodash(accession: str) -> str:
    return accession.replace("-", "")


def iter_13f_filings(cik: str) -> Iterator[Filing]:
    """Yield 13F-HR filings (most recent first) for the given CIK."""
    cik = _normalize_cik(cik)
    url = SUBMISSIONS_URL.format(cik=cik)
    data = _get(url).json()

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filing_dates = recent.get("filingDate", [])
    report_dates = recent.get("reportDate", [])

    for i, form in enumerate(forms):
        if form in ("13F-HR", "13F-HR/A"):
            yield Filing(
                accession=accessions[i],
                filing_date=filing_dates[i],
                period_of_report=report_dates[i],
                form=form,
                cik=cik,
            )


def get_latest_13f_filings(cik: str, limit: int = 2) -> list[Filing]:
    """Return the most recent `limit` 13F-HR filings, newest first."""
    out = []
    for f in iter_13f_filings(cik):
        out.append(f)
        if len(out) >= limit:
            break
    return out


def _find_info_table_url(filing: Filing) -> str:
    """Locate the information-table XML document inside a filing's index."""
    cik_int = int(filing.cik)
    nodash = _accession_nodash(filing.accession)
    idx_url = INDEX_JSON_URL.format(cik_int=cik_int, accession_nodash=nodash)
    idx = _get(idx_url).json()

    items = idx.get("directory", {}).get("item", [])
    # Prefer files whose name matches known patterns; fall back to any info table XML.
    candidates = []
    for item in items:
        name = item.get("name", "")
        if not name.lower().endswith(".xml"):
            continue
        if name.lower() == "primary_doc.xml":
            continue  # the summary doc, not the info table
        candidates.append(name)

    if not candidates:
        raise RuntimeError(f"No info-table XML found in filing {filing.accession}")

    # Heuristic: if multiple XMLs, pick the one likely to be the information table.
    # It's typically the larger file, or one containing "form13f" or "info".
    preferred = [n for n in candidates if "info" in n.lower() or "form13f" in n.lower()]
    chosen = preferred[0] if preferred else candidates[0]

    base = ARCHIVES_BASE.format(cik_int=cik_int, accession_nodash=nodash)
    return f"{base}/{chosen}"


def fetch_info_table(filing: Filing) -> list[Holding]:
    """Fetch and parse the information-table XML for a filing."""
    url = _find_info_table_url(filing)
    return parse_info_table_xml(_get(url, accept="application/xml").content)


# The information-table XSD uses this namespace (both possible URIs — SEC has used both).
_NS_CANDIDATES = (
    "http://www.sec.gov/edgar/document/thirteenf/informationtable",
    "http://www.sec.gov/edgar/thirteenf/informationtable",
)


def _local(tag: str) -> str:
    """Strip XML namespace from an lxml tag."""
    return tag.split("}", 1)[-1] if "}" in tag else tag


def parse_info_table_xml(xml_bytes: bytes) -> list[Holding]:
    """Parse 13F information table XML into Holding records.

    Raw values are in whole USD for filings after 2022-Q4; we trust the filing.
    """
    root = etree.fromstring(xml_bytes)
    holdings: list[Holding] = []

    # Iterate over all infoTable elements regardless of namespace prefix.
    for elem in root.iter():
        if _local(elem.tag) != "infoTable":
            continue

        d: dict[str, str] = {}
        for child in elem:
            tag = _local(child.tag)
            if tag == "shrsOrPrnAmt":
                # shares nested inside
                for gc in child:
                    d[_local(gc.tag)] = (gc.text or "").strip()
            elif tag == "putCall":
                d["putCall"] = (child.text or "").strip()
            else:
                d[tag] = (child.text or "").strip()

        if not d.get("cusip"):
            continue

        holdings.append(
            Holding(
                issuer=d.get("nameOfIssuer", ""),
                cusip=d.get("cusip", ""),
                title_of_class=d.get("titleOfClass", ""),
                value_usd=int(d.get("value", "0") or 0),
                shares=int(d.get("sshPrnamt", d.get("sshPrnAmt", "0")) or 0),
                put_call=d.get("putCall") or None,
                investment_discretion=d.get("investmentDiscretion", ""),
            )
        )

    if not holdings:
        raise RuntimeError("Parsed info table contained zero holdings; possible EDGAR partial response.")

    return holdings


def fetch_with_retry(filing: Filing, retries: int = 3) -> list[Holding]:
    """Fetch the info table, retrying on transient empty responses."""
    last_exc = None
    for attempt in range(retries):
        try:
            return fetch_info_table(filing)
        except Exception as exc:
            last_exc = exc
            sleep = 2 ** attempt
            log.warning("Filing %s fetch failed (attempt %d/%d): %s. Retrying in %ds.",
                        filing.accession, attempt + 1, retries, exc, sleep)
            time.sleep(sleep)
    raise RuntimeError(f"Failed to fetch filing {filing.accession} after {retries} attempts") from last_exc
