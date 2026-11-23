"""Restaurant table reservations (release 1.2): book a table for a date and time, prevent clashes on the same table,
seat the party (opens a POS order on that table), complete, cancel or mark no-show."""
from __future__ import annotations

import datetime as dt
import re

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, not_found, route
from ..services import get_hotel, hotel_today

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _minutes(t: str) -> int:
    return int(t[:2]) * 60 + int(t[3:5])


def _clash(c, table_id: int, day: str, start: str, duration: int, exclude: int | None = None) -> dict | None:
    s = _minutes(start)
    for b in c.all("SELECT * FROM table_reservations WHERE table_id = ? AND reserved_date = ? AND status IN ('booked','seated')"
                   + (" AND id <> ?" if exclude else ""), [table_id, day] + ([exclude] if exclude else [])):
        bs = _minutes(b["reserved_time"])
        if s < bs + b["duration_min"] and bs < s + duration:
            return b
    return None


@route("GET", "/api/hotels/{hotel_id:int}/table-reservations", perm="pos.view", tag="pos",
       summary="Table reservations for a date (?date, ?outlet_id)")
def list_bookings(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        day = ctx.q("date") or hotel_today(get_hotel(c, hid)).isoformat()
        sql = ("SELECT b.*, o.name AS outlet, t.code AS table_name, t.seats, r.reference FROM table_reservations b JOIN outlets o ON o.id = b.outlet_id "
               "LEFT JOIN pos_tables t ON t.id = b.table_id LEFT JOIN reservations r ON r.id = b.reservation_id WHERE b.hotel_id = ? AND b.reserved_date = ?")
        params: list = [hid, day]
        if ctx.q("outlet_id"):
            sql += " AND b.outlet_id = ?"
            params.append(int(ctx.q("outlet_id")))
        return {"date": day, "items": c.all(sql + " ORDER BY b.reserved_time, b.id", params)}


@route("POST", "/api/hotels/{hotel_id:int}/table-reservations", perm="pos.order", tag="pos",
       summary="Book a table: outlet_id, table_id (optional), guest_name, phone, party_size, reserved_date, reserved_time, duration_min, reservation_id (in-house guest), notes")
def create_booking(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    t = str(ctx.field("reserved_time", kind=str))
    if not TIME_RE.match(t):
        raise bad_request("reserved_time must be HH:MM")
    party = int(ctx.field("party_size", kind=int))
    if party <= 0 or party > 200:
        raise bad_request("party_size must be 1–200")
    duration = int(ctx.field("duration_min", required=False, default=90) or 90)
    if duration < 15 or duration > 600:
        raise bad_request("duration_min must be 15–600")
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        try:
            day = dt.date.fromisoformat(str(ctx.field("reserved_date", kind=str)))
        except ValueError:
            raise bad_request("reserved_date must be YYYY-MM-DD")
        if day < hotel_today(hotel):
            raise bad_request("The booking date is in the past")
        outlet = c.one("SELECT * FROM outlets WHERE id = ? AND hotel_id = ? AND active = 1", [ctx.field("outlet_id", kind=int), hid])
        if not outlet:
            raise bad_request("Choose an active outlet of this hotel")
        table_id = ctx.field("table_id", required=False)
        if table_id:
            table = c.one("SELECT * FROM pos_tables WHERE id = ? AND outlet_id = ? AND active = 1", [int(table_id), outlet["id"]])
            if not table:
                raise bad_request("The table does not belong to this outlet")
            if table.get("seats") and party > table["seats"]:
                raise bad_request(f"{table['code']} seats {table['seats']}; choose a larger table")
            other = _clash(c, table["id"], day.isoformat(), t, duration)
            if other:
                raise conflict(f"Table {table['code']} is already booked at {other['reserved_time']} for {other['guest_name']}")
        res_id = ctx.field("reservation_id", required=False)
        if res_id:
            r = c.one("SELECT * FROM reservations WHERE id = ? AND hotel_id = ?", [int(res_id), hid])
            if not r:
                raise bad_request("Unknown reservation")
        bid = c.insert("table_reservations", {"hotel_id": hid, "outlet_id": outlet["id"], "table_id": int(table_id) if table_id else None,
                                              "guest_name": str(ctx.field("guest_name", kind=str))[:150], "phone": ctx.field("phone", required=False, kind=str),
                                              "party_size": party, "reserved_date": day.isoformat(), "reserved_time": t, "duration_min": duration,
                                              "reservation_id": int(res_id) if res_id else None, "status": "booked",
                                              "notes": (ctx.field("notes", required=False, kind=str) or "")[:300] or None,
                                              "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "pos.table_booked", "table_reservation", bid, new=ctx.body, hotel_id=hid)
    return {"id": bid, "_created": True}


@route("POST", "/api/table-reservations/{booking_id:int}/status", perm="pos.order", tag="pos",
       summary="Change a table booking: status seated | completed | cancelled | no_show; table_id when seating an unassigned booking")
def booking_status(ctx: Ctx):
    status = ctx.field("status", kind=str)
    allowed = {"booked": ("seated", "cancelled", "no_show"), "seated": ("completed",)}
    with get_db().tx() as c:
        b = c.one("SELECT * FROM table_reservations WHERE id = ?", [ctx.path["booking_id"]])
        if not b:
            raise not_found("Table booking")
        ctx.check_hotel(b["hotel_id"])
        if status not in allowed.get(b["status"], ()):
            raise conflict(f"A {b['status']} booking cannot become {status}")
        change = {"status": status}
        if status == "seated" and not b["table_id"]:
            tid = ctx.field("table_id", kind=int)
            if not c.one("SELECT id FROM pos_tables WHERE id = ? AND outlet_id = ? AND active = 1", [tid, b["outlet_id"]]):
                raise bad_request("The table does not belong to this outlet")
            other = _clash(c, tid, b["reserved_date"], b["reserved_time"], b["duration_min"], exclude=b["id"])
            if other:
                raise conflict(f"That table is booked at {other['reserved_time']} for {other['guest_name']}")
            change["table_id"] = tid
        c.update("table_reservations", b["id"], change)
        audit(c, ctx, f"pos.table_{status}", "table_reservation", b["id"], old={"status": b["status"]}, new=change, hotel_id=b["hotel_id"])
    return {"status": status}
