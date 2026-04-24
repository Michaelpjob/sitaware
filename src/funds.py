"""Configured funds + plays — single source of truth.

A `Play` is a curated subset of a fund's 13F holdings that expresses a headline
thesis (e.g. SA LP's "AI Power" basket). Weights are derived from the latest
13F at render time; the chart uses *current* weights against historical prices
(standard ETF-backtest convention, documented in the UI footnote).

Adding a fund or play: edit this file. The weekly workflow picks it up next run.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Play:
    name: str                               # "AI Power"
    slug: str                               # "ai-power" — used in URLs / state
    thesis: str                             # short paragraph, shown under the title
    tickers: tuple[str, ...]                # subset of the fund's 13F tickers
    inception_date: str                     # ISO "YYYY-MM-DD"; chart starts here
    benchmark: str = "SPY"                  # ticker of the benchmark overlay


@dataclass(frozen=True)
class Fund:
    slug: str
    name: str
    cik: str
    manager: str
    thesis: str = ""
    plays: tuple[Play, ...] = field(default_factory=tuple)


FUNDS: list[Fund] = [
    Fund(
        slug="sa-lp",
        name="Situational Awareness LP",
        cik="0002045724",
        manager="Leopold Aschenbrenner",
        thesis="AI compute scaling, power generation, energy infrastructure",
        plays=(
            Play(
                name="AI Power",
                slug="ai-power",
                thesis=(
                    "The supply side of the AI buildout — on-site primary power (Bloom fuel "
                    "cells, Babcock & Wilcox power equipment, Power Solutions' natural-gas "
                    "engines), the natural-gas producer feeding that generation (EQT), and "
                    "the frac/drilling services upstream (Solaris, Liberty, ProPetro). "
                    "Bloom alone is the fund's largest position at 20.6% — the slower, "
                    "longer-duration half of the buildout where 2026 capex decisions show "
                    "up as 2028 electricity demand."
                ),
                tickers=("BE", "PSIX", "BW", "EQT", "SEI", "LBRT", "PUMP"),
                inception_date="2025-06-01",
                benchmark="XLE",
            ),
            Play(
                name="AI Demand",
                slug="ai-demand",
                thesis=(
                    "The demand side — companies consuming electrons to sell AI compute. "
                    "CoreWeave (held as call options, ~18% of the fund), and the cluster "
                    "of Bitcoin miners converting fleets to AI/HPC hosting — Core Scientific, "
                    "IREN, Applied Digital, Cipher, Riot, Hut 8, Bitdeer, CleanSpark, "
                    "Bitfarms. Plus inside-the-rack: Lumentum and Coherent for optical "
                    "networking, SanDisk for memory, Tower Semi for mixed-signal, WhiteFiber "
                    "for datacenter fiber."
                ),
                tickers=("CRWV", "LITE", "CORZ", "IREN", "APLD", "SNDK", "CIFR", "COHR",
                         "TSEM", "RIOT", "HUT", "WYFI", "BTDR", "CLSK", "BITF"),
                inception_date="2025-06-01",
                benchmark="IGV",
            ),
        ),
    ),
    Fund(
        slug="appaloosa",
        name="Appaloosa LP",
        cik="0001656456",
        manager="David Tepper",
        thesis="Macro-inflected concentrated equity — US mega-cap + China tech",
        plays=(
            Play(
                name="Mega-Cap AI Beneficiaries",
                slug="mega-cap-ai",
                thesis=(
                    "Tepper's Q4 2025 moves — Micron +200%, Meta +62%, Alphabet +29% — "
                    "expressed a view that US mega-caps and leading-edge memory capture "
                    "the bulk of the AI economic cycle. Alibaba (his #1 position) is "
                    "deliberately held out because China tech is a separate thesis."
                ),
                tickers=("GOOG", "META", "AMZN", "MU", "NVDA"),
                inception_date="2025-06-01",
                benchmark="QQQ",
            ),
        ),
    ),
    Fund(
        slug="perceptive",
        name="Perceptive Advisors",
        cik="0001224962",
        manager="Joseph Edelman",
        thesis="Biotech & life sciences — catalyst-driven",
        plays=(
            Play(
                name="Catalyst-Driven Biotech",
                slug="catalyst-biotech",
                thesis=(
                    "Edelman's highest-conviction clinical-stage bets — names he'll size "
                    "up despite binary trial-readout risk. FDA approvals, Phase 3 results, "
                    "and M&A drive returns."
                ),
                tickers=("PRAX", "CELC", "RYTM", "ASND", "APGE"),
                inception_date="2025-06-01",
                benchmark="XBI",
            ),
        ),
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
