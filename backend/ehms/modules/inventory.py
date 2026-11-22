"""Inventory & stores: item catalogue, stores, stock balances, movements, requisitions, transfers,
adjustments/wastage, stock counts, low-stock and expiry alerts. (FR-INV-001..005)

Accounting: issues to departments post Dr department expense / Cr Inventory; adjustments, wastage and
count variances post against Inventory Shrinkage & Wastage. Transfers between stores move carrying value
without a journal (both stores sit in the same Inventory account)."""
from __future__ import annotations

import datetime as dt

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import (DEPARTMENT_EXPENSE_KEYS, account_id, business_date, from_milli, get_hotel, next_number, post_journal,
                        to_milli, to_minor)
from ..stock import apply_movement, get_item, get_store, outflow_value

ITEM_CATEGORIES = ("food", "beverage", "cleaning", "toiletries", "linen", "furniture", "electrical", "plumbing", "kitchen_equipment",
                   "office", "maintenance", "fuel", "other")
STORE_KINDS = ("main", "kitchen", "bar", "housekeeping", "laundry", "maintenance", "other")


def _qty_out(row: dict, *cols: str) -> dict:
    for col in cols:
        if col in row:
            row[col.replace("_milli", "")] = from_milli(row.pop(col))
    return row


# ------------------------------------------------------------------ stores
@route("GET", "/api/hotels/{hotel_id:int}/stores", perm="inventory.view", tag="inventory", summary="Stores / storage locations")
def list_stores(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        rows = c.all("SELECT s.*, COALESCE(SUM(l.value),0) AS stock_value, COUNT(CASE WHEN l.quantity_milli <> 0 THEN 1 END) AS items_in_stock "
                     "FROM stores s LEFT JOIN stock_levels l ON l.store_id = s.id WHERE s.hotel_id = ? GROUP BY s.id ORDER BY s.code", [hid])
    return {"items": rows, "kinds": STORE_KINDS}


@route("POST", "/api/hotels/{hotel_id:int}/stores", perm="inventory.manage", tag="inventory", summary="Create a store")
def create_store(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    kind = ctx.field("kind", required=False, default="main", kind=str)
    if kind not in STORE_KINDS:
        raise bad_request(f"kind must be one of {', '.join(STORE_KINDS)}")
    with get_db().tx() as c:
        sid = c.insert("stores", {"hotel_id": hid, "code": ctx.field("code", kind=str).upper(), "name": ctx.field("name", kind=str), "kind": kind,
                                  "allow_negative": 1 if ctx.field("allow_negative", required=False, default=False) else 0, "active": 1})
        audit(c, ctx, "store.created", "store", sid, new=ctx.body, hotel_id=hid)
    return {"id": sid, "_created": True}


@route("PATCH", "/api/stores/{store_id:int}", perm="inventory.manage", tag="inventory", summary="Edit a store")
def update_store(ctx: Ctx):
    with get_db().tx() as c:
        st = c.one("SELECT * FROM stores WHERE id = ?", [ctx.path["store_id"]])
        if not st:
            raise not_found("Store")
        ctx.check_hotel(st["hotel_id"])
        data = {}
        for k in ("name", "kind"):
            if k in (ctx.body or {}):
                data[k] = str(ctx.body[k]).strip()
        for k in ("allow_negative", "active"):
            if k in (ctx.body or {}):
                data[k] = 1 if ctx.body[k] else 0
        if data.get("kind") and data["kind"] not in STORE_KINDS:
            raise bad_request("Unknown store kind")
        c.update("stores", st["id"], data)
        audit(c, ctx, "store.updated", "store", st["id"], old=st, new=data, hotel_id=st["hotel_id"])
    return {"ok": True}


# ------------------------------------------------------------------ items
def _item_payload(ctx: Ctx, partial: bool) -> dict:
    b = ctx.body or {}
    data: dict = {}
    for k in ("name", "unit"):
        if k in b or not partial:
            data[k] = ctx.field(k, kind=str)
    if "barcode" in b:
        data["barcode"] = ctx.field("barcode", required=False, kind=str)
    if "category" in b or not partial:
        cat = ctx.field("category", kind=str)
        if cat not in ITEM_CATEGORIES:
            raise bad_request(f"category must be one of {', '.join(ITEM_CATEGORIES)}")
        data["category"] = cat
    if "last_cost" in b:
        data["last_cost"] = to_minor(b["last_cost"], "last_cost")
    if "sale_price" in b:
        data["sale_price"] = None if b["sale_price"] in (None, "") else to_minor(b["sale_price"], "sale_price")
    for k in ("reorder_level", "reorder_qty"):
        if k in b:
            data[k + "_milli"] = to_milli(b[k], k, allow_zero=True)
    for k in ("track_expiry", "active"):
        if k in b:
            data[k] = 1 if b[k] else 0
    return data


@route("GET", "/api/hotels/{hotel_id:int}/inventory/items", perm="inventory.view", tag="inventory",
       summary="Item catalogue with on-hand quantity, value and low-stock flag (?q, category, low=1)")
def list_items(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT i.*, COALESCE(SUM(l.quantity_milli),0) AS on_hand_milli, COALESCE(SUM(l.value),0) AS stock_value "
           "FROM inventory_items i LEFT JOIN stock_levels l ON l.item_id = i.id WHERE i.hotel_id = ?")
    params: list = [hid]
    if ctx.q("category"):
        sql += " AND i.category = ?"
        params.append(ctx.q("category"))
    if ctx.q("q"):
        sql += " AND (LOWER(i.name) LIKE ? OR LOWER(i.code) LIKE ? OR i.barcode = ?)"
        q = f"%{ctx.q('q').lower()}%"
        params += [q, q, ctx.q("q")]
    if ctx.q("active", "1") == "1":
        sql += " AND i.active = 1"
    sql += " GROUP BY i.id ORDER BY i.category, i.name"
    with get_db().tx() as c:
        rows = c.all(sql, params)
    out = []
    for r in rows:
        r["low_stock"] = r["reorder_level_milli"] > 0 and r["on_hand_milli"] <= r["reorder_level_milli"]
        r["avg_cost"] = (r["stock_value"] * 1000 // r["on_hand_milli"]) if r["on_hand_milli"] > 0 else r["last_cost"]
        if ctx.q("low") == "1" and not r["low_stock"]:
            continue
        out.append(_qty_out(r, "on_hand_milli", "reorder_level_milli", "reorder_qty_milli"))
    return {"items": out, "categories": ITEM_CATEGORIES}


@route("POST", "/api/hotels/{hotel_id:int}/inventory/items", perm="inventory.manage", tag="inventory", summary="Register an inventory item")
def create_item(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    data = _item_payload(ctx, partial=False)
    with get_db().tx() as c:
        code = ctx.field("code", required=False, kind=str)
        if not code:
            code = next_number(c, hid, "item", "ITM", 5).split("-")[-1]
            code = f"ITM{code}"
        iid = c.insert("inventory_items", {"hotel_id": hid, "code": code.upper(), "created_at": now_iso(), **data})
        audit(c, ctx, "inventory.item_created", "inventory_item", iid, code, new=ctx.body, hotel_id=hid)
    return {"id": iid, "code": code.upper(), "_created": True}


@route("PATCH", "/api/inventory/items/{item_id:int}", perm="inventory.manage", tag="inventory", summary="Edit an inventory item")
def update_item(ctx: Ctx):
    with get_db().tx() as c:
        it = c.one("SELECT * FROM inventory_items WHERE id = ?", [ctx.path["item_id"]])
        if not it:
            raise not_found("Inventory item")
        ctx.check_hotel(it["hotel_id"])
        data = _item_payload(ctx, partial=True)
        c.update("inventory_items", it["id"], data)
        audit(c, ctx, "inventory.item_updated", "inventory_item", it["id"], it["code"], old={k: it.get(k) for k in data}, new=data, hotel_id=it["hotel_id"])
    return {"ok": True}


@route("GET", "/api/inventory/items/{item_id:int}", perm="inventory.view", tag="inventory", summary="Item detail: balances per store, batches and recent movements")
def item_detail(ctx: Ctx):
    with get_db().tx() as c:
        it = c.one("SELECT * FROM inventory_items WHERE id = ?", [ctx.path["item_id"]])
        if not it:
            raise not_found("Inventory item")
        ctx.check_hotel(it["hotel_id"])
        levels = c.all("SELECT l.*, s.code AS store_code, s.name AS store_name FROM stock_levels l JOIN stores s ON s.id = l.store_id "
                       "WHERE l.item_id = ? ORDER BY s.code", [it["id"]])
        batches = c.all("SELECT b.*, s.name AS store_name FROM stock_batches b JOIN stores s ON s.id = b.store_id WHERE b.item_id = ? "
                        "AND b.quantity_milli > 0 ORDER BY b.expiry_date", [it["id"]])
        moves = c.all("SELECT m.*, s.name AS store_name, u.full_name AS user_name FROM stock_movements m JOIN stores s ON s.id = m.store_id "
                      "LEFT JOIN users u ON u.id = m.created_by WHERE m.item_id = ? ORDER BY m.id DESC LIMIT 100", [it["id"]])
    return {"item": _qty_out(it, "reorder_level_milli", "reorder_qty_milli"),
            "levels": [_qty_out(l, "quantity_milli") for l in levels],
            "batches": [_qty_out(b, "quantity_milli") for b in batches],
            "movements": [_qty_out(m, "quantity_milli", "balance_milli") for m in moves]}


# ------------------------------------------------------------------ balances & movements
@route("GET", "/api/hotels/{hotel_id:int}/inventory/stock", perm="inventory.view", tag="inventory",
       summary="Stock balances by store and item (?store_id, low=1)")
def stock_balances(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT l.item_id, l.store_id, l.quantity_milli, l.value, i.code, i.name, i.unit, i.category, i.reorder_level_milli, "
           "s.code AS store_code, s.name AS store_name FROM stock_levels l JOIN inventory_items i ON i.id = l.item_id "
           "JOIN stores s ON s.id = l.store_id WHERE i.hotel_id = ? AND i.active = 1")
    params: list = [hid]
    if ctx.q("store_id"):
        sql += " AND l.store_id = ?"
        params.append(int(ctx.q("store_id")))
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY s.code, i.category, i.name", params)
    total = sum(r["value"] for r in rows)
    return {"items": [_qty_out(r, "quantity_milli", "reorder_level_milli") for r in rows], "total_value": total}


@route("GET", "/api/hotels/{hotel_id:int}/inventory/movements", perm="inventory.view", tag="inventory",
       summary="Stock movement history (?item_id, store_id, type, from, to)")
def list_movements(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT m.*, i.code, i.name, i.unit, s.name AS store_name, u.full_name AS user_name FROM stock_movements m "
           "JOIN inventory_items i ON i.id = m.item_id JOIN stores s ON s.id = m.store_id LEFT JOIN users u ON u.id = m.created_by WHERE m.hotel_id = ?")
    params: list = [hid]
    for q, col in (("item_id", "m.item_id"), ("store_id", "m.store_id")):
        if ctx.q(q):
            sql += f" AND {col} = ?"
            params.append(int(ctx.q(q)))
    if ctx.q("type"):
        sql += " AND m.movement_type = ?"
        params.append(ctx.q("type"))
    if ctx.q("from"):
        sql += " AND m.business_date >= ?"
        params.append(ctx.q("from"))
    if ctx.q("to"):
        sql += " AND m.business_date <= ?"
        params.append(ctx.q("to"))
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY m.id DESC LIMIT 500", params)
    return {"items": [_qty_out(r, "quantity_milli", "balance_milli") for r in rows]}


@route("GET", "/api/hotels/{hotel_id:int}/inventory/alerts", perm="inventory.view", tag="inventory",
       summary="Low-stock items and batches expiring within ?days (default 30)")
def alerts(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    days = int(ctx.q("days", 30))
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        low = c.all("SELECT i.id, i.code, i.name, i.unit, i.reorder_level_milli, i.reorder_qty_milli, COALESCE(SUM(l.quantity_milli),0) AS on_hand_milli "
                    "FROM inventory_items i LEFT JOIN stock_levels l ON l.item_id = i.id WHERE i.hotel_id = ? AND i.active = 1 "
                    "AND i.reorder_level_milli > 0 GROUP BY i.id HAVING COALESCE(SUM(l.quantity_milli),0) <= i.reorder_level_milli ORDER BY i.name", [hid])
        expiring = c.all("SELECT b.*, i.code, i.name, i.unit, s.name AS store_name FROM stock_batches b JOIN inventory_items i ON i.id = b.item_id "
                         "JOIN stores s ON s.id = b.store_id WHERE i.hotel_id = ? AND b.quantity_milli > 0 AND b.expiry_date IS NOT NULL "
                         "AND b.expiry_date <= ? ORDER BY b.expiry_date", [hid, (today + dt.timedelta(days=days)).isoformat()])
    for e in expiring:
        e["expired"] = e["expiry_date"] < today.isoformat()
    return {"low_stock": [_qty_out(r, "reorder_level_milli", "reorder_qty_milli", "on_hand_milli") for r in low],
            "expiring": [_qty_out(e, "quantity_milli") for e in expiring], "as_of": today.isoformat()}


# ------------------------------------------------------------------ adjustments & wastage
@route("POST", "/api/hotels/{hotel_id:int}/inventory/adjustments", perm="inventory.adjust", tag="inventory",
       summary="Stock adjustment (direction in/out), wastage, damaged or expired stock write-off, or opening balance")
def adjust(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    kind = ctx.field("kind", required=False, default="adjustment", kind=str)
    if kind not in ("adjustment", "wastage", "opening"):
        raise bad_request("kind must be adjustment, wastage or opening")
    direction = "in" if kind == "opening" else ctx.field("direction", required=kind == "adjustment", default="out", kind=str)
    if direction not in ("in", "out"):
        raise bad_request("direction must be in or out")
    if kind == "wastage" and direction != "out":
        raise bad_request("Wastage always reduces stock")
    qty = to_milli(ctx.field("quantity"))
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        item = get_item(c, hid, ctx.field("item_id", kind=int))
        store = get_store(c, hid, ctx.field("store_id", kind=int))
        on = business_date(hotel)
        org = hotel["organisation_id"]
        if direction == "in":
            unit_cost = to_minor(ctx.field("unit_cost", required=False, default=item["last_cost"]), "unit_cost")
            value = (unit_cost * qty + 500) // 1000
            contra = account_id(c, org, "equity" if kind == "opening" else "inv_variance")
            je = post_journal(c, hid, on, f"Stock {kind} in: {item['name']} ({reason})", "inventory", item["code"], [
                (account_id(c, org, "inventory"), value, 0, None, item["name"]), (contra, 0, value, None, reason)], ctx.user_id) if value else None
            mid, _ = apply_movement(c, hid, item, store, "opening" if kind == "opening" else "adjustment", qty, value, "adjustment", item["code"],
                                    ctx.user_id, on, reason=reason, batch_no=ctx.field("batch_no", required=False, kind=str),
                                    expiry_date=ctx.field("expiry_date", required=False, kind=str), journal_entry_id=je)
        else:
            value = outflow_value(c, item, store, qty)
            je = post_journal(c, hid, on, f"Stock {kind}: {item['name']} ({reason})", "inventory", item["code"], [
                (account_id(c, org, "inv_variance"), value, 0, None, reason), (account_id(c, org, "inventory"), 0, value, None, item["name"])],
                ctx.user_id) if value else None
            mid, _ = apply_movement(c, hid, item, store, "wastage" if kind == "wastage" else "adjustment", -qty, value, "adjustment", item["code"],
                                    ctx.user_id, on, reason=reason, journal_entry_id=je)
        audit(c, ctx, f"inventory.{kind}", "stock_movement", mid, item["code"], new={**(ctx.body or {}), "value": value}, hotel_id=hid)
    return {"movement_id": mid, "value": value, "_created": True}


# ------------------------------------------------------------------ transfers
def _transfer(c, ctx: Ctx, hid: int, on: dt.date, item: dict, src: dict, dst: dict, qty: int, ref: str) -> None:
    if src["id"] == dst["id"]:
        raise bad_request("Choose two different stores")
    _, val = apply_movement(c, hid, item, src, "transfer_out", -qty, None, "transfer", ref, ctx.user_id, on, reason=f"To {dst['name']}")
    apply_movement(c, hid, item, dst, "transfer_in", qty, -val, "transfer", ref, ctx.user_id, on, reason=f"From {src['name']}")


@route("POST", "/api/hotels/{hotel_id:int}/inventory/transfers", perm="inventory.issue", tag="inventory",
       summary="Transfer stock between stores (lines: item_id, quantity)")
def transfer(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    lines = ctx.field("lines")
    if not isinstance(lines, list) or not lines:
        raise bad_request("Add at least one line")
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        src = get_store(c, hid, ctx.field("from_store_id", kind=int))
        dst = get_store(c, hid, ctx.field("to_store_id", kind=int))
        on = business_date(hotel)
        ref = next_number(c, hid, "transfer", "TRF")
        for ln in lines:
            _transfer(c, ctx, hid, on, get_item(c, hid, ln.get("item_id")), src, dst, to_milli(ln.get("quantity")), ref)
        audit(c, ctx, "inventory.transfer", "transfer", None, ref, new=ctx.body, hotel_id=hid)
    return {"reference": ref, "_created": True}


# ------------------------------------------------------------------ requisitions
def _req(c, ctx: Ctx, rid) -> dict:
    r = c.one("SELECT * FROM stock_requisitions WHERE id = ?", [int(rid)])
    if not r:
        raise not_found("Requisition")
    ctx.check_hotel(r["hotel_id"])
    return r


def _req_detail(c, r: dict) -> dict:
    r["lines"] = [_qty_out(l, "requested_milli", "issued_milli") for l in c.all(
        "SELECT l.*, i.code, i.name, i.unit, COALESCE((SELECT quantity_milli FROM stock_levels WHERE item_id = l.item_id AND store_id = ?),0) AS available_milli "
        "FROM stock_requisition_lines l JOIN inventory_items i ON i.id = l.item_id WHERE l.requisition_id = ? ORDER BY l.id",
        [r["from_store_id"], r["id"]])]
    for l in r["lines"]:
        l["available"] = from_milli(l.pop("available_milli"))
    return r


@route("GET", "/api/hotels/{hotel_id:int}/inventory/requisitions", perm="inventory.view", tag="inventory",
       summary="Stock requisitions (?status)")
def list_requisitions(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT r.*, fs.name AS from_store, ts.name AS to_store, u.full_name AS requested_by_name, a.full_name AS approved_by_name "
           "FROM stock_requisitions r JOIN stores fs ON fs.id = r.from_store_id LEFT JOIN stores ts ON ts.id = r.to_store_id "
           "JOIN users u ON u.id = r.requested_by LEFT JOIN users a ON a.id = r.approved_by WHERE r.hotel_id = ?")
    params: list = [hid]
    if ctx.q("status"):
        sql += " AND r.status = ?"
        params.append(ctx.q("status"))
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY r.id DESC LIMIT 200", params)
        return {"items": [_req_detail(c, r) for r in rows], "departments": list(DEPARTMENT_EXPENSE_KEYS)}


@route("POST", "/api/hotels/{hotel_id:int}/inventory/requisitions", perm="inventory.requisition", tag="inventory",
       summary="Request stock from a store, either for another store or for consumption by a department")
def create_requisition(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    lines = ctx.field("lines")
    if not isinstance(lines, list) or not lines:
        raise bad_request("Add at least one item")
    with get_db().tx() as c:
        src = get_store(c, hid, ctx.field("from_store_id", kind=int))
        to_store = ctx.field("to_store_id", required=False)
        dept = ctx.field("department", required=False, kind=str)
        if bool(to_store) == bool(dept):
            raise bad_request("Choose either a destination store or a consuming department")
        if to_store:
            dst = get_store(c, hid, to_store)
            if dst["id"] == src["id"]:
                raise bad_request("Choose two different stores")
        if dept and dept not in DEPARTMENT_EXPENSE_KEYS:
            raise bad_request(f"department must be one of {', '.join(DEPARTMENT_EXPENSE_KEYS)}")
        number = next_number(c, hid, "stock_requisition", "SRQ")
        rid = c.insert("stock_requisitions", {"hotel_id": hid, "number": number, "from_store_id": src["id"], "to_store_id": int(to_store) if to_store else None,
                                              "department": dept, "status": "pending", "note": ctx.field("note", required=False, kind=str),
                                              "requested_by": ctx.user_id, "created_at": now_iso()})
        for ln in lines:
            item = get_item(c, hid, ln.get("item_id"))
            c.insert("stock_requisition_lines", {"requisition_id": rid, "item_id": item["id"], "requested_milli": to_milli(ln.get("quantity"))})
        audit(c, ctx, "inventory.requisition_created", "stock_requisition", rid, number, new=ctx.body, hotel_id=hid)
    return {"id": rid, "number": number, "_created": True}


@route("POST", "/api/inventory/requisitions/{req_id:int}/decide", perm="inventory.approve", tag="inventory",
       summary="Approve or reject a stock requisition (not your own)")
def decide_requisition(ctx: Ctx):
    decision = ctx.field("decision", kind=str)
    if decision not in ("approve", "reject"):
        raise bad_request("decision must be approve or reject")
    with get_db().tx() as c:
        r = _req(c, ctx, ctx.path["req_id"])
        if r["status"] != "pending":
            raise conflict(f"This requisition is already {r['status']}")
        if r["requested_by"] == ctx.user_id:
            raise forbidden("You cannot approve your own requisition")
        note = ctx.field("note", required=decision == "reject", kind=str)
        c.update("stock_requisitions", r["id"], {"status": "approved" if decision == "approve" else "rejected", "approved_by": ctx.user_id,
                                                 "approved_at": now_iso(), "decision_note": note})
        audit(c, ctx, f"inventory.requisition_{decision}d", "stock_requisition", r["id"], r["number"], new={"note": note}, hotel_id=r["hotel_id"])
    return {"status": "approved" if decision == "approve" else "rejected"}


@route("POST", "/api/inventory/requisitions/{req_id:int}/issue", perm="inventory.issue", tag="inventory",
       summary="Issue an approved requisition (optional per-line quantities: lines[{line_id, quantity}])")
def issue_requisition(ctx: Ctx):
    with get_db().tx() as c:
        r = _req(c, ctx, ctx.path["req_id"])
        if r["status"] != "approved":
            raise conflict("Only approved requisitions can be issued")
        hid = r["hotel_id"]
        hotel = get_hotel(c, hid)
        on = business_date(hotel)
        src = get_store(c, hid, r["from_store_id"])
        overrides = {int(l["line_id"]): to_milli(l.get("quantity"), allow_zero=True) for l in (ctx.field("lines", required=False) or [])}
        total = 0
        for ln in c.all("SELECT * FROM stock_requisition_lines WHERE requisition_id = ?", [r["id"]]):
            qty = overrides.get(ln["id"], ln["requested_milli"])
            if qty > ln["requested_milli"]:
                raise bad_request("You cannot issue more than was requested")
            if qty == 0:
                continue
            item = get_item(c, hid, ln["item_id"])
            if r["to_store_id"]:
                _transfer(c, ctx, hid, on, item, src, get_store(c, hid, r["to_store_id"]), qty, r["number"])
            else:
                _, val = apply_movement(c, hid, item, src, "issue", -qty, None, "requisition", r["number"], ctx.user_id, on,
                                        department=r["department"], reason=f"Issued to {r['department']}")
                total += -val
            c.execute("UPDATE stock_requisition_lines SET issued_milli = ? WHERE id = ?", [qty, ln["id"]])
        je = None
        if total:
            org = hotel["organisation_id"]
            je = post_journal(c, hid, on, f"Stock issued to {r['department']} ({r['number']})", "inventory", r["number"], [
                (account_id(c, org, DEPARTMENT_EXPENSE_KEYS[r["department"]]), total, 0, r["department"], r["number"]),
                (account_id(c, org, "inventory"), 0, total, r["department"], r["number"])], ctx.user_id)
        c.update("stock_requisitions", r["id"], {"status": "issued", "issued_by": ctx.user_id, "issued_at": now_iso()})
        audit(c, ctx, "inventory.requisition_issued", "stock_requisition", r["id"], r["number"], new={"value": total, "journal": je}, hotel_id=hid)
    return {"status": "issued", "value": total, "journal_entry_id": je}


# ------------------------------------------------------------------ stock counts
@route("GET", "/api/hotels/{hotel_id:int}/inventory/counts", perm="inventory.view", tag="inventory", summary="Stock counts (stocktaking)")
def list_counts(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": c.all("SELECT k.*, s.name AS store_name, u.full_name AS created_by_name, "
                               "(SELECT COUNT(*) FROM stock_count_lines WHERE count_id = k.id) AS lines "
                               "FROM stock_counts k JOIN stores s ON s.id = k.store_id JOIN users u ON u.id = k.created_by "
                               "WHERE k.hotel_id = ? ORDER BY k.id DESC LIMIT 100", [hid])}


@route("POST", "/api/hotels/{hotel_id:int}/inventory/counts", perm="inventory.adjust", tag="inventory",
       summary="Start a stock count for a store (snapshots current balances; optional category)")
def create_count(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        store = get_store(c, hid, ctx.field("store_id", kind=int))
        sql = ("SELECT i.id, COALESCE(l.quantity_milli,0) AS q FROM inventory_items i LEFT JOIN stock_levels l ON l.item_id = i.id AND l.store_id = ? "
               "WHERE i.hotel_id = ? AND i.active = 1")
        params: list = [store["id"], hid]
        if ctx.field("category", required=False):
            sql += " AND i.category = ?"
            params.append(ctx.field("category", kind=str))
        if not ctx.field("include_zero", required=False, default=False):
            sql += " AND l.id IS NOT NULL"
        items = c.all(sql, params)
        if not items:
            raise bad_request("There are no items to count in this store")
        number = next_number(c, hid, "stock_count", "CNT")
        cid = c.insert("stock_counts", {"hotel_id": hid, "number": number, "store_id": store["id"], "status": "draft",
                                        "note": ctx.field("note", required=False, kind=str), "created_by": ctx.user_id, "created_at": now_iso()})
        for it in items:
            c.insert("stock_count_lines", {"count_id": cid, "item_id": it["id"], "system_milli": it["q"]})
        audit(c, ctx, "inventory.count_started", "stock_count", cid, number, hotel_id=hid)
    return {"id": cid, "number": number, "_created": True}


def _count(c, ctx: Ctx, cid) -> dict:
    k = c.one("SELECT k.*, s.name AS store_name FROM stock_counts k JOIN stores s ON s.id = k.store_id WHERE k.id = ?", [int(cid)])
    if not k:
        raise not_found("Stock count")
    ctx.check_hotel(k["hotel_id"])
    return k


@route("GET", "/api/inventory/counts/{count_id:int}", perm="inventory.view", tag="inventory", summary="Stock count sheet")
def get_count(ctx: Ctx):
    with get_db().tx() as c:
        k = _count(c, ctx, ctx.path["count_id"])
        lines = c.all("SELECT l.*, i.code, i.name, i.unit, i.category, COALESCE(sl.quantity_milli,0) AS current_milli, "
                      "COALESCE(sl.value,0) AS current_value FROM stock_count_lines l JOIN inventory_items i ON i.id = l.item_id "
                      "LEFT JOIN stock_levels sl ON sl.item_id = l.item_id AND sl.store_id = ? WHERE l.count_id = ? ORDER BY i.category, i.name",
                      [k["store_id"], k["id"]])
    for l in lines:
        l["variance_milli"] = None if l["counted_milli"] is None else l["counted_milli"] - (l["current_milli"] if k["status"] == "draft" else l["system_milli"])
        _qty_out(l, "system_milli", "counted_milli", "current_milli", "variance_milli")
    return {"count": k, "lines": lines}


@route("PUT", "/api/inventory/counts/{count_id:int}/lines", perm="inventory.adjust", tag="inventory",
       summary="Record counted quantities: lines[{item_id, counted}]")
def save_count_lines(ctx: Ctx):
    with get_db().tx() as c:
        k = _count(c, ctx, ctx.path["count_id"])
        if k["status"] != "draft":
            raise conflict("This count has already been posted")
        for ln in ctx.field("lines") or []:
            counted = None if ln.get("counted") in (None, "") else to_milli(ln["counted"], "counted", allow_zero=True)
            c.execute("UPDATE stock_count_lines SET counted_milli = ? WHERE count_id = ? AND item_id = ?", [counted, k["id"], int(ln["item_id"])])
    return {"ok": True}


@route("POST", "/api/inventory/counts/{count_id:int}/post", perm="inventory.adjust", tag="inventory",
       summary="Post a stock count: adjusts balances to counted quantities and journals the variance")
def post_count(ctx: Ctx):
    with get_db().tx() as c:
        k = _count(c, ctx, ctx.path["count_id"])
        if k["status"] != "draft":
            raise conflict("This count has already been posted")
        hid = k["hotel_id"]
        hotel = get_hotel(c, hid)
        on = business_date(hotel)
        store = get_store(c, hid, k["store_id"])
        lines = c.all("SELECT * FROM stock_count_lines WHERE count_id = ?", [k["id"]])
        if any(l["counted_milli"] is None for l in lines):
            raise bad_request("Enter a counted quantity for every line before posting (enter 0 for none)")
        gain = loss = 0
        adjusted = 0
        for l in lines:
            item = get_item(c, hid, l["item_id"])
            cur = c.scalar("SELECT quantity_milli FROM stock_levels WHERE item_id = ? AND store_id = ?", [item["id"], store["id"]]) or 0
            diff = l["counted_milli"] - cur
            if diff == 0:
                continue
            if diff > 0:
                avg = c.one("SELECT * FROM stock_levels WHERE item_id = ? AND store_id = ?", [item["id"], store["id"]])
                unit = (avg["value"] * 1000 // avg["quantity_milli"]) if avg and avg["quantity_milli"] > 0 else item["last_cost"]
                val = (unit * diff + 500) // 1000
                apply_movement(c, hid, item, store, "count", diff, val, "stock_count", k["number"], ctx.user_id, on, reason="Count surplus")
                gain += val
            else:
                _, val = apply_movement(c, hid, item, {**store, "allow_negative": 1}, "count", diff, None, "stock_count", k["number"], ctx.user_id, on,
                                        reason="Count shortage")
                loss += -val
            adjusted += 1
        org = hotel["organisation_id"]
        net = gain - loss
        je = None
        if net:
            inv, var = account_id(c, org, "inventory"), account_id(c, org, "inv_variance")
            je = post_journal(c, hid, on, f"Stock count variance {k['number']} ({store['name']})", "inventory", k["number"],
                              [(inv, net, 0, None, "Count variance"), (var, 0, net, None, "Count variance")] if net > 0 else
                              [(var, -net, 0, None, "Count variance"), (inv, 0, -net, None, "Count variance")], ctx.user_id)
        c.update("stock_counts", k["id"], {"status": "posted", "posted_by": ctx.user_id, "posted_at": now_iso()})
        audit(c, ctx, "inventory.count_posted", "stock_count", k["id"], k["number"], new={"gain": gain, "loss": loss, "lines_adjusted": adjusted},
              hotel_id=hid)
    return {"status": "posted", "gain": gain, "loss": loss, "lines_adjusted": adjusted, "journal_entry_id": je}


@route("GET", "/api/hotels/{hotel_id:int}/inventory/costing", perm="inventory.view", tag="inventory", summary="Stock costing method (wac or fifo)")
def get_costing(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    from ..stock import costing_method
    with get_db().tx() as c:
        return {"method": costing_method(c, hid)}


@route("PUT", "/api/hotels/{hotel_id:int}/inventory/costing", perm="inventory.manage", tag="inventory",
       summary="Choose weighted-average (wac) or FIFO costing ({method, reason}); applies to issues from now on and needs accounting.view")
def set_costing(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    ctx.require("accounting.view")
    method = ctx.field("method", kind=str)
    if method not in ("wac", "fifo"):
        raise bad_request("method must be wac or fifo")
    reason = ctx.field("reason", kind=str)
    from ..services import set_hotel_setting
    from ..stock import costing_method
    with get_db().tx() as c:
        old = costing_method(c, hid)
        set_hotel_setting(c, hid, "inventory.costing", method)
        audit(c, ctx, "inventory.costing_changed", "hotel", hid, None, old={"method": old}, new={"method": method, "reason": reason}, hotel_id=hid)
    return {"method": method}
