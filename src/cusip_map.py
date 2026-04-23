"""CUSIP → ticker resolution.

Maintains a local JSON cache (`data/cusip_tickers.json`) of known mappings,
seeded from prior 13F parses. Falls back to OpenFIGI's free API for unknown
CUSIPs. OpenFIGI has no API key required for low volume; responses are cached
so lookups stay cheap over time.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger(__name__)

CACHE_PATH = Path("data/cusip_tickers.json")
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_MIN_INTERVAL_S = 0.25  # 25 req/6s unauthenticated; we go conservative.

_last_openfigi_at = 0.0

# Seed mapping for CUSIPs observed in Situational Awareness LP's recent filings.
# Each run enriches this via OpenFIGI; the cache file is what's committed.
SEED_MAP: dict[str, str] = {
    "038169207": "APLD",   # Applied Digital Corp
    "05614L209": "BW",     # Babcock & Wilcox Enterprises
    "G11448100": "BTDR",   # Bitdeer Technologies Group
    "09173B107": "BITF",   # Bitfarms Ltd (delisted Apr 2026 → KEEL)
    "093712107": "BE",     # Bloom Energy Corp
    "093712AH0": "BE",     # Bloom Energy convertible-note CUSIP (treat as BE for mapping)
    "11135F101": "AVGO",   # Broadcom Inc
    "17253J106": "CIFR",   # Cipher Mining Inc
    "17253JAA4": "CIFR",   # Cipher Mining note CUSIP
    "18452B209": "CLSK",   # CleanSpark Inc
    "19247G107": "COHR",   # Coherent Corp
    "21874A106": "CORZ",   # Core Scientific Inc
    "21873S108": "CRWV",   # CoreWeave Inc
    "26884L109": "EQT",    # EQT Corp
    "36317J209": "GLXY",   # Galaxy Digital Inc
    "44812J104": "HUT",    # Hut 8 Corp
    "Q4982L109": "IREN",   # IREN Limited (Iris Energy)
    "456788108": "INFY",   # Infosys Ltd ADR
    "458140100": "INTC",   # Intel Corp
    "49427F108": "KRC",    # Kilroy Realty Corp
    "53115L104": "LBRT",   # Liberty Energy Inc
    "55024U109": "LITE",   # Lumentum Holdings Inc
    "55024UAD1": "LITE",   # Lumentum note CUSIP
    "595112103": "MU",     # Micron Technology Inc
    "67066G104": "NVDA",   # NVIDIA Corporation
    "73933G202": "PSIX",   # Power Solutions International
    "74347M108": "PUMP",   # ProPetro Holding Corp
    "767292105": "RIOT",   # Riot Platforms Inc
    "80004C200": "SNDK",   # Sandisk Corp
    "G7997R103": "STX",    # Seagate Technology Hldns
    "83418M103": "SEI",    # Solaris Energy Infrastructure
    "874039100": "TSM",    # Taiwan Semiconductor ADR
    "M87915274": "TSEM",   # Tower Semiconductor Ltd
    "92189F106": "SMH",    # VanEck Semiconductor ETF
    "92840M102": "VST",    # Vistra Corp
    "958102AT2": "WDC",    # Western Digital Corp
    "G96115103": "WYFI",   # WhiteFiber Inc
}


def _load_cache() -> dict[str, str]:
    if CACHE_PATH.exists():
        try:
            return {**SEED_MAP, **json.loads(CACHE_PATH.read_text())}
        except Exception as exc:
            log.warning("Failed to read %s: %s. Using seed only.", CACHE_PATH, exc)
    return dict(SEED_MAP)


def _save_cache(mapping: dict[str, str]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Only write the portion beyond seed to keep diffs small.
    extras = {k: v for k, v in sorted(mapping.items()) if SEED_MAP.get(k) != v or k not in SEED_MAP}
    CACHE_PATH.write_text(json.dumps(extras, indent=2, sort_keys=True) + "\n")


def _openfigi_lookup(cusip: str) -> str | None:
    """Resolve a CUSIP via OpenFIGI. Returns ticker or None."""
    global _last_openfigi_at
    wait = OPENFIGI_MIN_INTERVAL_S - (time.monotonic() - _last_openfigi_at)
    if wait > 0:
        time.sleep(wait)

    try:
        resp = requests.post(
            OPENFIGI_URL,
            json=[{"idType": "ID_CUSIP", "idValue": cusip}],
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        _last_openfigi_at = time.monotonic()
        resp.raise_for_status()
        body: list[Any] = resp.json()
        if not body or "data" not in body[0]:
            return None
        for entry in body[0]["data"]:
            t = entry.get("ticker")
            if t and entry.get("exchCode") in ("US", "UN", "UW", "UA", "UR", "UQ", "UP", "UV"):
                return t
        # Fall back to any ticker
        for entry in body[0]["data"]:
            if t := entry.get("ticker"):
                return t
    except Exception as exc:
        log.warning("OpenFIGI lookup failed for CUSIP %s: %s", cusip, exc)
    return None


class CusipResolver:
    """Resolve CUSIPs to tickers with caching."""

    def __init__(self, enable_openfigi: bool = True):
        self._cache = _load_cache()
        self._dirty = False
        self._enable_openfigi = enable_openfigi

    def resolve(self, cusip: str) -> str | None:
        if not cusip:
            return None
        if cusip in self._cache:
            return self._cache[cusip]
        if not self._enable_openfigi:
            return None
        ticker = _openfigi_lookup(cusip)
        if ticker:
            self._cache[cusip] = ticker
            self._dirty = True
            log.info("Resolved %s → %s via OpenFIGI", cusip, ticker)
        return ticker

    def save(self) -> None:
        if self._dirty:
            _save_cache(self._cache)
            self._dirty = False
