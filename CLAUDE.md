# CLAUDE.md — Situational Awareness LP 13F Tracker

Context for Claude Code working in this repo.

## What this is

A weekly job that watches SEC EDGAR for new 13F-HR filings by **Situational Awareness LP** (Leopold Aschenbrenner's hedge fund, CIK 0002045724) and rebuilds a static dashboard (`docs/index.html`) showing the fund's holdings, estimated cost basis, current returns, and a quarter-over-quarter diff of new buys / exits / size changes. When a new filing is detected, it emails a summary via Resend.

Deployed via GitHub Pages + a GitHub Actions cron (Monday mornings). The dashboard is committed to `docs/index.html` each run; GitHub Pages serves it.

## Architecture at a glance

```
run.py                  ← Entry point. Orchestrates the whole pipeline.
src/
  edgar.py              ← Fetch 13F filings from SEC EDGAR, parse info-table XML.
  prices.py             ← yfinance wrappers: current price + quarterly average close.
  cusip_map.py          ← CUSIP → ticker lookup. Seeded mapping in data/cusip_tickers.json;
                          unknown CUSIPs fall back to OpenFIGI's free API.
  compute.py            ← Pure functions: diff two filings, compute returns, QoQ shares.
  render.py             ← Jinja2 render of templates/dashboard.html.j2 → docs/index.html.
  alert.py              ← Resend email; fallback to stdout if no API key.
templates/
  dashboard.html.j2     ← Dashboard HTML + CSS. Ported from a Cowork artifact prototype.
data/
  state.json            ← Persisted state: last-seen accession number. Read/written by run.py.
  cusip_tickers.json    ← Known CUSIP→ticker mappings. Grows over time.
tests/                  ← pytest. Offline, uses recorded fixtures.
docs/
  index.html            ← Generated dashboard. Committed to the repo. GitHub Pages serves it.
.github/workflows/
  weekly-check.yml      ← Cron: Monday 13:00 UTC (9am ET). Also manual dispatch.
```

Data flow on each run:

1. `run.py` calls `edgar.get_latest_13f_hr("0002045724")` to find the most recent filing.
2. Compares its accession number to `data/state.json.last_accession`. If unchanged → no-op, exit 0.
3. If new: also fetch the prior 13F-HR for the QoQ diff.
4. Parse each info table into a list of positions.
5. Resolve CUSIPs to tickers via `cusip_map.resolve(cusip)`.
6. For each unique ticker, call `prices.get_current()` and `prices.get_quarterly_avg(year, quarter)`.
7. `compute.build_dashboard_data()` assembles the enriched positions + diff payload.
8. `render.write_dashboard()` renders `docs/index.html`.
9. `alert.send_new_filing_alert()` emails the diff summary.
10. Write the new accession to `state.json`.

## Invariants / gotchas

- **SEC User-Agent**: Every request to sec.gov must include a `User-Agent` header identifying the requester (SEC rate-limits unidentified traffic). Controlled by `SEC_USER_AGENT` env var, defaulted in `edgar.py`. Don't remove this or EDGAR will 403.
- **SEC rate limit**: Max 10 req/sec. `edgar.py` sleeps 110ms between requests as a safety.
- **Info-table values are in whole USD** (post-2022 filings). Older filings reported thousands — don't assume!
- **Options rows**: 13F `<infoTable>` entries with `<putCall>` set (Call/Put) have the *notional* of the underlying, not option premium. Don't compute P&L on options rows — only % change in the underlying reference price. The render layer labels these clearly.
- **Bloom Energy Q3 2025 anomaly**: The Q3 2025 filing listed BE under CUSIP `093712AH0` (the convertible-note CUSIP), not the common CUSIP `093712107`. Q4 2025 corrected it. The CUSIP map handles both, but the diff logic may see this as a fake "exit + new buy" if not treated carefully — see `compute._reconcile_issuer_cusip_changes()`.
- **CUSIP stability**: CUSIPs occasionally change when a security is reclassified (e.g., convertible → common). Issuers can also rename, so rely on CUSIP as the join key, not issuer name.
- **Quarterly average price**: `prices.get_quarterly_avg()` uses the mean daily close over the quarter — a proxy for VWAP since 13Fs don't disclose actual fills. This is the "estimated entry price" shown in the dashboard.
- **Unknown CUSIPs**: OpenFIGI responds in ~1-2s per lookup. We cache results in `data/cusip_tickers.json` and commit that file so lookups are mostly free after first run.
- **Empty filing result**: EDGAR occasionally serves a partial or empty document for a few minutes around filing time. `edgar.py` treats an empty `<informationTable>` as an error and retries up to 3 times with exponential backoff.
- **No new filings for 3+ months is normal** — 13Fs are quarterly with a 45-day lag. Don't interpret silence as a bug.

## Environment

Required env vars:
```
SEC_USER_AGENT       "Michael J (michael.job.gb@gmail.com)"   # SEC requires identification
RESEND_API_KEY       re_xxx...                                 # optional; if absent, email is skipped
ALERT_EMAIL_FROM     alerts@yourdomain.com                     # must be a verified Resend sender
ALERT_EMAIL_TO       michael.job.gb@gmail.com
```

In production (GitHub Actions), these are set as repo secrets. Locally, use a `.env` file (not committed) — see `.env.example`.

## Running locally

```bash
# Install
pip install -e .

# Run the full pipeline (won't send email if RESEND_API_KEY unset)
python run.py

# Run tests
pytest

# Force-regenerate the dashboard even if no new filing (useful for template edits)
python run.py --force

# Check EDGAR without writing anything
python run.py --dry-run
```

## Deploying to GitHub Pages

1. Push the repo to GitHub.
2. In Settings → Pages, set source to "Deploy from a branch", branch `main`, folder `/docs`.
3. Add `RESEND_API_KEY`, `ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO` as repo secrets.
4. The weekly workflow (`.github/workflows/weekly-check.yml`) runs every Monday at 13:00 UTC and on manual dispatch. It commits `docs/index.html` + `data/state.json` + `data/cusip_tickers.json` back to `main` when anything changes.

The Action also files a GitHub Issue whenever a new 13F is detected — a belt-and-suspenders alert alongside email.

## Tests

```bash
pytest                 # everything
pytest -k edgar        # just parsing
pytest --cov=src       # with coverage
```

Tests use recorded fixture XML in `tests/fixtures/` so they're fully offline. If SEC changes the 13F schema, re-record by running `scripts/refresh_fixtures.py` (TODO: not written yet — Claude Code, this is a reasonable thing to add).

## Extending to other funds

The CIK is parameterized in `run.py`. To watch a different fund:

```bash
python run.py --cik 0001234567
```

To track multiple funds, loop over a list of CIKs in `run.py` and render one dashboard per fund (or a combined one). The render layer accepts a fund name/CIK as a parameter.

## Known TODOs

- [ ] Add a "historical AUM" sparkline using older filings (go back further than 2 quarters).
- [ ] Distinguish between "new position" and "position reclassified under different CUSIP" in the diff panel.
- [ ] Add Form 4 (insider buy/sell) monitoring as a separate job — would give faster signal than 13F's 45-day lag.
- [ ] Write `scripts/refresh_fixtures.py` for easy fixture re-recording.
- [ ] Consider options P&L: infer approximate premium from IV at filing date → compute real P&L on option rows.
