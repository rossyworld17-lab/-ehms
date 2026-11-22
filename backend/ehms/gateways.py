"""Payment gateway adapters (Paystack, Flutterwave) and a small resilient HTTP client.

Rules: an online payment is credited only after the gateway's *verify* API confirms it (webhook bodies are
never trusted on their own), the amount and currency must match what was requested, and crediting is
idempotent per gateway reference. Every outbound call and inbound webhook is written to integration_logs.

Configuration (environment):
  PAYSTACK_SECRET_KEY                       enables Paystack (webhook signature = HMAC-SHA512 of the body)
  FLUTTERWAVE_SECRET_KEY, FLUTTERWAVE_WEBHOOK_HASH   enables Flutterwave (webhook header 'verif-hash')
  EHMS_PAYMENT_PROVIDER                     preferred provider when both are configured
  EHMS_PUBLIC_URL                           public base URL used for the gateway return page
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request

from .db import Connection, get_db, now_iso
from .http import ApiError

PROVIDERS = ("paystack", "flutterwave")


def configured_providers() -> list[str]:
    out = []
    if os.environ.get("PAYSTACK_SECRET_KEY"):
        out.append("paystack")
    if os.environ.get("FLUTTERWAVE_SECRET_KEY"):
        out.append("flutterwave")
    return out


def default_provider() -> str | None:
    prov = configured_providers()
    pref = os.environ.get("EHMS_PAYMENT_PROVIDER")
    return pref if pref in prov else (prov[0] if prov else None)


def log_integration(hotel_id: int | None, integration: str, direction: str, endpoint: str, status_code: int | None, ok: bool,
                    summary: str = "", error: str | None = None, attempt: int = 1) -> None:
    """Integration logs are written in their own transaction so they survive a rolled-back business transaction."""
    try:
        with get_db().tx() as c:
            c.insert("integration_logs", {"hotel_id": hotel_id, "integration": integration, "direction": direction, "endpoint": endpoint[:300],
                                          "status_code": status_code, "attempt": attempt, "ok": 1 if ok else 0, "summary": (summary or "")[:500],
                                          "error": (error or "")[:500] or None, "created_at": now_iso()})
    except Exception:  # pragma: no cover - logging must never break the caller
        pass


def _transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# tests replace this with a fake; production uses urllib
transport = _transport


def http_json(integration: str, hotel_id: int | None, method: str, url: str, headers: dict, payload: dict | None = None,
              retries: int = 3, timeout: float = 20.0) -> dict:
    """JSON request with retries on network errors and 5xx responses (exponential back-off)."""
    body = json.dumps(payload).encode() if payload is not None else None
    hdrs = {"Content-Type": "application/json", "Accept": "application/json", **headers}
    last = "unknown error"
    for attempt in range(1, retries + 1):
        try:
            status, raw = transport(method, url, hdrs, body, timeout)
            data = json.loads(raw or b"{}")
            ok = 200 <= status < 300
            log_integration(hotel_id, integration, "outbound", f"{method} {url.split('?')[0]}", status, ok,
                            str(data.get("message") or data.get("status") or "")[:200], None if ok else str(data)[:300], attempt)
            if status >= 500:
                last = f"HTTP {status}"
            else:
                return {"status": status, "data": data}
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            last = str(e)
            log_integration(hotel_id, integration, "outbound", f"{method} {url.split('?')[0]}", None, False, "", last, attempt)
        if attempt < retries:
            time.sleep(min(4.0, 0.5 * 2 ** (attempt - 1)))
    raise ApiError(502, "gateway_unreachable", f"The payment provider could not be reached ({last}). No payment was taken; try again.")


# ------------------------------------------------------------------ provider adapters
def initialize(provider: str, hotel_id: int, reference: str, amount_minor: int, currency: str, email: str, callback_url: str) -> str:
    """Create a hosted checkout and return the URL the payer is sent to."""
    if provider == "paystack":
        r = http_json("paystack", hotel_id, "POST", "https://api.paystack.co/transaction/initialize",
                      {"Authorization": f"Bearer {os.environ['PAYSTACK_SECRET_KEY']}"},
                      {"email": email, "amount": amount_minor, "currency": currency, "reference": reference, "callback_url": callback_url})
        d = r["data"]
        if r["status"] != 200 or not d.get("status"):
            raise ApiError(502, "gateway_error", f"Paystack refused the request: {d.get('message', 'unknown error')}")
        return d["data"]["authorization_url"]
    if provider == "flutterwave":
        r = http_json("flutterwave", hotel_id, "POST", "https://api.flutterwave.com/v3/payments",
                      {"Authorization": f"Bearer {os.environ['FLUTTERWAVE_SECRET_KEY']}"},
                      {"tx_ref": reference, "amount": f"{amount_minor / 100:.2f}", "currency": currency, "redirect_url": callback_url,
                       "customer": {"email": email}})
        d = r["data"]
        if r["status"] != 200 or d.get("status") != "success":
            raise ApiError(502, "gateway_error", f"Flutterwave refused the request: {d.get('message', 'unknown error')}")
        return d["data"]["link"]
    raise ApiError(400, "bad_request", "Unknown payment provider")


def verify(provider: str, hotel_id: int, reference: str) -> dict:
    """Ask the provider for the authoritative status. Returns {paid, amount (minor), currency, status}."""
    if provider == "paystack":
        r = http_json("paystack", hotel_id, "GET", f"https://api.paystack.co/transaction/verify/{reference}",
                      {"Authorization": f"Bearer {os.environ['PAYSTACK_SECRET_KEY']}"})
        d = (r["data"] or {}).get("data") or {}
        return {"paid": d.get("status") == "success", "amount": int(d.get("amount") or 0), "currency": d.get("currency"),
                "status": d.get("status") or "unknown"}
    if provider == "flutterwave":
        r = http_json("flutterwave", hotel_id, "GET", f"https://api.flutterwave.com/v3/transactions/verify_by_reference?tx_ref={reference}",
                      {"Authorization": f"Bearer {os.environ['FLUTTERWAVE_SECRET_KEY']}"})
        d = (r["data"] or {}).get("data") or {}
        amount = int(round(float(d.get("amount") or 0) * 100))
        return {"paid": d.get("status") == "successful", "amount": amount, "currency": d.get("currency"), "status": d.get("status") or "unknown"}
    raise ApiError(400, "bad_request", "Unknown payment provider")


def valid_webhook(provider: str, raw: bytes, headers) -> bool:
    if provider == "paystack":
        secret = os.environ.get("PAYSTACK_SECRET_KEY", "")
        sig = headers.get("x-paystack-signature", "")
        return bool(secret and sig) and hmac.compare_digest(hmac.new(secret.encode(), raw, hashlib.sha512).hexdigest(), sig)
    if provider == "flutterwave":
        expected = os.environ.get("FLUTTERWAVE_WEBHOOK_HASH", "")
        return bool(expected) and hmac.compare_digest(expected, headers.get("verif-hash", ""))
    return False


def webhook_reference(provider: str, body: dict) -> str | None:
    data = (body or {}).get("data") or {}
    return data.get("reference") if provider == "paystack" else data.get("tx_ref")


# ------------------------------------------------------------------ crediting
def online_method(c: Connection, hotel_id: int, organisation_id: int) -> dict:
    m = c.one("SELECT * FROM payment_methods WHERE hotel_id = ? AND kind = 'online' AND active = 1 ORDER BY id LIMIT 1", [hotel_id])
    if m:
        return m
    from .services import account_id
    c.insert("payment_methods", {"hotel_id": hotel_id, "code": "ONLINE", "name": "Online payment (card / transfer via gateway)", "kind": "online",
                                 "account_id": account_id(c, organisation_id, "online_clearing"), "active": 1})
    return c.one("SELECT * FROM payment_methods WHERE hotel_id = ? AND code = 'ONLINE'", [hotel_id])
