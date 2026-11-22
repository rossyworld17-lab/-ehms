"""Front office: check-in, check-out, room moves, guest folios, payments, refunds (maker-checker)
and night audit. (FR-FO-001..007, FR-PAY-001..005, Workflow 9.1)"""
from __future__ import annotations

import datetime as dt
import json

from ..db import get_db, now_iso
from ..http import Ctx, ApiError, audit, bad_request, conflict, forbidden, not_found, route
from ..services import (REVENUE_KEYS, account_id, business_date, get_hotel, hotel_today, next_number, nights_between, post_journal,
                        price_breakdown, queue_notification, reverse_journal, to_minor)
from .reservations import _load, night_rate, reservation_detail
from .rooms import overlapping_room_reservations

CHARGE_DEPARTMENTS = ("room", "fnb", "minibar", "laundry", "events", "transport", "spa", "other")


# ------------------------------------------------------------------ helpers
def folio_balance(c, folio_id: int) -> dict:
    b = c.one("SELECT COALESCE(SUM(CASE WHEN kind = 'charge' THEN total_amount ELSE 0 END),0) AS charges, "
              "COALESCE(SUM(CASE WHEN kind = 'adjustment' THEN total_amount ELSE 0 END),0) AS adjustments, "
              "COALESCE(SUM(CASE WHEN kind = 'payment' THEN total_amount ELSE 0 END),0) AS payments, "
              "COALESCE(SUM(CASE WHEN kind = 'refund' THEN total_amount ELSE 0 END),0) AS refunds FROM folio_lines WHERE folio_id = ?", [folio_id])
    b["balance"] = b["charges"] + b["adjustments"] + b["refunds"] - b["payments"]
    return b


def ensure_folio(c, r: dict) -> dict:
    f = c.one("SELECT * FROM folios WHERE reservation_id = ?", [r["id"]])
    if f:
        return f
    number = next_number(c, r["hotel_id"], "folio", "FOL")
    fid = c.insert("folios", {"hotel_id": r["hotel_id"], "number": number, "reservation_id": r["id"], "guest_id": r["guest_id"],
                              "status": "open", "opened_at": now_iso()})
    return c.one("SELECT * FROM folios WHERE id = ?", [fid])


def post_charge(c, ctx: Ctx | None, hotel: dict, folio: dict, department: str, description: str, amount: int, quantity: int = 1,
                reference: str | None = None, on: dt.date | None = None) -> int:
    if folio["status"] != "open":
        raise conflict("This folio is closed")
    if department not in CHARGE_DEPARTMENTS:
        raise bad_request(f"department must be one of {', '.join(CHARGE_DEPARTMENTS)}")
    if amount <= 0 or quantity <= 0:
        raise bad_request("Amount and quantity must be greater than zero")
    on = on or business_date(hotel)
    bd = price_breakdown(c, hotel, "room" if department == "room" else ("fnb" if department in ("fnb", "minibar") else department), amount * quantity, on)
    org = hotel["organisation_id"]
    uid = ctx.user_id if ctx else None
    je = post_journal(c, hotel["id"], on, f"{description} ({folio['number']})", "folio", folio["number"], [
        (account_id(c, org, "guest_ledger"), bd["total"], 0, department, description),
        (account_id(c, org, REVENUE_KEYS[department]), 0, bd["net"], department, description),
        (account_id(c, org, "vat_payable"), 0, bd["tax"], department, "Tax on " + description),
        (account_id(c, org, "service_charge_payable"), 0, bd["service_charge"], department, "Service charge on " + description),
    ], uid)
    return c.insert("folio_lines", {"folio_id": folio["id"], "business_date": on.isoformat(), "kind": "charge", "department": department,
                                    "description": description[:300], "quantity": quantity, "net_amount": bd["net"], "tax_amount": bd["tax"],
                                    "service_charge": bd["service_charge"], "total_amount": bd["total"], "reference": reference,
                                    "journal_entry_id": je, "posted_by": uid, "posted_at": now_iso()})


def post_room_night(c, ctx: Ctx | None, hotel: dict, r: dict, folio: dict, night: dt.date) -> int | None:
    from .groups import room_night_folio
    folio = room_night_folio(c, r, folio)
    ref = f"ROOM:{r['id']}:{night.isoformat()}"
    if c.one("SELECT id FROM folio_lines WHERE folio_id = ? AND reference = ? AND kind = 'charge'", [folio["id"], ref]):
        return None
    rt = c.one("SELECT * FROM room_types WHERE id = ?", [r["room_type_id"]])
    room = c.one("SELECT number FROM rooms WHERE id = ?", [r["room_id"]]) if r["room_id"] else None
    from ..pricing import stay_night_rate
    rate = stay_night_rate(c, r, rt, night)
    rate += max(0, r["adults"] - 2) * (rt.get("extra_person_charge") or 0)
    planned = max(1, (dt.date.fromisoformat(r["departure"]) - dt.date.fromisoformat(r["arrival"])).days)
    disc = 0
    if r["discount_amount"]:
        disc = r["discount_amount"] // planned
        if night.isoformat() == r["arrival"]:
            disc += r["discount_amount"] - disc * planned
    amount = max(rate - disc, 0)
    if amount == 0:
        return None
    desc = f"Room {room['number'] if room else ''} {rt['name']} — night of {night.isoformat()}"
    return post_charge(c, ctx, hotel, folio, "room", desc, amount, 1, ref, night)


def _room_ready(c, ctx: Ctx, room: dict, allow_uninspected: bool) -> None:
    if room["occupancy"] == "occupied":
        raise conflict(f"Room {room['number']} is occupied")
    if room["service_status"] not in ("in_service", "vip_hold"):
        raise conflict(f"Room {room['number']} is {room['service_status'].replace('_', ' ')}")
    if room["hk_status"] != "inspected":
        if not allow_uninspected:
            raise conflict(f"Room {room['number']} has not been cleaned and inspected (status: {room['hk_status'].replace('_', ' ')})",
                           {"code": "room_not_ready"})
        ctx.require("housekeeping.inspect")


def _hk_task(c, hotel: dict, room_id: int, task_type: str, notes: str | None = None) -> int:
    return c.insert("housekeeping_tasks", {"hotel_id": hotel["id"], "room_id": room_id, "task_type": task_type, "status": "pending",
                                           "priority": 1 if task_type == "checkout_clean" else 2, "notes": notes,
                                           "business_date": business_date(hotel).isoformat(), "created_at": now_iso()})


# ------------------------------------------------------------------ check-in / out
@route("POST", "/api/reservations/{res_id:int}/check-in", perm="frontdesk.checkin", tag="frontdesk", summary="Check a guest in")
def check_in(ctx: Ctx):
    body = ctx.body or {}
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        hotel = get_hotel(c, r["hotel_id"])
        if r["status"] not in ("confirmed", "tentative"):
            raise conflict(f"A {r['status'].replace('_', ' ')} reservation cannot be checked in")
        bdate = business_date(hotel)
        if dt.date.fromisoformat(r["arrival"]) > bdate:
            raise conflict(f"Arrival is {r['arrival']}; guests can be checked in from their arrival date. Modify the reservation for an earlier arrival.")
        if dt.date.fromisoformat(r["departure"]) <= bdate:
            raise conflict("The departure date has passed; extend the stay before checking in")
        room_id = int(body["room_id"]) if body.get("room_id") else r["room_id"]
        if not room_id:
            raise bad_request("Assign a room before check-in", {"field": "room_id"})
        room = c.lock("rooms", room_id)
        if not room or room["hotel_id"] != r["hotel_id"]:
            raise bad_request("Room not found in this hotel")
        if room["room_type_id"] != r["room_type_id"]:
            ctx.require("reservations.override_rate")
        _room_ready(c, ctx, room, bool(body.get("allow_uninspected")))
        clashes = overlapping_room_reservations(c, room_id, bdate.isoformat(), r["departure"], r["id"])
        if clashes:
            raise conflict(f"Room {room['number']} is allocated to another reservation during this stay",
                           {"reservations": [x["reference"] for x in clashes]})
        # lawful identification capture (optional fields, restricted)
        id_fields = {k: body[k] for k in ("id_type", "id_number", "nationality", "address") if body.get(k)}
        if id_fields:
            ctx.require("guests.identity.view")
            c.update("guests", r["guest_id"], id_fields)
        folio = ensure_folio(c, r)
        c.update("rooms", room_id, {"occupancy": "occupied"})
        c.update("reservations", r["id"], {"status": "checked_in", "room_id": room_id, "room_type_id": room["room_type_id"],
                                           "checked_in_at": now_iso(), "updated_at": now_iso(), "arrival": min(r["arrival"], bdate.isoformat())})
        bal = folio_balance(c, folio["id"])
        audit(c, ctx, "frontdesk.check_in", "reservation", r["id"], r["reference"], old={"status": r["status"]},
              new={"status": "checked_in", "room": room["number"], "id_captured": bool(id_fields)}, hotel_id=r["hotel_id"])
        out = reservation_detail(c, c.one("SELECT * FROM reservations WHERE id = ?", [r["id"]]))
    warnings = []
    if r["deposit_required"] and bal["payments"] < r["deposit_required"]:
        warnings.append(f"Required deposit not yet received (outstanding {r['deposit_required'] - bal['payments']})")
    out["warnings"] = warnings
    return out


@route("GET", "/api/reservations/{res_id:int}/checkout-preview", perm="frontdesk.checkout", tag="frontdesk",
       summary="Preview charges still to be posted and the balance due at check-out")
def checkout_preview(ctx: Ctx):
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        if r["status"] != "checked_in":
            raise conflict("Only in-house reservations can be checked out")
        hotel = get_hotel(c, r["hotel_id"])
        folio = ensure_folio(c, r)
        bdate = business_date(hotel)
        end = max(dt.date.fromisoformat(r["arrival"]) + dt.timedelta(days=1), bdate)
        pending = []
        rt = c.one("SELECT * FROM room_types WHERE id = ?", [r["room_type_id"]])
        for n in nights_between(dt.date.fromisoformat(r["arrival"]), end):
            from .groups import room_night_folio
            if room_night_folio(c, r, folio)["id"] != folio["id"]:
                continue  # billed to the group master folio
            if not c.one("SELECT id FROM folio_lines WHERE folio_id = ? AND reference = ?", [folio["id"], f"ROOM:{r['id']}:{n.isoformat()}"]):
                from ..pricing import stay_night_rate
                rate = stay_night_rate(c, r, rt, n) + max(0, r["adults"] - 2) * (rt.get("extra_person_charge") or 0)
                bd = price_breakdown(c, hotel, "room", rate, n)
                pending.append({"date": n.isoformat(), "total": bd["total"]})
        bal = folio_balance(c, folio["id"])
    pending_total = sum(p["total"] for p in pending)
    return {"pending_room_nights": pending, "pending_total": pending_total, "current_balance": bal["balance"],
            "balance_due": bal["balance"] + pending_total, "early_departure": dt.date.fromisoformat(r["departure"]) > bdate}


@route("POST", "/api/reservations/{res_id:int}/check-out", perm="frontdesk.checkout", tag="frontdesk",
       summary="Check a guest out (posts remaining room nights; balance must be settled)")
def check_out(ctx: Ctx):
    body = ctx.body or {}
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        if r["status"] != "checked_in":
            raise conflict("Only in-house reservations can be checked out")
        hotel = get_hotel(c, r["hotel_id"])
        folio = ensure_folio(c, r)
        bdate = business_date(hotel)
        end = max(dt.date.fromisoformat(r["arrival"]) + dt.timedelta(days=1), bdate)
        for n in nights_between(dt.date.fromisoformat(r["arrival"]), end):
            post_room_night(c, ctx, hotel, r, folio, n)
        bal = folio_balance(c, folio["id"])
        if bal["balance"] != 0:
            # Roll back the posted nights; the guest must settle first. Report what is due.
            raise ApiError(409, "balance_outstanding",
                           "The folio must be settled before check-out" if bal["balance"] > 0 else
                           "The guest has a credit balance; process a refund before check-out",
                           {"balance": bal["balance"]})
        extra = c.all("SELECT * FROM folios WHERE linked_reservation_id = ? AND status = 'open'", [r["id"]])
        for xf in extra:
            xb = folio_balance(c, xf["id"])["balance"]
            if xb != 0:
                raise ApiError(409, "balance_outstanding", f"Folio {xf['number']} ({xf['window_name'] or 'extra'}) must be settled before check-out",
                               {"balance": xb, "folio_id": xf["id"]})
            c.update("folios", xf["id"], {"status": "closed", "closed_at": now_iso()})
        room = c.lock("rooms", r["room_id"])
        c.update("rooms", room["id"], {"occupancy": "vacant", "hk_status": "dirty"})
        _hk_task(c, hotel, room["id"], "checkout_clean", f"Departure {r['reference']}")
        c.update("folios", folio["id"], {"status": "closed", "closed_at": now_iso()})
        c.update("reservations", r["id"], {"status": "checked_out", "checked_out_at": now_iso(), "updated_at": now_iso(),
                                           "departure": min(r["departure"], end.isoformat()) if end.isoformat() < r["departure"] else r["departure"]})
        audit(c, ctx, "frontdesk.check_out", "reservation", r["id"], r["reference"], old={"status": "checked_in"},
              new={"status": "checked_out", "room": room["number"], "folio": folio["number"], "total_charges": bal["charges"]}, hotel_id=r["hotel_id"])
        from .crm import earn_for_stay, invite_after_checkout
        earned = earn_for_stay(c, ctx, hotel, r, folio["id"])
        if body.get("send_survey", True):
            invite_after_checkout(c, hotel, r)
        g = c.one("SELECT first_name, email FROM guests WHERE id = ?", [r["guest_id"]])
        if body.get("send_invoice", True):
            queue_notification(c, hotel["id"], "email", g["email"], f"Thank you for staying at {hotel['name']} — invoice {folio['number']}",
                               f"Dear {g['first_name']},\n\nThank you for staying with us. Your final invoice {folio['number']} totals "
                               f"{hotel['currency']} {bal['charges'] / 100:,.2f}. We hope to welcome you again soon.\n\n{hotel['name']}",
                               "reservation", r["id"])
        return {**reservation_detail(c, c.one("SELECT * FROM reservations WHERE id = ?", [r["id"]])), "loyalty_points_earned": earned}


@route("POST", "/api/reservations/{res_id:int}/room-move", perm="frontdesk.room_move", tag="frontdesk", summary="Move an in-house guest to another room")
def room_move(ctx: Ctx):
    new_room_id = ctx.field("room_id", kind=int)
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        if r["status"] != "checked_in":
            raise conflict("Only in-house guests can be moved; use room assignment for future reservations")
        hotel = get_hotel(c, r["hotel_id"])
        new = c.lock("rooms", new_room_id)
        if not new or new["hotel_id"] != r["hotel_id"]:
            raise bad_request("Room not found in this hotel")
        if new["id"] == r["room_id"]:
            raise bad_request("The guest is already in this room")
        if new["room_type_id"] != r["room_type_id"]:
            ctx.require("reservations.override_rate")
        _room_ready(c, ctx, new, bool((ctx.body or {}).get("allow_uninspected")))
        bdate = business_date(hotel)
        clashes = overlapping_room_reservations(c, new["id"], bdate.isoformat(), r["departure"], r["id"])
        if clashes:
            raise conflict(f"Room {new['number']} is allocated to another reservation", {"reservations": [x["reference"] for x in clashes]})
        old = c.lock("rooms", r["room_id"])
        c.update("rooms", old["id"], {"occupancy": "vacant", "hk_status": "dirty"})
        _hk_task(c, hotel, old["id"], "checkout_clean", f"Room move {r['reference']}")
        c.update("rooms", new["id"], {"occupancy": "occupied"})
        keep_rate = (ctx.body or {}).get("keep_rate", True)
        changes = {"room_id": new["id"], "room_type_id": new["room_type_id"], "updated_at": now_iso()}
        if keep_rate and new["room_type_id"] != r["room_type_id"] and not r["rate_overridden"]:
            # complimentary upgrade: keep the original category's rate
            orig = c.one("SELECT base_rate FROM room_types WHERE id = ?", [r["room_type_id"]])
            changes.update({"nightly_rate": orig["base_rate"], "rate_overridden": 1})
        c.update("reservations", r["id"], changes)
        audit(c, ctx, "frontdesk.room_move", "reservation", r["id"], r["reference"], old={"room": old["number"]},
              new={"room": new["number"], "reason": reason, "keep_rate": keep_rate}, hotel_id=r["hotel_id"])
        return reservation_detail(c, c.one("SELECT * FROM reservations WHERE id = ?", [r["id"]]))


# ------------------------------------------------------------------ folio
def _load_folio(c, ctx: Ctx, folio_id) -> dict:
    f = c.one("SELECT * FROM folios WHERE id = ?", [int(folio_id)])
    if not f:
        raise not_found("Folio")
    ctx.check_hotel(f["hotel_id"])
    return f


@route("GET", "/api/folios/{folio_id:int}", perm="folio.view", tag="folio", summary="Guest folio with all lines and balance")
def get_folio(ctx: Ctx):
    with get_db().tx() as c:
        f = _load_folio(c, ctx, ctx.path["folio_id"])
        lines = c.all("SELECT fl.*, u.full_name AS posted_by_name FROM folio_lines fl LEFT JOIN users u ON u.id = fl.posted_by "
                      "WHERE fl.folio_id = ? ORDER BY fl.id", [f["id"]])
        guest = c.one("SELECT id, first_name, last_name, email, phone, company FROM guests WHERE id = ?", [f["guest_id"]])
        res = c.one("SELECT r.id, r.reference, r.arrival, r.departure, r.status, rm.number AS room_number FROM reservations r "
                    "LEFT JOIN rooms rm ON rm.id = r.room_id WHERE r.id = ?", [f["reservation_id"]]) if f["reservation_id"] else None
        reversed_ids = {l["reverses_line_id"] for l in lines if l["reverses_line_id"]}
        for l in lines:
            l["reversed"] = l["id"] in reversed_ids
        approvals = c.all("SELECT * FROM approvals WHERE entity = 'folio' AND entity_id = ? ORDER BY id DESC", [f["id"]])
        stay_id = f["reservation_id"] or f.get("linked_reservation_id")
        if not res and stay_id:
            res = c.one("SELECT r.id, r.reference, r.arrival, r.departure, r.status, rm.number AS room_number FROM reservations r "
                        "LEFT JOIN rooms rm ON rm.id = r.room_id WHERE r.id = ?", [stay_id])
        siblings = []
        if stay_id:
            siblings = c.all("SELECT id, number, window_name, status FROM folios WHERE (reservation_id = ? OR linked_reservation_id = ?) AND id <> ? ORDER BY id",
                             [stay_id, stay_id, f["id"]])
        if f.get("group_block_id"):
            siblings += c.all("SELECT f.id, f.number, r.reference AS window_name, f.status FROM folios f JOIN reservations r ON r.id = f.reservation_id "
                              "WHERE r.group_block_id = ? AND f.status = 'open' ORDER BY f.id", [f["group_block_id"]])
        notes = c.all("SELECT id, number, kind, status, total_amount FROM customer_notes WHERE folio_id = ? ORDER BY id DESC", [f["id"]])
        for s in siblings:
            s["balance"] = folio_balance(c, s["id"])["balance"]
        return {**f, "lines": lines, "guest": guest, "reservation": res, "totals": folio_balance(c, f["id"]), "approvals": approvals,
                "other_folios": siblings, "notes": notes}


@route("GET", "/api/reservations/{res_id:int}/folio", perm="folio.view", tag="folio", summary="Open (or create) the folio for a reservation")
def reservation_folio(ctx: Ctx):
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        if r["status"] in ("cancelled", "no_show") and not c.one("SELECT id FROM folios WHERE reservation_id = ?", [r["id"]]):
            raise conflict("This reservation has no folio")
        f = ensure_folio(c, r)
    ctx.path["folio_id"] = f["id"]
    return get_folio(ctx)


@route("POST", "/api/folios/{folio_id:int}/charges", perm="folio.post_charge", tag="folio",
       summary="Post a charge (restaurant, minibar, laundry, transport …) to a folio")
def add_charge(ctx: Ctx):
    with get_db().tx() as c:
        f = _load_folio(c, ctx, ctx.path["folio_id"])
        hotel = get_hotel(c, f["hotel_id"])
        if f["reservation_id"]:
            st = c.scalar("SELECT status FROM reservations WHERE id = ?", [f["reservation_id"]])
            if st not in ("checked_in", "confirmed", "tentative", "cancelled", "no_show"):
                raise conflict("Charges cannot be posted to this reservation")
        dept = ctx.field("department", kind=str)
        if dept == "room" and not ctx.can("folio.adjust"):
            raise forbidden("Manual room charges require the folio.adjust permission; room nights post automatically")
        line_id = post_charge(c, ctx, hotel, f, dept, ctx.field("description", kind=str), to_minor(ctx.field("amount")),
                              int(ctx.field("quantity", required=False, default=1)), ctx.field("reference", required=False))
        audit(c, ctx, "folio.charge_posted", "folio", f["id"], f["number"], new=ctx.body, hotel_id=f["hotel_id"])
    return {"id": line_id, "_created": True}


@route("POST", "/api/folios/{folio_id:int}/adjustments", perm="folio.adjust", tag="folio",
       summary="Reverse a charge line, or grant an allowance (credit) with a reason")
def add_adjustment(ctx: Ctx):
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        f = _load_folio(c, ctx, ctx.path["folio_id"])
        if f["status"] != "open":
            raise conflict("This folio is closed")
        hotel = get_hotel(c, f["hotel_id"])
        bdate = business_date(hotel)
        line_id = ctx.field("line_id", required=False)
        if line_id:
            line = c.one("SELECT * FROM folio_lines WHERE id = ? AND folio_id = ?", [int(line_id), f["id"]])
            if not line or line["kind"] != "charge":
                raise bad_request("Only charge lines can be reversed")
            if c.one("SELECT id FROM folio_lines WHERE reverses_line_id = ?", [line["id"]]):
                raise conflict("This charge has already been reversed")
            je = reverse_journal(c, line["journal_entry_id"], bdate, reason, ctx.user_id)
            new_id = c.insert("folio_lines", {"folio_id": f["id"], "business_date": bdate.isoformat(), "kind": "adjustment",
                                              "department": line["department"], "description": f"Reversal: {line['description']} — {reason}"[:300],
                                              "quantity": line["quantity"], "net_amount": -line["net_amount"], "tax_amount": -line["tax_amount"],
                                              "service_charge": -line["service_charge"], "total_amount": -line["total_amount"],
                                              "reference": line["reference"] and f"REV:{line['reference']}", "reverses_line_id": line["id"],
                                              "journal_entry_id": je, "posted_by": ctx.user_id, "posted_at": now_iso()})
        else:
            amount = to_minor(ctx.field("amount"))
            if amount <= 0:
                raise bad_request("Allowance amount must be greater than zero")
            org = hotel["organisation_id"]
            je = post_journal(c, hotel["id"], bdate, f"Allowance on {f['number']}: {reason}", "folio", f["number"], [
                (account_id(c, org, "allowances"), amount, 0, "other", reason),
                (account_id(c, org, "guest_ledger"), 0, amount, "other", reason)], ctx.user_id)
            new_id = c.insert("folio_lines", {"folio_id": f["id"], "business_date": bdate.isoformat(), "kind": "adjustment", "department": "other",
                                              "description": f"Allowance — {reason}"[:300], "quantity": 1, "net_amount": -amount, "tax_amount": 0,
                                              "service_charge": 0, "total_amount": -amount, "journal_entry_id": je, "posted_by": ctx.user_id,
                                              "posted_at": now_iso()})
        audit(c, ctx, "folio.adjustment", "folio", f["id"], f["number"], new={"line_id": line_id, "amount": ctx.field("amount", required=False),
              "reason": reason}, hotel_id=f["hotel_id"])
    return {"id": new_id, "_created": True}


# ------------------------------------------------------------------ payments & refunds
@route("POST", "/api/folios/{folio_id:int}/payments", perm="payments.receive", tag="payments",
       summary="Record a payment or deposit (cash, transfer, POS card, city ledger)")
def add_payment(ctx: Ctx):
    fx_cur = (ctx.field("currency", required=False, kind=str) or "").upper() or None
    foreign = to_minor(ctx.field("foreign_amount"), "foreign_amount") if fx_cur else None
    amount = to_minor(ctx.field("amount")) if not fx_cur else None
    if (amount if amount is not None else foreign) <= 0:
        raise bad_request("Amount must be greater than zero")
    key = ctx.field("idempotency_key", kind=str)
    with get_db().tx() as c:
        existing = c.one("SELECT * FROM payments WHERE idempotency_key = ?", [key])
        if existing:
            same = existing["foreign_amount"] == foreign if fx_cur else existing["amount"] == amount
            if existing["folio_id"] != int(ctx.path["folio_id"]) or not same:
                raise conflict("This idempotency key was already used for a different payment")
            return {"id": existing["id"], "duplicate": True, "status": existing["status"]}
        f = _load_folio(c, ctx, ctx.path["folio_id"])
        if f["status"] != "open":
            raise conflict("This folio is closed")
        hotel = get_hotel(c, f["hotel_id"])
        rate = None
        if fx_cur:
            if fx_cur == hotel["currency"]:
                raise bad_request(f"{fx_cur} is the hotel's own currency; send amount instead")
            from .billing import convert, rate_for
            rate = rate_for(c, hotel["organisation_id"], fx_cur, business_date(hotel))
            if not rate:
                raise conflict(f"No {fx_cur} exchange rate has been recorded; finance must enter today's rate first")
            amount = convert(foreign, rate["rate_micro"])
        m = c.one("SELECT * FROM payment_methods WHERE id = ? AND hotel_id = ? AND active = 1", [ctx.field("method_id", kind=int), f["hotel_id"]])
        if not m:
            raise bad_request("Payment method not found", {"field": "method_id"})
        if m["kind"] == "online":
            raise ApiError(501, "gateway_not_configured",
                           "Online payments are confirmed by the payment gateway webhook, not entered manually. Configure Paystack/Flutterwave credentials first.")
        ref = ctx.field("reference", required=m["kind"] in ("bank_transfer", "card_pos"), kind=str)
        if m["kind"] == "city_ledger":
            if not c.one("SELECT company FROM guests WHERE id = ? AND company IS NOT NULL", [f["guest_id"]]) and not ctx.field("company", required=False):
                raise bad_request("City-ledger settlement requires a company name on the guest profile or in the request")
        if ref and c.one("SELECT id FROM payments WHERE hotel_id = ? AND method_id = ? AND reference = ? AND amount = ? AND kind = 'payment'",
                         [f["hotel_id"], m["id"], ref, amount]):
            raise conflict("A payment with the same method, reference and amount already exists (possible duplicate)")
        bdate = business_date(hotel)
        fx_note = f" ({fx_cur} {foreign / 100:,.2f} @ {rate['rate_micro'] / 1_000_000:g})" if fx_cur else ""
        je = post_journal(c, hotel["id"], bdate, f"Payment {m['name']} on {f['number']}{fx_note}", "payment", ref or key, [
            (m["account_id"], amount, 0, None, f"{m['name']} {ref or ''}"),
            (account_id(c, hotel["organisation_id"], "guest_ledger"), 0, amount, None, f"Payment on {f['number']}")], ctx.user_id)
        pid = c.insert("payments", {"hotel_id": f["hotel_id"], "folio_id": f["id"], "method_id": m["id"], "kind": "payment", "amount": amount,
                                    "currency": hotel["currency"], "status": "completed", "reference": ref, "idempotency_key": key,
                                    "note": ctx.field("note", required=False), "received_by": ctx.user_id, "journal_entry_id": je, "created_at": now_iso(),
                                    "foreign_currency": fx_cur, "foreign_amount": foreign, "exchange_rate_micro": rate["rate_micro"] if rate else None})
        c.insert("folio_lines", {"folio_id": f["id"], "business_date": bdate.isoformat(), "kind": "payment", "department": "payment",
                                 "description": f"Payment — {m['name']}" + (f" ({ref})" if ref else "") + fx_note, "quantity": 1, "net_amount": amount,
                                 "tax_amount": 0, "service_charge": 0, "total_amount": amount, "reference": ref, "payment_id": pid,
                                 "journal_entry_id": je, "posted_by": ctx.user_id, "posted_at": now_iso()})
        audit(c, ctx, "payment.received", "payment", pid, ref or key, new={"folio": f["number"], "amount": amount, "method": m["code"]}, hotel_id=f["hotel_id"])
        bal = folio_balance(c, f["id"])
    return {"id": pid, "status": "completed", "balance": bal["balance"], "amount": amount, "_created": True}


@route("POST", "/api/folios/{folio_id:int}/refund-requests", perm="payments.refund_request", tag="payments",
       summary="Request a refund (requires approval by a different authorised user)")
def request_refund(ctx: Ctx):
    amount = to_minor(ctx.field("amount"))
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        f = _load_folio(c, ctx, ctx.path["folio_id"])
        m = c.one("SELECT * FROM payment_methods WHERE id = ? AND hotel_id = ? AND active = 1", [ctx.field("method_id", kind=int), f["hotel_id"]])
        if not m or m["kind"] in ("online", "city_ledger"):
            raise bad_request("Choose a cash, transfer or POS method for the refund")
        bal = folio_balance(c, f["id"])
        if amount <= 0 or amount > -bal["balance"]:
            raise bad_request(f"Refund amount must be positive and no more than the guest's credit balance ({max(-bal['balance'], 0)})")
        aid = c.insert("approvals", {"hotel_id": f["hotel_id"], "kind": "refund", "entity": "folio", "entity_id": f["id"],
                                     "payload": json.dumps({"method_id": m["id"], "amount": amount}), "amount": amount, "reason": reason,
                                     "status": "pending", "requested_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "refund.requested", "approval", aid, f["number"], new={"amount": amount, "reason": reason}, hotel_id=f["hotel_id"])
    return {"id": aid, "status": "pending", "_created": True}


@route("GET", "/api/hotels/{hotel_id:int}/approvals", perm="approvals.view", tag="payments", summary="Approval requests")
def list_approvals(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    status = ctx.q("status", "pending")
    with get_db().tx() as c:
        return {"items": c.all("SELECT a.*, u.full_name AS requested_by_name, d.full_name AS decided_by_name, f.number AS folio_number "
                               "FROM approvals a JOIN users u ON u.id = a.requested_by LEFT JOIN users d ON d.id = a.decided_by "
                               "LEFT JOIN folios f ON a.entity = 'folio' AND f.id = a.entity_id WHERE a.hotel_id = ? AND a.status = ? "
                               "ORDER BY a.id DESC", [hid, status])}


@route("POST", "/api/approvals/{approval_id:int}/decide", perm="payments.refund_approve", tag="payments",
       summary="Approve or reject a refund request (maker-checker)")
def decide(ctx: Ctx):
    decision = ctx.field("decision", kind=str)
    if decision not in ("approve", "reject"):
        raise bad_request("decision must be approve or reject")
    with get_db().tx() as c:
        a = c.one("SELECT * FROM approvals WHERE id = ?", [ctx.path["approval_id"]])
        if not a:
            raise not_found("Approval request")
        ctx.check_hotel(a["hotel_id"])
        if a["status"] != "pending":
            raise conflict("This request has already been decided")
        if a["requested_by"] == ctx.user_id:
            raise forbidden("You cannot approve your own request")
        note = ctx.field("note", required=decision == "reject", kind=str)
        result = {}
        if decision == "approve" and a["kind"] == "refund":
            payload = json.loads(a["payload"])
            f = c.one("SELECT * FROM folios WHERE id = ?", [a["entity_id"]])
            hotel = get_hotel(c, f["hotel_id"])
            bal = folio_balance(c, f["id"])
            amount = payload["amount"]
            if amount > -bal["balance"]:
                raise conflict("The folio credit balance is now lower than the requested refund")
            m = c.one("SELECT * FROM payment_methods WHERE id = ?", [payload["method_id"]])
            bdate = business_date(hotel)
            je = post_journal(c, hotel["id"], bdate, f"Refund {m['name']} on {f['number']}", "payment", f"APPROVAL-{a['id']}", [
                (account_id(c, hotel["organisation_id"], "guest_ledger"), amount, 0, None, f"Refund on {f['number']}"),
                (m["account_id"], 0, amount, None, f"Refund {m['name']}")], ctx.user_id)
            pid = c.insert("payments", {"hotel_id": f["hotel_id"], "folio_id": f["id"], "method_id": m["id"], "kind": "refund", "amount": amount,
                                        "currency": hotel["currency"], "status": "completed", "reference": f"APPROVAL-{a['id']}",
                                        "idempotency_key": f"refund-approval-{a['id']}", "note": a["reason"], "received_by": ctx.user_id,
                                        "journal_entry_id": je, "created_at": now_iso()})
            c.insert("folio_lines", {"folio_id": f["id"], "business_date": bdate.isoformat(), "kind": "refund", "department": "payment",
                                     "description": f"Refund — {m['name']} ({a['reason']})"[:300], "quantity": 1, "net_amount": amount, "tax_amount": 0,
                                     "service_charge": 0, "total_amount": amount, "payment_id": pid, "journal_entry_id": je,
                                     "posted_by": ctx.user_id, "posted_at": now_iso()})
            result = {"payment_id": pid}
        c.update("approvals", a["id"], {"status": "approved" if decision == "approve" else "rejected", "decided_by": ctx.user_id,
                                        "decision_note": note, "decided_at": now_iso()})
        audit(c, ctx, f"approval.{decision}d", "approval", a["id"], a["kind"], new={"note": note, **result}, hotel_id=a["hotel_id"])
    return {"status": "approved" if decision == "approve" else "rejected", **result}


# ------------------------------------------------------------------ night audit
@route("POST", "/api/hotels/{hotel_id:int}/night-audit", perm="frontdesk.night_audit", tag="frontdesk",
       summary="Night audit: post tonight's room charges for in-house guests and roll the business date")
def night_audit(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        bdate = business_date(hotel)
        if bdate > hotel_today(hotel):
            raise conflict(f"Business date {bdate} is already ahead of today's date; night audit for it can run tomorrow")
        posted = 0
        inhouse = c.all("SELECT * FROM reservations WHERE hotel_id = ? AND status = 'checked_in'", [hid])
        for r in inhouse:  # includes overstays: every occupied night is charged
            folio = ensure_folio(c, r)
            if post_room_night(c, ctx, hotel, r, folio, bdate):
                posted += 1
        pending_arrivals = c.all("SELECT reference FROM reservations WHERE hotel_id = ? AND arrival = ? AND status IN ('confirmed','tentative')",
                                 [hid, bdate.isoformat()])
        overstays = c.all("SELECT reference FROM reservations WHERE hotel_id = ? AND status = 'checked_in' AND departure <= ?", [hid, bdate.isoformat()])
        new_date = bdate + dt.timedelta(days=1)
        c.update("hotels", hid, {"business_date": new_date.isoformat()})
        # stay-over cleaning for occupied rooms
        for r in inhouse:
            if r["departure"] > new_date.isoformat():
                c.insert("housekeeping_tasks", {"hotel_id": hid, "room_id": r["room_id"], "task_type": "stayover", "status": "pending", "priority": 3,
                                                "notes": f"Stay-over {r['reference']}", "business_date": new_date.isoformat(), "created_at": now_iso()})
        summary = {"audited_date": bdate.isoformat(), "new_business_date": new_date.isoformat(), "room_charges_posted": posted,
                   "in_house": len(inhouse), "arrivals_not_checked_in": [p["reference"] for p in pending_arrivals],
                   "overstays": [o["reference"] for o in overstays]}
        audit(c, ctx, "frontdesk.night_audit", "hotel", hid, hotel["code"], new=summary, hotel_id=hid)
    return summary
