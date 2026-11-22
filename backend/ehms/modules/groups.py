"""Group blocks and rooming lists (FR-RES-007).

A block holds an allotment of rooms per category for a date range at an agreed group rate. Held rooms are not
available to other bookings until they are picked up (a reservation made into the block) or released — by staff,
or automatically by the worker after the cut-off date. A rooming list (pasted or uploaded as CSV) creates the
individual reservations. Room nights can be billed to a group master folio instead of each guest's folio."""
from __future__ import annotations

import csv
import datetime as dt
import io

from starlette.responses import Response

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import business_date, get_hotel, next_number, nights_between, parse_date, to_minor

STATUSES = ("tentative", "definite", "released", "cancelled", "completed")
BILLING = ("individual", "master_room", "master_all")


def _load(c, ctx: Ctx, bid) -> dict:
    b = c.one("SELECT * FROM group_blocks WHERE id = ?", [int(bid)])
    if not b:
        raise not_found("Group block")
    ctx.check_hotel(b["hotel_id"])
    return b


def block_rate_for(c, ctx: Ctx, hid: int, bid: int, rt: dict, arrival: dt.date, departure: dt.date) -> tuple[dict, int]:
    b = c.one("SELECT * FROM group_blocks WHERE id = ? AND hotel_id = ?", [bid, hid])
    if not b:
        raise bad_request("Group block not found", {"field": "group_block_id"})
    if b["status"] not in ("tentative", "definite"):
        raise conflict(f"Group {b['code']} is {b['status']}; no more rooms can be added")
    if arrival.isoformat() < str(b["arrival"])[:10] or departure.isoformat() > str(b["departure"])[:10]:
        raise bad_request(f"Dates must fall within the group's stay ({b['arrival']} – {b['departure']})")
    row = c.one("SELECT * FROM group_block_rooms WHERE block_id = ? AND room_type_id = ?", [bid, rt["id"]])
    if not row:
        raise bad_request(f"Group {b['code']} has no {rt['name']} rooms in its block")
    return b, row["rate"]


def pickup(c, b: dict) -> list[dict]:
    rows = c.all("SELECT br.*, rt.name AS room_type, rt.code AS room_type_code FROM group_block_rooms br JOIN room_types rt ON rt.id = br.room_type_id "
                 "WHERE br.block_id = ? ORDER BY rt.base_rate", [b["id"]])
    res = c.all("SELECT room_type_id, arrival, departure FROM reservations WHERE group_block_id = ? AND status IN ('tentative','confirmed','checked_in','checked_out')", [b["id"]])
    nights = nights_between(dt.date.fromisoformat(str(b["arrival"])[:10]), dt.date.fromisoformat(str(b["departure"])[:10]))
    for r in rows:
        per = [sum(1 for x in res if x["room_type_id"] == r["room_type_id"] and x["arrival"] <= n.isoformat() < x["departure"]) for n in nights]
        r["picked_up_max"] = max(per) if per else 0
        r["room_nights_held"] = r["rooms"] * len(nights)
        r["room_nights_picked"] = sum(per)
        r["remaining"] = max(0, r["rooms"] - r["picked_up_max"])
    return rows


def _detail(c, b: dict) -> dict:
    from .frontoffice import folio_balance
    out = dict(b)
    out["rooms"] = pickup(c, b)
    held = sum(r["room_nights_held"] for r in out["rooms"])
    picked = sum(r["room_nights_picked"] for r in out["rooms"])
    out["pickup_pct"] = round(picked * 100 / held, 1) if held else 0
    out["reservations"] = c.all("SELECT r.id, r.reference, r.status, r.arrival, r.departure, r.adults, r.children, r.special_requests, rt.name AS room_type, "
                                "rm.number AS room_number, g.first_name, g.last_name, g.email, g.phone FROM reservations r JOIN guests g ON g.id = r.guest_id "
                                "JOIN room_types rt ON rt.id = r.room_type_id LEFT JOIN rooms rm ON rm.id = r.room_id WHERE r.group_block_id = ? ORDER BY g.last_name, g.first_name",
                                [b["id"]])
    out["account"] = c.one("SELECT id, code, name FROM corporate_accounts WHERE id = ?", [b["corporate_account_id"]]) if b["corporate_account_id"] else None
    out["contact"] = c.one("SELECT id, first_name, last_name, email, phone FROM guests WHERE id = ?", [b["contact_guest_id"]]) if b["contact_guest_id"] else None
    if b["master_folio_id"]:
        f = c.one("SELECT id, number, status FROM folios WHERE id = ?", [b["master_folio_id"]])
        out["master_folio"] = {**f, "balance": folio_balance(c, f["id"])["balance"]}
    else:
        out["master_folio"] = None
    return out


@route("GET", "/api/hotels/{hotel_id:int}/groups", perm="reservations.view", tag="groups", summary="Group blocks with pickup (?status)")
def list_groups(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        sql = "SELECT * FROM group_blocks WHERE hotel_id = ?"
        params: list = [hid]
        if ctx.q("status"):
            sql += " AND status = ?"
            params.append(ctx.q("status"))
        blocks = c.all(sql + " ORDER BY arrival DESC LIMIT 200", params)
        out = []
        for b in blocks:
            rows = pickup(c, b)
            held = sum(r["room_nights_held"] for r in rows)
            picked = sum(r["room_nights_picked"] for r in rows)
            out.append({**b, "rooms_blocked": sum(r["rooms"] for r in rows), "rooms_picked": sum(r["picked_up_max"] for r in rows),
                        "pickup_pct": round(picked * 100 / held, 1) if held else 0})
    return {"items": out}


@route("POST", "/api/hotels/{hotel_id:int}/groups", perm="reservations.groups", tag="groups",
       summary="Create a group block (name, arrival, departure, cutoff_date, rooms[{room_type_id, rooms, rate}], corporate_account_id, contact guest, billing)")
def create_group(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    a = parse_date(ctx.field("arrival", kind=str), "arrival")
    d = parse_date(ctx.field("departure", kind=str), "departure")
    cut = parse_date(ctx.field("cutoff_date", kind=str), "cutoff_date")
    if d <= a:
        raise bad_request("Departure must be after arrival")
    if cut > a:
        raise bad_request("The cut-off date must be on or before arrival")
    billing = ctx.field("billing", required=False, kind=str) or "individual"
    if billing not in BILLING:
        raise bad_request(f"billing must be one of {', '.join(BILLING)}")
    rooms = ctx.field("rooms")
    if not isinstance(rooms, list) or not rooms:
        raise bad_request("Add at least one room category to the block")
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        if a < business_date(hotel):
            raise bad_request("A block cannot start in the past")
        acct = ctx.field("corporate_account_id", required=False)
        if acct and not c.one("SELECT id FROM corporate_accounts WHERE id = ? AND organisation_id = ? AND status = 'active'", [int(acct), ctx.org_id]):
            raise bad_request("Account not found or not active")
        contact = ctx.field("contact_guest_id", required=False)
        if contact and not c.one("SELECT id FROM guests WHERE id = ? AND organisation_id = ?", [int(contact), ctx.org_id]):
            raise bad_request("Contact guest not found")
        from .rooms import type_availability
        avail = {t["id"]: t for t in type_availability(c, hid, a, d)}
        code = (ctx.field("code", required=False, kind=str) or next_number(c, hid, "group_block", "GRP", 4)).upper()[:30]
        bid = c.insert("group_blocks", {"hotel_id": hid, "code": code, "name": ctx.field("name", kind=str)[:200], "corporate_account_id": int(acct) if acct else None,
                                        "contact_guest_id": int(contact) if contact else None, "arrival": a.isoformat(), "departure": d.isoformat(),
                                        "cutoff_date": cut.isoformat(), "status": ctx.field("status", required=False, kind=str) or "tentative", "billing": billing,
                                        "notes": ctx.field("notes", required=False, kind=str), "created_by": ctx.user_id, "created_at": now_iso()})
        warnings = []
        for r in rooms:
            rt_id, n = int(r.get("room_type_id") or 0), int(r.get("rooms") or 0)
            if rt_id not in avail:
                raise bad_request("Unknown room category in the block")
            if n <= 0:
                raise bad_request("Each category needs at least one room")
            if n > avail[rt_id]["available"]:
                if not ctx.can("reservations.overbook"):
                    raise conflict(f"Only {avail[rt_id]['available']} {avail[rt_id]['name']} room(s) are free for every night of the block")
                warnings.append(f"{avail[rt_id]['name']}: block exceeds free rooms")
            rate = to_minor(r.get("rate") if r.get("rate") not in (None, "") else avail[rt_id]["base_rate"], "rate")
            c.insert("group_block_rooms", {"block_id": bid, "room_type_id": rt_id, "rooms": n, "rate": rate})
        audit(c, ctx, "group.created", "group_block", bid, code, new={"rooms": rooms, "arrival": a.isoformat(), "departure": d.isoformat()}, hotel_id=hid)
        out = _detail(c, c.one("SELECT * FROM group_blocks WHERE id = ?", [bid]))
    out["warnings"] = warnings
    out["_created"] = True
    return out


@route("GET", "/api/groups/{block_id:int}", perm="reservations.view", tag="groups", summary="Group block with allotment, pickup, rooming list and master folio")
def get_group(ctx: Ctx):
    with get_db().tx() as c:
        return _detail(c, _load(c, ctx, ctx.path["block_id"]))


@route("PATCH", "/api/groups/{block_id:int}", perm="reservations.groups", tag="groups",
       summary="Change status, cut-off date, billing, notes or allotment (rooms[{room_type_id, rooms}] — never below rooms picked up)")
def update_group(ctx: Ctx):
    body = ctx.body or {}
    with get_db().tx() as c:
        b = _load(c, ctx, ctx.path["block_id"])
        if b["status"] in ("cancelled", "completed"):
            raise conflict(f"This group is {b['status']}")
        ch = {}
        if "status" in body:
            if body["status"] not in STATUSES:
                raise bad_request(f"status must be one of {', '.join(STATUSES)}")
            if body["status"] == "cancelled" and c.one("SELECT id FROM reservations WHERE group_block_id = ? AND status IN ('confirmed','tentative','checked_in')", [b["id"]]):
                raise conflict("Cancel or move the group's reservations first")
            ch["status"] = body["status"]
        if "cutoff_date" in body:
            cut = parse_date(body["cutoff_date"], "cutoff_date")
            if cut.isoformat() > str(b["arrival"])[:10]:
                raise bad_request("The cut-off date must be on or before arrival")
            ch["cutoff_date"] = cut.isoformat()
        if "billing" in body:
            if body["billing"] not in BILLING:
                raise bad_request("Invalid billing option")
            ch["billing"] = body["billing"]
        if "notes" in body:
            ch["notes"] = body["notes"]
        if isinstance(body.get("rooms"), list):
            current = {r["room_type_id"]: r for r in pickup(c, b)}
            for r in body["rooms"]:
                rt_id, n = int(r["room_type_id"]), int(r["rooms"])
                if rt_id in current:
                    if n < current[rt_id]["picked_up_max"]:
                        raise conflict(f"{current[rt_id]['room_type']}: {current[rt_id]['picked_up_max']} room(s) are already picked up")
                    c.execute("UPDATE group_block_rooms SET rooms = ? WHERE block_id = ? AND room_type_id = ?", [n, b["id"], rt_id])
                else:
                    rt = c.one("SELECT * FROM room_types WHERE id = ? AND hotel_id = ?", [rt_id, b["hotel_id"]])
                    if not rt:
                        raise bad_request("Unknown room category")
                    c.insert("group_block_rooms", {"block_id": b["id"], "room_type_id": rt_id, "rooms": n, "rate": to_minor(r.get("rate") or rt["base_rate"], "rate")})
        if ch:
            c.update("group_blocks", b["id"], ch)
        audit(c, ctx, "group.updated", "group_block", b["id"], b["code"], old={k: b[k] for k in ch}, new={**ch, "rooms": body.get("rooms")}, hotel_id=b["hotel_id"])
        return _detail(c, c.one("SELECT * FROM group_blocks WHERE id = ?", [b["id"]]))


def release_unpicked(c, b: dict, user_id: int | None = None) -> int:
    """Reduce each category to the rooms picked up; returns the number of rooms released."""
    freed = 0
    for r in pickup(c, b):
        if r["rooms"] > r["picked_up_max"]:
            freed += r["rooms"] - r["picked_up_max"]
            c.execute("UPDATE group_block_rooms SET rooms = ? WHERE id = ?", [r["picked_up_max"], r["id"]])
    picked_any = c.one("SELECT id FROM reservations WHERE group_block_id = ? AND status IN ('confirmed','tentative','checked_in','checked_out')", [b["id"]])
    c.update("group_blocks", b["id"], {"released_at": now_iso(), **({} if picked_any else {"status": "released"})})
    return freed


@route("POST", "/api/groups/{block_id:int}/release", perm="reservations.groups", tag="groups", summary="Release rooms not yet picked up back to general sale")
def release(ctx: Ctx):
    with get_db().tx() as c:
        b = _load(c, ctx, ctx.path["block_id"])
        if b["status"] not in ("tentative", "definite"):
            raise conflict(f"This group is {b['status']}")
        freed = release_unpicked(c, b, ctx.user_id)
        audit(c, ctx, "group.released", "group_block", b["id"], b["code"], new={"rooms_released": freed}, hotel_id=b["hotel_id"])
    return {"rooms_released": freed}


def release_after_cutoff(c, hotel: dict) -> int:
    """Worker job: release unpicked rooms of blocks whose cut-off date has passed."""
    today = business_date(hotel).isoformat()
    n = 0
    for b in c.all("SELECT * FROM group_blocks WHERE hotel_id = ? AND status IN ('tentative','definite') AND cutoff_date < ? AND released_at IS NULL", [hotel["id"], today]):
        freed = release_unpicked(c, b)
        from ..http import audit as _audit
        _audit(c, None, "group.auto_released", "group_block", b["id"], b["code"], new={"rooms_released": freed, "cutoff": str(b["cutoff_date"])}, hotel_id=hotel["id"])
        n += 1
    return n


@route("POST", "/api/groups/{block_id:int}/rooming-list", perm="reservations.groups", tag="groups",
       summary="Create reservations from a rooming list: rows[{first_name, last_name, email, phone, room_type (code) or room_type_id, arrival, departure, adults, children, special_requests}] or csv text")
def rooming_list(ctx: Ctx):
    rows = ctx.field("rows", required=False)
    text = ctx.field("csv", required=False, kind=str)
    if text and not rows:
        rows = [{k.strip().lower().replace(" ", "_"): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(io.StringIO(text))]
    if not isinstance(rows, list) or not rows:
        raise bad_request("Provide rows or CSV text with a header line")
    if len(rows) > 300:
        raise bad_request("At most 300 guests per upload")
    with get_db().tx() as c:
        b = _load(c, ctx, ctx.path["block_id"])
        if b["status"] not in ("tentative", "definite"):
            raise conflict(f"Group {b['code']} is {b['status']}")
        types = {t["code"].upper(): t["id"] for t in c.all("SELECT id, code FROM room_types WHERE hotel_id = ?", [b["hotel_id"]])}
        block_types = {r["room_type_id"] for r in c.all("SELECT room_type_id FROM group_block_rooms WHERE block_id = ?", [b["id"]])}
    from .reservations import create_reservation
    results = []
    for i, row in enumerate(rows, 1):
        rt_id = row.get("room_type_id") or types.get(str(row.get("room_type") or "").upper())
        if not rt_id and len(block_types) == 1:
            rt_id = next(iter(block_types))
        if not row.get("first_name") or not row.get("last_name"):
            results.append({"row": i, "ok": False, "error": "first_name and last_name are required"})
            continue
        if not rt_id:
            results.append({"row": i, "ok": False, "error": "room_type is missing or unknown"})
            continue
        # creating the guests' profiles is part of loading a rooming list, which reservations.groups authorises
        sub = Ctx(request=ctx.request, user=ctx.user, permissions=set(ctx.permissions) | {"guests.manage"}, hotel_ids=ctx.hotel_ids, path={"hotel_id": b["hotel_id"]}, body={
            "arrival": row.get("arrival") or str(b["arrival"])[:10], "departure": row.get("departure") or str(b["departure"])[:10],
            "room_type_id": int(rt_id), "group_block_id": b["id"], "group_name": b["name"], "status": "confirmed" if b["status"] == "definite" else "tentative",
            "booking_type": "group", "source": "group", "adults": int(row.get("adults") or 1), "children": int(row.get("children") or 0),
            "special_requests": row.get("special_requests") or None,
            "guest": {"first_name": row["first_name"], "last_name": row["last_name"], "email": row.get("email") or None, "phone": row.get("phone") or None, "force": True}})
        try:
            r = create_reservation(sub)
            results.append({"row": i, "ok": True, "reference": r["reference"], "guest": f"{row['first_name']} {row['last_name']}"})
        except Exception as e:  # each row is independent; report and continue
            results.append({"row": i, "ok": False, "error": getattr(e, "message", str(e))})
    with get_db().tx() as c:
        audit(c, ctx, "group.rooming_list", "group_block", b["id"], b["code"], new={"rows": len(rows), "created": sum(1 for r in results if r["ok"])}, hotel_id=b["hotel_id"])
    return {"created": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"]), "results": results}


@route("GET", "/api/groups/{block_id:int}/rooming-list.csv", perm="reservations.view", tag="groups", summary="Rooming list as CSV")
def rooming_csv(ctx: Ctx):
    with get_db().tx() as c:
        d = _detail(c, _load(c, ctx, ctx.path["block_id"]))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Reference", "Last name", "First name", "Room type", "Room", "Arrival", "Departure", "Adults", "Children", "Status", "Requests"])
    for r in d["reservations"]:
        w.writerow([r["reference"], r["last_name"], r["first_name"], r["room_type"], r["room_number"] or "", r["arrival"], r["departure"], r["adults"], r["children"],
                    r["status"], r["special_requests"] or ""])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="rooming-list-{d["code"]}.csv"'})


@route("POST", "/api/groups/{block_id:int}/master-folio", perm="reservations.groups", tag="groups",
       summary="Open the group master folio (room nights are billed to it when billing is master_room or master_all)")
def master_folio(ctx: Ctx):
    with get_db().tx() as c:
        b = _load(c, ctx, ctx.path["block_id"])
        if b["master_folio_id"]:
            raise conflict("This group already has a master folio")
        guest = b["contact_guest_id"] or c.scalar("SELECT guest_id FROM reservations WHERE group_block_id = ? ORDER BY id LIMIT 1", [b["id"]])
        if not guest:
            raise conflict("Set a contact guest or add a reservation first (the master folio needs a billing contact)")
        number = next_number(c, b["hotel_id"], "folio", "FOL")
        fid = c.insert("folios", {"hotel_id": b["hotel_id"], "number": number, "guest_id": guest, "group_block_id": b["id"], "window_name": f"Group master — {b['name']}"[:80],
                                  "corporate_account_id": b["corporate_account_id"], "status": "open", "opened_at": now_iso()})
        c.update("group_blocks", b["id"], {"master_folio_id": fid})
        audit(c, ctx, "group.master_folio", "group_block", b["id"], b["code"], new={"folio": number}, hotel_id=b["hotel_id"])
    return {"id": fid, "number": number, "_created": True}


def room_night_folio(c, r: dict, default: dict) -> dict:
    """Folio that receives a room night: the group master folio when the group is billed that way."""
    if not r.get("group_block_id"):
        return default
    b = c.one("SELECT billing, master_folio_id FROM group_blocks WHERE id = ?", [r["group_block_id"]])
    if b and b["billing"] in ("master_room", "master_all") and b["master_folio_id"]:
        f = c.one("SELECT * FROM folios WHERE id = ?", [b["master_folio_id"]])
        if f and f["status"] == "open":
            return f
    return default
