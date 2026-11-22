"""Laundry: guest laundry orders (billed to the guest folio on delivery) and internal linen batches for hotel
departments, with item registration, processing stages, quality check, lost/damaged records and pricing.
(FR-HSK-004/005, master prompt section 11)"""
from __future__ import annotations

import datetime as dt

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, not_found, route
from ..services import business_date, get_hotel, hotel_setting, next_number, set_hotel_setting, to_minor

SERVICES = ("wash_iron", "dry_clean", "iron_only", "wash_only")
FLOW = ["received", "washing", "drying", "ironing", "quality_check", "ready", "delivered"]
DEPARTMENTS = ("housekeeping", "fnb", "kitchen", "spa", "front_office", "security", "other")


def _surcharge_bp(c, hid: int) -> int:
    return int(hotel_setting(c, hid, "laundry.express_surcharge_bp", "5000"))


@route("GET", "/api/hotels/{hotel_id:int}/laundry/prices", perm="laundry.view", tag="laundry", summary="Laundry price list and express surcharge")
def prices(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": c.all("SELECT * FROM laundry_prices WHERE hotel_id = ? ORDER BY item, service", [hid]), "services": SERVICES,
                "express_surcharge_bp": _surcharge_bp(c, hid), "departments": DEPARTMENTS}


@route("POST", "/api/hotels/{hotel_id:int}/laundry/prices", perm="laundry.manage", tag="laundry", summary="Add or update a price (item, service, price)")
def set_price(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    svc = ctx.field("service", kind=str)
    if svc not in SERVICES:
        raise bad_request(f"service must be one of {', '.join(SERVICES)}")
    item = ctx.field("item", kind=str)
    price = to_minor(ctx.field("price"), "price")
    active = 1 if ctx.field("active", required=False, default=True) else 0
    with get_db().tx() as c:
        row = c.one("SELECT * FROM laundry_prices WHERE hotel_id = ? AND lower(item) = ? AND service = ?", [hid, item.lower(), svc])
        if row:
            c.update("laundry_prices", row["id"], {"price": price, "active": active})
            pid = row["id"]
        else:
            pid = c.insert("laundry_prices", {"hotel_id": hid, "item": item, "service": svc, "price": price, "active": active})
        if "express_surcharge_bp" in (ctx.body or {}):
            set_hotel_setting(c, hid, "laundry.express_surcharge_bp", str(int(ctx.body["express_surcharge_bp"])))
        audit(c, ctx, "laundry.price_set", "laundry_price", pid, item, old=row, new={"service": svc, "price": price, "active": active}, hotel_id=hid)
    return {"id": pid, "_created": True}


def _order(c, ctx: Ctx, oid) -> dict:
    o = c.lock("laundry_orders", int(oid))
    if not o:
        raise not_found("Laundry order")
    ctx.check_hotel(o["hotel_id"])
    return o


def _detail(c, o: dict) -> dict:
    o = dict(o)
    o["items"] = c.all("SELECT * FROM laundry_order_items WHERE order_id = ? ORDER BY id", [o["id"]])
    if o["reservation_id"]:
        o["reservation"] = c.one("SELECT r.id, r.reference, r.status, rm.number AS room_number, g.first_name || ' ' || g.last_name AS guest FROM reservations r "
                                 "JOIN guests g ON g.id = r.guest_id LEFT JOIN rooms rm ON rm.id = r.room_id WHERE r.id = ?", [o["reservation_id"]])
    return o


def _total(c, o: dict) -> int:
    base = c.scalar("SELECT COALESCE(SUM(quantity * unit_price),0) FROM laundry_order_items WHERE order_id = ? AND outcome = 'ok'", [o["id"]]) or 0
    return base + (base * _surcharge_bp(c, o["hotel_id"]) // 10000 if o["express"] else 0)


@route("GET", "/api/hotels/{hotel_id:int}/laundry/orders", perm="laundry.view", tag="laundry",
       summary="Laundry orders (?status, ?kind, ?open=1 for everything not yet delivered)")
def list_orders(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT o.*, rm.number AS room_number, g.first_name || ' ' || g.last_name AS guest, "
           "(SELECT COALESCE(SUM(quantity),0) FROM laundry_order_items WHERE order_id = o.id) AS pieces, "
           "(SELECT COUNT(*) FROM laundry_order_items WHERE order_id = o.id AND outcome <> 'ok') AS issues "
           "FROM laundry_orders o LEFT JOIN reservations r ON r.id = o.reservation_id LEFT JOIN rooms rm ON rm.id = r.room_id "
           "LEFT JOIN guests g ON g.id = r.guest_id WHERE o.hotel_id = ?")
    params: list = [hid]
    if ctx.q("open") == "1":
        sql += " AND o.status NOT IN ('delivered','cancelled')"
    for k in ("status", "kind"):
        if ctx.q(k):
            sql += f" AND o.{k} = ?"
            params.append(ctx.q(k))
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY o.id DESC LIMIT 300", params)
        counts = {r["status"]: r["n"] for r in c.all("SELECT status, COUNT(*) AS n FROM laundry_orders WHERE hotel_id = ? AND status NOT IN ('delivered','cancelled') "
                                                     "GROUP BY status", [hid])}
    return {"items": rows, "counts": counts, "flow": FLOW}


@route("POST", "/api/hotels/{hotel_id:int}/laundry/orders", perm="laundry.manage", tag="laundry",
       summary="Register a laundry order: guest (reservation_id) or internal (department); items[{price_id | description+service, quantity, condition_note}]")
def create_order(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    kind = ctx.field("kind", kind=str)
    if kind not in ("guest", "internal"):
        raise bad_request("kind must be guest or internal")
    items = ctx.field("items")
    if not isinstance(items, list) or not items:
        raise bad_request("Add at least one item")
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        res_id = dept = None
        if kind == "guest":
            r = c.one("SELECT * FROM reservations WHERE id = ? AND hotel_id = ?", [ctx.field("reservation_id", kind=int), hid])
            if not r or r["status"] != "checked_in":
                raise conflict("Guest laundry can only be taken for a checked-in guest")
            res_id = r["id"]
        else:
            dept = ctx.field("department", kind=str)
            if dept not in DEPARTMENTS:
                raise bad_request(f"department must be one of {', '.join(DEPARTMENTS)}")
        number = next_number(c, hid, "laundry", "LDY")
        due = ctx.field("due_at", required=False, kind=str)
        oid = c.insert("laundry_orders", {"hotel_id": hid, "number": number, "kind": kind, "reservation_id": res_id, "department": dept, "status": "received",
                                          "express": 1 if ctx.field("express", required=False, default=False) else 0, "notes": ctx.field("notes", required=False, kind=str),
                                          "due_at": due, "received_by": ctx.user_id, "created_at": now_iso(), "business_date": business_date(hotel).isoformat()})
        for it in items:
            qty = int(it.get("quantity") or 0)
            if qty <= 0:
                raise bad_request("Each item needs a quantity")
            price = None
            if it.get("price_id"):
                price = c.one("SELECT * FROM laundry_prices WHERE id = ? AND hotel_id = ? AND active = 1", [int(it["price_id"]), hid])
                if not price:
                    raise bad_request("Price list item not found")
            desc = price["item"] if price else str(it.get("description") or "").strip()
            svc = price["service"] if price else it.get("service", "wash_iron")
            if not desc or svc not in SERVICES:
                raise bad_request("Each item needs a price-list entry or a description and service")
            unit = price["price"] if price and kind == "guest" else (to_minor(it.get("unit_price", 0)) if kind == "guest" else 0)
            c.insert("laundry_order_items", {"order_id": oid, "price_id": price["id"] if price else None, "description": desc[:120], "service": svc,
                                             "quantity": qty, "unit_price": unit, "condition_note": (it.get("condition_note") or "")[:200] or None})
        o = c.one("SELECT * FROM laundry_orders WHERE id = ?", [oid])
        c.update("laundry_orders", oid, {"total": _total(c, o)})
        audit(c, ctx, "laundry.order_received", "laundry_order", oid, number, new=ctx.body, hotel_id=hid)
        return {**_detail(c, c.one("SELECT * FROM laundry_orders WHERE id = ?", [oid])), "_created": True}


@route("GET", "/api/laundry/orders/{order_id:int}", perm="laundry.view", tag="laundry", summary="Laundry order with items")
def get_order(ctx: Ctx):
    with get_db().tx() as c:
        o = c.one("SELECT * FROM laundry_orders WHERE id = ?", [ctx.path["order_id"]])
        if not o:
            raise not_found("Laundry order")
        ctx.check_hotel(o["hotel_id"])
        return _detail(c, o)


@route("POST", "/api/laundry/items/{item_id:int}/outcome", perm="laundry.manage", tag="laundry",
       summary="Record an item as ok, damaged or lost (note required); damaged/lost items are not charged")
def item_outcome(ctx: Ctx):
    outcome = ctx.field("outcome", kind=str)
    if outcome not in ("ok", "damaged", "lost"):
        raise bad_request("outcome must be ok, damaged or lost")
    note = ctx.field("note", required=outcome != "ok", kind=str)
    with get_db().tx() as c:
        it = c.one("SELECT * FROM laundry_order_items WHERE id = ?", [ctx.path["item_id"]])
        if not it:
            raise not_found("Item")
        o = _order(c, ctx, it["order_id"])
        if o["status"] in ("delivered", "cancelled"):
            raise conflict(f"This order is already {o['status']}")
        c.update("laundry_order_items", it["id"], {"outcome": outcome, "outcome_note": note})
        c.update("laundry_orders", o["id"], {"total": _total(c, o)})
        audit(c, ctx, f"laundry.item_{outcome}", "laundry_order_item", it["id"], o["number"], new={"note": note, "item": it["description"]}, hotel_id=o["hotel_id"])
        return _detail(c, c.one("SELECT * FROM laundry_orders WHERE id = ?", [o["id"]]))


@route("POST", "/api/laundry/orders/{order_id:int}/status", perm="laundry.manage", tag="laundry",
       summary="Advance an order (washing → drying → ironing → quality_check → ready → delivered) or cancel it; delivery bills guest orders")
def set_status(ctx: Ctx):
    status = ctx.field("status", kind=str)
    with get_db().tx() as c:
        o = _order(c, ctx, ctx.path["order_id"])
        if o["status"] in ("delivered", "cancelled"):
            raise conflict(f"This order is already {o['status']}")
        if status == "cancelled":
            if o["status"] != "received":
                raise conflict("Only orders not yet in process can be cancelled")
            reason = ctx.field("reason", kind=str)
            c.update("laundry_orders", o["id"], {"status": "cancelled", "notes": f"{o['notes'] or ''} Cancelled: {reason}".strip()[:300]})
            audit(c, ctx, "laundry.cancelled", "laundry_order", o["id"], o["number"], new={"reason": reason}, hotel_id=o["hotel_id"])
            return _detail(c, c.one("SELECT * FROM laundry_orders WHERE id = ?", [o["id"]]))
        if status not in FLOW or FLOW.index(status) <= FLOW.index(o["status"]):
            raise bad_request(f"Choose a later stage than {o['status'].replace('_', ' ')}")
        if status == "delivered" and o["status"] not in ("ready", "quality_check"):
            raise conflict("Orders must pass quality check before delivery")
        data = {"status": status}
        if status == "delivered":
            data.update({"delivered_by": ctx.user_id, "delivered_at": now_iso()})
            total = _total(c, o)
            data["total"] = total
            if o["kind"] == "guest" and total > 0:
                from .frontoffice import ensure_folio, post_charge
                r = c.one("SELECT * FROM reservations WHERE id = ?", [o["reservation_id"]])
                if r["status"] != "checked_in":
                    raise conflict("The guest has checked out; post the charge from the folio or city ledger instead")
                hotel = get_hotel(c, o["hotel_id"])
                pieces = c.scalar("SELECT COALESCE(SUM(quantity),0) FROM laundry_order_items WHERE order_id = ? AND outcome = 'ok'", [o["id"]])
                data["folio_line_id"] = post_charge(c, ctx, hotel, ensure_folio(c, r), "laundry",
                                                    f"Laundry {o['number']} — {pieces} piece(s){' (express)' if o['express'] else ''}", total, 1, o["number"])
        c.update("laundry_orders", o["id"], data)
        audit(c, ctx, "laundry.status", "laundry_order", o["id"], o["number"], old={"status": o["status"]}, new={"status": status}, hotel_id=o["hotel_id"])
        return _detail(c, c.one("SELECT * FROM laundry_orders WHERE id = ?", [o["id"]]))


@route("GET", "/api/hotels/{hotel_id:int}/laundry/summary", perm="laundry.view", tag="laundry",
       summary="Laundry summary for a date range: orders, pieces, revenue, lost & damaged, internal linen by department")
def summary(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid)).isoformat()
        frm, to = ctx.q("from", today), ctx.q("to", today)
        guest = c.one("SELECT COUNT(*) AS orders, COALESCE(SUM(total),0) AS revenue FROM laundry_orders WHERE hotel_id = ? AND kind = 'guest' AND status = 'delivered' "
                      "AND business_date >= ? AND business_date <= ?", [hid, frm, to])
        internal = c.all("SELECT o.department, COUNT(DISTINCT o.id) AS batches, COALESCE(SUM(i.quantity),0) AS pieces FROM laundry_orders o JOIN laundry_order_items i ON i.order_id = o.id "
                         "WHERE o.hotel_id = ? AND o.kind = 'internal' AND o.business_date >= ? AND o.business_date <= ? AND o.status <> 'cancelled' GROUP BY o.department", [hid, frm, to])
        issues = c.all("SELECT o.number, o.kind, i.description, i.quantity, i.outcome, i.outcome_note FROM laundry_order_items i JOIN laundry_orders o ON o.id = i.order_id "
                       "WHERE o.hotel_id = ? AND i.outcome <> 'ok' AND o.business_date >= ? AND o.business_date <= ? ORDER BY o.id", [hid, frm, to])
    return {"from": frm, "to": to, "guest": guest, "internal": internal, "issues": issues}


@route("GET", "/api/hotels/{hotel_id:int}/laundry/in-house", perm="laundry.manage", tag="laundry", summary="Checked-in guests for a laundry order (?q room or name)")
def in_house(ctx: Ctx):
    from .pos import in_house as pos_in_house
    return pos_in_house(ctx)
