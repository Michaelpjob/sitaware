/**
 * Live prices endpoint — Vercel serverless function.
 *
 * GET /api/prices?tickers=BE,VST,EQT,...
 *
 * Calls Yahoo Finance's public quote endpoint, normalizes the response, and
 * caches at the edge for 60s so reload spam doesn't burn through rate limits.
 *
 * No API key needed. Yahoo can rate-limit by IP and occasionally returns 4xx;
 * the frontend handles that by falling back to the static render.
 */

const YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote";
const YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart";

// Yahoo blocks some "default" UAs. Pretend to be a real browser.
const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

const TICKER_RE = /^[A-Za-z0-9.\-^]{1,12}$/;
const MAX_TICKERS = 80;

async function fetchQuoteBatch(tickers) {
  const url = `${YAHOO_QUOTE_URL}?symbols=${encodeURIComponent(tickers.join(","))}`;
  const resp = await fetch(url, { headers: { "User-Agent": BROWSER_UA, Accept: "application/json" } });
  if (!resp.ok) throw new Error(`yahoo quote ${resp.status}`);
  const data = await resp.json();
  return data?.quoteResponse?.result || [];
}

async function fetchChartFallback(ticker) {
  // Per-ticker fallback that works when /v7/finance/quote is rate-limited.
  const url = `${YAHOO_CHART_URL}/${encodeURIComponent(ticker)}?interval=1d&range=5d`;
  const resp = await fetch(url, { headers: { "User-Agent": BROWSER_UA, Accept: "application/json" } });
  if (!resp.ok) return null;
  const data = await resp.json();
  const r = data?.chart?.result?.[0];
  if (!r) return null;
  const meta = r.meta || {};
  const closes = r.indicators?.quote?.[0]?.close || [];
  const last = [...closes].reverse().find((v) => v != null);
  if (last == null) return null;
  const prev = meta.chartPreviousClose ?? meta.previousClose ?? null;
  const change = prev != null ? last - prev : null;
  const changePct = prev != null && prev !== 0 ? ((last - prev) / prev) * 100 : null;
  return {
    symbol: ticker,
    regularMarketPrice: last,
    regularMarketChange: change,
    regularMarketChangePercent: changePct,
    regularMarketTime: meta.regularMarketTime ?? Math.floor(Date.now() / 1000),
    currency: meta.currency || null,
  };
}

export default async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).json({ ok: false, error: "method not allowed" });
  }

  const raw = String(req.query.tickers || "").trim();
  if (!raw) return res.status(400).json({ ok: false, error: "missing tickers" });

  const tickers = [...new Set(raw.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean))]
    .filter((t) => TICKER_RE.test(t))
    .slice(0, MAX_TICKERS);
  if (tickers.length === 0) return res.status(400).json({ ok: false, error: "no valid tickers" });

  const out = {};
  let primaryFailed = false;
  try {
    const quotes = await fetchQuoteBatch(tickers);
    for (const q of quotes) {
      if (!q?.symbol) continue;
      out[q.symbol.toUpperCase()] = {
        price: q.regularMarketPrice ?? null,
        change: q.regularMarketChange ?? null,
        changePct: q.regularMarketChangePercent ?? null,
        ts: q.regularMarketTime ?? null,
        currency: q.currency ?? null,
      };
    }
  } catch (err) {
    console.warn("yahoo batch failed:", err.message);
    primaryFailed = true;
  }

  // Fill in any missing tickers via the chart fallback.
  const missing = tickers.filter((t) => !out[t]);
  if (missing.length) {
    const results = await Promise.allSettled(missing.map(fetchChartFallback));
    for (let i = 0; i < missing.length; i++) {
      const r = results[i];
      if (r.status !== "fulfilled" || !r.value) continue;
      const q = r.value;
      out[q.symbol.toUpperCase()] = {
        price: q.regularMarketPrice ?? null,
        change: q.regularMarketChange ?? null,
        changePct: q.regularMarketChangePercent ?? null,
        ts: q.regularMarketTime ?? null,
        currency: q.currency ?? null,
      };
    }
  }

  res.setHeader("Cache-Control", "public, s-maxage=60, stale-while-revalidate=300");
  res.status(200).json({
    ok: true,
    asOf: Math.floor(Date.now() / 1000),
    primaryFailed,
    quotes: out,
  });
}
