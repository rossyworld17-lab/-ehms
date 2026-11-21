"""Notification delivery. Email is sent through SMTP when EHMS_SMTP_HOST is configured.
SMS and WhatsApp providers are integration points: until credentials and an adapter are
configured, messages are stored with status 'not_configured' and are never reported as sent."""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage

from .db import get_db, now_iso


def provider_for(channel: str) -> bool:
    if channel == "email":
        return bool(os.environ.get("EHMS_SMTP_HOST"))
    if channel == "in_app":
        return True
    # SMS / WhatsApp adapters are added per provider contract (e.g. Termii, Twilio, Meta Cloud API).
    return False


def send_email(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = os.environ.get("EHMS_SMTP_FROM", "no-reply@ehms.local")
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    host = os.environ["EHMS_SMTP_HOST"]
    port = int(os.environ.get("EHMS_SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as s:
        if os.environ.get("EHMS_SMTP_TLS", "1") == "1":
            s.starttls()
        if os.environ.get("EHMS_SMTP_USER"):
            s.login(os.environ["EHMS_SMTP_USER"], os.environ.get("EHMS_SMTP_PASSWORD", ""))
        s.send_message(msg)


def deliver_queued(limit: int = 50) -> dict:
    """Deliver queued notifications. Run from a scheduler/worker (see docs/DEPLOYMENT.md)."""
    db = get_db()
    sent = failed = 0
    with db.tx() as c:
        rows = c.all("SELECT * FROM notifications WHERE status = 'queued' ORDER BY id LIMIT ?", [limit])
    for n in rows:
        try:
            if n["channel"] == "email":
                send_email(n["recipient"], n["subject"] or "", n["body"])
            status, err = "sent", None
            sent += 1
        except Exception as e:  # pragma: no cover - network
            status, err = "failed", str(e)[:300]
            failed += 1
        with db.tx() as c:
            c.execute("UPDATE notifications SET status = ?, error = ?, sent_at = ? WHERE id = ?",
                      [status, err, now_iso() if status == "sent" else None, n["id"]])
    return {"sent": sent, "failed": failed}
