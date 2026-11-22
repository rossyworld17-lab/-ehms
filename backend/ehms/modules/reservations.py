"""Reservations: quote, create, modify, assign rooms, confirm, cancel, no-show. (FR-RES-001..007, FR-PMS-004)"""
from __future__ import annotations

import datetime as dt
import json

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import business_date, get_hotel, nights_between, parse_date, price_breakdown, queue_notification, to_minor, next_number
from .guests import create_guest_row, find_duplicates
from .rooms import ACTIVE_RES, overlapping_room_reservations, type_availability

EDITABLE_STATUSES = ("enquiry", "tentative", "confirmed", "waitlisted")
BOOKING_TYPES = ("individual", "group", "corporate", "walk_in", "travel_agent", "vip", "event")
SOURCES = ("front_desk", "phone", "email", "walk_in", "website", "booking_engine", "travel_agent", "corporate", "ota", "other")


# ------------------------------------------------------------------ pricing
def night_rate(rt: dict, booking_type: str, night: dt.date, override: int | None) -> int:
    if override is not None:
        return override
    if booking_type == "corporate" and rt.get("corporate_rate"):
        return rt["corporate_rate"]
    if night.weekday() in (4, 5) and rt.get("weekend_rate"):  # Friday and Saturday nights
        return rt["weekend_rate"]
    return rt["base_rate"]


def quote(c, hotel: dict, rt: dict, arrival: dt.date, departure: dt.date, adults: int, children: int,
          booking_type: str, override: int | None, discount: int, account_id: int | None = None) -> dict:
    from ..pricing import quote_night
    extra = max(0, adults - 2)
    nights = []
    for n in nights_between(arrival, departure):
        base, why = quote_night(c, hotel["id"], rt, booking_type, n, override, account_id)
        nights.append({"date": n.isoformat(), "rate": base + extra * (rt.get("extra_person_charge") or 0), "room_rate": base, "applied": why})
    room_total = sum(n["rate"] for n in nights)
    if discount > room_total:
        raise bad_request("Discount cannot exceed the room total")
    taxable = room_total - discount
    bd = price_breakdown(c, hotel, "room", taxable, arrival)
    return {"nights": nights, "room_total": room_total, "discount": discount, "net": bd["net"], "service_charge": bd["service_charge"],
            "tax": bd["tax"], "total": bd["total"], "taxes": bd["taxes"], "currency": hotel["currency"],
            "locked_rates": json.dumps({n["date"]: n["room_rate"] for n in nights})}


def _load(c, ctx: Ctx, res_id) -> dict:
    r = c.one("SELECT * FROM reservations WHERE id = ?", [int(res_id)])
    if not r:
        raise not_found("Reservation")
    ctx.check_hotel(r["hotel_id"])
    return r


def reservation_detail(c, r: dict) -> dict:
    out = dict(r)
    out["guest"] = c.one("SELECT id, first_name, last_name, email, phone, vip, company, nationality FROM guests WHERE id = ?", [r["guest_id"]])
    out["room_type"] = c.one("SELECT id, code, name, max_occupancy FROM room_types WHERE id = ?", [r["room_type_id"]])
    out["room"] = c.one("SELECT id, number, floor, hk_status, occupancy FROM rooms WHERE id = ?", [r["room_id"]]) if r["room_id"] else None
    out["nights"] = (dt.date.fromisoformat(r["departure"]) - dt.date.fromisoformat(r["arrival"])).days
    f = c.one("SELECT * FROM folios WHERE reservation_id = ?", [r["id"]])
    if f:
        bal = c.one("SELECT COALESCE(SUM(CASE WHEN kind IN ('charge','refund') THEN total_amount ELSE 0 END),0) AS charges, "
                    "COALESCE(SUM(CASE WHEN kind = 'payment' THEN total_amount ELSE 0 END),0) AS payments, "
                    "COALESCE(SUM(CASE WHEN kind = 'adjustment' THEN total_amount ELSE 0 END),0) AS adjustments FROM folio_lines WHERE folio_id = ?", [f["id"]])
        out["folio"] = {"id": f["id"], "number": f["number"], "status": f["status"], **bal,
                        "balance": bal["charges"] + bal["adjustments"] - bal["payments"]}
    else:
        out["folio"] = None
    out["rate_overridden"] = bool(r["rate_overridden"])
    return out


def _validate_common(c, ctx: Ctx, hotel: dict, data: dict, exclude_id: int | None = None) -> tuple[dict, dt.date, dt.date]:
    arrival = parse_date(data["arrival"], "arrival")
    departure = parse_date(data["departure"], "departure")
    if departure <= arrival:
        raise bad_request("Departure must be after arrival", {"field": "departure"})
    if (departure - arrival).days > 90:
        raise bad_request("Stays longer than 90 nights must be split into separate reservations")
    if exclude_id is None and arrival < business_date(hotel):
        raise bad_request("Arrival date cannot be before the hotel's current business date", {"field": "arrival"})
    rt = c.one("SELECT * FROM room_types WHERE id = ? AND hotel_id = ? AND active = 1", [int(data["room_type_id"]), hotel["id"]])
    if not rt:
        raise bad_request("Room category not found for this hotel", {"field": "room_type_id"})
    adults, children = int(data.get("adults") or 1), int(data.get("children") or 0)
    if adults < 1 or children < 0:
        raise bad_request("At least one adult is required")
    if adults + children > rt["max_occupancy"]:
        raise bad_request(f"{rt['name']} allows a maximum of {rt['max_occupancy']} guests", {"field": "adults"})
    return rt, arrival, departure


def _check_inventory(c, ctx: Ctx, hotel_id: int, rt: dict, arrival: dt.date, departure: dt.date, status: str,
                     room_id: int | None, exclude_id: int | None, overbook_reason: str | None) -> list[str]:
    """Raises if the booking would overbook, unless an authorised override is supplied. Returns warnings."""
    warnings = []
    if status not in ACTIVE_RES:
        return warnings
    c.lock("room_types", rt["id"])  # serialise concurrent bookings of the same category (PostgreSQL row lock)
    avail = next((t for t in type_availability(c, hotel_id, arrival, departure, exclude_id) if t["id"] == rt["id"]), None)
    if not avail or avail["available"] < 1:
        if not overbook_reason:
            raise conflict(f"No {rt['name']} rooms are available for every night of this stay", {"code": "no_availability"})
        if not ctx.can("reservations.overbook"):
            raise forbidden("Overbooking requires the reservations.overbook permission")
        warnings.append("overbooked_category")
    if room_id:
        room = c.lock("rooms", room_id)
        if not room or room["hotel_id"] != hotel_id or not room["active"]:
            raise bad_request("Room not found in this hotel", {"field": "room_id"})
        if room["room_type_id"] != rt["id"]:
            raise bad_request(f"Room {room['number']} is not a {rt['name']}", {"field": "room_id"})
        if room["service_status"] not in ("in_service", "vip_hold"):
            raise conflict(f"Room {room['number']} is {room['service_status'].replace('_', ' ')}")
        clashes = overlapping_room_reservations(c, room_id, arrival.isoformat(), departure.isoformat(), exclude_id)
        if clashes:
            if not overbook_reason:
                raise conflict(f"Room {room['number']} is already allocated for these dates",
                               {"code": "room_clash", "reservations": [x["reference"] for x in clashes]})
            if not ctx.can("reservations.overbook"):
                raise forbidden("Overlapping room allocation requires the reservations.overbook permission")
            warnings.append("overlapping_room_allocation")
    return warnings


# ------------------------------------------------------------------ endpoints
@route("POST", "/api/hotels/{hotel_id:int}/quote", perm="reservations.view", tag="reservations", summary="Price a stay (per night, taxes, total)")
def quote_endpoint(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        rt, a, d = _validate_common(c, ctx, hotel, ctx.body or {}, exclude_id=-1)
        override = to_minor(ctx.body["nightly_rate"], "nightly_rate") if (ctx.body or {}).get("nightly_rate") not in (None, "") else None
        acct = (ctx.body or {}).get("corporate_account_id")
        if acct and not c.one("SELECT id FROM corporate_accounts WHERE id = ? AND organisation_id = ? AND status = 'active'", [int(acct), ctx.org_id]):
            raise bad_request("Corporate / agent account not found or not active")
        return quote(c, hotel, rt, a, d, int(ctx.body.get("adults") or 1), int(ctx.body.get("children") or 0),
                     ctx.body.get("booking_type") or "individual", override, to_minor(ctx.body.get("discount_amount") or 0, "discount_amount"), int(acct) if acct else None)


@route("GET", "/api/hotels/{hotel_id:int}/reservations", perm="reservations.view", tag="reservations",
       summary="Search reservations (by status, dates, guest, reference, room)")
def list_reservations(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT r.*, g.first_name, g.last_name, g.phone, g.email, g.vip, rt.code AS room_type_code, rt.name AS room_type_name, "
           "rm.number AS room_number FROM reservations r JOIN guests g ON g.id = r.guest_id JOIN room_types rt ON rt.id = r.room_type_id "
           "LEFT JOIN rooms rm ON rm.id = r.room_id WHERE r.hotel_id = ?")
    params: list = [hid]
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid)).isoformat()
        view = ctx.q("view")
        if view == "arrivals":
            sql += " AND r.arrival = ? AND r.status IN ('confirmed','tentative')"
            params.append(ctx.q("date", today))
        elif view == "departures":
            sql += " AND r.departure <= ? AND r.status = 'checked_in'"
            params.append(ctx.q("date", today))
        elif view == "in_house":
            sql += " AND r.status = 'checked_in'"
        if ctx.q("status"):
            statuses = ctx.q("status").split(",")
            sql += f" AND r.status IN ({','.join('?' for _ in statuses)})"
            params += statuses
        if ctx.q("from"):
            sql += " AND r.departure > ?"
            params.append(ctx.q("from"))
        if ctx.q("to"):
            sql += " AND r.arrival <= ?"
            params.append(ctx.q("to"))
        if ctx.q("search"):
            s = f"%{ctx.q('search').lower()}%"
            sql += (" AND (lower(r.reference) LIKE ? OR lower(g.first_name || ' ' || g.last_name) LIKE ? OR g.phone LIKE ? "
                    "OR lower(g.email) LIKE ? OR rm.number = ? OR lower(r.company_name) LIKE ?)")
            params += [s, s, s, s, ctx.q("search"), s]
        rows = c.all(sql + " ORDER BY r.arrival, r.id LIMIT 500", params)
    return {"items": rows, "business_date": today}


@route("POST", "/api/hotels/{hotel_id:int}/reservations", perm="reservations.create", tag="reservations",
       summary="Create a reservation (individual, group, corporate, walk-in …)")
def create_reservation(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    body = ctx.body or {}
    status = body.get("status") or "confirmed"
    if status not in ("enquiry", "tentative", "confirmed", "waitlisted"):
        raise bad_request("New reservations must be enquiry, tentative, confirmed or waitlisted")
    booking_type = body.get("booking_type") or "individual"
    if booking_type not in BOOKING_TYPES:
        raise bad_request("Invalid booking_type")
    source = body.get("source") or "front_desk"
    if source not in SOURCES:
        raise bad_request("Invalid booking source")
    for f in ("arrival", "departure", "room_type_id"):
        if body.get(f) in (None, ""):
            raise bad_request(f"'{f}' is required", {"field": f})
    override = to_minor(body["nightly_rate"], "nightly_rate") if body.get("nightly_rate") not in (None, "") else None
    discount = to_minor(body.get("discount_amount") or 0, "discount_amount")
    if (override is not None or discount) and not ctx.can("reservations.override_rate"):
        raise forbidden("Changing the rate or applying a discount requires the reservations.override_rate permission")
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        rt, arrival, departure = _validate_common(c, ctx, hotel, body)
        # guest
        if body.get("guest_id"):
            g = c.one("SELECT id FROM guests WHERE id = ? AND organisation_id = ?", [int(body["guest_id"]), ctx.org_id])
            if not g:
                raise bad_request("Guest not found", {"field": "guest_id"})
            guest_id = g["id"]
        elif isinstance(body.get("guest"), dict):
            ctx.require("guests.manage")
            gd = body["guest"]
            dups = find_duplicates(c, ctx.org_id, str(gd.get("first_name", "")), str(gd.get("last_name", "")), gd.get("email"), gd.get("phone"))
            if dups and not gd.get("force"):
                raise conflict("Possible duplicate guest profile(s) found — select one or confirm a new profile", {"duplicates": dups})
            guest_id = create_guest_row(c, ctx, gd)
        else:
            raise bad_request("Provide guest_id or guest details", {"field": "guest"})
        room_id = int(body["room_id"]) if body.get("room_id") else None
        warnings = _check_inventory(c, ctx, hid, rt, arrival, departure, status, room_id, None, body.get("overbook_reason"))
        account = None
        if body.get("corporate_account_id"):
            account = c.one("SELECT * FROM corporate_accounts WHERE id = ? AND organisation_id = ? AND status = 'active'", [int(body["corporate_account_id"]), ctx.org_id])
            if not account:
                raise bad_request("Corporate / agent account not found or not active", {"field": "corporate_account_id"})
        q = quote(c, hotel, rt, arrival, departure, int(body.get("adults") or 1), int(body.get("children") or 0), booking_type, override, discount,
                  account["id"] if account else None)
        ref = next_number(c, hid, "reservation", "RES")
        rid = c.insert("reservations", {
            "hotel_id": hid, "reference": ref, "guest_id": guest_id, "status": status, "booking_type": booking_type, "source": source,
            "arrival": arrival.isoformat(), "departure": departure.isoformat(), "adults": int(body.get("adults") or 1),
            "children": int(body.get("children") or 0), "room_type_id": rt["id"], "room_id": room_id,
            "nightly_rate": override if override is not None else rt["base_rate"], "rate_overridden": 1 if override is not None else 0,
            "discount_amount": discount, "deposit_required": to_minor(body.get("deposit_required") or 0, "deposit_required"),
            "company_name": body.get("company_name") or (account["name"] if account else None), "group_name": body.get("group_name"),
            "special_requests": body.get("special_requests"), "corporate_account_id": account["id"] if account else None, "locked_rates": q["locked_rates"],
            "notes": body.get("notes"), "created_by": ctx.user_id, "created_at": now_iso(), "updated_at": now_iso()})
        audit(c, ctx, "reservation.created", "reservation", rid, ref, new={"status": status, "arrival": arrival.isoformat(),
              "departure": departure.isoformat(), "room_type": rt["code"], "room_id": room_id, "total": q["total"],
              "override_rate": override, "discount": discount, "warnings": warnings, "overbook_reason": body.get("overbook_reason")}, hotel_id=hid)
        if status == "confirmed":
            _send_confirmation(c, hotel, rid)
        out = reservation_detail(c, c.one("SELECT * FROM reservations WHERE id = ?", [rid]))
    out.update({"quote": q, "warnings": warnings, "_created": True})
    return out


def _send_confirmation(c, hotel: dict, res_id: int) -> None:
    r = c.one("SELECT r.*, g.first_name, g.email, rt.name AS room_type_name FROM reservations r JOIN guests g ON g.id = r.guest_id "
              "JOIN room_types rt ON rt.id = r.room_type_id WHERE r.id = ?", [res_id])
    body = (f"Dear {r['first_name']},\n\nYour reservation at {hotel['name']} is confirmed.\n\nReference: {r['reference']}\n"
            f"Arrival: {r['arrival']} (check-in from {hotel['check_in_time']})\nDeparture: {r['departure']} (check-out by {hotel['check_out_time']})\n"
            f"Room: {r['room_type_name']}\nGuests: {r['adults']} adult(s), {r['children']} child(ren)\n\n"
            f"{hotel.get('cancellation_policy') or ''}\n\nWe look forward to welcoming you.\n{hotel['name']}\n{hotel.get('phone') or ''}")
    queue_notification(c, hotel["id"], "email", r["email"], f"Booking confirmation {r['reference']} — {hotel['name']}", body, "reservation", res_id)


@route("GET", "/api/reservations/{res_id:int}", perm="reservations.view", tag="reservations", summary="Reservation detail with folio balance and history")
def get_reservation(ctx: Ctx):
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        out = reservation_detail(c, r)
        out["history"] = c.all("SELECT a.action, a.created_at, a.new_value, u.full_name AS user_name FROM audit_logs a LEFT JOIN users u "
                               "ON u.id = a.user_id WHERE a.entity = 'reservation' AND a.entity_id = ? ORDER BY a.id", [str(r["id"])])
        out["notifications"] = c.all("SELECT channel, recipient, subject, status, error, created_at FROM notifications "
                                     "WHERE related_entity = 'reservation' AND related_id = ? ORDER BY id DESC", [str(r["id"])])
    return out


@route("PATCH", "/api/reservations/{res_id:int}", perm="reservations.modify", tag="reservations",
       summary="Modify dates, room category, occupants, rate or notes")
def modify_reservation(ctx: Ctx):
    body = ctx.body or {}
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        hotel = get_hotel(c, r["hotel_id"])
        if r["status"] == "checked_in":
            allowed = {"departure", "special_requests", "notes", "adults", "children"}
            if set(body) - allowed - {"overbook_reason"}:
                raise conflict("For in-house guests only departure, occupants and notes can be changed here; use room move for room changes")
        elif r["status"] not in EDITABLE_STATUSES:
            raise conflict(f"A {r['status'].replace('_', ' ')} reservation cannot be modified")
        merged = {**r, **{k: v for k, v in body.items() if k in ("arrival", "departure", "room_type_id", "adults", "children")}}
        if r["status"] == "checked_in":
            merged["arrival"] = r["arrival"]
            if parse_date(merged["departure"], "departure") < business_date(hotel):
                raise bad_request("Departure cannot be before today's business date")
        rt, arrival, departure = _validate_common(c, ctx, hotel, merged, exclude_id=r["id"])
        room_id = r["room_id"]
        if "room_id" in body:
            room_id = int(body["room_id"]) if body["room_id"] else None
        if rt["id"] != r["room_type_id"] and "room_id" not in body:
            room_id = None  # category changed: room must be re-assigned
        override = r["nightly_rate"] if r["rate_overridden"] else None
        discount = r["discount_amount"]
        if "nightly_rate" in body or "discount_amount" in body:
            ctx.require("reservations.override_rate")
            if "nightly_rate" in body:
                override = to_minor(body["nightly_rate"], "nightly_rate") if body["nightly_rate"] not in (None, "") else None
            if "discount_amount" in body:
                discount = to_minor(body["discount_amount"] or 0, "discount_amount")
        warnings = _check_inventory(c, ctx, r["hotel_id"], rt, arrival, departure, r["status"], room_id, r["id"], body.get("overbook_reason"))
        changes = {"arrival": arrival.isoformat(), "departure": departure.isoformat(), "room_type_id": rt["id"], "room_id": room_id,
                   "adults": int(merged.get("adults") or 1), "children": int(merged.get("children") or 0),
                   "nightly_rate": override if override is not None else rt["base_rate"], "rate_overridden": 1 if override is not None else 0,
                   "discount_amount": discount, "updated_at": now_iso()}
        for f in ("special_requests", "notes", "company_name", "group_name", "source"):
            if f in body:
                changes[f] = body[f]
        if "deposit_required" in body:
            changes["deposit_required"] = to_minor(body["deposit_required"] or 0, "deposit_required")
        q = quote(c, hotel, rt, arrival, departure, changes["adults"], changes["children"], r["booking_type"], override, discount, r.get("corporate_account_id"))
        fresh = json.loads(q["locked_rates"])
        if rt["id"] == r["room_type_id"] and override is None and r.get("locked_rates"):
            prior = json.loads(r["locked_rates"])      # keep the rates the guest was quoted for nights already booked
            fresh = {d: prior.get(d, v) for d, v in fresh.items()}
        changes["locked_rates"] = json.dumps(fresh)
        old = {k: r[k] for k in changes if k not in ("updated_at", "locked_rates") and r.get(k) != changes[k]}
        c.update("reservations", r["id"], changes)
        audit(c, ctx, "reservation.modified", "reservation", r["id"], r["reference"], old=old,
              new={k: changes[k] for k in old} | {"warnings": warnings}, hotel_id=r["hotel_id"])
        out = reservation_detail(c, c.one("SELECT * FROM reservations WHERE id = ?", [r["id"]]))
    out.update({"quote": q, "warnings": warnings})
    return out


@route("POST", "/api/reservations/{res_id:int}/assign-room", perm="reservations.modify", tag="reservations",
       summary="Assign or change the room for a future reservation")
def assign_room(ctx: Ctx):
    room_id = ctx.field("room_id", kind=int)
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        if r["status"] not in ("tentative", "confirmed"):
            raise conflict("Rooms can be assigned to tentative or confirmed reservations; use room move for in-house guests")
        rt = c.one("SELECT * FROM room_types WHERE id = ?", [r["room_type_id"]])
        room = c.one("SELECT * FROM rooms WHERE id = ?", [room_id])
        if room and room["room_type_id"] != r["room_type_id"]:
            # assigning a different category is an upgrade/downgrade: change the category too
            ctx.require("reservations.override_rate")
            rt = c.one("SELECT * FROM room_types WHERE id = ?", [room["room_type_id"]])
        warnings = _check_inventory(c, ctx, r["hotel_id"], rt, dt.date.fromisoformat(r["arrival"]), dt.date.fromisoformat(r["departure"]),
                                    r["status"], room_id, r["id"], ctx.field("overbook_reason", required=False))
        c.update("reservations", r["id"], {"room_id": room_id, "room_type_id": rt["id"], "updated_at": now_iso()})
        audit(c, ctx, "reservation.room_assigned", "reservation", r["id"], r["reference"], old={"room_id": r["room_id"]},
              new={"room_id": room_id, "room_number": room["number"] if room else None, "warnings": warnings}, hotel_id=r["hotel_id"])
        return reservation_detail(c, c.one("SELECT * FROM reservations WHERE id = ?", [r["id"]])) | {"warnings": warnings}


@route("POST", "/api/reservations/{res_id:int}/confirm", perm="reservations.modify", tag="reservations", summary="Confirm a tentative/waitlisted reservation")
def confirm(ctx: Ctx):
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        if r["status"] not in ("tentative", "waitlisted", "enquiry"):
            raise conflict(f"A {r['status']} reservation cannot be confirmed")
        rt = c.one("SELECT * FROM room_types WHERE id = ?", [r["room_type_id"]])
        if r["status"] in ("waitlisted", "enquiry"):
            _check_inventory(c, ctx, r["hotel_id"], rt, dt.date.fromisoformat(r["arrival"]), dt.date.fromisoformat(r["departure"]),
                             "confirmed", r["room_id"], r["id"], ctx.field("overbook_reason", required=False))
        c.update("reservations", r["id"], {"status": "confirmed", "updated_at": now_iso()})
        audit(c, ctx, "reservation.confirmed", "reservation", r["id"], r["reference"], old={"status": r["status"]}, new={"status": "confirmed"}, hotel_id=r["hotel_id"])
        _send_confirmation(c, get_hotel(c, r["hotel_id"]), r["id"])
        return reservation_detail(c, c.one("SELECT * FROM reservations WHERE id = ?", [r["id"]]))


@route("POST", "/api/reservations/{res_id:int}/cancel", perm="reservations.cancel", tag="reservations", summary="Cancel a reservation with a reason")
def cancel(ctx: Ctx):
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        if r["status"] not in EDITABLE_STATUSES:
            raise conflict(f"A {r['status'].replace('_', ' ')} reservation cannot be cancelled")
        c.update("reservations", r["id"], {"status": "cancelled", "cancelled_at": now_iso(), "cancel_reason": reason, "updated_at": now_iso()})
        audit(c, ctx, "reservation.cancelled", "reservation", r["id"], r["reference"], old={"status": r["status"]},
              new={"status": "cancelled", "reason": reason}, hotel_id=r["hotel_id"])
        out = reservation_detail(c, c.one("SELECT * FROM reservations WHERE id = ?", [r["id"]]))
    if out["folio"] and out["folio"]["balance"] < 0:
        out["message"] = "The guest has a credit balance on the folio. Request a refund or post a cancellation fee from the folio."
    return out


@route("POST", "/api/reservations/{res_id:int}/no-show", perm="reservations.cancel", tag="reservations", summary="Mark a reservation as no-show")
def no_show(ctx: Ctx):
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        if r["status"] not in ("confirmed", "tentative"):
            raise conflict("Only confirmed or tentative reservations can be marked no-show")
        if dt.date.fromisoformat(r["arrival"]) > business_date(get_hotel(c, r["hotel_id"])):
            raise conflict("A reservation can only be marked no-show on or after its arrival date")
        c.update("reservations", r["id"], {"status": "no_show", "updated_at": now_iso()})
        audit(c, ctx, "reservation.no_show", "reservation", r["id"], r["reference"], old={"status": r["status"]}, new={"status": "no_show"}, hotel_id=r["hotel_id"])
        return reservation_detail(c, c.one("SELECT * FROM reservations WHERE id = ?", [r["id"]]))
