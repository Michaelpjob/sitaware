"""Email alerts via Resend."""
from __future__ import annotations

import logging
import os

import resend

log = logging.getLogger(__name__)


def send_new_filing_alert(subject: str, body_text: str, body_html: str | None = None) -> bool:
    """Send an email. Returns True on success, False if skipped/failed.

    Requires RESEND_API_KEY, ALERT_EMAIL_FROM, ALERT_EMAIL_TO env vars.
    If any is missing, logs a warning and returns False.
    """
    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = os.environ.get("ALERT_EMAIL_FROM", "").strip()
    recipient = os.environ.get("ALERT_EMAIL_TO", "").strip()

    if not api_key:
        log.info("RESEND_API_KEY not set; email skipped. Body follows:\n%s", body_text)
        return False
    if not sender or not recipient:
        log.warning("ALERT_EMAIL_FROM or ALERT_EMAIL_TO missing; email skipped.")
        return False

    resend.api_key = api_key
    try:
        resend.Emails.send({
            "from": sender,
            "to": [recipient],
            "subject": subject,
            "text": body_text,
            "html": body_html or f"<pre style='font-family:ui-monospace,Menlo,monospace;font-size:13px;'>{body_text}</pre>",
        })
        log.info("Email sent to %s via Resend.", recipient)
        return True
    except Exception as exc:
        log.error("Resend send failed: %s", exc)
        return False
