"""Online payments (payment links, booking-engine prepayment, gateway webhooks) and promotional codes.
(FR-PAY-001/003, FR-BKG-003/005, FR-SAL-002, integration requirements in section 26)"""
from __future__ import annotations

import datetime as dt
import os
import uuid

from ..db import get_db, now_iso
from ..http import ApiError, Ctx, audit, bad_request, conflict, not_found, route
from .. import gateways
from ..services import account_id, business_date, get_hotel, parse_date, post_journal, queue_notification, to_minor


def _callback_url(ctx: Ctx | None) -> str:
    base = os.environ.get("EHMS_PUBLIC_URL")
    if not base and ctx and ctx.request:
        base = str(ctx.request.base_url).rstrip("/")
    return f"{(base or 'http://localhost:8000').rstrip('/')}/payment-return"


def start_payment(ctx: Ctx | None, hotel_id: int, purpose: str, folio_id: int, reservation_id: int | None, amount: int, email: str,
                  provider: str | None = None) -> dict:
    """Record the transaction first, then call the gateway outside any database transaction."""
    provider = provider or gateways.default_provider()
    if not provider or provider not in gateways.configured_providers():
        raise ApiError(501, "gateway_not_configured", "No online payment provider is configured (set PAYSTACK_SECRET_KEY or FLUTTERWAVE_SECRET_KEY).")
    with get_db().tx() as c:
        hotel = get_hotel(c, hotel_id)
        ref = f"EHMS-{hotel['code']}-{uuid.uuid4().hex[:16].upper()}"
        tid = c.insert("gateway_transactions", {"hotel_id": hotel_id, "provider": provider, "reference": ref, "purpose": purpose, "folio_id": folio_id,
                                                "reservation_id": reservation_id, "amount": amount, "currency": hotel["currency"], "email": email,
                                                "status": "initialized", "created_by": ctx.user_id if ctx else None, "created_at": now_iso()})
    url = gateways.initialize(provider, hotel_id, ref, amount, hotel["currency"], email, _callback_url(ctx))
    with get_db().tx() as c:
        c.update("gateway_transactions", tid, {"authorization_url": url})
    return {"id": tid, "reference": ref, "provider": provider, "authorization_url": url, "amount": amount, "currency": hotel["currency"]}


def apply_verification(reference: str, source: str) -> dict:
    """Verify with the provider and credit the folio exactly once."""
    with get_db().tx() as c:
        tx = c.one("SELECT * FROM gateway_transactions WHERE reference = ?", [reference])
    if not tx:
        raise not_found("Payment")
    if tx["status"] == "success":
        return {"reference": reference, "status": "success", "already_recorded": True, "reservation_id": tx["reservation_id"]}
    result = gateways.verify(tx["provider"], tx["hotel_id"], reference)
    with get_db().tx() as c:
        tx = c.lock("gateway_transactions", tx["id"])
        if tx["status"] == "success":
            return {"reference": reference, "status": "success", "already_recorded": True, "reservation_id": tx["reservation_id"]}
        if not result["paid"]:
            c.update("gateway_transactions", tx["id"], {"gateway_status": result["status"], "status": "failed" if result["status"] in ("failed", "abandoned", "cancelled") else tx["status"]})
            return {"reference": reference, "status": "failed" if result["status"] in ("failed", "abandoned", "cancelled") else "pending",
                    "gateway_status": result["status"]}
        if result["amount"] != tx["amount"] or (result["currency"] or tx["currency"]) != tx["currency"]:
            c.update("gateway_transactions", tx["id"], {"status": "amount_mismatch", "gateway_status": result["status"], "verified_at": now_iso()})
            audit(c, None, "gateway.amount_mismatch", "gateway_transaction", tx["id"], reference,
                  new={"expected": tx["amount"], "received": result["amount"], "currency": result["currency"]}, hotel_id=tx["hotel_id"])
            return {"reference": reference, "status": "amount_mismatch"}
        hotel = get_hotel(c, tx["hotel_id"])
        folio = c.one("SELECT * FROM folios WHERE id = ?", [tx["folio_id"]])
        m = gateways.online_method(c, hotel["id"], hotel["organisation_id"])
        on = business_date(hotel)
        je = post_journal(c, hotel["id"], on, f"Online payment {tx['provider']} {reference} on {folio['number']}", "payment", reference, [
            (m["account_id"], tx["amount"], 0, None, f"{tx['provider']} {reference}"),
            (account_id(c, hotel["organisation_id"], "guest_ledger"), 0, tx["amount"], None, f"Payment on {folio['number']}")], None)
        pid = c.insert("payments", {"hotel_id": hotel["id"], "folio_id": folio["id"], "method_id": m["id"], "kind": "payment", "amount": tx["amount"],
                                    "currency": tx["currency"], "status": "completed", "reference": reference, "idempotency_key": f"gw-{reference}",
                                    "gateway": tx["provider"], "gateway_reference": reference, "note": f"Verified via {source}", "journal_entry_id": je,
                                    "created_at": now_iso()})
        c.insert("folio_lines", {"folio_id": folio["id"], "business_date": on.isoformat(), "kind": "payment", "department": "payment",
                                 "description": f"Online payment — {tx['provider'].title()} ({reference})", "quantity": 1, "net_amount": tx["amount"],
                                 "tax_amount": 0, "service_charge": 0, "total_amount": tx["amount"], "reference": reference, "payment_id": pid,
                                 "journal_entry_id": je, "posted_at": now_iso()})
        c.update("gateway_transactions", tx["id"], {"status": "success", "gateway_status": result["status"], "payment_id": pid, "verified_at": now_iso()})
        if tx["purpose"] == "booking" and tx["reservation_id"]:
            r = c.one("SELECT * FROM reservations WHERE id = ?", [tx["reservation_id"]])
            if r["status"] == "tentative":
                c.update("reservations", r["id"], {"status": "confirmed", "notes": "Online booking — prepaid online", "updated_at": now_iso()})
            queue_notification(c, hotel["id"], "email", tx["email"], f"Payment received — booking {r['reference']} confirmed",
                               f"Thank you. We received {tx['currency']} {tx['amount'] / 100:,.2f} for booking {r['reference']} at {hotel['name']}. "
                               f"Your reservation is confirmed.", "reservation", r["id"])
        audit(c, None, "gateway.payment_recorded", "payment", pid, reference, new={"amount": tx["amount"], "provider": tx["provider"], "source": source},
              hotel_id=hotel["id"])
    return {"reference": reference, "status": "success", "payment_id": pid, "reservation_id": tx["reservation_id"]}


@route("GET", "/api/payments/gateway-status", tag="payments", summary="Which online payment providers are configured")
def gateway_status(ctx: Ctx):
    return {"providers": gateways.configured_providers(), "default": gateways.default_provider()}


@route("POST", "/api/folios/{folio_id:int}/payment-link", perm="payments.receive", tag="payments",
       summary="Create an online payment link for a folio amount and (optionally) email it to the guest")
def payment_link(ctx: Ctx):
    amount = to_minor(ctx.field("amount"))
    if amount <= 0:
        raise bad_request("Amount must be greater than zero")
    with get_db().tx() as c:
        f = c.one("SELECT * FROM folios WHERE id = ?", [ctx.path["folio_id"]])
        if not f:
            raise not_found("Folio")
        ctx.check_hotel(f["hotel_id"])
        if f["status"] != "open":
            raise conflict("This folio is closed")
        email = ctx.field("email", required=False, kind=str) or c.scalar("SELECT email FROM guests WHERE id = ?", [f["guest_id"]])
        if not email:
            raise bad_request("The guest has no email address; enter one for the payment link", {"field": "email"})
    out = start_payment(ctx, f["hotel_id"], "folio", f["id"], f["reservation_id"], amount, email, ctx.field("provider", required=False, kind=str))
    with get_db().tx() as c:
        hotel = get_hotel(c, f["hotel_id"])
        if ctx.field("send", required=False, default=True):
            from .messaging import notify_template
            notify_template(c, hotel, "payment_link", {"email": email}, {"amount": f"{hotel['currency']} {amount / 100:,.2f}", "link": out["authorization_url"],
                                                                       "folio": f["number"]}, "folio", f["id"])
        audit(c, ctx, "payment_link.created", "gateway_transaction", out["id"], out["reference"], new={"amount": amount, "email": email}, hotel_id=f["hotel_id"])
    return {**out, "_created": True}


@route("GET", "/api/public/payments/{reference}", public=True, rate_limit=30, tag="booking-engine",
       summary="Return page: verify an online payment with the provider and show its outcome")
def public_verify(ctx: Ctx):
    out = apply_verification(ctx.path["reference"], "return page")
    with get_db().tx() as c:
        if out.get("reservation_id"):
            r = c.one("SELECT r.reference, r.status, h.code AS hotel_code, h.name AS hotel_name FROM reservations r JOIN hotels h ON h.id = r.hotel_id "
                      "WHERE r.id = ?", [out["reservation_id"]])
            out["booking"] = r
        tx = c.one("SELECT amount, currency FROM gateway_transactions WHERE reference = ?", [ctx.path["reference"]])
        out.update(tx or {})
    out.pop("payment_id", None)
    out.pop("reservation_id", None)
    return out


def _webhook(ctx: Ctx, provider: str):
    if not gateways.valid_webhook(provider, ctx.raw, ctx.request.headers):
        gateways.log_integration(None, provider, "inbound", f"webhook/{provider}", 401, False, "", "invalid signature")
        raise ApiError(401, "invalid_signature", "Invalid webhook signature")
    ref = gateways.webhook_reference(provider, ctx.body if isinstance(ctx.body, dict) else {})
    gateways.log_integration(None, provider, "inbound", f"webhook/{provider}", 200, True, f"event {(ctx.body or {}).get('event', '')} ref {ref}")
    if not ref:
        return {"ok": True, "ignored": "no reference"}
    with get_db().tx() as c:
        known = c.one("SELECT id FROM gateway_transactions WHERE reference = ? AND provider = ?", [ref, provider])
    if not known:
        return {"ok": True, "ignored": "unknown reference"}
    return {"ok": True, **{k: v for k, v in apply_verification(ref, f"{provider} webhook").items() if k in ("status", "reference")}}


@route("POST", "/api/public/webhooks/paystack", public=True, tag="booking-engine", summary="Paystack webhook (HMAC-SHA512 signed)")
def paystack_webhook(ctx: Ctx):
    return _webhook(ctx, "paystack")


@route("POST", "/api/public/webhooks/flutterwave", public=True, tag="booking-engine", summary="Flutterwave webhook (verif-hash header)")
def flutterwave_webhook(ctx: Ctx):
    return _webhook(ctx, "flutterwave")


@route("GET", "/api/hotels/{hotel_id:int}/gateway-transactions", perm="accounting.view", tag="payments",
       summary="Online payment transactions and integration log")
def gateway_transactions(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": c.all("SELECT g.*, f.number AS folio_number, r.reference AS reservation_reference FROM gateway_transactions g "
                               "LEFT JOIN folios f ON f.id = g.folio_id LEFT JOIN reservations r ON r.id = g.reservation_id WHERE g.hotel_id = ? "
                               "ORDER BY g.id DESC LIMIT 200", [hid]),
                "log": c.all("SELECT * FROM integration_logs WHERE hotel_id = ? OR hotel_id IS NULL ORDER BY id DESC LIMIT 200", [hid]),
                "providers": gateways.configured_providers()}


@route("POST", "/api/gateway-transactions/{tx_id:int}/verify", perm="payments.receive", tag="payments",
       summary="Re-check a pending online payment with the provider")
def staff_verify(ctx: Ctx):
    with get_db().tx() as c:
        tx = c.one("SELECT * FROM gateway_transactions WHERE id = ?", [ctx.path["tx_id"]])
        if not tx:
            raise not_found("Transaction")
        ctx.check_hotel(tx["hotel_id"])
    return apply_verification(tx["reference"], "staff re-check")


# ------------------------------------------------------------------ promotional codes
def promo_discount(c, hotel_id: int, code: str | None, room_type_id: int, arrival: dt.date, departure: dt.date, room_total: int) -> tuple[int, dict | None]:
    if not code:
        return 0, None
    p = c.one("SELECT * FROM promo_codes WHERE hotel_id = ? AND upper(code) = ? AND active = 1", [hotel_id, code.strip().upper()])
    nights = (departure - arrival).days
    if not p or not (p["valid_from"] <= arrival.isoformat() <= p["valid_to"]):
        raise bad_request("This promo code is not valid for your dates", {"field": "promo_code"})
    if p["room_type_id"] and p["room_type_id"] != room_type_id:
        raise bad_request("This promo code does not apply to the selected room", {"field": "promo_code"})
    if nights < p["min_nights"]:
        raise bad_request(f"This promo code needs a stay of at least {p['min_nights']} nights", {"field": "promo_code"})
    if p["max_uses"] is not None and p["uses"] >= p["max_uses"]:
        raise bad_request("This promo code has been fully used", {"field": "promo_code"})
    disc = room_total * p["value"] // 100 if p["discount_type"] == "percent" else p["value"]
    return min(disc, room_total), p


@route("GET", "/api/hotels/{hotel_id:int}/promo-codes", perm="promotions.manage", tag="sales", summary="Promotional codes")
def list_promos(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": c.all("SELECT p.*, rt.name AS room_type_name FROM promo_codes p LEFT JOIN room_types rt ON rt.id = p.room_type_id "
                               "WHERE p.hotel_id = ? ORDER BY p.active DESC, p.valid_to DESC", [hid])}


def _promo_payload(ctx: Ctx, partial: bool) -> dict:
    b = ctx.body or {}
    data: dict = {}
    if "discount_type" in b or not partial:
        data["discount_type"] = ctx.field("discount_type", kind=str)
        if data["discount_type"] not in ("percent", "amount"):
            raise bad_request("discount_type must be percent or amount")
    if "value" in b or not partial:
        data["value"] = int(ctx.field("value"))
    if data.get("discount_type") == "percent" and not 1 <= data.get("value", 1) <= 100:
        raise bad_request("A percentage discount must be between 1 and 100")
    for k in ("valid_from", "valid_to"):
        if k in b or not partial:
            data[k] = parse_date(ctx.field(k), k).isoformat()
    if data.get("valid_from") and data.get("valid_to") and data["valid_to"] < data["valid_from"]:
        raise bad_request("The end date must be after the start date")
    for k in ("min_nights", "max_uses", "room_type_id"):
        if k in b:
            data[k] = int(b[k]) if b[k] not in (None, "") else (1 if k == "min_nights" else None)
    if "description" in b:
        data["description"] = ctx.field("description", required=False, kind=str)
    if "active" in b:
        data["active"] = 1 if b["active"] else 0
    return data


@route("POST", "/api/hotels/{hotel_id:int}/promo-codes", perm="promotions.manage", tag="sales", summary="Create a promotional code")
def create_promo(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    data = _promo_payload(ctx, partial=False)
    code = ctx.field("code", kind=str).upper().replace(" ", "")
    with get_db().tx() as c:
        if data.get("room_type_id") and not c.one("SELECT id FROM room_types WHERE id = ? AND hotel_id = ?", [data["room_type_id"], hid]):
            raise bad_request("Room category not found")
        pid = c.insert("promo_codes", {"hotel_id": hid, "code": code, "created_by": ctx.user_id, "created_at": now_iso(), **data})
        audit(c, ctx, "promo.created", "promo_code", pid, code, new=data, hotel_id=hid)
    return {"id": pid, "_created": True}


@route("PATCH", "/api/promo-codes/{promo_id:int}", perm="promotions.manage", tag="sales", summary="Edit or deactivate a promotional code")
def update_promo(ctx: Ctx):
    with get_db().tx() as c:
        p = c.one("SELECT * FROM promo_codes WHERE id = ?", [ctx.path["promo_id"]])
        if not p:
            raise not_found("Promo code")
        ctx.check_hotel(p["hotel_id"])
        data = _promo_payload(ctx, partial=True)
        c.update("promo_codes", p["id"], data)
        audit(c, ctx, "promo.updated", "promo_code", p["id"], p["code"], old={k: p[k] for k in data}, new=data, hotel_id=p["hotel_id"])
    return {"ok": True}
