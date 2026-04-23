"""Compute enriched position data and quarter-over-quarter diffs.

Pure functions — no I/O. Takes parsed Holdings + prices + ticker map and
emits the payload the renderer needs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.edgar import Filing, Holding


@dataclass
class EnrichedPosition:
    issuer: str
    ticker: str | None
    cusip: str
    title_of_class: str
    put_call: str | None  # None, "Call", "Put"

    latest_shares: int
    latest_value_usd: int
    prior_shares: int | None
    prior_value_usd: int | None

    pct_portfolio: float       # latest_value_usd / total * 100
    q_end_price: float         # latest_value_usd / latest_shares
    entry_price: float | None  # quarterly avg in first-seen quarter (cost-basis proxy)
    current_price: float | None
    current_value_usd: float | None

    est_return_pct: float | None   # (current - entry) / entry * 100
    qoq_shares_pct: float | None   # (latest - prior) / prior * 100; None if new
    is_new: bool                   # not in prior quarter

    flag: str | None = None        # freeform data-quality note


@dataclass
class Exit:
    issuer: str
    ticker: str | None
    cusip: str
    put_call: str | None
    prior_value_usd: int


@dataclass
class AumHistoryPoint:
    """One point on the reported-AUM sparkline: the total 13F value for a filing."""
    period: str        # ISO date string, e.g. "2025-09-30"
    filing_date: str
    accession: str
    total_usd: int


@dataclass
class DashboardPayload:
    filer_name: str
    cik: str
    latest: Filing
    prior: Filing | None
    latest_total_usd: int
    prior_total_usd: int | None
    positions: list[EnrichedPosition]
    exits: list[Exit]
    prices_as_of: str


def _key(h: Holding) -> tuple[str, str | None]:
    """Unique key per row: (cusip, putCall). Same issuer may appear as common + option."""
    return (h.cusip, h.put_call)


def _issuer_cusip_equivalents() -> dict[str, str]:
    """Known CUSIP aliases where the same issuer was filed under different CUSIPs.

    Left = alias CUSIP, Right = canonical. Used to avoid false exits/new-buys
    when an issuer was reclassified (e.g. convertible → common).
    """
    return {
        # Bloom Energy: Q3 2025 filed under convertible-note CUSIP; Q4 corrected to common.
        "093712AH0": "093712107",
        # Cipher Mining: similar pattern
        "17253JAA4": "17253J106",
        # Lumentum: similar pattern
        "55024UAD1": "55024U109",
        # Western Digital: Q3 used convertible CUSIP
        "958102AT2": "958102107",
    }


def _canonicalize_cusip(cusip: str) -> str:
    return _issuer_cusip_equivalents().get(cusip, cusip)


def build_dashboard_payload(
    filer_name: str,
    cik: str,
    latest_filing: Filing,
    latest_holdings: list[Holding],
    prior_filing: Filing | None,
    prior_holdings: list[Holding],
    ticker_map: dict[str, str | None],
    current_prices: dict[str, float | None],
    entry_prices: dict[str, float | None],
    prices_as_of: str,
) -> DashboardPayload:
    """Join latest + prior holdings, compute derived fields, identify exits."""

    total_latest = sum(h.value_usd for h in latest_holdings)
    total_prior = sum(h.value_usd for h in prior_holdings) if prior_holdings else None

    # Build prior lookup by (canonical cusip, putCall)
    prior_by_key: dict[tuple[str, str | None], Holding] = {}
    for h in prior_holdings:
        key = (_canonicalize_cusip(h.cusip), h.put_call)
        # If multiple rows share the same canonical key, sum them (rare edge case)
        if key in prior_by_key:
            existing = prior_by_key[key]
            prior_by_key[key] = Holding(
                issuer=existing.issuer,
                cusip=existing.cusip,
                title_of_class=existing.title_of_class,
                value_usd=existing.value_usd + h.value_usd,
                shares=existing.shares + h.shares,
                put_call=existing.put_call,
                investment_discretion=existing.investment_discretion,
            )
        else:
            prior_by_key[key] = h

    latest_keys: set[tuple[str, str | None]] = set()
    positions: list[EnrichedPosition] = []

    for h in latest_holdings:
        canonical = _canonicalize_cusip(h.cusip)
        key = (canonical, h.put_call)
        latest_keys.add(key)
        prior = prior_by_key.get(key)
        ticker = ticker_map.get(h.cusip)

        current_price = current_prices.get(ticker) if ticker else None
        entry_price = entry_prices.get(ticker) if ticker else None

        q_end_price = h.value_usd / h.shares if h.shares else 0.0
        pct_portfolio = (h.value_usd / total_latest * 100) if total_latest else 0.0
        current_value = current_price * h.shares if current_price and h.shares else None
        est_return = (
            (current_price - entry_price) / entry_price * 100
            if current_price is not None and entry_price
            else None
        )
        is_new = prior is None
        qoq_shares = (
            None if is_new else ((h.shares - prior.shares) / prior.shares * 100 if prior.shares else None)
        )

        flag = None
        if h.cusip == "093712107" and prior and prior.cusip == "093712AH0":
            flag = "Q3 filed under convertible CUSIP (093712AH0); Q4 uses common. Entry priced at Q-end."
        elif h.cusip in ("093712AH0",):
            flag = "Filed under convertible-note CUSIP; treat with care."

        positions.append(EnrichedPosition(
            issuer=h.issuer,
            ticker=ticker,
            cusip=h.cusip,
            title_of_class=h.title_of_class,
            put_call=h.put_call,
            latest_shares=h.shares,
            latest_value_usd=h.value_usd,
            prior_shares=prior.shares if prior else None,
            prior_value_usd=prior.value_usd if prior else None,
            pct_portfolio=pct_portfolio,
            q_end_price=q_end_price,
            entry_price=entry_price,
            current_price=current_price,
            current_value_usd=current_value,
            est_return_pct=est_return,
            qoq_shares_pct=qoq_shares,
            is_new=is_new,
            flag=flag,
        ))

    # Exits: in prior but not in latest (by canonical key)
    exits: list[Exit] = []
    for key, h in prior_by_key.items():
        if key in latest_keys:
            continue
        exits.append(Exit(
            issuer=h.issuer,
            ticker=ticker_map.get(h.cusip),
            cusip=h.cusip,
            put_call=h.put_call,
            prior_value_usd=h.value_usd,
        ))

    return DashboardPayload(
        filer_name=filer_name,
        cik=cik,
        latest=latest_filing,
        prior=prior_filing,
        latest_total_usd=total_latest,
        prior_total_usd=total_prior,
        positions=positions,
        exits=exits,
        prices_as_of=prices_as_of,
    )


def unique_tickers(payload_holdings: Iterable[Holding], ticker_map: dict[str, str | None]) -> list[str]:
    """Unique, non-null tickers across a holdings list (helper for price fetching)."""
    seen: set[str] = set()
    out: list[str] = []
    for h in payload_holdings:
        t = ticker_map.get(h.cusip)
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def format_diff_summary(payload: DashboardPayload) -> str:
    """Plain-text diff summary for email / logs / issue body."""
    new_buys = sorted([p for p in payload.positions if p.is_new], key=lambda p: -p.latest_value_usd)
    size_moves = sorted(
        [p for p in payload.positions if not p.is_new and p.qoq_shares_pct not in (None, 0)],
        key=lambda p: -abs(p.qoq_shares_pct or 0),
    )[:10]
    exits = sorted(payload.exits, key=lambda e: -e.prior_value_usd)

    def fmt_money(n: float | int | None) -> str:
        if n is None:
            return "—"
        n = float(n)
        if abs(n) >= 1e9:
            return f"${n/1e9:.2f}B"
        if abs(n) >= 1e6:
            return f"${n/1e6:.1f}M"
        if abs(n) >= 1e3:
            return f"${n/1e3:.0f}K"
        return f"${n:.0f}"

    def pc_tag(pc: str | None) -> str:
        return f" [{pc.upper()}]" if pc else ""

    lines = [
        f"NEW 13F FILING — {payload.filer_name}",
        f"Period: {payload.latest.period_of_report}",
        f"Filed: {payload.latest.filing_date}",
        f"Accession: {payload.latest.accession}",
        f"Total reported value: {fmt_money(payload.latest_total_usd)}",
    ]
    if payload.prior_total_usd:
        delta = (payload.latest_total_usd - payload.prior_total_usd) / payload.prior_total_usd * 100
        lines.append(
            f"vs prior quarter: {fmt_money(payload.prior_total_usd)} ({delta:+.1f}%)"
        )
    lines.append("")

    lines.append(f"NEW BUYS ({len(new_buys)}):")
    for p in new_buys:
        lines.append(
            f"  - {p.issuer} ({p.ticker or p.cusip}){pc_tag(p.put_call)} — {fmt_money(p.latest_value_usd)}"
        )
    if not new_buys:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"EXITS ({len(exits)}):")
    for e in exits:
        lines.append(
            f"  - {e.issuer} ({e.ticker or e.cusip}){pc_tag(e.put_call)} — was {fmt_money(e.prior_value_usd)}"
        )
    if not exits:
        lines.append("  (none)")

    lines.append("")
    lines.append(f"BIGGEST SIZE CHANGES (top {len(size_moves)}):")
    for p in size_moves:
        pct = p.qoq_shares_pct or 0
        sign = "+" if pct >= 0 else ""
        lines.append(
            f"  - {p.issuer} ({p.ticker or p.cusip}){pc_tag(p.put_call)}: "
            f"{sign}{pct:.0f}% shares (now {fmt_money(p.latest_value_usd)})"
        )
    if not size_moves:
        lines.append("  (none)")

    return "\n".join(lines)
