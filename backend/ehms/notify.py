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
    if channel == "sms":
        return bool(os.environ.get("EHMS_TERMII_API_KEY"))
    if channel == "whatsapp":
        return bool(os.environ.get("EHMS_WHATSAPP_TOKEN") and os.environ.get("EHMS_WHATSAPP_PHONE_ID"))
    return False


def send_sms(to: str, body: str) -> None:
    """Termii SMS API (Nigeria). Raises on a non-success response."""
    from .gateways import http_json
    r = http_json("termii", None, "POST", "https://api.ng.termii.com/api/sms/send", {},
                  {"api_key": os.environ["EHMS_TERMII_API_KEY"], "to": to.replace("+", "").replace(" ", ""),
                   "from": os.environ.get("EHMS_TERMII_SENDER", "EHMS"), "sms": body[:900], "type": "plain", "channel": "generic"}, retries=2)
    if r["status"] >= 300:
        raise RuntimeError(f"Termii HTTP {r['status']}: {str(r['data'])[:200]}")


def send_whatsapp(to: str, body: str) -> None:
    """WhatsApp Business Cloud API text message (an approved template is needed outside the 24-hour service window)."""
    from .gateways import http_json
    r = http_json("whatsapp", None, "POST", f"https://graph.facebook.com/v19.0/{os.environ['EHMS_WHATSAPP_PHONE_ID']}/messages",
                  {"Authorization": f"Bearer {os.environ['EHMS_WHATSAPP_TOKEN']}"},
                  {"messaging_product": "whatsapp", "to": to.replace("+", "").replace(" ", ""), "type": "text", "text": {"body": body[:4000]}}, retries=2)
    if r["status"] >= 300:
        raise RuntimeError(f"WhatsApp HTTP {r['status']}: {str(r['data'])[:200]}")


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


MAX_ATTEMPTS = 3


def deliver_queued(limit: int = 50) -> dict:
    """Deliver queued email/SMS/WhatsApp messages. Failed sends are retried up to MAX_ATTEMPTS times, then
    marked 'failed' with the provider's error (visible in Messaging → Delivery log)."""
    db = get_db()
    sent = failed = 0
    with db.tx() as c:
        rows = c.all("SELECT * FROM notifications WHERE status = 'queued' AND channel <> 'in_app' ORDER BY id LIMIT ?", [limit])
    for n in rows:
        try:
            if n["channel"] == "email":
                send_email(n["recipient"], n["subject"] or "", n["body"])
            elif n["channel"] == "sms":
                send_sms(n["recipient"], n["body"])
            elif n["channel"] == "whatsapp":
                send_whatsapp(n["recipient"], n["body"])
            status, err = "sent", None
            sent += 1
        except Exception as e:
            err = str(e)[:300]
            status = "failed" if (n.get("attempts") or 0) + 1 >= MAX_ATTEMPTS else "queued"
            failed += 1
        with db.tx() as c:
            c.execute("UPDATE notifications SET status = ?, error = ?, sent_at = ?, attempts = attempts + 1 WHERE id = ?",
                      [status, err, now_iso() if status == "sent" else None, n["id"]])
    return {"sent": sent, "failed": failed}
