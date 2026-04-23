/**
 * Email signup endpoint — Cloudflare Worker.
 *
 * Accepts { email } POSTs from the tracker dashboard, validates, and adds
 * the address to a Resend audience. Returns JSON { ok: true } on success.
 *
 * Env bindings (set via `wrangler secret put` or dashboard):
 *   RESEND_API_KEY     — Resend API key (starts with `re_`)
 *   RESEND_AUDIENCE_ID — Resend audience UUID
 *   ALLOWED_ORIGIN     — comma-separated list of allowed Origin values (your
 *                        dashboard URL; e.g. https://tracker.example.com)
 */

const JSON_HEADERS = { "Content-Type": "application/json" };

function corsHeaders(origin, allowedOrigins) {
  const allowList = (allowedOrigins || "").split(",").map(s => s.trim()).filter(Boolean);
  const allow = allowList.includes(origin) ? origin : allowList[0] || "*";
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

function jsonResponse(body, status, extraHeaders = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...JSON_HEADERS, ...extraHeaders },
  });
}

// Basic RFC5322-ish email check. We're not trying to be perfect — Resend will
// reject invalid addresses downstream.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const cors = corsHeaders(origin, env.ALLOWED_ORIGIN);

    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    if (request.method !== "POST") {
      return jsonResponse({ ok: false, error: "method not allowed" }, 405, cors);
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return jsonResponse({ ok: false, error: "invalid JSON" }, 400, cors);
    }

    const email = (body?.email || "").trim().toLowerCase();
    if (!email || !EMAIL_RE.test(email) || email.length > 254) {
      return jsonResponse({ ok: false, error: "invalid email" }, 400, cors);
    }

    if (!env.RESEND_API_KEY || !env.RESEND_AUDIENCE_ID) {
      return jsonResponse({ ok: false, error: "server not configured" }, 500, cors);
    }

    const resp = await fetch(
      `https://api.resend.com/audiences/${env.RESEND_AUDIENCE_ID}/contacts`,
      {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${env.RESEND_API_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ email, unsubscribed: false }),
      }
    );

    // Resend returns 200 for new contacts and also for already-present ones (idempotent).
    // A 4xx/5xx means something actually went wrong.
    if (!resp.ok) {
      const errText = await resp.text().catch(() => "");
      console.error(`Resend error ${resp.status}: ${errText}`);
      return jsonResponse({ ok: false, error: "upstream error" }, 502, cors);
    }

    return jsonResponse({ ok: true }, 200, cors);
  },
};
