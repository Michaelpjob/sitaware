# Situational Awareness LP — 13F Tracker

A weekly watcher for **Leopold Aschenbrenner's hedge fund** (Situational Awareness LP, SEC CIK `0002045724`). Fetches 13F-HR filings, computes estimated cost basis and returns, renders a static dashboard, and emails a diff when a new filing lands.

Built to run on GitHub Actions + GitHub Pages, free. Works locally too.

## What you get

- A clean static dashboard at `docs/index.html` — sortable holdings table, new-buys/exits/size-changes panels, top-line AUM and concentration stats.
- A weekly cron that checks SEC EDGAR, updates the dashboard, and alerts you on new filings (email via Resend, plus a GitHub Issue).
- Tests that run offline using recorded fixtures, so you (and Claude Code) can iterate safely.

![dashboard preview](docs/preview.png)

## Quick start

### 1. Clone and set up

```bash
git clone <your fork of this repo>
cd situational-awareness-tracker

python -m venv .venv && source .venv/bin/activate   # or use uv/poetry
pip install -e .

cp .env.example .env
# Edit .env — at minimum, set SEC_USER_AGENT
```

### 2. Run the pipeline

```bash
python run.py
```

First run will:
- Pull the two most recent 13F-HR filings from EDGAR for CIK 0002045724.
- Resolve CUSIPs → tickers (cached to `data/cusip_tickers.json`).
- Fetch current prices + quarterly average prices via yfinance.
- Render `docs/index.html`.
- Save the filing's accession number to `data/state.json`.
- Send an email (if `RESEND_API_KEY` is set).

Open `docs/index.html` in a browser to view the dashboard.

### 3. Schedule it

**GitHub Actions (recommended)**
1. Push to GitHub.
2. Repo → Settings → Pages → Source: `Deploy from a branch`, branch `main`, folder `/docs`.
3. Repo → Settings → Secrets and variables → Actions → add:
   - `SEC_USER_AGENT` (e.g. `"Michael J (michael.job.gb@gmail.com)"`)
   - `RESEND_API_KEY`
   - `ALERT_EMAIL_FROM` (a verified Resend sender)
   - `ALERT_EMAIL_TO`
4. The workflow in `.github/workflows/weekly-check.yml` runs every Monday at 13:00 UTC and on manual dispatch.

**Local cron (alternative)**
```cron
0 13 * * 1 cd /path/to/tracker && .venv/bin/python run.py >> tracker.log 2>&1
```

### 4. Extend it

See `CLAUDE.md` for architecture and gotchas — written for Claude Code to work in this repo productively.

To track a different fund:
```bash
python run.py --cik 0001234567 --name "Fund Name"
```

## CLI

```
python run.py                     # normal run
python run.py --force             # regenerate dashboard even if no new filing
python run.py --dry-run           # check EDGAR, log what would happen, exit
python run.py --cik 0002045724    # override which CIK to watch
python run.py --no-email          # skip email alert
```

## Testing

```bash
pytest                           # everything (offline)
pytest -v                        # verbose
pytest --cov=src                 # coverage
```

Fixtures are recorded in `tests/fixtures/`. Re-record with `scripts/refresh_fixtures.py` if SEC changes their format (Claude Code can write this if needed).

## How it works

1. **EDGAR discovery** — `src/edgar.py` hits `data.sec.gov/submissions/CIK{cik}.json` to find recent filings, filters to form `13F-HR` (or `13F-HR/A` amendments).
2. **Info-table parsing** — grabs the information table XML from the filing's document set and parses each `<infoTable>` (issuer, CUSIP, class, value in USD, shares, put/call if option).
3. **CUSIP → ticker** — `src/cusip_map.py` uses a local JSON cache, falling back to OpenFIGI's free API for unknown CUSIPs.
4. **Prices** — `src/prices.py` wraps `yfinance` for current price and the mean daily close over the quarter the position first appeared (used as a cost-basis proxy).
5. **Compute** — `src/compute.py` joins the two filings by CUSIP, tags new/exited/changed positions, and computes per-position returns and % of portfolio.
6. **Render** — `src/render.py` feeds the enriched data into `templates/dashboard.html.j2` and writes `docs/index.html`.
7. **Alert** — `src/alert.py` emails via Resend when the new filing's accession number differs from what's in `data/state.json`.

## Caveats to read before using this seriously

- **13Fs show long US equity + listed options only.** No shorts on common stock, no foreign listings, no private positions, no fixed income.
- **~45-day lag** from quarter-end to filing — by the time you see a holding, the position may already be different.
- **Cost basis is an estimate.** The "entry price" shown is the quarterly average closing price, not actual fills. True VWAP requires intraday data 13Fs don't disclose.
- **Option rows show notional, not premium.** Returns on option rows reflect % change in the underlying, not actual option P&L.
- **Not investment advice.** This is a tool to observe public filings, not a recommendation.

## License

MIT.
