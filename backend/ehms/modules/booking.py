"""Public online booking engine (no staff login). (FR-BKG-001..005)

Bookings made here are created against the same central inventory as front-desk bookings, inside
the same transaction-safe availability check, so double bookings are prevented. Without a configured
payment gateway the guest books with 'pay at hotel' and the reservation is held as TENTATIVE until
staff confirm it. The system never reports an online payment as successful unless a gateway confirms it.
"""
from __future__ import annotations

import datetime as dt
import os

from ..db import get_db, now_iso
from ..http import ApiError, Ctx, audit, bad_request, conflict, not_found, route
from ..services import business_date, get_hotel, next_number, parse_date, queue_notification
from .reservations import quote
from .rooms import type_availability


def _hotel_by_code(c, code: str) -> dict:
    h = c.one("SELECT * FROM hotels WHERE upper(code) = ? AND active = 1", [code.upper()])
    if not h:
        raise not_found("Hotel")
    return h


def gateway_configured() -> bool:
    from ..gateways import configured_providers
    return bool(configured_providers())


@route("GET", "/api/public/hotels/{code}", public=True, tag="booking-engine", summary="Public hotel profile and room categories")
def public_hotel(ctx: Ctx):
    with get_db().tx() as c:
        h = _hotel_by_code(c, ctx.path["code"])
        types = c.all("SELECT id, code, name, description, max_occupancy, beds, bed_config, size_sqm, amenities, base_rate, weekend_rate, image_url "
                      "FROM room_types WHERE hotel_id = ? AND active = 1 ORDER BY base_rate", [h["id"]])
        taxes = c.all("SELECT name, rate_bp, is_inclusive FROM tax_rules WHERE hotel_id = ? AND active = 1", [h["id"]])
    return {"code": h["code"], "name": h["name"], "address": h["address"], "city": h["city"], "phone": h["phone"], "email": h["email"],
            "star_rating": h["star_rating"], "currency": h["currency"], "check_in_time": h["check_in_time"], "check_out_time": h["check_out_time"],
            "cancellation_policy": h["cancellation_policy"], "terms": h["terms"], "amenities": h["amenities"], "room_types": types,
            "taxes": taxes, "service_charge_bp": h["service_charge_bp"], "online_payment_available": gateway_configured()}


@route("GET", "/api/public/hotels/{code}/availability", public=True, tag="booking-engine", rate_limit=60,
       summary="Available room categories and total prices for dates")
def public_availability(ctx: Ctx):
    a = parse_date(ctx.q("arrival"), "arrival")
    d = parse_date(ctx.q("departure"), "departure")
    adults, children = int(ctx.q("adults", 1)), int(ctx.q("children", 0))
    if d <= a:
        raise bad_request("Departure must be after arrival")
    if (d - a).days > 30:
        raise bad_request("Online bookings are limited to 30 nights; please contact the hotel for longer stays")
    with get_db().tx() as c:
        h = _hotel_by_code(c, ctx.path["code"])
        if a < business_date(h):
            raise bad_request("Arrival date is in the past")
        out = []
        for t in type_availability(c, h["id"], a, d):
            if t["available"] < 1 or adults + children > t["max_occupancy"]:
                continue
            q = quote(c, h, t, a, d, adults, children, "individual", None, 0)
            promo_error = None
            if ctx.q("promo_code"):
                from .online import promo_discount
                try:
                    disc, _ = promo_discount(c, h["id"], ctx.q("promo_code"), t["id"], a, d, q["room_total"])
                    q = quote(c, h, t, a, d, adults, children, "individual", None, disc)
                except ApiError as e:
                    promo_error = e.message
            out.append({"promo_error": promo_error, "room_type_id": t["id"], "code": t["code"], "name": t["name"], "description": t["description"],
                        "amenities": t["amenities"], "max_occupancy": t["max_occupancy"], "image_url": t["image_url"],
                        "rooms_left": t["available"] if t["available"] <= 3 else None, "price": q})
    return {"arrival": a.isoformat(), "departure": d.isoformat(), "nights": (d - a).days, "options": out}


@route("POST", "/api/public/hotels/{code}/bookings", public=True, tag="booking-engine", rate_limit=10,
       summary="Submit an online booking (pay at hotel unless a payment gateway is configured)")
def public_book(ctx: Ctx):
    b = ctx.body or {}
    for f in ("arrival", "departure", "room_type_id", "first_name", "last_name", "email", "phone"):
        if not str(b.get(f) or "").strip():
            raise bad_request(f"'{f}' is required", {"field": f})
    if not b.get("accept_terms"):
        raise bad_request("Please accept the booking terms and privacy notice", {"field": "accept_terms"})
    if "@" not in str(b["email"]):
        raise bad_request("Enter a valid email address", {"field": "email"})
    pay_online = b.get("payment_option", "pay_at_hotel") != "pay_at_hotel"   # 'pay_online' (or legacy 'card')
    if pay_online:
        if not gateway_configured():
            raise ApiError(501, "gateway_not_configured", "Online payment is not available yet. Choose 'Pay at hotel'.")
    a, d = parse_date(b["arrival"], "arrival"), parse_date(b["departure"], "departure")
    adults, children = int(b.get("adults") or 1), int(b.get("children") or 0)
    with get_db().tx() as c:
        h = _hotel_by_code(c, ctx.path["code"])
        if d <= a or a < business_date(h) or (d - a).days > 30:
            raise bad_request("Please choose valid dates")
        c.lock("room_types", int(b["room_type_id"]))  # serialise concurrent bookings of the same category
        t = next((x for x in type_availability(c, h["id"], a, d) if x["id"] == int(b["room_type_id"])), None)
        if not t:
            raise bad_request("Room category not found")
        if t["available"] < 1:
            raise conflict("Sorry, this room category has just sold out for your dates. Please choose another.")
        if adults + children > t["max_occupancy"]:
            raise bad_request(f"{t['name']} allows a maximum of {t['max_occupancy']} guests")
        q = quote(c, h, t, a, d, adults, children, "individual", None, 0)
        promo = None
        if b.get("promo_code"):
            from .online import promo_discount
            disc, promo = promo_discount(c, h["id"], str(b["promo_code"]), t["id"], a, d, q["room_total"])
            q = quote(c, h, t, a, d, adults, children, "individual", None, disc)
            c.execute("UPDATE promo_codes SET uses = uses + 1 WHERE id = ?", [promo["id"]])
        email = str(b["email"]).strip().lower()
        g = c.one("SELECT id FROM guests WHERE organisation_id = ? AND lower(email) = ? ORDER BY id LIMIT 1", [h["organisation_id"], email])
        if g:
            gid = g["id"]
        else:
            gid = c.insert("guests", {"organisation_id": h["organisation_id"], "first_name": str(b["first_name"]).strip()[:100],
                                      "last_name": str(b["last_name"]).strip()[:100], "email": email, "phone": str(b["phone"]).strip()[:50],
                                      "nationality": b.get("nationality"), "marketing_consent": 1 if b.get("marketing_consent") else 0,
                                      "created_at": now_iso()})
        ref = next_number(c, h["id"], "reservation", "RES")
        rid = c.insert("reservations", {"hotel_id": h["id"], "reference": ref, "guest_id": gid, "status": "tentative", "booking_type": "individual",
                                        "source": "booking_engine", "arrival": a.isoformat(), "departure": d.isoformat(), "adults": adults,
                                        "children": children, "room_type_id": t["id"], "nightly_rate": t["base_rate"], "rate_overridden": 0,
                                        "discount_amount": q["discount"], "promo_code": promo["code"] if promo else None, "deposit_required": 0, "locked_rates": q["locked_rates"],
                                        "cancellation_policy_id": c.scalar("SELECT id FROM cancellation_policies WHERE hotel_id = ? AND is_default = 1 AND active = 1", [h["id"]]),
                                        "special_requests": (b.get("special_requests") or "")[:1000],
                                        "notes": "Online booking — awaiting online payment" if pay_online else "Online booking — pay at hotel", "created_at": now_iso(), "updated_at": now_iso()})
        audit(c, None, "booking_engine.booking", "reservation", rid, ref, new={"total": q["total"], "ip": ctx.ip}, hotel_id=h["id"])
        queue_notification(c, h["id"], "email", email, f"Booking received {ref} — {h['name']}",
                           f"Dear {b['first_name']},\n\nThank you for booking with {h['name']}. Your booking reference is {ref}.\n"
                           f"Arrival {a.isoformat()}, departure {d.isoformat()}, {t['name']}.\nEstimated total: {h['currency']} {q['total'] / 100:,.2f} "
                           f"(payable at the hotel).\nWe will confirm your reservation shortly.\n\n{h['name']}", "reservation", rid)
        if pay_online:
            from .frontoffice import ensure_folio
            folio = ensure_folio(c, c.one("SELECT * FROM reservations WHERE id = ?", [rid]))
    if pay_online:
        from .online import start_payment
        try:
            pay = start_payment(None, h["id"], "booking", folio["id"], rid, q["total"], email)
        except ApiError as e:
            return {"reference": ref, "status": "tentative", "total": q["total"], "currency": h["currency"], "payment": "pay_at_hotel",
                    "message": f"Your booking is held, but online payment could not be started ({e.message}). You can pay at the hotel.", "_created": True}
        return {"reference": ref, "status": "tentative", "total": q["total"], "currency": h["currency"], "payment": "pay_online",
                "authorization_url": pay["authorization_url"], "payment_reference": pay["reference"],
                "message": "Complete your payment to confirm the booking.", "_created": True}
    return {"reference": ref, "status": "tentative", "total": q["total"], "currency": h["currency"], "payment": "pay_at_hotel",
            "discount": q["discount"], "message": "Your booking request has been received. The hotel will confirm it shortly.", "_created": True}


@route("GET", "/api/public/bookings/{reference}", public=True, tag="booking-engine", rate_limit=20,
       summary="Look up a booking by reference and email")
def public_lookup(ctx: Ctx):
    email = (ctx.q("email") or "").strip().lower()
    with get_db().tx() as c:
        r = c.one("SELECT r.reference, r.status, r.arrival, r.departure, r.adults, r.children, rt.name AS room_type, h.name AS hotel, h.code AS hotel_code "
                  "FROM reservations r JOIN guests g ON g.id = r.guest_id JOIN room_types rt ON rt.id = r.room_type_id JOIN hotels h ON h.id = r.hotel_id "
                  "WHERE r.reference = ? AND lower(g.email) = ?", [ctx.path["reference"], email])
    if not r:
        raise not_found("Booking")
    return r


@route("POST", "/api/public/bookings/{reference}/cancel", public=True, tag="booking-engine", rate_limit=10,
       summary="Guest cancellation of a future booking (subject to hotel policy)")
def public_cancel(ctx: Ctx):
    email = str(ctx.field("email")).strip().lower()
    with get_db().tx() as c:
        r = c.one("SELECT r.*, h.business_date, h.timezone FROM reservations r JOIN guests g ON g.id = r.guest_id JOIN hotels h ON h.id = r.hotel_id "
                  "WHERE r.reference = ? AND lower(g.email) = ?", [ctx.path["reference"], email])
        if not r:
            raise not_found("Booking")
        if r["status"] not in ("tentative", "confirmed"):
            raise conflict("This booking can no longer be cancelled online")
        if dt.date.fromisoformat(r["arrival"]) <= business_date({"business_date": r["business_date"], "timezone": r["timezone"]}):
            raise conflict("Bookings cannot be cancelled online on or after the arrival date; please contact the hotel")
        from .billing import fee_for
        fee = fee_for(c, get_hotel(c, r["hotel_id"]), r, "cancel")
        if fee["fee"] > 0:
            raise conflict(f"The free-cancellation period has ended ({fee['explanation']}) Please contact the hotel to cancel.")
        if c.one("SELECT id FROM payments WHERE folio_id IN (SELECT id FROM folios WHERE reservation_id = ?)", [r["id"]]):
            raise conflict("This booking has a payment attached; please contact the hotel to cancel and arrange any refund")
        c.update("reservations", r["id"], {"status": "cancelled", "cancelled_at": now_iso(), "cancel_reason": "Cancelled by guest online", "updated_at": now_iso()})
        audit(c, None, "booking_engine.cancelled", "reservation", r["id"], r["reference"], hotel_id=r["hotel_id"])
    return {"reference": ctx.path["reference"], "status": "cancelled"}
