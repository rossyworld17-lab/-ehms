"""Events, conference & banqueting: venues with capacities, enquiries → tentative → confirmed bookings without
venue clashes, quotations (catering, equipment, decoration…), an event folio for deposits and the final invoice
(posted through the normal folio/ledger), direct costs, staff allocation and profitability. (FR-EVT-001..005)"""
from __future__ import annotations

import datetime as dt
import io

from starlette.responses import Response

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, not_found, route
from ..services import business_date, get_hotel, next_number, price_breakdown, to_minor

EVENT_TYPES = ("wedding", "conference", "seminar", "workshop", "meeting", "birthday", "banquet", "social", "private", "other")
ITEM_KINDS = ("venue", "catering", "beverage", "equipment", "decoration", "accommodation", "service", "other")
KIND_DEPT = {"venue": "events", "catering": "fnb", "beverage": "fnb", "equipment": "events", "decoration": "events", "accommodation": "room",
             "service": "events", "other": "other"}
HOLDS = ("tentative", "confirmed")     # statuses that occupy a venue


def _ts(v: str, field: str) -> str:
    try:
        d = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        raise bad_request(f"'{field}' must be a date-time (YYYY-MM-DDTHH:MM)")
    return d.replace(tzinfo=None).isoformat(timespec="minutes")


def clashes(c, venue_id: int, start: str, end: str, exclude_event: int | None = None) -> list[dict]:
    sql = ("SELECT e.number, e.title, e.status, ev.start_at, ev.end_at FROM event_venues ev JOIN events e ON e.id = ev.event_id "
           f"WHERE ev.venue_id = ? AND e.status IN ('tentative','confirmed') AND ev.start_at < ? AND ev.end_at > ?")
    params: list = [venue_id, end, start]
    if exclude_event:
        sql += " AND e.id <> ?"
        params.append(exclude_event)
    return c.all(sql, params)


# ------------------------------------------------------------------ venues
@route("GET", "/api/hotels/{hotel_id:int}/venues", perm="events.view", tag="events", summary="Venues")
def list_venues(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": c.all("SELECT * FROM venues WHERE hotel_id = ? ORDER BY name", [hid])}


@route("POST", "/api/hotels/{hotel_id:int}/venues", perm="events.manage", tag="events", summary="Add or edit a venue (by code)")
def save_venue(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    code = ctx.field("code", kind=str).upper()
    data = {"name": ctx.field("name", kind=str), "facilities": ctx.field("facilities", required=False, kind=str),
            "area_sqm": ctx.field("area_sqm", required=False, kind=int), "active": 1 if ctx.field("active", required=False, default=True) else 0}
    for k in ("capacity_theatre", "capacity_banquet", "capacity_classroom"):
        data[k] = ctx.field(k, required=False, default=0, kind=int)
    for k in ("hourly_rate", "daily_rate"):
        data[k] = to_minor(ctx.field(k, required=False, default=0), k)
    with get_db().tx() as c:
        row = c.one("SELECT id FROM venues WHERE hotel_id = ? AND code = ?", [hid, code])
        if row:
            c.update("venues", row["id"], data)
            vid = row["id"]
        else:
            vid = c.insert("venues", {"hotel_id": hid, "code": code, **data})
        audit(c, ctx, "events.venue_saved", "venue", vid, code, new=data, hotel_id=hid)
    return {"id": vid, "_created": True}


@route("GET", "/api/hotels/{hotel_id:int}/venues/calendar", perm="events.view", tag="events", summary="Venue bookings between ?from and ?to (dates)")
def venue_calendar(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        frm = ctx.q("from", today.isoformat())
        to = ctx.q("to", (today + dt.timedelta(days=30)).isoformat())
        rows = c.all("SELECT ev.*, e.number, e.title, e.status, e.event_type, e.client_name, e.expected_guests, v.name AS venue_name FROM event_venues ev "
                     "JOIN events e ON e.id = ev.event_id JOIN venues v ON v.id = ev.venue_id WHERE v.hotel_id = ? AND e.status <> 'cancelled' "
                     "AND ev.start_at < ? AND ev.end_at > ? ORDER BY ev.start_at", [hid, to + "T23:59", frm])
        venues = c.all("SELECT id, name FROM venues WHERE hotel_id = ? AND active = 1 ORDER BY name", [hid])
    return {"from": frm, "to": to, "venues": venues, "bookings": rows}


# ------------------------------------------------------------------ events
def _event(c, ctx: Ctx, eid, lock=False) -> dict:
    e = c.lock("events", int(eid)) if lock else c.one("SELECT * FROM events WHERE id = ?", [int(eid)])
    if not e:
        raise not_found("Event")
    ctx.check_hotel(e["hotel_id"])
    return e


def _totals(c, hotel: dict, e: dict) -> dict:
    items = c.all("SELECT * FROM event_items WHERE event_id = ?", [e["id"]])
    on = dt.date.fromisoformat(e["start_at"][:10])
    net = svc = tax = 0
    for i in items:
        bd = price_breakdown(c, hotel, KIND_DEPT[i["kind"]] if KIND_DEPT[i["kind"]] in ("room", "fnb") else KIND_DEPT[i["kind"]], i["quantity"] * i["unit_price"], on)
        net += bd["net"]
        svc += bd["service_charge"]
        tax += bd["tax"]
    costs = c.scalar("SELECT COALESCE(SUM(amount),0) FROM event_costs WHERE event_id = ?", [e["id"]]) or 0
    paid = 0
    if e["folio_id"]:
        paid = c.scalar("SELECT COALESCE(SUM(CASE WHEN kind = 'payment' THEN total_amount WHEN kind = 'refund' THEN -total_amount ELSE 0 END),0) FROM folio_lines WHERE folio_id = ?",
                        [e["folio_id"]]) or 0
    return {"net": net, "service_charge": svc, "tax": tax, "total": net + svc + tax, "costs": costs, "profit": net - costs, "paid": paid,
            "margin_pct": round((net - costs) * 100 / net, 1) if net else None}


def event_detail(c, e: dict) -> dict:
    hotel = get_hotel(c, e["hotel_id"])
    e = dict(e)
    e["venues"] = c.all("SELECT ev.*, v.name AS venue_name, v.code FROM event_venues ev JOIN venues v ON v.id = ev.venue_id WHERE ev.event_id = ? ORDER BY ev.start_at", [e["id"]])
    e["items"] = c.all("SELECT * FROM event_items WHERE event_id = ? ORDER BY id", [e["id"]])
    e["costs"] = c.all("SELECT ec.*, u.full_name AS by_name FROM event_costs ec JOIN users u ON u.id = ec.created_by WHERE ec.event_id = ? ORDER BY ec.id", [e["id"]])
    e["staff"] = c.all("SELECT s.*, em.first_name || ' ' || em.last_name AS employee, em.department FROM event_staff s JOIN employees em ON em.id = s.employee_id "
                       "WHERE s.event_id = ? ORDER BY s.id", [e["id"]])
    e["totals"] = _totals(c, hotel, e)
    e["folio_number"] = c.scalar("SELECT number FROM folios WHERE id = ?", [e["folio_id"]]) if e["folio_id"] else None
    e["currency"] = hotel["currency"]
    return e


@route("GET", "/api/hotels/{hotel_id:int}/events", perm="events.view", tag="events", summary="Events (?status, ?from, ?to)")
def list_events(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = "SELECT e.* FROM events e WHERE e.hotel_id = ?"
    params: list = [hid]
    if ctx.q("status"):
        sql += " AND e.status = ?"
        params.append(ctx.q("status"))
    if ctx.q("from"):
        sql += " AND e.end_at >= ?"
        params.append(ctx.q("from"))
    if ctx.q("to"):
        sql += " AND e.start_at <= ?"
        params.append(ctx.q("to") + "T23:59")
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY e.start_at DESC LIMIT 300", params)
        hotel = get_hotel(c, hid)
        for r in rows:
            r["venue_names"] = ", ".join(v["name"] for v in c.all("SELECT v.name FROM event_venues ev JOIN venues v ON v.id = ev.venue_id WHERE ev.event_id = ?", [r["id"]]))
            r["total"] = _totals(c, hotel, r)["total"]
    return {"items": rows, "types": EVENT_TYPES, "item_kinds": ITEM_KINDS}


@route("POST", "/api/hotels/{hotel_id:int}/events", perm="events.manage", tag="events",
       summary="Create an enquiry/booking: title, event_type, client, start_at, end_at, expected_guests, venues[{venue_id, start_at, end_at}], status")
def create_event(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    etype = ctx.field("event_type", kind=str)
    if etype not in EVENT_TYPES:
        raise bad_request(f"event_type must be one of {', '.join(EVENT_TYPES)}")
    status = ctx.field("status", required=False, default="enquiry", kind=str)
    if status not in ("enquiry", "tentative", "confirmed"):
        raise bad_request("status must be enquiry, tentative or confirmed")
    start, end = _ts(ctx.field("start_at"), "start_at"), _ts(ctx.field("end_at"), "end_at")
    if end <= start:
        raise bad_request("The event must end after it starts")
    with get_db().tx() as c:
        number = next_number(c, hid, "event", "EVT")
        eid = c.insert("events", {"hotel_id": hid, "number": number, "title": ctx.field("title", kind=str), "event_type": etype, "status": "enquiry",
                                  "client_name": ctx.field("client_name", kind=str), "client_phone": ctx.field("client_phone", required=False, kind=str),
                                  "client_email": ctx.field("client_email", required=False, kind=str), "company": ctx.field("company", required=False, kind=str),
                                  "start_at": start, "end_at": end, "expected_guests": ctx.field("expected_guests", required=False, default=0, kind=int),
                                  "layout": ctx.field("layout", required=False, kind=str), "deposit_required": to_minor(ctx.field("deposit_required", required=False, default=0)),
                                  "notes": ctx.field("notes", required=False, kind=str), "sales_owner": ctx.user_id, "created_by": ctx.user_id, "created_at": now_iso()})
        for v in ctx.field("venues", required=False) or []:
            _add_venue(c, hid, eid, v)
        if status != "enquiry":
            _set_status(c, ctx, c.one("SELECT * FROM events WHERE id = ?", [eid]), status)
        audit(c, ctx, "events.created", "event", eid, number, new=ctx.body, hotel_id=hid)
        return {**event_detail(c, c.one("SELECT * FROM events WHERE id = ?", [eid])), "_created": True}


def _add_venue(c, hid: int, eid: int, v: dict) -> None:
    venue = c.one("SELECT * FROM venues WHERE id = ? AND hotel_id = ? AND active = 1", [int(v.get("venue_id") or 0), hid])
    if not venue:
        raise bad_request("Venue not found")
    s, e = _ts(v.get("start_at"), "start_at"), _ts(v.get("end_at"), "end_at")
    if e <= s:
        raise bad_request("Venue time must end after it starts")
    c.insert("event_venues", {"event_id": eid, "venue_id": venue["id"], "start_at": s, "end_at": e})


def _set_status(c, ctx: Ctx, e: dict, status: str) -> None:
    if status in HOLDS:
        for v in c.all("SELECT ev.*, vn.name, vn.capacity_theatre, vn.capacity_banquet, vn.capacity_classroom FROM event_venues ev JOIN venues vn ON vn.id = ev.venue_id WHERE ev.event_id = ?", [e["id"]]):
            cl = clashes(c, v["venue_id"], v["start_at"], v["end_at"], e["id"])
            if cl:
                raise conflict(f"{v['name']} is already held by {cl[0]['number']} ({cl[0]['title']}, {cl[0]['status']}) at that time",
                               {"code": "venue_clash", "events": [x["number"] for x in cl]})
            cap = max(v["capacity_theatre"], v["capacity_banquet"], v["capacity_classroom"])
            if cap and e["expected_guests"] > cap:
                raise conflict(f"{v['name']} holds at most {cap} guests; {e['expected_guests']} expected")
        if not c.one("SELECT id FROM event_venues WHERE event_id = ?", [e["id"]]):
            raise bad_request("Add at least one venue booking before holding the event")
    data: dict = {"status": status}
    if status == "confirmed" and not e["folio_id"]:
        data["folio_id"] = _event_folio(c, e)
    c.update("events", e["id"], data)


def _event_folio(c, e: dict) -> int:
    """An event folio (no room reservation) for deposits and the final invoice."""
    hotel = get_hotel(c, e["hotel_id"])
    guest = None
    if e["client_email"]:
        guest = c.scalar("SELECT id FROM guests WHERE organisation_id = ? AND lower(email) = ? ORDER BY id LIMIT 1", [hotel["organisation_id"], e["client_email"].lower()])
    if not guest:
        parts = e["client_name"].split(" ", 1)
        guest = c.insert("guests", {"organisation_id": hotel["organisation_id"], "first_name": parts[0][:100], "last_name": (parts[1] if len(parts) > 1 else "(event client)")[:100],
                                    "email": e["client_email"], "phone": e["client_phone"], "company": e["company"], "created_at": now_iso()})
    number = next_number(c, e["hotel_id"], "folio", "FOL")
    fid = c.insert("folios", {"hotel_id": e["hotel_id"], "number": number, "reservation_id": None, "guest_id": guest, "status": "open", "opened_at": now_iso()})
    c.update("events", e["id"], {"guest_id": guest})
    return fid


@route("GET", "/api/events/{event_id:int}", perm="events.view", tag="events", summary="Event with venues, quotation items, totals, costs, staff and folio")
def get_event(ctx: Ctx):
    with get_db().tx() as c:
        return event_detail(c, _event(c, ctx, ctx.path["event_id"]))


@route("PATCH", "/api/events/{event_id:int}", perm="events.manage", tag="events", summary="Edit event details (not after invoicing)")
def update_event(ctx: Ctx):
    with get_db().tx() as c:
        e = _event(c, ctx, ctx.path["event_id"], lock=True)
        if e["invoiced_at"] or e["status"] in ("completed", "cancelled"):
            raise conflict("This event can no longer be edited")
        b = ctx.body or {}
        data = {k: b[k] for k in ("title", "client_name", "client_phone", "client_email", "company", "layout", "notes") if k in b}
        if "expected_guests" in b:
            data["expected_guests"] = int(b["expected_guests"])
        if "deposit_required" in b:
            data["deposit_required"] = to_minor(b["deposit_required"] or 0)
        for k in ("start_at", "end_at"):
            if k in b:
                data[k] = _ts(b[k], k)
        c.update("events", e["id"], data)
        audit(c, ctx, "events.updated", "event", e["id"], e["number"], old={k: e[k] for k in data}, new=data, hotel_id=e["hotel_id"])
        return event_detail(c, c.one("SELECT * FROM events WHERE id = ?", [e["id"]]))


@route("POST", "/api/events/{event_id:int}/venues", perm="events.manage", tag="events", summary="Book another venue slot for the event")
def add_venue(ctx: Ctx):
    with get_db().tx() as c:
        e = _event(c, ctx, ctx.path["event_id"], lock=True)
        if e["status"] in ("completed", "cancelled"):
            raise conflict(f"This event is {e['status']}")
        _add_venue(c, e["hotel_id"], e["id"], ctx.body or {})
        if e["status"] in HOLDS:
            _set_status(c, ctx, e, e["status"])   # re-check clashes
        return event_detail(c, e)


@route("DELETE", "/api/event-venues/{slot_id:int}", perm="events.manage", tag="events", summary="Remove a venue slot")
def remove_venue(ctx: Ctx):
    with get_db().tx() as c:
        s = c.one("SELECT * FROM event_venues WHERE id = ?", [ctx.path["slot_id"]])
        if not s:
            raise not_found("Venue slot")
        e = _event(c, ctx, s["event_id"])
        c.execute("DELETE FROM event_venues WHERE id = ?", [s["id"]])
        return event_detail(c, e)


@route("POST", "/api/events/{event_id:int}/items", perm="events.manage", tag="events",
       summary="Add a quotation line (kind venue/catering/beverage/equipment/decoration/accommodation/service/other, description, quantity, unit_price)")
def add_item(ctx: Ctx):
    kind = ctx.field("kind", kind=str)
    if kind not in ITEM_KINDS:
        raise bad_request(f"kind must be one of {', '.join(ITEM_KINDS)}")
    qty = ctx.field("quantity", required=False, default=1, kind=int)
    if qty <= 0:
        raise bad_request("Quantity must be positive")
    with get_db().tx() as c:
        e = _event(c, ctx, ctx.path["event_id"], lock=True)
        if e["invoiced_at"] or e["status"] in ("completed", "cancelled"):
            raise conflict("Quotation lines can no longer be changed")
        c.insert("event_items", {"event_id": e["id"], "kind": kind, "description": ctx.field("description", kind=str)[:200], "quantity": qty,
                                 "unit_price": to_minor(ctx.field("unit_price"), "unit_price")})
        return event_detail(c, e)


@route("DELETE", "/api/event-items/{item_id:int}", perm="events.manage", tag="events", summary="Remove a quotation line (before invoicing)")
def remove_item(ctx: Ctx):
    with get_db().tx() as c:
        i = c.one("SELECT * FROM event_items WHERE id = ?", [ctx.path["item_id"]])
        if not i:
            raise not_found("Item")
        e = _event(c, ctx, i["event_id"])
        if i["folio_line_id"]:
            raise conflict("This line has been invoiced")
        c.execute("DELETE FROM event_items WHERE id = ?", [i["id"]])
        return event_detail(c, e)


@route("POST", "/api/events/{event_id:int}/status", perm="events.manage", tag="events",
       summary="Move an event: tentative / confirmed (checks venue clashes and capacity; opens the event folio) / cancelled (reason) / completed")
def set_status(ctx: Ctx):
    status = ctx.field("status", kind=str)
    allowed = {"enquiry": ("tentative", "confirmed", "cancelled"), "tentative": ("confirmed", "cancelled", "enquiry"), "confirmed": ("completed", "cancelled")}
    with get_db().tx() as c:
        e = _event(c, ctx, ctx.path["event_id"], lock=True)
        if status not in allowed.get(e["status"], ()):
            raise conflict(f"A {e['status']} event cannot become {status}")
        if status == "cancelled":
            reason = ctx.field("reason", kind=str)
            # any deposit stays on the event folio: retain it with a cancellation-fee charge or refund it (maker-checker) from the folio
            c.update("events", e["id"], {"status": "cancelled", "cancel_reason": reason})
        elif status == "completed":
            if not e["invoiced_at"]:
                raise conflict("Invoice the event before completing it")
            c.update("events", e["id"], {"status": "completed"})
        else:
            _set_status(c, ctx, e, status)
        audit(c, ctx, f"events.{status}", "event", e["id"], e["number"], old={"status": e["status"]}, new={"status": status}, hotel_id=e["hotel_id"])
        return event_detail(c, c.one("SELECT * FROM events WHERE id = ?", [e["id"]]))


@route("POST", "/api/events/{event_id:int}/invoice", perm="events.invoice", tag="events",
       summary="Post every quotation line to the event folio (with taxes and service charge); deposits already taken are credited")
def invoice(ctx: Ctx):
    with get_db().tx() as c:
        e = _event(c, ctx, ctx.path["event_id"], lock=True)
        if e["status"] != "confirmed":
            raise conflict("Only confirmed events can be invoiced")
        if e["invoiced_at"]:
            raise conflict("This event has already been invoiced")
        items = c.all("SELECT * FROM event_items WHERE event_id = ? AND folio_line_id IS NULL", [e["id"]])
        if not items:
            raise bad_request("There are no quotation lines to invoice")
        hotel = get_hotel(c, e["hotel_id"])
        folio = c.one("SELECT * FROM folios WHERE id = ?", [e["folio_id"]])
        from .frontoffice import post_charge
        for i in items:
            dept = KIND_DEPT[i["kind"]]
            lid = post_charge(c, ctx, hotel, folio, dept if dept != "room" else "room", f"{e['number']} {e['title']}: {i['description']}", i["unit_price"], i["quantity"], e["number"])
            c.update("event_items", i["id"], {"folio_line_id": lid})
        c.update("events", e["id"], {"invoiced_at": now_iso()})
        audit(c, ctx, "events.invoiced", "event", e["id"], e["number"], new={"lines": len(items), "folio": folio["number"]}, hotel_id=e["hotel_id"])
        return event_detail(c, c.one("SELECT * FROM events WHERE id = ?", [e["id"]]))


@route("POST", "/api/events/{event_id:int}/costs", perm="events.manage", tag="events", summary="Record a direct event cost (for profitability)")
def add_cost(ctx: Ctx):
    amount = to_minor(ctx.field("amount"))
    if amount <= 0:
        raise bad_request("Amount must be greater than zero")
    with get_db().tx() as c:
        e = _event(c, ctx, ctx.path["event_id"])
        c.insert("event_costs", {"event_id": e["id"], "description": ctx.field("description", kind=str)[:200], "amount": amount, "created_by": ctx.user_id, "created_at": now_iso()})
        return event_detail(c, e)


@route("POST", "/api/events/{event_id:int}/staff", perm="events.manage", tag="events", summary="Allocate an employee to the event (employee_id, role)")
def add_staff(ctx: Ctx):
    with get_db().tx() as c:
        e = _event(c, ctx, ctx.path["event_id"])
        emp = c.one("SELECT id, user_id FROM employees WHERE id = ? AND hotel_id = ? AND status = 'active'", [ctx.field("employee_id", kind=int), e["hotel_id"]])
        if not emp:
            raise bad_request("Employee not found")
        if c.one("SELECT id FROM event_staff WHERE event_id = ? AND employee_id = ?", [e["id"], emp["id"]]):
            raise conflict("Already allocated")
        c.insert("event_staff", {"event_id": e["id"], "employee_id": emp["id"], "role": ctx.field("role", kind=str)[:100]})
        if emp["user_id"]:
            from ..services import queue_notification
            queue_notification(c, e["hotel_id"], "in_app", str(emp["user_id"]), "Event assignment", f"You are on {e['title']} ({e['start_at'][:16].replace('T', ' ')})", "event", e["id"])
        return event_detail(c, e)


@route("GET", "/api/events/{event_id:int}/quotation.pdf", perm="events.view", tag="events", summary="Quotation / proforma invoice PDF")
def quotation_pdf(ctx: Ctx):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    with get_db().tx() as c:
        e = event_detail(c, _event(c, ctx, ctx.path["event_id"]))
        hotel = get_hotel(c, e["hotel_id"])
    f = lambda v: f"{v / 100:,.2f}"  # noqa: E731
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, title=f"Quotation {e['number']}")
    ss = getSampleStyleSheet()
    title = "INVOICE" if e["invoiced_at"] else "QUOTATION / PROFORMA INVOICE"
    story = [Paragraph(f"<b>{hotel['name']}</b>", ss["Title"]), Paragraph(f"{title} {e['number']}", ss["Heading2"]),
             Paragraph(f"Client: {e['client_name']}{' — ' + e['company'] if e['company'] else ''}<br/>Event: {e['title']} ({e['event_type']}), "
                       f"{e['start_at'].replace('T', ' ')} to {e['end_at'].replace('T', ' ')}, {e['expected_guests']} guests<br/>"
                       f"Venue(s): {', '.join(v['venue_name'] for v in e['venues']) or '—'}", ss["Normal"]), Spacer(1, 8)]
    rows = [["Item", "Qty", "Unit price", "Amount"]] + [[Paragraph(f"{i['description']} <font color='grey'>({i['kind']})</font>", ss["BodyText"]), i["quantity"], f(i["unit_price"]),
                                                         f(i["quantity"] * i["unit_price"])] for i in e["items"]]
    t = Table(rows, colWidths=[95 * mm, 15 * mm, 30 * mm, 30 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f1f3d")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
    tt = e["totals"]
    summary = [["Subtotal", f(tt["net"])], ["Service charge", f(tt["service_charge"])], ["Taxes", f(tt["tax"])], [f"TOTAL {e['currency']}", f(tt["total"])],
               ["Deposit required", f(e["deposit_required"])], ["Paid to date", f(tt["paid"])]]
    st = Table(summary, colWidths=[40 * mm, 35 * mm], hAlign="RIGHT")
    st.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"), ("LINEABOVE", (0, 3), (-1, 3), 1, colors.HexColor("#c8a96a"))]))
    story += [t, Spacer(1, 8), st, Spacer(1, 10)]
    if hotel.get("terms"):
        story.append(Paragraph(hotel["terms"], ss["BodyText"]))
    doc.build(story)
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{e["number"]}.pdf"'})


@route("GET", "/api/hotels/{hotel_id:int}/events/summary", perm="events.view", tag="events", summary="Events revenue and profitability for a period (?from, ?to)")
def events_summary(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        today = business_date(hotel)
        frm, to = ctx.q("from", today.replace(day=1).isoformat()), ctx.q("to", (today + dt.timedelta(days=90)).isoformat())
        evs = c.all("SELECT * FROM events WHERE hotel_id = ? AND status <> 'cancelled' AND start_at >= ? AND start_at <= ? ORDER BY start_at", [hid, frm, to + "T23:59"])
        out = []
        for e in evs:
            t = _totals(c, hotel, e)
            out.append({"id": e["id"], "number": e["number"], "title": e["title"], "status": e["status"], "start_at": e["start_at"], **t})
        pipeline = {s: sum(1 for e in evs if e["status"] == s) for s in ("enquiry", "tentative", "confirmed", "completed")}
    return {"from": frm, "to": to, "events": out, "pipeline": pipeline, "revenue": sum(x["net"] for x in out if x["status"] in ("confirmed", "completed")),
            "profit": sum(x["profit"] for x in out if x["status"] in ("confirmed", "completed"))}
