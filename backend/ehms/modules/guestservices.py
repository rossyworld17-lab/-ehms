"""Front-office guest services (release 1.2): wake-up calls, early check-in and late check-out with configurable fees
posted to the folio, and the guest registration card (PDF)."""
from __future__ import annotations

import datetime as dt
import io
import json
import re

from starlette.responses import Response

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, not_found, route
from ..services import business_date, get_hotel, hotel_setting, hotel_today, queue_notification, set_hotel_setting, to_minor
from .frontoffice import ensure_folio, post_charge
from .reservations import _load, reservation_detail

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DEFAULT_FEES = {"early_check_in": 0, "late_check_out": 0}


def _time(value, field: str) -> str:
    v = str(value or "").strip()
    if not TIME_RE.match(v):
        raise bad_request(f"{field} must be a time like 06:30")
    return v


def stay_fees(c, hotel_id: int) -> dict:
    raw = hotel_setting(c, hotel_id, "frontdesk.stay_fees")
    return {**DEFAULT_FEES, **(json.loads(raw) if raw else {})}


# ------------------------------------------------------------------ wake-up calls
@route("GET", "/api/hotels/{hotel_id:int}/wake-up-calls", perm="frontdesk.checkin", tag="frontdesk",
       summary="Wake-up calls for a date (?date, default today) with guest and room")
def list_wakeups(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        day = ctx.q("date") or hotel_today(hotel).isoformat()
        rows = c.all("SELECT w.*, r.reference, g.first_name, g.last_name, rm.number AS room_number, u.full_name AS done_by_name "
                     "FROM wake_up_calls w JOIN reservations r ON r.id = w.reservation_id JOIN guests g ON g.id = r.guest_id "
                     "LEFT JOIN rooms rm ON rm.id = r.room_id LEFT JOIN users u ON u.id = w.done_by "
                     "WHERE w.hotel_id = ? AND w.call_date = ? ORDER BY w.call_time, w.id", [hid, day])
        now = dt.datetime.now(dt.timezone.utc)
        local = _hotel_clock(hotel).replace(tzinfo=None)
        for w in rows:
            w["overdue"] = w["status"] == "pending" and dt.datetime.fromisoformat(f"{w['call_date']}T{w['call_time']}") < local
    return {"date": day, "items": rows, "now": now.isoformat()}


def _hotel_clock(hotel: dict) -> dt.datetime:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo(hotel["timezone"]))
    except Exception:  # pragma: no cover - unknown zone
        return dt.datetime.now()


@route("POST", "/api/reservations/{res_id:int}/wake-up-calls", perm="frontdesk.checkin", tag="frontdesk",
       summary="Book a wake-up call for an in-house (or arriving) guest: call_date, call_time (HH:MM), note")
def add_wakeup(ctx: Ctx):
    t = _time(ctx.field("call_time"), "call_time")
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        if r["status"] not in ("checked_in", "confirmed"):
            raise conflict("Wake-up calls can be booked for confirmed or in-house guests")
        hotel = get_hotel(c, r["hotel_id"])
        d = ctx.field("call_date", required=False, kind=str) or hotel_today(hotel).isoformat()
        try:
            day = dt.date.fromisoformat(d)
        except ValueError:
            raise bad_request("call_date must be YYYY-MM-DD")
        if day < hotel_today(hotel) or day > dt.date.fromisoformat(r["departure"]):
            raise bad_request("The call must be between today and the departure date")
        if c.one("SELECT id FROM wake_up_calls WHERE reservation_id = ? AND call_date = ? AND call_time = ? AND status = 'pending'", [r["id"], day.isoformat(), t]):
            raise conflict("This wake-up call is already booked")
        wid = c.insert("wake_up_calls", {"hotel_id": r["hotel_id"], "reservation_id": r["id"], "call_date": day.isoformat(), "call_time": t,
                                         "note": (ctx.field("note", required=False, kind=str) or "")[:200] or None, "status": "pending",
                                         "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "frontdesk.wakeup_booked", "reservation", r["id"], r["reference"], new={"date": day.isoformat(), "time": t}, hotel_id=r["hotel_id"])
    return {"id": wid, "_created": True}


@route("POST", "/api/wake-up-calls/{call_id:int}/status", perm="frontdesk.checkin", tag="frontdesk",
       summary="Record the outcome of a wake-up call: status done | missed | cancelled")
def wakeup_status(ctx: Ctx):
    status = ctx.field("status", kind=str)
    if status not in ("done", "missed", "cancelled"):
        raise bad_request("status must be done, missed or cancelled")
    with get_db().tx() as c:
        w = c.one("SELECT * FROM wake_up_calls WHERE id = ?", [ctx.path["call_id"]])
        if not w:
            raise not_found("Wake-up call")
        ctx.check_hotel(w["hotel_id"])
        if w["status"] != "pending":
            raise conflict(f"This call is already {w['status']}")
        c.update("wake_up_calls", w["id"], {"status": status, "done_by": ctx.user_id, "done_at": now_iso()})
        audit(c, ctx, f"frontdesk.wakeup_{status}", "wake_up_call", w["id"], old={"status": "pending"}, new={"status": status}, hotel_id=w["hotel_id"])
    return {"status": status}


def wakeup_alerts(c, hotel: dict) -> int:
    """Worker: remind front desk staff of wake-up calls due in the next 10 minutes, or already overdue (once per call).
    Compares full date-times, so calls just after midnight are found correctly."""
    from ..worker import _once, _users_with
    local = _hotel_clock(hotel).replace(tzinfo=None, second=0, microsecond=0)
    soon = local + dt.timedelta(minutes=10)
    days = sorted({local.date().isoformat(), soon.date().isoformat()})
    n = 0
    for w in c.all(f"SELECT w.*, rm.number AS room FROM wake_up_calls w JOIN reservations r ON r.id = w.reservation_id LEFT JOIN rooms rm ON rm.id = r.room_id "
                   f"WHERE w.hotel_id = ? AND w.status = 'pending' AND w.call_date IN ({','.join('?' for _ in days)})", [hotel["id"], *days]):
        due = dt.datetime.fromisoformat(f"{w['call_date']}T{w['call_time']}")
        if due <= soon and due >= local - dt.timedelta(hours=6) and _once(c, "wakeup_alert", str(w["id"])):
            for uid in _users_with(c, hotel["id"], "frontdesk.checkin"):
                queue_notification(c, hotel["id"], "in_app", str(uid), f"Wake-up call {w['call_time']} — room {w['room'] or '?'}",
                                   w["note"] or "Call the guest and record the outcome under Front desk → Wake-up calls.", "wake_up_call", w["id"])
            n += 1
    return n


# ------------------------------------------------------------------ early check-in / late check-out
@route("GET", "/api/hotels/{hotel_id:int}/stay-fees", perm="reservations.view", tag="frontdesk", summary="Early check-in and late check-out fees")
def get_stay_fees(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        h = get_hotel(c, hid)
        return {**stay_fees(c, hid), "check_in_time": h["check_in_time"], "check_out_time": h["check_out_time"]}


@route("PUT", "/api/hotels/{hotel_id:int}/stay-fees", perm="admin.settings.manage", tag="frontdesk",
       summary="Set the early check-in and late check-out fees (amounts in the hotel currency; 0 = free)")
def set_stay_fees(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    fees = {k: to_minor(ctx.field(k, required=False, default=0) or 0, k) for k in DEFAULT_FEES}
    if any(v < 0 for v in fees.values()):
        raise bad_request("Fees cannot be negative")
    with get_db().tx() as c:
        old = stay_fees(c, hid)
        set_hotel_setting(c, hid, "frontdesk.stay_fees", json.dumps(fees))
        audit(c, ctx, "settings.stay_fees", "hotel", hid, old=old, new=fees, hotel_id=hid)
    return fees


@route("POST", "/api/reservations/{res_id:int}/early-late", perm="reservations.modify", tag="frontdesk",
       summary="Grant early check-in or late check-out: kind early_check_in | late_check_out, until (HH:MM, late check-out), "
               "waive_reason (needs reservations.waive_fee to waive the fee)")
def early_late(ctx: Ctx):
    kind = ctx.field("kind", kind=str)
    if kind not in DEFAULT_FEES:
        raise bad_request("kind must be early_check_in or late_check_out")
    waive = ctx.field("waive_reason", required=False, kind=str)
    if waive:
        ctx.require("reservations.waive_fee")
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        hotel = get_hotel(c, r["hotel_id"])
        if kind == "early_check_in":
            if r["status"] not in ("confirmed", "tentative"):
                raise conflict("Early check-in is granted before the guest checks in")
            if r["early_check_in"]:
                raise conflict("Early check-in is already granted")
            if r["arrival"] != business_date(hotel).isoformat():
                raise conflict("Early check-in applies on the arrival day")
            change = {"early_check_in": 1}
            label = f"Early check-in (before {hotel['check_in_time']})"
        else:
            if r["status"] != "checked_in":
                raise conflict("Late check-out is granted to in-house guests")
            until = _time(ctx.field("until"), "until")
            if until <= hotel["check_out_time"]:
                raise bad_request(f"Late check-out must be after the normal check-out time ({hotel['check_out_time']})")
            if r["late_check_out_until"]:
                raise conflict(f"Late check-out until {r['late_check_out_until']} is already granted")
            change = {"late_check_out_until": until}
            label = f"Late check-out until {until}"
        fee = stay_fees(c, r["hotel_id"])[kind]
        line_id = None
        if fee and not waive:
            if not ctx.can("folio.post_charge"):
                raise conflict("Posting the fee needs the folio.post_charge permission")
            folio = ensure_folio(c, r)
            line_id = post_charge(c, ctx, hotel, folio, "room", label, fee, 1, r["reference"])
        c.update("reservations", r["id"], {**change, "updated_at": now_iso()})
        audit(c, ctx, f"frontdesk.{kind}", "reservation", r["id"], r["reference"], new={**change, "fee": 0 if waive else fee, "waive_reason": waive}, hotel_id=r["hotel_id"])
        return {**reservation_detail(c, c.one("SELECT * FROM reservations WHERE id = ?", [r["id"]])), "fee_posted": 0 if (waive or not fee) else fee,
                "folio_line_id": line_id}


# ------------------------------------------------------------------ registration card
@route("GET", "/api/reservations/{res_id:int}/registration-card.pdf", perm="frontdesk.checkin", tag="frontdesk",
       summary="Guest registration card (PDF) to print and sign at check-in")
def registration_card(ctx: Ctx):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    with get_db().tx() as c:
        r = _load(c, ctx, ctx.path["res_id"])
        hotel = get_hotel(c, r["hotel_id"])
        g = c.one("SELECT * FROM guests WHERE id = ?", [r["guest_id"]])
        rt = c.one("SELECT name FROM room_types WHERE id = ?", [r["room_type_id"]])
        room = c.one("SELECT number FROM rooms WHERE id = ?", [r["room_id"]]) if r["room_id"] else None
        audit(c, ctx, "frontdesk.registration_card", "reservation", r["id"], r["reference"], hotel_id=r["hotel_id"])
    show_id = ctx.can("guests.identity.view")
    idno = g.get("id_number") or ""
    if idno and not show_id:
        idno = "•" * max(0, len(idno) - 4) + idno[-4:]
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    cv.setFont("Helvetica-Bold", 16)
    cv.drawString(50, 795, hotel["name"])
    cv.setFont("Helvetica", 9)
    cv.drawString(50, 781, " · ".join(x for x in [hotel.get("address"), hotel.get("phone"), hotel.get("email")] if x))
    cv.setFont("Helvetica-Bold", 14)
    cv.drawString(50, 748, "GUEST REGISTRATION CARD")
    cv.setFont("Helvetica", 10)
    cv.drawRightString(545, 748, f"Reservation {r['reference']}")
    rows = [
        ("Guest name", f"{g['first_name']} {g['last_name']}"),
        ("Nationality", g.get("nationality") or ""), ("Date of birth", str(g.get("date_of_birth") or "")[:10]),
        ("Address", (g.get("address") or "")[:80]), ("Phone", g.get("phone") or ""), ("Email", g.get("email") or ""),
        ("Identification", f"{(g.get('id_type') or '').replace('_', ' ')} {idno}".strip()),
        ("Company", r.get("company_name") or g.get("company") or ""),
        ("Arrival", f"{r['arrival']}  (check-in from {hotel['check_in_time']}{', early check-in granted' if r.get('early_check_in') else ''})"),
        ("Departure", f"{r['departure']}  (check-out by {r.get('late_check_out_until') or hotel['check_out_time']})"),
        ("Room", f"{room['number'] if room else 'to be assigned'} — {rt['name'] if rt else ''}"),
        ("Guests", f"{r['adults']} adult(s), {r['children']} child(ren)"),
        ("Rate / night", f"{hotel['currency']} {r['nightly_rate'] / 100:,.2f}"),
        ("Special requests", (r.get("special_requests") or "")[:90]),
        ("Vehicle / plate", ""), ("Purpose of visit", ""), ("Next destination", ""),
    ]
    y = 715
    for k, v in rows:
        cv.setFont("Helvetica-Bold", 10)
        cv.drawString(50, y, k)
        cv.setFont("Helvetica", 10)
        cv.drawString(180, y, str(v))
        cv.line(180, y - 3, 545, y - 3)
        y -= 24
    y -= 6
    cv.setFont("Helvetica", 8.5)
    terms = (hotel.get("terms") or "I agree to settle all charges incurred during my stay and to abide by the hotel's terms and policies.")
    words, line = terms.split(), ""
    for w in words:
        if len(line) + len(w) > 110:
            cv.drawString(50, y, line)
            y -= 12
            line = ""
        line += w + " "
    if line:
        cv.drawString(50, y, line)
        y -= 12
    cv.drawString(50, y - 6, "Personal data is processed under the Nigeria Data Protection Act 2023 for registration, billing and legal obligations only.")
    y -= 60
    cv.line(50, y, 250, y)
    cv.line(330, y, 545, y)
    cv.setFont("Helvetica", 9)
    cv.drawString(50, y - 12, "Guest signature")
    cv.drawString(330, y - 12, "Receptionist")
    cv.showPage()
    cv.save()
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="registration-{r["reference"]}.pdf"'})
