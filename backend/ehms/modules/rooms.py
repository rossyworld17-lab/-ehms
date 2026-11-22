"""Room types, rooms, room-status board and availability. (FR-PMS-001..007)"""
from __future__ import annotations

import datetime as dt

from ..db import get_db
from ..http import Ctx, audit, bad_request, conflict, not_found, route
from ..services import business_date, get_hotel, nights_between, parse_date, to_minor

ACTIVE_RES = ("tentative", "confirmed", "checked_in")
SELLABLE_SERVICE = ("in_service", "vip_hold")


# ------------------------------------------------------------------ availability helpers
def overlapping_room_reservations(c, room_id: int, arrival: str, departure: str, exclude_id: int | None = None) -> list[dict]:
    sql = (f"SELECT id, reference, arrival, departure, status FROM reservations WHERE room_id = ? AND status IN {ACTIVE_RES} "
           "AND arrival < ? AND departure > ?")
    params: list = [room_id, departure, arrival]
    if exclude_id:
        sql += " AND id <> ?"
        params.append(exclude_id)
    return c.all(sql, params)


def free_rooms(c, hotel_id: int, room_type_id: int | None, arrival: str, departure: str, exclude_id: int | None = None) -> list[dict]:
    sql = (f"SELECT r.*, rt.name AS room_type_name, rt.code AS room_type_code FROM rooms r JOIN room_types rt ON rt.id = r.room_type_id "
           f"WHERE r.hotel_id = ? AND r.active = 1 AND r.service_status IN {SELLABLE_SERVICE}")
    params: list = [hotel_id]
    if room_type_id:
        sql += " AND r.room_type_id = ?"
        params.append(room_type_id)
    rooms = c.all(sql + " ORDER BY r.number", params)
    ex = " AND id <> ?" if exclude_id else ""
    busy = {r["room_id"] for r in c.all(
        f"SELECT room_id FROM reservations WHERE hotel_id = ? AND room_id IS NOT NULL AND status IN {ACTIVE_RES} "
        f"AND arrival < ? AND departure > ?{ex}", [hotel_id, departure, arrival] + ([exclude_id] if exclude_id else []))}
    return [r for r in rooms if r["id"] not in busy]


def block_holds(c, hotel_id: int, arrival: dt.date, departure: dt.date, skip_block: int | None = None) -> dict:
    """Rooms still held by group blocks per (room_type_id, night): allotment minus rooms picked up into the block."""
    blocks = c.all("SELECT b.id, b.arrival, b.departure, br.room_type_id, br.rooms FROM group_blocks b JOIN group_block_rooms br ON br.block_id = b.id "
                   "WHERE b.hotel_id = ? AND b.status IN ('tentative','definite') AND b.arrival < ? AND b.departure > ?",
                   [hotel_id, departure.isoformat(), arrival.isoformat()])
    if not blocks:
        return {}
    picked = c.all(f"SELECT group_block_id, room_type_id, arrival, departure FROM reservations WHERE group_block_id IN ({','.join('?' * len({b['id'] for b in blocks}))}) "
                   f"AND status IN {ACTIVE_RES}", list({b["id"] for b in blocks}))
    held: dict = {}
    for b in blocks:
        if b["id"] == skip_block:
            continue
        for n in nights_between(max(arrival, dt.date.fromisoformat(b["arrival"])), min(departure, dt.date.fromisoformat(b["departure"]))):
            ns = n.isoformat()
            used = sum(1 for p in picked if p["group_block_id"] == b["id"] and p["room_type_id"] == b["room_type_id"] and p["arrival"] <= ns < p["departure"])
            key = (b["room_type_id"], ns)
            held[key] = held.get(key, 0) + max(0, b["rooms"] - used)
    return held


def type_availability(c, hotel_id: int, arrival: dt.date, departure: dt.date, exclude_id: int | None = None, for_block: int | None = None) -> list[dict]:
    """Rooms available per room type for every night in the range (minimum across nights). Rooms held by group
    blocks are not available to others; a booking into a block (for_block) may use that block's own allotment."""
    types = c.all("SELECT * FROM room_types WHERE hotel_id = ? AND active = 1 ORDER BY base_rate", [hotel_id])
    totals = {r["room_type_id"]: r["n"] for r in c.all(
        f"SELECT room_type_id, COUNT(*) AS n FROM rooms WHERE hotel_id = ? AND active = 1 AND service_status IN {SELLABLE_SERVICE} "
        "GROUP BY room_type_id", [hotel_id])}
    ex = " AND id <> ?" if exclude_id else ""
    res = c.all(f"SELECT room_type_id, arrival, departure FROM reservations WHERE hotel_id = ? AND status IN {ACTIVE_RES} "
                f"AND arrival < ? AND departure > ?{ex}", [hotel_id, departure.isoformat(), arrival.isoformat()] + ([exclude_id] if exclude_id else []))
    out = []
    nights = nights_between(arrival, departure)
    held = block_holds(c, hotel_id, arrival, departure, skip_block=for_block)
    for t in types:
        total = totals.get(t["id"], 0)
        worst = total
        for n in nights:
            ns = n.isoformat()
            booked = sum(1 for r in res if r["room_type_id"] == t["id"] and r["arrival"] <= ns < r["departure"])
            worst = min(worst, total - booked - held.get((t["id"], ns), 0))
        out.append({**t, "total_rooms": total, "available": max(worst, 0)})
    return out


def display_status(room: dict, arriving_today: bool) -> str:
    if room["service_status"] not in ("in_service", "vip_hold"):
        return room["service_status"]
    if room["occupancy"] == "occupied":
        return "occupied"
    if arriving_today:
        return "reserved"
    if room["service_status"] == "vip_hold":
        return "vip_hold"
    return {"dirty": "dirty", "in_progress": "cleaning", "clean": "clean", "inspected": "available"}[room["hk_status"]]


# ------------------------------------------------------------------ room types
ROOM_TYPE_FIELDS = ("name", "description", "max_occupancy", "beds", "bed_config", "size_sqm", "amenities", "image_url", "active")
MONEY_FIELDS = ("base_rate", "weekend_rate", "corporate_rate", "extra_person_charge")


@route("GET", "/api/hotels/{hotel_id:int}/room-types", perm="rooms.view", tag="rooms", summary="List room categories")
def list_room_types(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        rows = c.all("SELECT rt.*, (SELECT COUNT(*) FROM rooms r WHERE r.room_type_id = rt.id AND r.active = 1) AS room_count "
                     "FROM room_types rt WHERE rt.hotel_id = ? ORDER BY rt.base_rate", [hid])
    return {"items": rows}


@route("POST", "/api/hotels/{hotel_id:int}/room-types", perm="rooms.manage", tag="rooms", summary="Create a room category")
def create_room_type(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    data = {f: ctx.body.get(f) for f in ROOM_TYPE_FIELDS if f in ctx.body}
    for m in MONEY_FIELDS:
        if ctx.body.get(m) not in (None, ""):
            data[m] = to_minor(ctx.body[m], m)
    if "base_rate" not in data:
        raise bad_request("'base_rate' is required", {"field": "base_rate"})
    data["name"] = ctx.field("name", kind=str)
    code = ctx.field("code", kind=str).upper()
    with get_db().tx() as c:
        if c.one("SELECT id FROM room_types WHERE hotel_id = ? AND code = ?", [hid, code]):
            raise conflict("A room category with this code already exists")
        rid = c.insert("room_types", {"hotel_id": hid, "code": code, **data})
        audit(c, ctx, "room_type.created", "room_type", rid, code, new=data, hotel_id=hid)
    return {"id": rid, "_created": True}


@route("PATCH", "/api/room-types/{type_id:int}", perm="rooms.manage", tag="rooms", summary="Update a room category and its rates")
def update_room_type(ctx: Ctx):
    with get_db().tx() as c:
        t = c.one("SELECT * FROM room_types WHERE id = ?", [ctx.path["type_id"]])
        if not t:
            raise not_found("Room category")
        ctx.check_hotel(t["hotel_id"])
        data = {f: ctx.body[f] for f in ROOM_TYPE_FIELDS if f in (ctx.body or {})}
        for m in MONEY_FIELDS:
            if m in (ctx.body or {}):
                data[m] = None if ctx.body[m] in (None, "") and m != "base_rate" else to_minor(ctx.body[m], m)
        c.update("room_types", t["id"], data)
        audit(c, ctx, "room_type.updated", "room_type", t["id"], t["code"], old={k: t[k] for k in data}, new=data, hotel_id=t["hotel_id"])
    return {"ok": True}


# ------------------------------------------------------------------ rooms
@route("GET", "/api/hotels/{hotel_id:int}/rooms", perm="rooms.view", tag="rooms", summary="Room-status board")
def list_rooms(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        today = business_date(hotel).isoformat()
        rooms = c.all("SELECT r.*, rt.code AS room_type_code, rt.name AS room_type_name FROM rooms r "
                      "JOIN room_types rt ON rt.id = r.room_type_id WHERE r.hotel_id = ? AND r.active = 1 ORDER BY r.floor, r.number", [hid])
        arrivals = {r["room_id"]: r for r in c.all(
            "SELECT res.room_id, res.reference, g.first_name || ' ' || g.last_name AS guest_name FROM reservations res "
            "JOIN guests g ON g.id = res.guest_id WHERE res.hotel_id = ? AND res.arrival = ? AND res.status IN ('confirmed','tentative') "
            "AND res.room_id IS NOT NULL", [hid, today])}
        inhouse = {r["room_id"]: r for r in c.all(
            "SELECT res.room_id, res.reference, res.departure, g.first_name || ' ' || g.last_name AS guest_name FROM reservations res "
            "JOIN guests g ON g.id = res.guest_id WHERE res.hotel_id = ? AND res.status = 'checked_in'", [hid])}
    for r in rooms:
        r["display_status"] = display_status(r, r["id"] in arrivals)
        r["arrival"] = arrivals.get(r["id"])
        r["in_house"] = inhouse.get(r["id"])
        r["departing_today"] = bool(inhouse.get(r["id"]) and inhouse[r["id"]]["departure"] <= today)
    summary: dict[str, int] = {}
    for r in rooms:
        summary[r["display_status"]] = summary.get(r["display_status"], 0) + 1
    return {"items": rooms, "summary": summary, "business_date": today}


@route("POST", "/api/hotels/{hotel_id:int}/rooms", perm="rooms.manage", tag="rooms", summary="Create a room")
def create_room(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    number = ctx.field("number", kind=str)
    with get_db().tx() as c:
        rt = c.one("SELECT id FROM room_types WHERE id = ? AND hotel_id = ?", [ctx.field("room_type_id", kind=int), hid])
        if not rt:
            raise bad_request("room_type_id is not a category of this hotel")
        if c.one("SELECT id FROM rooms WHERE hotel_id = ? AND number = ?", [hid, number]):
            raise conflict(f"Room {number} already exists")
        rid = c.insert("rooms", {"hotel_id": hid, "room_type_id": rt["id"], "number": number,
                                 "name": ctx.field("name", required=False), "floor": ctx.field("floor", required=False),
                                 "wing": ctx.field("wing", required=False), "hk_status": "inspected"})
        audit(c, ctx, "room.created", "room", rid, number, hotel_id=hid)
    return {"id": rid, "_created": True}


@route("PATCH", "/api/rooms/{room_id:int}", perm="rooms.manage", tag="rooms", summary="Edit room details")
def update_room(ctx: Ctx):
    with get_db().tx() as c:
        r = c.one("SELECT * FROM rooms WHERE id = ?", [ctx.path["room_id"]])
        if not r:
            raise not_found("Room")
        ctx.check_hotel(r["hotel_id"])
        data = {f: ctx.body[f] for f in ("name", "floor", "wing", "room_type_id", "active") if f in (ctx.body or {})}
        if "room_type_id" in data and not c.one("SELECT id FROM room_types WHERE id = ? AND hotel_id = ?", [data["room_type_id"], r["hotel_id"]]):
            raise bad_request("Invalid room category")
        if data.get("active") in (0, False) and r["occupancy"] == "occupied":
            raise conflict("An occupied room cannot be deactivated")
        c.update("rooms", r["id"], data)
        audit(c, ctx, "room.updated", "room", r["id"], r["number"], old={k: r[k] for k in data}, new=data, hotel_id=r["hotel_id"])
    return {"ok": True}


@route("POST", "/api/rooms/{room_id:int}/housekeeping-status", perm="rooms.status.update", tag="rooms",
       summary="Set room housekeeping status (dirty / clean / inspected)")
def set_hk_status(ctx: Ctx):
    status = ctx.field("hk_status", kind=str)
    if status not in ("dirty", "clean", "in_progress", "inspected"):
        raise bad_request("hk_status must be dirty, in_progress, clean or inspected")
    if status == "inspected":
        ctx.require("housekeeping.inspect")
    with get_db().tx() as c:
        r = c.one("SELECT * FROM rooms WHERE id = ?", [ctx.path["room_id"]])
        if not r:
            raise not_found("Room")
        ctx.check_hotel(r["hotel_id"])
        if status == "inspected" and r["hk_status"] not in ("clean", "inspected"):
            raise conflict("A room must be cleaned before it can be marked inspected")
        c.update("rooms", r["id"], {"hk_status": status})
        audit(c, ctx, "room.hk_status", "room", r["id"], r["number"], old={"hk_status": r["hk_status"]}, new={"hk_status": status}, hotel_id=r["hotel_id"])
    return {"ok": True}


@route("POST", "/api/rooms/{room_id:int}/service-status", perm="rooms.block", tag="rooms",
       summary="Block a room / set out of order, out of service, maintenance, VIP hold, or return to service")
def set_service_status(ctx: Ctx):
    status = ctx.field("service_status", kind=str)
    if status not in ("in_service", "out_of_order", "out_of_service", "maintenance", "blocked", "vip_hold"):
        raise bad_request("Invalid service status")
    note = ctx.field("note", required=status != "in_service", kind=str)
    with get_db().tx() as c:
        r = c.one("SELECT * FROM rooms WHERE id = ?", [ctx.path["room_id"]])
        if not r:
            raise not_found("Room")
        hid = ctx.check_hotel(r["hotel_id"])
        if status not in SELLABLE_SERVICE:
            if r["occupancy"] == "occupied":
                raise conflict("Move the in-house guest before taking this room out of service")
            today = business_date(get_hotel(c, hid)).isoformat()
            future = c.all(f"SELECT reference FROM reservations WHERE room_id = ? AND status IN ('confirmed','tentative') AND departure > ?", [r["id"], today])
            if future:
                raise conflict("Reassign future reservations before blocking this room", {"reservations": [f["reference"] for f in future]})
        c.update("rooms", r["id"], {"service_status": status, "service_note": note})
        audit(c, ctx, "room.service_status", "room", r["id"], r["number"], old={"service_status": r["service_status"]},
              new={"service_status": status, "note": note}, hotel_id=hid)
    return {"ok": True}


@route("GET", "/api/hotels/{hotel_id:int}/availability", perm="reservations.view", tag="reservations",
       summary="Availability by room category for a date range")
def availability(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    a = parse_date(ctx.q("arrival"), "arrival")
    d = parse_date(ctx.q("departure"), "departure")
    if d <= a:
        raise bad_request("departure must be after arrival")
    if (d - a).days > 90:
        raise bad_request("Stays longer than 90 nights must be split")
    with get_db().tx() as c:
        types = type_availability(c, hid, a, d, int(ctx.q("exclude_reservation_id")) if ctx.q("exclude_reservation_id") else None)
        rooms = free_rooms(c, hid, int(ctx.q("room_type_id")) if ctx.q("room_type_id") else None, a.isoformat(), d.isoformat(),
                           int(ctx.q("exclude_reservation_id")) if ctx.q("exclude_reservation_id") else None)
    return {"arrival": a.isoformat(), "departure": d.isoformat(), "nights": (d - a).days, "room_types": types,
            "free_rooms": [{"id": r["id"], "number": r["number"], "room_type_id": r["room_type_id"], "room_type_code": r["room_type_code"],
                            "floor": r["floor"], "hk_status": r["hk_status"]} for r in rooms]}


@route("GET", "/api/hotels/{hotel_id:int}/calendar", perm="reservations.view", tag="reservations",
       summary="Room-by-day occupancy calendar")
def calendar(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    start = parse_date(ctx.q("start"), "start")
    days = min(int(ctx.q("days", 14)), 62)
    end = start + dt.timedelta(days=days)
    with get_db().tx() as c:
        rooms = c.all("SELECT r.id, r.number, r.floor, r.service_status, rt.code AS room_type_code FROM rooms r JOIN room_types rt "
                      "ON rt.id = r.room_type_id WHERE r.hotel_id = ? AND r.active = 1 ORDER BY r.number", [hid])
        res = c.all(f"SELECT res.id, res.reference, res.room_id, res.room_type_id, res.arrival, res.departure, res.status, "
                    "g.first_name || ' ' || g.last_name AS guest_name FROM reservations res JOIN guests g ON g.id = res.guest_id "
                    f"WHERE res.hotel_id = ? AND res.status IN {ACTIVE_RES} AND res.arrival < ? AND res.departure > ?",
                    [hid, end.isoformat(), start.isoformat()])
    return {"start": start.isoformat(), "days": days, "rooms": rooms, "reservations": res,
            "unassigned": [r for r in res if not r["room_id"]]}
