"""Restaurant, bar and room-service point of sale with kitchen display. (FR-POS-001..006, FR-KIT-001..003)

Workflow: open a cashier shift -> open an order (dine-in table, takeaway or room service) -> add items ->
send to kitchen (items appear on the kitchen display for their station) -> kitchen marks preparing/ready ->
service marks served -> settle with one or more tenders (cash, POS card, transfer, or charge to an in-house
guest's room folio) -> receipt.

Settlement posts one balanced journal (Dr tenders / guest ledger; Cr F&B revenue, service charge, VAT using
the hotel's configured rules) and, for items with recipes, consumes ingredients from the outlet's store at
weighted average cost (Dr Cost of F&B Sold / Cr Inventory)."""
from __future__ import annotations

import datetime as dt
import io

from starlette.responses import Response

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import (account_id, business_date, from_milli, get_hotel, next_number, post_journal, price_breakdown, queue_notification,
                        to_milli, to_minor)
from ..stock import apply_movement, get_item, get_store

OUTLET_KINDS = ("restaurant", "bar", "room_service", "cafe", "pool_bar", "banquet")
STATIONS = ("kitchen", "bar", "pastry", "grill", "none")
ORDER_TYPES = ("dine_in", "takeaway", "room_service")
TENDER_KINDS = ("cash", "card_pos", "bank_transfer")


def _outlet(c, ctx: Ctx, outlet_id) -> dict:
    o = c.one("SELECT * FROM outlets WHERE id = ?", [int(outlet_id)])
    if not o:
        raise not_found("Outlet")
    ctx.check_hotel(o["hotel_id"])
    return o


# ------------------------------------------------------------------ outlets & tables
@route("GET", "/api/hotels/{hotel_id:int}/pos/outlets", perm="pos.view", tag="pos", summary="Outlets with tables and open-order counts")
def list_outlets(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        outlets = c.all("SELECT o.*, s.name AS store_name FROM outlets o LEFT JOIN stores s ON s.id = o.store_id WHERE o.hotel_id = ? ORDER BY o.name", [hid])
        for o in outlets:
            o["tables"] = c.all("SELECT t.*, (SELECT COUNT(*) FROM pos_orders po WHERE po.table_id = t.id AND po.status = 'open') AS open_orders "
                                "FROM pos_tables t WHERE t.outlet_id = ? ORDER BY t.area, LENGTH(t.code), t.code", [o["id"]])
            o["open_orders"] = c.scalar("SELECT COUNT(*) FROM pos_orders WHERE outlet_id = ? AND status = 'open'", [o["id"]])
    return {"items": outlets, "kinds": OUTLET_KINDS}


@route("POST", "/api/hotels/{hotel_id:int}/pos/outlets", perm="pos.manage", tag="pos", summary="Create an outlet (restaurant, bar, room service…)")
def create_outlet(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    kind = ctx.field("kind", required=False, default="restaurant", kind=str)
    if kind not in OUTLET_KINDS:
        raise bad_request(f"kind must be one of {', '.join(OUTLET_KINDS)}")
    with get_db().tx() as c:
        store = ctx.field("store_id", required=False)
        if store:
            get_store(c, hid, store)
        oid = c.insert("outlets", {"hotel_id": hid, "code": ctx.field("code", kind=str).upper(), "name": ctx.field("name", kind=str), "kind": kind,
                                   "store_id": int(store) if store else None, "active": 1})
        audit(c, ctx, "pos.outlet_created", "outlet", oid, new=ctx.body, hotel_id=hid)
    return {"id": oid, "_created": True}


@route("PATCH", "/api/pos/outlets/{outlet_id:int}", perm="pos.manage", tag="pos", summary="Edit an outlet")
def update_outlet(ctx: Ctx):
    with get_db().tx() as c:
        o = _outlet(c, ctx, ctx.path["outlet_id"])
        b = ctx.body or {}
        data = {k: str(b[k]).strip() for k in ("name", "kind") if k in b}
        if "kind" in data and data["kind"] not in OUTLET_KINDS:
            raise bad_request("Unknown outlet kind")
        if "store_id" in b:
            if b["store_id"]:
                get_store(c, o["hotel_id"], b["store_id"])
            data["store_id"] = int(b["store_id"]) if b["store_id"] else None
        if "active" in b:
            data["active"] = 1 if b["active"] else 0
        c.update("outlets", o["id"], data)
        audit(c, ctx, "pos.outlet_updated", "outlet", o["id"], old=o, new=data, hotel_id=o["hotel_id"])
    return {"ok": True}


@route("POST", "/api/pos/outlets/{outlet_id:int}/tables", perm="pos.manage", tag="pos", summary="Add a table to an outlet")
def create_table(ctx: Ctx):
    with get_db().tx() as c:
        o = _outlet(c, ctx, ctx.path["outlet_id"])
        tid = c.insert("pos_tables", {"outlet_id": o["id"], "code": ctx.field("code", kind=str).upper(), "area": ctx.field("area", required=False, kind=str),
                                      "seats": ctx.field("seats", required=False, default=4, kind=int), "active": 1})
        audit(c, ctx, "pos.table_created", "pos_table", tid, new=ctx.body, hotel_id=o["hotel_id"])
    return {"id": tid, "_created": True}


@route("PATCH", "/api/pos/tables/{table_id:int}", perm="pos.manage", tag="pos", summary="Edit or deactivate a table")
def update_table(ctx: Ctx):
    with get_db().tx() as c:
        t = c.one("SELECT t.*, o.hotel_id FROM pos_tables t JOIN outlets o ON o.id = t.outlet_id WHERE t.id = ?", [ctx.path["table_id"]])
        if not t:
            raise not_found("Table")
        ctx.check_hotel(t["hotel_id"])
        b = ctx.body or {}
        data = {k: b[k] for k in ("area",) if k in b}
        if "seats" in b:
            data["seats"] = int(b["seats"])
        if "active" in b:
            data["active"] = 1 if b["active"] else 0
        c.update("pos_tables", t["id"], data)
    return {"ok": True}


# ------------------------------------------------------------------ menu & recipes
@route("GET", "/api/hotels/{hotel_id:int}/pos/menu", perm="pos.view", tag="pos",
       summary="Menu categories and items (?outlet_id narrows to items sold there; ?all=1 includes inactive)")
def get_menu(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        cats = c.all("SELECT * FROM menu_categories WHERE hotel_id = ? ORDER BY sort_order, name", [hid])
        sql = ("SELECT m.*, o.name AS outlet_name, s.name AS issue_store_name FROM menu_items m LEFT JOIN outlets o ON o.id = m.outlet_id "
               "LEFT JOIN stores s ON s.id = m.issue_store_id WHERE m.hotel_id = ?")
        params: list = [hid]
        if ctx.q("outlet_id"):
            sql += " AND (m.outlet_id IS NULL OR m.outlet_id = ?)"
            params.append(int(ctx.q("outlet_id")))
        if ctx.q("all") != "1":
            sql += " AND m.active = 1"
        items = c.all(sql + " ORDER BY m.name", params)
        if ctx.can("pos.manage") or ctx.can("inventory.view"):
            recipes = c.all("SELECT r.*, i.code AS item_code, i.name AS item_name, i.unit, i.last_cost FROM recipe_lines r "
                            "JOIN inventory_items i ON i.id = r.item_id JOIN menu_items m ON m.id = r.menu_item_id WHERE m.hotel_id = ?", [hid])
            by_item: dict[int, list] = {}
            for r in recipes:
                r["quantity"] = from_milli(r.pop("quantity_milli"))
                r["cost"] = round(r["quantity"] * r["last_cost"])
                by_item.setdefault(r["menu_item_id"], []).append(r)
            for m in items:
                m["recipe"] = by_item.get(m["id"], [])
                m["recipe_cost"] = sum(r["cost"] for r in m["recipe"])
    return {"categories": cats, "items": items, "stations": STATIONS}


@route("POST", "/api/hotels/{hotel_id:int}/pos/menu-categories", perm="pos.manage", tag="pos", summary="Create a menu category")
def create_category(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    kind = ctx.field("kind", required=False, default="food", kind=str)
    if kind not in ("food", "beverage", "other"):
        raise bad_request("kind must be food, beverage or other")
    with get_db().tx() as c:
        cid = c.insert("menu_categories", {"hotel_id": hid, "name": ctx.field("name", kind=str), "kind": kind,
                                           "sort_order": ctx.field("sort_order", required=False, default=0, kind=int), "active": 1})
        audit(c, ctx, "pos.category_created", "menu_category", cid, new=ctx.body, hotel_id=hid)
    return {"id": cid, "_created": True}


def _menu_payload(c, ctx: Ctx, hid: int, partial: bool) -> dict:
    b = ctx.body or {}
    data: dict = {}
    for k in ("name",):
        if k in b or not partial:
            data[k] = ctx.field(k, kind=str)
    if "description" in b:
        data["description"] = ctx.field("description", required=False, kind=str)
    if "image_url" in b:
        url = ctx.field("image_url", required=False, kind=str)
        if url and not url.startswith(("https://", "/")):
            raise bad_request("image_url must be an https:// address")
        data["image_url"] = url
    if "price" in b or not partial:
        data["price"] = to_minor(ctx.field("price"), "price")
        if data["price"] < 0:
            raise bad_request("Price cannot be negative")
    if "category_id" in b or not partial:
        cat = c.one("SELECT id FROM menu_categories WHERE id = ? AND hotel_id = ?", [ctx.field("category_id", kind=int), hid])
        if not cat:
            raise bad_request("Menu category not found")
        data["category_id"] = cat["id"]
    if "station" in b or not partial:
        st = ctx.field("station", required=False, default="kitchen", kind=str)
        if st not in STATIONS:
            raise bad_request(f"station must be one of {', '.join(STATIONS)}")
        data["station"] = st
    if "issue_store_id" in b:
        if b["issue_store_id"]:
            get_store(c, hid, b["issue_store_id"])
        data["issue_store_id"] = int(b["issue_store_id"]) if b["issue_store_id"] else None
    if "outlet_id" in b:
        oid = b["outlet_id"]
        if oid:
            if not c.one("SELECT id FROM outlets WHERE id = ? AND hotel_id = ?", [int(oid), hid]):
                raise bad_request("Outlet not found")
        data["outlet_id"] = int(oid) if oid else None
    for k in ("available", "active"):
        if k in b:
            data[k] = 1 if b[k] else 0
    return data


@route("POST", "/api/hotels/{hotel_id:int}/pos/menu-items", perm="pos.manage", tag="pos", summary="Create a menu item")
def create_menu_item(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        data = _menu_payload(c, ctx, hid, partial=False)
        code = (ctx.field("code", required=False, kind=str) or f"M{next_number(c, hid, 'menu_item', 'M', 4).split('-')[-1]}").upper()
        mid = c.insert("menu_items", {"hotel_id": hid, "code": code, "available": 1, "active": 1, **data})
        audit(c, ctx, "pos.menu_item_created", "menu_item", mid, code, new=ctx.body, hotel_id=hid)
    return {"id": mid, "code": code, "_created": True}


@route("PATCH", "/api/pos/menu-items/{item_id:int}", perm="pos.manage", tag="pos", summary="Edit a menu item (price, availability…)")
def update_menu_item(ctx: Ctx):
    with get_db().tx() as c:
        m = c.one("SELECT * FROM menu_items WHERE id = ?", [ctx.path["item_id"]])
        if not m:
            raise not_found("Menu item")
        ctx.check_hotel(m["hotel_id"])
        data = _menu_payload(c, ctx, m["hotel_id"], partial=True)
        c.update("menu_items", m["id"], data)
        audit(c, ctx, "pos.menu_item_updated", "menu_item", m["id"], m["code"], old={k: m.get(k) for k in data}, new=data, hotel_id=m["hotel_id"])
    return {"ok": True}


@route("POST", "/api/pos/menu-items/{item_id:int}/availability", perm="pos.order", tag="pos",
       summary="Mark a menu item available / sold out (service staff, e.g. when the kitchen runs out)")
def set_availability(ctx: Ctx):
    with get_db().tx() as c:
        m = c.one("SELECT * FROM menu_items WHERE id = ?", [ctx.path["item_id"]])
        if not m:
            raise not_found("Menu item")
        ctx.check_hotel(m["hotel_id"])
        avail = 1 if ctx.field("available") else 0
        c.update("menu_items", m["id"], {"available": avail})
        audit(c, ctx, "pos.availability", "menu_item", m["id"], m["code"], new={"available": avail}, hotel_id=m["hotel_id"])
    return {"ok": True}


@route("PUT", "/api/pos/menu-items/{item_id:int}/recipe", perm="pos.manage", tag="pos",
       summary="Replace a menu item's recipe: lines[{item_id, quantity}] in each ingredient's stock unit per portion")
def set_recipe(ctx: Ctx):
    lines = ctx.field("lines", required=False) or []
    with get_db().tx() as c:
        m = c.one("SELECT * FROM menu_items WHERE id = ?", [ctx.path["item_id"]])
        if not m:
            raise not_found("Menu item")
        ctx.check_hotel(m["hotel_id"])
        seen = set()
        parsed = []
        for ln in lines:
            item = get_item(c, m["hotel_id"], ln.get("item_id"))
            if item["id"] in seen:
                raise bad_request(f"{item['name']} appears twice in the recipe")
            seen.add(item["id"])
            parsed.append((item["id"], to_milli(ln.get("quantity"))))
        old = c.all("SELECT item_id, quantity_milli FROM recipe_lines WHERE menu_item_id = ?", [m["id"]])
        c.execute("DELETE FROM recipe_lines WHERE menu_item_id = ?", [m["id"]])
        for iid, q in parsed:
            c.insert("recipe_lines", {"menu_item_id": m["id"], "item_id": iid, "quantity_milli": q})
        audit(c, ctx, "pos.recipe_updated", "menu_item", m["id"], m["code"], old=old, new=lines, hotel_id=m["hotel_id"])
    return {"ok": True, "lines": len(parsed)}


# ------------------------------------------------------------------ cashier shifts
def _open_shift(c, user_id: int, outlet_id: int) -> dict | None:
    return c.one("SELECT * FROM cashier_shifts WHERE user_id = ? AND outlet_id = ? AND status = 'open'", [user_id, outlet_id])


def _shift_summary(c, s: dict) -> dict:
    tenders = c.all("SELECT COALESCE(pm.name, 'Charged to room') AS method, pm.kind, p.tender, COUNT(*) AS count, SUM(p.amount) AS amount "
                    "FROM pos_payments p LEFT JOIN payment_methods pm ON pm.id = p.method_id WHERE p.shift_id = ? "
                    "GROUP BY pm.name, pm.kind, p.tender ORDER BY amount DESC", [s["id"]])
    cash = sum(t["amount"] for t in tenders if t["kind"] == "cash")
    orders = c.one("SELECT COUNT(*) AS n, COALESCE(SUM(total_amount),0) AS total, COALESCE(SUM(discount_amount),0) AS discounts "
                   "FROM pos_orders WHERE shift_id = ? AND status = 'settled'", [s["id"]])
    vsql = ("SELECT COUNT(*) FROM pos_order_items i JOIN pos_orders o ON o.id = i.order_id WHERE o.outlet_id = ? AND i.kitchen_status = 'void' "
            "AND i.voided_by = ? AND i.created_at >= ?")
    vparams = [s["outlet_id"], s["user_id"], s["opened_at"]]
    if s["closed_at"]:
        vsql += " AND i.created_at <= ?"
        vparams.append(s["closed_at"])
    voids = c.scalar(vsql, vparams)
    s = dict(s)
    s.update({"tenders": tenders, "cash_sales": cash, "expected_cash_now": s["opening_float"] + cash, "orders_settled": orders["n"],
              "sales_total": orders["total"], "discounts": orders["discounts"], "voided_items": voids})
    return s


@route("GET", "/api/hotels/{hotel_id:int}/pos/shifts", perm="pos.view", tag="pos",
       summary="Cashier shifts (?mine=1, ?outlet_id, ?status); managers see all")
def list_shifts(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT s.*, u.full_name AS cashier, o.name AS outlet_name FROM cashier_shifts s JOIN users u ON u.id = s.user_id "
           "JOIN outlets o ON o.id = s.outlet_id WHERE s.hotel_id = ?")
    params: list = [hid]
    if ctx.q("mine") == "1" or not ctx.can("pos.manage"):
        sql += " AND s.user_id = ?"
        params.append(ctx.user_id)
    for q, col in (("outlet_id", "s.outlet_id"), ("status", "s.status")):
        if ctx.q(q):
            sql += f" AND {col} = ?"
            params.append(ctx.q(q))
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY s.id DESC LIMIT 100", params)
        return {"items": [_shift_summary(c, s) if s["status"] == "open" else s for s in rows]}


@route("POST", "/api/hotels/{hotel_id:int}/pos/shifts", perm="pos.shift", tag="pos", summary="Open a cashier shift with an opening float")
def open_shift(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        o = _outlet(c, ctx, ctx.field("outlet_id", kind=int))
        if _open_shift(c, ctx.user_id, o["id"]):
            raise conflict("You already have an open shift at this outlet")
        number = next_number(c, hid, "shift", "SHF")
        sid = c.insert("cashier_shifts", {"hotel_id": hid, "outlet_id": o["id"], "user_id": ctx.user_id, "number": number, "status": "open",
                                          "opening_float": to_minor(ctx.field("opening_float", required=False, default=0), "opening_float"),
                                          "opened_at": now_iso()})
        audit(c, ctx, "pos.shift_opened", "cashier_shift", sid, number, new=ctx.body, hotel_id=hid)
    return {"id": sid, "number": number, "_created": True}


@route("GET", "/api/pos/shifts/{shift_id:int}", perm="pos.view", tag="pos", summary="Shift summary: tenders, expected cash, discounts, voids")
def get_shift(ctx: Ctx):
    with get_db().tx() as c:
        s = c.one("SELECT s.*, u.full_name AS cashier, o.name AS outlet_name FROM cashier_shifts s JOIN users u ON u.id = s.user_id "
                  "JOIN outlets o ON o.id = s.outlet_id WHERE s.id = ?", [ctx.path["shift_id"]])
        if not s:
            raise not_found("Shift")
        ctx.check_hotel(s["hotel_id"])
        if s["user_id"] != ctx.user_id and not ctx.can("pos.manage"):
            raise forbidden("You can only view your own shifts")
        return _shift_summary(c, s)


@route("POST", "/api/pos/shifts/{shift_id:int}/close", perm="pos.shift", tag="pos",
       summary="Close a shift: declare counted cash; the system records expected cash and the variance")
def close_shift(ctx: Ctx):
    counted = to_minor(ctx.field("counted_cash"), "counted_cash")
    with get_db().tx() as c:
        s = c.one("SELECT * FROM cashier_shifts WHERE id = ?", [ctx.path["shift_id"]])
        if not s:
            raise not_found("Shift")
        ctx.check_hotel(s["hotel_id"])
        if s["user_id"] != ctx.user_id and not ctx.can("pos.manage"):
            raise forbidden("Only the cashier or a POS manager can close this shift")
        if s["status"] != "open":
            raise conflict("This shift is already closed")
        summ = _shift_summary(c, s)
        expected = summ["expected_cash_now"]
        variance = counted - expected
        note = ctx.field("note", required=variance != 0, kind=str)
        c.update("cashier_shifts", s["id"], {"status": "closed", "expected_cash": expected, "counted_cash": counted, "variance": variance,
                                             "note": note, "closed_at": now_iso()})
        audit(c, ctx, "pos.shift_closed", "cashier_shift", s["id"], s["number"], new={"expected": expected, "counted": counted, "variance": variance},
              hotel_id=s["hotel_id"])
    return {"status": "closed", "expected_cash": expected, "counted_cash": counted, "variance": variance}


# ------------------------------------------------------------------ orders
def _order(c, ctx: Ctx, order_id, lock: bool = False) -> dict:
    o = c.lock("pos_orders", int(order_id)) if lock else c.one("SELECT * FROM pos_orders WHERE id = ?", [int(order_id)])
    if not o:
        raise not_found("Order")
    ctx.check_hotel(o["hotel_id"])
    return o


def _require_open(o: dict) -> None:
    if o["status"] != "open":
        raise conflict(f"Order {o['number']} is {o['status']}")


def order_totals(c, hotel: dict, o: dict) -> dict:
    subtotal = c.scalar("SELECT COALESCE(SUM(quantity * unit_price),0) FROM pos_order_items WHERE order_id = ? AND kitchen_status <> 'void'", [o["id"]]) or 0
    discount = min(o["discount_amount"] or 0, subtotal)
    bd = price_breakdown(c, hotel, "fnb", subtotal - discount, dt.date.fromisoformat(o["business_date"]))
    return {"subtotal": subtotal, "discount": discount, "net": bd["net"], "service_charge": bd["service_charge"], "tax": bd["tax"],
            "total": bd["total"], "taxes": bd["taxes"]}


def order_detail(c, o: dict) -> dict:
    hotel = get_hotel(c, o["hotel_id"])
    o = dict(o)
    o["items"] = c.all("SELECT * FROM pos_order_items WHERE order_id = ? ORDER BY id", [o["id"]])
    o["payments"] = c.all("SELECT p.*, pm.name AS method_name, f.number AS folio_number FROM pos_payments p LEFT JOIN payment_methods pm ON pm.id = p.method_id "
                          "LEFT JOIN folios f ON f.id = p.folio_id WHERE p.order_id = ? ORDER BY p.id", [o["id"]])
    o["outlet"] = c.one("SELECT id, code, name, kind FROM outlets WHERE id = ?", [o["outlet_id"]])
    o["table"] = c.one("SELECT id, code, area FROM pos_tables WHERE id = ?", [o["table_id"]]) if o["table_id"] else None
    o["waiter"] = c.scalar("SELECT full_name FROM users WHERE id = ?", [o["waiter_id"]]) if o["waiter_id"] else None
    if o["reservation_id"]:
        o["reservation"] = c.one("SELECT r.id, r.reference, r.status, rm.number AS room_number, g.first_name || ' ' || g.last_name AS guest "
                                 "FROM reservations r JOIN guests g ON g.id = r.guest_id LEFT JOIN rooms rm ON rm.id = r.room_id WHERE r.id = ?",
                                 [o["reservation_id"]])
    o["totals"] = order_totals(c, hotel, o) if o["status"] == "open" else {
        "subtotal": o["net_amount"] + o["discount_amount"] if o["net_amount"] is not None else 0, "discount": o["discount_amount"],
        "net": o["net_amount"], "service_charge": o["service_charge"], "tax": o["tax_amount"], "total": o["total_amount"]}
    o["currency"] = hotel["currency"]
    return o


def _in_house(c, hid: int, reservation_id) -> dict:
    r = c.one("SELECT * FROM reservations WHERE id = ? AND hotel_id = ?", [int(reservation_id), hid])
    if not r:
        raise bad_request("Reservation not found")
    if r["status"] != "checked_in":
        raise conflict("Charges can only be posted to the room of a checked-in guest")
    return r


@route("GET", "/api/hotels/{hotel_id:int}/pos/in-house", perm="pos.view", tag="pos",
       summary="In-house guests for room service / charge to room (?q room number or name)")
def in_house(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT r.id AS reservation_id, r.reference, rm.number AS room_number, g.first_name || ' ' || g.last_name AS guest, r.departure "
           "FROM reservations r JOIN guests g ON g.id = r.guest_id LEFT JOIN rooms rm ON rm.id = r.room_id WHERE r.hotel_id = ? AND r.status = 'checked_in'")
    params: list = [hid]
    if ctx.q("q"):
        sql += " AND (rm.number = ? OR LOWER(g.last_name) LIKE ? OR LOWER(g.first_name) LIKE ?)"
        q = ctx.q("q").lower()
        params += [ctx.q("q"), f"%{q}%", f"%{q}%"]
    with get_db().tx() as c:
        return {"items": c.all(sql + " ORDER BY rm.number", params)}


@route("GET", "/api/hotels/{hotel_id:int}/pos/orders", perm="pos.view", tag="pos",
       summary="Orders (?outlet_id, ?status=open|settled|voided, ?date)")
def list_orders(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    status = ctx.q("status", "open")
    sql = ("SELECT o.*, t.code AS table_code, u.full_name AS waiter_name, rm.number AS room_number, "
           "(SELECT COALESCE(SUM(quantity * unit_price),0) FROM pos_order_items WHERE order_id = o.id AND kitchen_status <> 'void') AS subtotal, "
           "(SELECT COUNT(*) FROM pos_order_items WHERE order_id = o.id AND kitchen_status = 'ready') AS ready_items, "
           "(SELECT COUNT(*) FROM pos_order_items WHERE order_id = o.id AND kitchen_status = 'new') AS unsent_items "
           "FROM pos_orders o LEFT JOIN pos_tables t ON t.id = o.table_id LEFT JOIN users u ON u.id = o.waiter_id "
           "LEFT JOIN reservations r ON r.id = o.reservation_id LEFT JOIN rooms rm ON rm.id = r.room_id WHERE o.hotel_id = ? AND o.status = ?")
    params: list = [hid, status]
    if ctx.q("outlet_id"):
        sql += " AND o.outlet_id = ?"
        params.append(int(ctx.q("outlet_id")))
    if ctx.q("date"):
        sql += " AND o.business_date = ?"
        params.append(ctx.q("date"))
    with get_db().tx() as c:
        return {"items": c.all(sql + " ORDER BY o.id DESC LIMIT 300", params)}


@route("POST", "/api/hotels/{hotel_id:int}/pos/orders", perm="pos.order", tag="pos", summary="Open an order (dine-in, takeaway or room service)")
def create_order(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    otype = ctx.field("order_type", required=False, default="dine_in", kind=str)
    if otype not in ORDER_TYPES:
        raise bad_request(f"order_type must be one of {', '.join(ORDER_TYPES)}")
    with get_db().tx() as c:
        outlet = _outlet(c, ctx, ctx.field("outlet_id", kind=int))
        if not outlet["active"]:
            raise conflict("This outlet is inactive")
        table_id = ctx.field("table_id", required=otype == "dine_in", kind=int)
        if table_id and not c.one("SELECT id FROM pos_tables WHERE id = ? AND outlet_id = ? AND active = 1", [table_id, outlet["id"]]):
            raise bad_request("Table not found at this outlet")
        res_id = ctx.field("reservation_id", required=otype == "room_service", kind=int)
        guest_name = ctx.field("guest_name", required=False, kind=str)
        if res_id:
            r = _in_house(c, hid, res_id)
            if not guest_name:
                guest_name = c.scalar("SELECT first_name || ' ' || last_name FROM guests WHERE id = ?", [r["guest_id"]])
        hotel = get_hotel(c, hid)
        number = next_number(c, hid, "pos_order", "POS")
        oid = c.insert("pos_orders", {"hotel_id": hid, "outlet_id": outlet["id"], "number": number, "order_type": otype,
                                      "table_id": table_id if otype == "dine_in" else None, "reservation_id": res_id, "guest_name": guest_name,
                                      "covers": ctx.field("covers", required=False, default=1, kind=int), "waiter_id": ctx.user_id, "status": "open",
                                      "business_date": business_date(hotel).isoformat(), "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "pos.order_opened", "pos_order", oid, number, new=ctx.body, hotel_id=hid)
        return {**order_detail(c, c.one("SELECT * FROM pos_orders WHERE id = ?", [oid])), "_created": True}


@route("GET", "/api/pos/orders/{order_id:int}", perm="pos.view", tag="pos", summary="Order with items, totals (tax & service charge) and payments")
def get_order(ctx: Ctx):
    with get_db().tx() as c:
        return order_detail(c, _order(c, ctx, ctx.path["order_id"]))


@route("POST", "/api/pos/orders/{order_id:int}/items", perm="pos.order", tag="pos", summary="Add a menu item to an order")
def add_item(ctx: Ctx):
    qty = ctx.field("quantity", required=False, default=1, kind=int)
    if qty <= 0 or qty > 500:
        raise bad_request("Quantity must be between 1 and 500")
    with get_db().tx() as c:
        o = _order(c, ctx, ctx.path["order_id"], lock=True)
        _require_open(o)
        m = c.one("SELECT * FROM menu_items WHERE id = ? AND hotel_id = ?", [ctx.field("menu_item_id", kind=int), o["hotel_id"]])
        if not m or not m["active"]:
            raise bad_request("Menu item not found")
        if m["outlet_id"] and m["outlet_id"] != o["outlet_id"]:
            raise bad_request(f"{m['name']} is not sold at this outlet")
        if not m["available"]:
            raise conflict(f"{m['name']} is sold out")
        notes = ctx.field("notes", required=False, kind=str)
        rush = bool(ctx.field("rush", required=False, default=False))
        same = None if notes or rush else c.one("SELECT * FROM pos_order_items WHERE order_id = ? AND menu_item_id = ? AND kitchen_status = 'new' "
                                                 "AND notes IS NULL AND priority = 2 AND unit_price = ?", [o["id"], m["id"], m["price"]])
        if same:  # tapping the same item again increases the quantity on the unsent line
            c.update("pos_order_items", same["id"], {"quantity": min(500, same["quantity"] + qty)})
            return {**order_detail(c, o), "item_id": same["id"], "_created": True}
        iid = c.insert("pos_order_items", {"order_id": o["id"], "menu_item_id": m["id"], "name": m["name"], "quantity": qty, "unit_price": m["price"],
                                           "notes": notes, "station": m["station"], "priority": 1 if rush else 2,
                                           "kitchen_status": "new", "added_by": ctx.user_id, "created_at": now_iso()})
        return {**order_detail(c, o), "item_id": iid, "_created": True}


@route("PATCH", "/api/pos/order-items/{item_id:int}", perm="pos.order", tag="pos", summary="Change quantity or notes of an item not yet sent to the kitchen")
def update_item(ctx: Ctx):
    with get_db().tx() as c:
        it = c.one("SELECT * FROM pos_order_items WHERE id = ?", [ctx.path["item_id"]])
        if not it:
            raise not_found("Order item")
        o = _order(c, ctx, it["order_id"], lock=True)
        _require_open(o)
        if it["kitchen_status"] != "new":
            raise conflict("This item has already gone to the kitchen; void it instead (needs authorisation)")
        data = {}
        if "quantity" in (ctx.body or {}):
            q = ctx.field("quantity", kind=int)
            if q <= 0 or q > 500:
                raise bad_request("Quantity must be between 1 and 500")
            data["quantity"] = q
        if "notes" in (ctx.body or {}):
            data["notes"] = ctx.field("notes", required=False, kind=str)
        c.update("pos_order_items", it["id"], data)
        return order_detail(c, o)


@route("DELETE", "/api/pos/order-items/{item_id:int}", perm="pos.order", tag="pos", summary="Remove an item that has not been sent to the kitchen")
def remove_item(ctx: Ctx):
    with get_db().tx() as c:
        it = c.one("SELECT * FROM pos_order_items WHERE id = ?", [ctx.path["item_id"]])
        if not it:
            raise not_found("Order item")
        o = _order(c, ctx, it["order_id"], lock=True)
        _require_open(o)
        if it["kitchen_status"] != "new":
            raise conflict("This item has already gone to the kitchen; void it instead (needs authorisation)")
        c.execute("DELETE FROM pos_order_items WHERE id = ?", [it["id"]])
        return order_detail(c, o)


@route("POST", "/api/pos/order-items/{item_id:int}/void", perm="pos.void", tag="pos", summary="Void an item already sent to the kitchen (reason required)")
def void_item(ctx: Ctx):
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        it = c.one("SELECT * FROM pos_order_items WHERE id = ?", [ctx.path["item_id"]])
        if not it:
            raise not_found("Order item")
        o = _order(c, ctx, it["order_id"], lock=True)
        _require_open(o)
        if it["kitchen_status"] == "void":
            raise conflict("This item is already void")
        c.update("pos_order_items", it["id"], {"kitchen_status": "void", "void_reason": reason, "voided_by": ctx.user_id})
        audit(c, ctx, "pos.item_voided", "pos_order_item", it["id"], o["number"],
              old={"item": it["name"], "qty": it["quantity"], "status": it["kitchen_status"]}, new={"reason": reason}, hotel_id=o["hotel_id"])
        return order_detail(c, o)


@route("POST", "/api/pos/orders/{order_id:int}/send", perm="pos.order", tag="pos", summary="Send new items to the kitchen / bar display")
def send_to_kitchen(ctx: Ctx):
    with get_db().tx() as c:
        o = _order(c, ctx, ctx.path["order_id"], lock=True)
        _require_open(o)
        ts = now_iso()
        n = c.scalar("SELECT COUNT(*) FROM pos_order_items WHERE order_id = ? AND kitchen_status = 'new'", [o["id"]])
        if not n:
            raise bad_request("There are no new items to send")
        # items with no preparation station (e.g. bottled water at the bar counter) are ready immediately
        c.execute("UPDATE pos_order_items SET kitchen_status = 'ready', sent_at = ?, ready_at = ? WHERE order_id = ? AND kitchen_status = 'new' "
                  "AND station = 'none'", [ts, ts, o["id"]])
        c.execute("UPDATE pos_order_items SET kitchen_status = 'sent', sent_at = ? WHERE order_id = ? AND kitchen_status = 'new'", [ts, o["id"]])
        audit(c, ctx, "pos.sent_to_kitchen", "pos_order", o["id"], o["number"], new={"items": n}, hotel_id=o["hotel_id"])
        return {**order_detail(c, o), "sent": n}


@route("POST", "/api/pos/orders/{order_id:int}/discount", perm="pos.discount", tag="pos",
       summary="Apply a discount (amount in minor units or percent) with a reason; 0 removes it")
def discount(ctx: Ctx):
    reason = ctx.field("reason", required=False, kind=str)
    with get_db().tx() as c:
        o = _order(c, ctx, ctx.path["order_id"], lock=True)
        _require_open(o)
        subtotal = order_totals(c, get_hotel(c, o["hotel_id"]), {**o, "discount_amount": 0})["subtotal"]
        if ctx.field("percent", required=False) is not None:
            pct = float(ctx.field("percent"))
            if not 0 <= pct <= 100:
                raise bad_request("percent must be between 0 and 100")
            amount = round(subtotal * pct / 100)
        else:
            amount = to_minor(ctx.field("amount"), "amount")
        if amount < 0 or amount > subtotal:
            raise bad_request("The discount cannot be negative or more than the order subtotal")
        if amount and not reason:
            raise bad_request("A reason is required for a discount", {"field": "reason"})
        c.update("pos_orders", o["id"], {"discount_amount": amount, "discount_reason": reason if amount else None, "discount_by": ctx.user_id if amount else None})
        audit(c, ctx, "pos.discount", "pos_order", o["id"], o["number"], old={"discount": o["discount_amount"]}, new={"discount": amount, "reason": reason},
              hotel_id=o["hotel_id"])
        return order_detail(c, c.one("SELECT * FROM pos_orders WHERE id = ?", [o["id"]]))


@route("POST", "/api/pos/orders/{order_id:int}/split", perm="pos.order", tag="pos",
       summary="Split the bill: move the listed items (item_ids) to a new order for separate payment")
def split(ctx: Ctx):
    ids = [int(i) for i in (ctx.field("item_ids") or [])]
    if not ids:
        raise bad_request("Choose the items to move to the new bill")
    with get_db().tx() as c:
        o = _order(c, ctx, ctx.path["order_id"], lock=True)
        _require_open(o)
        items = c.all(f"SELECT * FROM pos_order_items WHERE order_id = ? AND kitchen_status <> 'void' AND id IN ({','.join('?' for _ in ids)})", [o["id"], *ids])
        if len(items) != len(set(ids)):
            raise bad_request("Some items are not on this order")
        remaining = c.scalar("SELECT COUNT(*) FROM pos_order_items WHERE order_id = ? AND kitchen_status <> 'void'", [o["id"]]) - len(items)
        if remaining <= 0:
            raise bad_request("Leave at least one item on the original bill")
        number = next_number(c, o["hotel_id"], "pos_order", "POS")
        new_id = c.insert("pos_orders", {k: o[k] for k in ("hotel_id", "outlet_id", "order_type", "table_id", "reservation_id", "guest_name", "waiter_id",
                                                           "business_date")} | {"number": number, "covers": 1, "status": "open", "split_from": o["id"],
                                                                                "created_by": ctx.user_id, "created_at": now_iso()})
        c.execute(f"UPDATE pos_order_items SET order_id = ? WHERE id IN ({','.join('?' for _ in ids)})", [new_id, *ids])
        audit(c, ctx, "pos.bill_split", "pos_order", o["id"], o["number"], new={"new_order": number, "items": ids}, hotel_id=o["hotel_id"])
        return {"original": order_detail(c, o), "new_order": order_detail(c, c.one("SELECT * FROM pos_orders WHERE id = ?", [new_id])), "_created": True}


@route("POST", "/api/pos/orders/{order_id:int}/merge", perm="pos.order", tag="pos",
       summary="Merge another open order (source_order_id) into this one, e.g. when tables are joined")
def merge(ctx: Ctx):
    with get_db().tx() as c:
        o = _order(c, ctx, ctx.path["order_id"], lock=True)
        src = _order(c, ctx, ctx.field("source_order_id", kind=int), lock=True)
        _require_open(o)
        _require_open(src)
        if src["id"] == o["id"] or src["outlet_id"] != o["outlet_id"]:
            raise bad_request("Choose a different open order from the same outlet")
        c.execute("UPDATE pos_order_items SET order_id = ? WHERE order_id = ?", [o["id"], src["id"]])
        c.update("pos_orders", src["id"], {"status": "merged", "merged_into": o["id"]})
        c.update("pos_orders", o["id"], {"covers": o["covers"] + src["covers"], "discount_amount": o["discount_amount"] + src["discount_amount"],
                                         "discount_reason": o["discount_reason"] or src["discount_reason"]})
        audit(c, ctx, "pos.orders_merged", "pos_order", o["id"], o["number"], new={"merged": src["number"]}, hotel_id=o["hotel_id"])
        return order_detail(c, c.one("SELECT * FROM pos_orders WHERE id = ?", [o["id"]]))


@route("POST", "/api/pos/orders/{order_id:int}/move-table", perm="pos.order", tag="pos", summary="Move an order to another table")
def move_table(ctx: Ctx):
    with get_db().tx() as c:
        o = _order(c, ctx, ctx.path["order_id"], lock=True)
        _require_open(o)
        t = c.one("SELECT id FROM pos_tables WHERE id = ? AND outlet_id = ? AND active = 1", [ctx.field("table_id", kind=int), o["outlet_id"]])
        if not t:
            raise bad_request("Table not found at this outlet")
        c.update("pos_orders", o["id"], {"table_id": t["id"], "order_type": "dine_in"})
        return order_detail(c, c.one("SELECT * FROM pos_orders WHERE id = ?", [o["id"]]))


@route("POST", "/api/pos/orders/{order_id:int}/void", perm="pos.void", tag="pos", summary="Void an unsettled order (reason required)")
def void_order(ctx: Ctx):
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        o = _order(c, ctx, ctx.path["order_id"], lock=True)
        _require_open(o)
        c.execute("UPDATE pos_order_items SET kitchen_status = 'void', void_reason = ?, voided_by = ? WHERE order_id = ? AND kitchen_status <> 'void'",
                  [reason, ctx.user_id, o["id"]])
        c.update("pos_orders", o["id"], {"status": "voided", "void_reason": reason})
        audit(c, ctx, "pos.order_voided", "pos_order", o["id"], o["number"], new={"reason": reason}, hotel_id=o["hotel_id"])
    return {"status": "voided"}


# ------------------------------------------------------------------ reporting helpers
def pos_direct_revenue(c, hid: int, d_from: str, d_to: str) -> dict:
    """POS revenue settled by cash/card/transfer (not charged to a room, which already appears on guest folios)."""
    rows = c.all("SELECT o.id, o.net_amount, o.service_charge, o.tax_amount, o.total_amount, "
                 "COALESCE((SELECT SUM(amount) FROM pos_payments p WHERE p.order_id = o.id AND p.tender = 'method'),0) AS direct "
                 "FROM pos_orders o WHERE o.hotel_id = ? AND o.status = 'settled' AND o.business_date >= ? AND o.business_date <= ?", [hid, d_from, d_to])
    out = {"orders": 0, "net": 0, "service_charge": 0, "tax": 0, "total": 0}
    for r in rows:
        if not r["direct"] or not r["total_amount"]:
            continue
        net = _prorate(r["direct"], r["total_amount"], r["net_amount"])
        svc = _prorate(r["direct"], r["total_amount"], r["service_charge"])
        out["orders"] += 1
        out["net"] += net
        out["service_charge"] += svc
        out["tax"] += r["direct"] - net - svc
        out["total"] += r["direct"]
    return out


# ------------------------------------------------------------------ settlement
def _prorate(part: int, whole: int, value: int) -> int:
    return (value * part * 2 + whole) // (whole * 2) if whole else 0


def consume_recipes(c, ctx: Ctx, hotel: dict, o: dict, outlet: dict, on: dt.date) -> int:
    """Deduct recipe ingredients for the order's items. Each menu item issues from its own store if set
    (e.g. drinks from the bar store), otherwise from the outlet's store. Returns the cost value consumed."""
    rows = c.all("SELECT r.item_id, m.issue_store_id, SUM(r.quantity_milli * i.quantity) AS qty FROM pos_order_items i "
                 "JOIN recipe_lines r ON r.menu_item_id = i.menu_item_id JOIN menu_items m ON m.id = i.menu_item_id "
                 "WHERE i.order_id = ? AND i.kitchen_status <> 'void' GROUP BY r.item_id, m.issue_store_id", [o["id"]])
    if not rows:
        return 0
    total = 0
    for r in rows:
        store_id = r["issue_store_id"] or outlet["store_id"]
        if not store_id:
            raise conflict(f"Outlet {outlet['name']} has no issuing store configured, so recipe ingredients cannot be deducted. "
                           "Set the outlet's store in POS setup.", {"code": "outlet_store_missing"})
        item = get_item(c, hotel["id"], r["item_id"])
        _, val = apply_movement(c, hotel["id"], item, get_store(c, hotel["id"], store_id), "consumption", -int(r["qty"]), None, "pos", o["number"],
                                ctx.user_id, on, department="fnb", reason=f"Sold via {outlet['name']}")
        total += -val
    return total


@route("POST", "/api/pos/orders/{order_id:int}/settle", perm="pos.settle", tag="pos",
       summary="Settle an order with one or more tenders: [{tender:'method', method_id, amount, reference} | {tender:'room', reservation_id, amount}]")
def settle(ctx: Ctx):
    tenders = ctx.field("tenders")
    if not isinstance(tenders, list) or not tenders:
        raise bad_request("Add at least one payment")
    with get_db().tx() as c:
        o = _order(c, ctx, ctx.path["order_id"], lock=True)
        _require_open(o)
        hotel = get_hotel(c, o["hotel_id"])
        outlet = c.one("SELECT * FROM outlets WHERE id = ?", [o["outlet_id"]])
        if c.scalar("SELECT COUNT(*) FROM pos_order_items WHERE order_id = ? AND kitchen_status = 'new'", [o["id"]]):
            raise conflict("Send all items to the kitchen (or remove them) before settling")
        tot = order_totals(c, hotel, o)
        if tot["subtotal"] <= 0:
            raise bad_request("This order has no chargeable items")
        total = tot["total"]
        parsed = []
        for t in tenders:
            kind = t.get("tender")
            amount = to_minor(t.get("amount"), "amount")
            if amount <= 0:
                raise bad_request("Each payment amount must be greater than zero")
            if kind == "method":
                m = c.one("SELECT * FROM payment_methods WHERE id = ? AND hotel_id = ? AND active = 1", [int(t.get("method_id") or 0), hotel["id"]])
                if not m:
                    raise bad_request("Payment method not found")
                if m["kind"] not in TENDER_KINDS:
                    raise bad_request(f"{m['name']} cannot be taken at the POS. Use cash, POS card or bank transfer"
                                      + (" (online payments are confirmed by the gateway)" if m["kind"] == "online" else ""))
                ref = (t.get("reference") or "").strip() or None
                if m["kind"] in ("card_pos", "bank_transfer") and not ref:
                    raise bad_request(f"Enter the {m['name']} reference (terminal slip / transfer reference)")
                parsed.append({"tender": "method", "method": m, "amount": amount, "reference": ref})
            elif kind == "room":
                ctx.require("pos.post_to_room")
                r = _in_house(c, hotel["id"], t.get("reservation_id") or o["reservation_id"] or 0)
                parsed.append({"tender": "room", "reservation": r, "amount": amount, "reference": None})
            else:
                raise bad_request("tender must be 'method' or 'room'")
        paid = sum(p["amount"] for p in parsed)
        cash_tendered = sum(p["amount"] for p in parsed if p["tender"] == "method" and p["method"]["kind"] == "cash")
        change = paid - total
        if change < 0:
            raise bad_request(f"Payments ({paid}) are less than the order total ({total})", {"total": total, "paid": paid})
        if change > cash_tendered:
            raise bad_request("Only cash can be over-tendered; card, transfer and room charges must not exceed the amount due", {"total": total})
        shift = _open_shift(c, ctx.user_id, outlet["id"])
        if any(p["tender"] == "method" for p in parsed) and not shift:
            raise conflict("Open a cashier shift at this outlet before taking payments", {"code": "shift_required"})
        # apply change to cash tenders (largest first)
        remaining = change
        for p in sorted(parsed, key=lambda p: -p["amount"]):
            if remaining and p["tender"] == "method" and p["method"]["kind"] == "cash":
                take = min(remaining, p["amount"])
                p["amount"] -= take
                remaining -= take
        parsed = [p for p in parsed if p["amount"] > 0]
        on = business_date(hotel)
        org = hotel["organisation_id"]
        desc = f"{outlet['name']} {o['number']}"
        debit_lines = []
        for p in parsed:
            if p["tender"] == "method":
                debit_lines.append((p["method"]["account_id"], p["amount"], 0, "fnb", f"{p['method']['name']} {p['reference'] or ''}".strip()))
            else:
                debit_lines.append((account_id(c, org, "guest_ledger"), p["amount"], 0, "fnb", f"Charged to room — {desc}"))
        je = post_journal(c, hotel["id"], on, f"POS sale {desc}", "pos", o["number"], debit_lines + [
            (account_id(c, org, "rev_fnb"), 0, tot["net"], "fnb", desc),
            (account_id(c, org, "service_charge_payable"), 0, tot["service_charge"], "fnb", "Service charge " + desc),
            (account_id(c, org, "vat_payable"), 0, tot["tax"], "fnb", "Tax " + desc)], ctx.user_id)
        from .frontoffice import ensure_folio
        n_items = c.scalar("SELECT COALESCE(SUM(quantity),0) FROM pos_order_items WHERE order_id = ? AND kitchen_status <> 'void'", [o["id"]])
        for p in parsed:
            folio_id = line_id = None
            if p["tender"] == "room":
                folio = ensure_folio(c, p["reservation"])
                if folio["status"] != "open":
                    raise conflict("The guest's folio is closed")
                net = _prorate(p["amount"], total, tot["net"])
                svc = _prorate(p["amount"], total, tot["service_charge"])
                line_id = c.insert("folio_lines", {"folio_id": folio["id"], "business_date": on.isoformat(), "kind": "charge", "department": "fnb",
                                                   "description": f"{desc} — {n_items} item(s)"[:300],
                                                   "quantity": 1, "net_amount": net, "tax_amount": p["amount"] - net - svc, "service_charge": svc,
                                                   "total_amount": p["amount"], "reference": o["number"], "journal_entry_id": je, "posted_by": ctx.user_id,
                                                   "posted_at": now_iso()})
                folio_id = folio["id"]
            c.insert("pos_payments", {"order_id": o["id"], "shift_id": shift["id"] if shift else None, "tender": p["tender"],
                                      "method_id": p["method"]["id"] if p["tender"] == "method" else None, "folio_id": folio_id, "folio_line_id": line_id,
                                      "amount": p["amount"], "reference": p["reference"], "received_by": ctx.user_id, "created_at": now_iso()})
        cost = consume_recipes(c, ctx, hotel, o, outlet, on)
        cogs = None
        if cost:
            cogs = post_journal(c, hotel["id"], on, f"Cost of sales {desc}", "pos", o["number"], [
                (account_id(c, org, "cogs_fnb"), cost, 0, "fnb", desc), (account_id(c, org, "inventory"), 0, cost, "fnb", desc)], ctx.user_id)
        c.update("pos_orders", o["id"], {"status": "settled", "net_amount": tot["net"], "service_charge": tot["service_charge"], "tax_amount": tot["tax"],
                                         "total_amount": total, "discount_amount": tot["discount"], "shift_id": shift["id"] if shift else None,
                                         "journal_entry_id": je, "cogs_entry_id": cogs, "settled_at": now_iso(), "settled_by": ctx.user_id})
        audit(c, ctx, "pos.order_settled", "pos_order", o["id"], o["number"],
              new={"total": total, "change": change, "tenders": [{"tender": p["tender"], "amount": p["amount"]} for p in parsed], "cost": cost},
              hotel_id=hotel["id"])
        return {**order_detail(c, c.one("SELECT * FROM pos_orders WHERE id = ?", [o["id"]])), "change": change, "cost_of_sales": cost}


@route("GET", "/api/pos/orders/{order_id:int}/receipt.pdf", perm="pos.view", tag="pos", summary="Order receipt / bill as PDF (80 mm)")
def receipt_pdf(ctx: Ctx):
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    with get_db().tx() as c:
        o = order_detail(c, _order(c, ctx, ctx.path["order_id"]))
        hotel = get_hotel(c, o["hotel_id"])
    cur = hotel["currency"]
    items = [i for i in o["items"] if i["kitchen_status"] != "void"]
    height = (95 + 6 * len(items) + 6 * len(o["payments"])) * mm
    buf = io.BytesIO()
    pdf = canvas.Canvas(buf, pagesize=(80 * mm, height))
    pdf.setTitle(f"{'Receipt' if o['status'] == 'settled' else 'Bill'} {o['number']}")
    y = height - 10 * mm

    def line(txt: str, right: str = "", bold: bool = False, size: float = 8.5):
        nonlocal y
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        pdf.drawString(5 * mm, y, txt[:42])
        if right:
            pdf.drawRightString(75 * mm, y, right)
        y -= 5 * mm

    fmt = lambda v: f"{(v or 0) / 100:,.2f}"  # noqa: E731
    line(hotel["name"], bold=True, size=11)
    line(o["outlet"]["name"])
    line(("RECEIPT " if o["status"] == "settled" else "BILL ") + o["number"], bold=True)
    line(f"Date {o['business_date']}", (f"Table {o['table']['code']}" if o["table"] else o["order_type"].replace("_", " ").title()))
    if o.get("reservation"):
        line(f"Room {o['reservation']['room_number']} — {o['reservation']['guest']}")
    if o["waiter"]:
        line(f"Served by {o['waiter']}")
    y -= 2 * mm
    for i in items:
        line(f"{i['quantity']} x {i['name']}", fmt(i["quantity"] * i["unit_price"]))
    y -= 2 * mm
    t = o["totals"]
    line("Subtotal", fmt(t["subtotal"]))
    if t["discount"]:
        line("Discount", "-" + fmt(t["discount"]))
    if t["service_charge"]:
        line("Service charge", fmt(t["service_charge"]))
    line("Tax", fmt(t["tax"]))
    line(f"TOTAL {cur}", fmt(t["total"]), bold=True, size=10)
    for p in o["payments"]:
        line(p["method_name"] or f"Charged to room ({p['folio_number']})", fmt(p["amount"]))
    y -= 3 * mm
    line("Thank you!" if o["status"] == "settled" else "This is not a receipt.", size=8)
    pdf.showPage()
    pdf.save()
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{o["number"]}.pdf"'})


# ------------------------------------------------------------------ kitchen display
@route("GET", "/api/hotels/{hotel_id:int}/kitchen/tickets", perm="kitchen.view", tag="kitchen",
       summary="Kitchen display tickets: open orders' items that are sent, preparing or ready (?station, ?outlet_id)")
def kitchen_tickets(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT i.*, o.number, o.order_type, o.outlet_id, o.waiter_id, ou.name AS outlet_name, t.code AS table_code, rm.number AS room_number, "
           "u.full_name AS waiter_name FROM pos_order_items i JOIN pos_orders o ON o.id = i.order_id JOIN outlets ou ON ou.id = o.outlet_id "
           "LEFT JOIN pos_tables t ON t.id = o.table_id LEFT JOIN reservations r ON r.id = o.reservation_id LEFT JOIN rooms rm ON rm.id = r.room_id "
           "LEFT JOIN users u ON u.id = o.waiter_id WHERE o.hotel_id = ? AND i.kitchen_status IN ('sent','preparing','ready') "
           "AND o.status IN ('open','settled') AND i.station <> 'none'")
    params: list = [hid]
    if ctx.q("station"):
        sql += " AND i.station = ?"
        params.append(ctx.q("station"))
    if ctx.q("outlet_id"):
        sql += " AND o.outlet_id = ?"
        params.append(int(ctx.q("outlet_id")))
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY i.priority, i.sent_at, i.id", params)
    tickets: dict[int, dict] = {}
    for r in rows:
        t = tickets.setdefault(r["order_id"], {"order_id": r["order_id"], "number": r["number"], "order_type": r["order_type"], "outlet": r["outlet_name"],
                                               "table": r["table_code"], "room": r["room_number"], "waiter": r["waiter_name"], "sent_at": r["sent_at"],
                                               "items": []})
        t["items"].append({k: r[k] for k in ("id", "name", "quantity", "notes", "station", "priority", "kitchen_status", "sent_at", "started_at", "ready_at")})
        t["sent_at"] = min(t["sent_at"], r["sent_at"])
    return {"tickets": list(tickets.values()), "server_time": now_iso(), "stations": STATIONS}


@route("POST", "/api/kitchen/items/{item_id:int}/status", perm="kitchen.view", tag="kitchen",
       summary="Move a kitchen item to preparing / ready (kitchen staff) or served (service staff)")
def kitchen_status(ctx: Ctx):
    status = ctx.field("status", kind=str)
    flow = {"preparing": ("sent",), "ready": ("sent", "preparing"), "served": ("ready",)}
    if status not in flow:
        raise bad_request("status must be preparing, ready or served")
    ctx.require("pos.order" if status == "served" else "kitchen.update")
    with get_db().tx() as c:
        it = c.one("SELECT * FROM pos_order_items WHERE id = ?", [ctx.path["item_id"]])
        if not it:
            raise not_found("Order item")
        o = _order(c, ctx, it["order_id"])
        if it["kitchen_status"] not in flow[status]:
            raise conflict(f"An item that is {it['kitchen_status']} cannot be marked {status}")
        ts = now_iso()
        data = {"kitchen_status": status, {"preparing": "started_at", "ready": "ready_at", "served": "served_at"}[status]: ts}
        if status == "ready" and not it["started_at"]:
            data["started_at"] = ts
        c.update("pos_order_items", it["id"], data)
        if status == "ready" and o["waiter_id"]:
            table = c.scalar("SELECT code FROM pos_tables WHERE id = ?", [o["table_id"]]) if o["table_id"] else None
            queue_notification(c, o["hotel_id"], "in_app", str(o["waiter_id"]), "Order ready",
                               f"{it['quantity']} x {it['name']} ready for {('table ' + table) if table else o['number']}", "pos_order", o["id"])
    return {"ok": True, "status": status}


@route("GET", "/api/hotels/{hotel_id:int}/kitchen/performance", perm="kitchen.view", tag="kitchen",
       summary="Kitchen performance: items, average and slowest preparation time per station (?from, ?to)")
def kitchen_performance(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid)).isoformat()
        rows = c.all("SELECT i.station, i.sent_at, i.ready_at, i.quantity FROM pos_order_items i JOIN pos_orders o ON o.id = i.order_id "
                     "WHERE o.hotel_id = ? AND o.business_date >= ? AND o.business_date <= ? AND i.ready_at IS NOT NULL AND i.sent_at IS NOT NULL "
                     "AND i.station <> 'none'", [hid, ctx.q("from", today), ctx.q("to", today)])
    stats: dict[str, dict] = {}
    for r in rows:
        secs = (dt.datetime.fromisoformat(r["ready_at"].replace("Z", "+00:00")) - dt.datetime.fromisoformat(r["sent_at"].replace("Z", "+00:00"))).total_seconds()
        s = stats.setdefault(r["station"], {"station": r["station"], "items": 0, "total_secs": 0, "max_secs": 0})
        s["items"] += r["quantity"]
        s["total_secs"] += secs
        s["max_secs"] = max(s["max_secs"], secs)
    out = [{"station": s["station"], "items": s["items"], "avg_minutes": round(s["total_secs"] / max(1, len([r for r in rows if r["station"] == s["station"]])) / 60, 1),
            "slowest_minutes": round(s["max_secs"] / 60, 1)} for s in stats.values()]
    return {"items": out, "from": ctx.q("from", today), "to": ctx.q("to", today)}
