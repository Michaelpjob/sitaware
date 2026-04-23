/**
 * Vercel serverless function — adds a submitted email to a Resend audience
 * and sends a short welcome message.
 *
 * Env vars (set in Vercel → Project Settings → Environment Variables):
 *   RESEND_API_KEY     — Resend API key (full access, so it can both add
 *                        contacts and send emails)
 *   RESEND_AUDIENCE_ID — Resend audience UUID
 *   EMAIL_FROM         — optional; defaults to "Fundwatch <alerts@fundwatch.app>"
 *   SITE_URL           — optional; defaults to "https://fundwatch.app"
 *
 * Because this is same-origin with the dashboard, no CORS handling is needed.
 */

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const WELCOME_SUBJECT = "You're subscribed — Fundwatch";

function welcomeHtml(siteUrl) {
  return `<!doctype html><html><body style="margin:0;padding:0;background:#fafaf7;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fafaf7;">
<tr><td align="center" style="padding:40px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;background:#ffffff;border:1px solid #e6e4dd;border-radius:8px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;color:#1a1a1a;">
<tr><td style="padding:32px 28px 8px;">
<h1 style="margin:0 0 12px;font-size:20px;font-weight:600;letter-spacing:-0.01em;">You're subscribed.</h1>
<p style="margin:0 0 14px;font-size:14px;line-height:1.55;color:#3b3b36;">You'll get a short email each time <strong>Situational Awareness LP</strong> (Leopold Aschenbrenner's fund) files a new 13F with the SEC — roughly once a quarter, with a summary of new buys, exits, and size changes.</p>
<p style="margin:0 0 18px;font-size:14px;line-height:1.55;color:#3b3b36;">In the meantime, the live dashboard stays fresh weekly:</p>
<p style="margin:0 0 24px;"><a href="${siteUrl}" style="display:inline-block;padding:10px 16px;background:#1a7f4e;color:#ffffff;text-decoration:none;border-radius:6px;font-size:14px;font-weight:500;">Open fundwatch.app →</a></p>
</td></tr>
<tr><td style="padding:0 28px 28px;border-top:1px solid #f1efe8;">
<p style="margin:20px 0 0;font-size:12px;line-height:1.55;color:#8a897f;">Not investment advice. To unsubscribe, just reply and say so.</p>
</td></tr>
</table>
</td></tr>
</table>
</body></html>`;
}

function welcomeText(siteUrl) {
  return `You're subscribed.

You'll get a short email each time Situational Awareness LP (Leopold Aschenbrenner's fund) files a new 13F with the SEC — roughly once a quarter, with a summary of new buys, exits, and size changes.

In the meantime, the live dashboard stays fresh weekly: ${siteUrl}

Not investment advice. To unsubscribe, just reply and say so.
`;
}

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ ok: false, error: "method not allowed" });
  }

  const email = (req.body?.email || "").trim().toLowerCase();
  if (!email || !EMAIL_RE.test(email) || email.length > 254) {
    return res.status(400).json({ ok: false, error: "invalid email" });
  }

  const {
    RESEND_API_KEY,
    RESEND_AUDIENCE_ID,
    EMAIL_FROM = "Fundwatch <alerts@fundwatch.app>",
    SITE_URL = "https://fundwatch.app",
  } = process.env;

  if (!RESEND_API_KEY || !RESEND_AUDIENCE_ID) {
    return res.status(500).json({ ok: false, error: "server not configured" });
  }

  // 1. Add contact to the audience.
  const addResp = await fetch(
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
  if (!addResp.ok) {
    const errText = await addResp.text().catch(() => "");
    console.error(`Resend add-contact error ${addResp.status}: ${errText}`);
    return res.status(502).json({ ok: false, error: "upstream error" });
  }

  // 2. Send the welcome email. If it fails, the subscription still succeeded,
  // so don't fail the whole request — just log it.
  try {
    const sendResp = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: EMAIL_FROM,
        to: [email],
        subject: WELCOME_SUBJECT,
        html: welcomeHtml(SITE_URL),
        text: welcomeText(SITE_URL),
      }),
    });
    if (!sendResp.ok) {
      const errText = await sendResp.text().catch(() => "");
      console.error(`Resend send-welcome error ${sendResp.status}: ${errText}`);
    }
  } catch (err) {
    console.error("Resend send-welcome threw:", err);
  }

  return res.status(200).json({ ok: true });
}
