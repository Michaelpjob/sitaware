"""Configured funds — single source of truth.

To track another fund, append an entry. The weekly workflow picks it up on the
next run; state is keyed by CIK so each fund's last-seen accession is independent.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fund:
    slug: str       # short identifier, used in URLs / state
    name: str       # display name
    cik: str        # SEC CIK, zero-padded to 10 digits
    manager: str    # portfolio manager (shown in header subtitle)


FUNDS: list[Fund] = [
    Fund(
        slug="sa-lp",
        name="Situational Awareness LP",
        cik="0002045724",
        manager="Leopold Aschenbrenner",
    ),
    Fund(
        slug="appaloosa",
        name="Appaloosa LP",
        cik="0001656456",
        manager="David Tepper",
    ),
    Fund(
        slug="perceptive",
        name="Perceptive Advisors",
        cik="0001224962",
        manager="Joseph Edelman",
    ),
]


def fund_by_slug(slug: str) -> Fund | None:
    for f in FUNDS:
        if f.slug == slug:
            return f
    return None


def fund_by_cik(cik: str) -> Fund | None:
    normalized = cik.lstrip("0").zfill(10)
    for f in FUNDS:
        if f.cik == normalized:
            return f
    return None
