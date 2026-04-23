/**
 * Vercel serverless function — adds a submitted email to a Resend audience.
 *
 * Env vars (set in Vercel → Project Settings → Environment Variables):
 *   RESEND_API_KEY     — Resend API key (starts with `re_`)
 *   RESEND_AUDIENCE_ID — Resend audience UUID
 *
 * Because this is same-origin with the dashboard, no CORS handling is needed.
 */

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "method not allowed" });
  }

  const email = (req.body?.email || "").trim().toLowerCase();
  if (!email || !EMAIL_RE.test(email) || email.length > 254) {
    return res.status(400).json({ ok: false, error: "invalid email" });
  }

  const { RESEND_API_KEY, RESEND_AUDIENCE_ID } = process.env;
  if (!RESEND_API_KEY || !RESEND_AUDIENCE_ID) {
    return res.status(500).json({ ok: false, error: "server not configured" });
  }

  const upstream = await fetch(
    `https://api.resend.com/audiences/${RESEND_AUDIENCE_ID}/contacts`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ email, unsubscribed: false }),
    }
  );

  if (!upstream.ok) {
    const errText = await upstream.text().catch(() => "");
    console.error(`Resend error ${upstream.status}: ${errText}`);
    return res.status(502).json({ ok: false, error: "upstream error" });
  }

  return res.status(200).json({ ok: true });
}
