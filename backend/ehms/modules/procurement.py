"""Procurement & suppliers: supplier register and performance, purchase requisitions, quotation comparison,
purchase orders with amount-based approval, goods received notes (GRN), three-way matched supplier invoices
and supplier payments with withholding tax. (FR-PRO-001..004)

Accounting (accrual):
  GRN            Dr Inventory (stock lines) / Dr expense (service lines)   Cr Goods Received Not Invoiced
  Invoice (on approval)   Dr GRNI (received value) +/- Purchase Price Variance   Cr Accounts Payable
  Payment        Dr Accounts Payable (gross)   Cr Cash/Bank (net)   Cr Withholding Tax Payable
Every approval enforces maker-checker (the requester cannot approve their own document)."""
from __future__ import annotations

import datetime as dt

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import (EXPENSE_KEYS, account_id, business_date, from_milli, get_hotel, hotel_setting, next_number, parse_date, post_journal,
                        set_hotel_setting, to_milli, to_minor)
from ..stock import apply_movement, get_item, get_store

DEFAULT_HIGH_VALUE = 50_000_000      # NGN 500,000.00
DEFAULT_TOLERANCE_BP = 50            # 0.5 % invoice-to-receipt tolerance


def _val(qty_milli: int, unit_cost: int) -> int:
    return (qty_milli * unit_cost + 500) // 1000


def _settings(c, hid: int) -> dict:
    return {"high_value_threshold": int(hotel_setting(c, hid, "procurement.high_value_threshold", str(DEFAULT_HIGH_VALUE))),
            "invoice_tolerance_bp": int(hotel_setting(c, hid, "procurement.invoice_tolerance_bp", str(DEFAULT_TOLERANCE_BP)))}


@route("GET", "/api/hotels/{hotel_id:int}/procurement/settings", perm="procurement.view", tag="procurement", summary="Procurement approval settings")
def get_settings(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return _settings(c, hid)


@route("PUT", "/api/hotels/{hotel_id:int}/procurement/settings", perm="admin.settings.manage", tag="procurement",
       summary="Set the high-value PO approval threshold and invoice matching tolerance")
def put_settings(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        old = _settings(c, hid)
        if "high_value_threshold" in (ctx.body or {}):
            v = to_minor(ctx.body["high_value_threshold"], "high_value_threshold")
            if v <= 0:
                raise bad_request("The threshold must be greater than zero")
            set_hotel_setting(c, hid, "procurement.high_value_threshold", str(v))
        if "invoice_tolerance_bp" in (ctx.body or {}):
            v = int(ctx.body["invoice_tolerance_bp"])
            if not 0 <= v <= 1000:
                raise bad_request("Tolerance must be between 0 and 1000 basis points (0–10%)")
            set_hotel_setting(c, hid, "procurement.invoice_tolerance_bp", str(v))
        new = _settings(c, hid)
        audit(c, ctx, "procurement.settings", "system_settings", hid, old=old, new=new, hotel_id=hid)
    return new


# ------------------------------------------------------------------ suppliers
def _mask(acct: str | None) -> str | None:
    return None if not acct else ("•" * max(0, len(acct) - 4)) + acct[-4:]


@route("GET", "/api/hotels/{hotel_id:int}/procurement/suppliers", perm="procurement.view", tag="procurement",
       summary="Suppliers with balance owed by this hotel and delivery performance")
def list_suppliers(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        rows = c.all("SELECT * FROM suppliers WHERE organisation_id = ? ORDER BY name", [ctx.org_id])
        for s in rows:
            s["balance"] = c.scalar("SELECT COALESCE(SUM(amount - amount_paid),0) FROM supplier_invoices WHERE supplier_id = ? AND hotel_id = ? "
                                    "AND status IN ('approved','part_paid')", [s["id"], hid])
            grns = c.all("SELECT g.received_at, g.business_date, po.expected_date, (SELECT COALESCE(SUM(received_milli),0) FROM goods_receipt_lines WHERE grn_id = g.id) AS rec, "
                         "(SELECT COALESCE(SUM(rejected_milli),0) FROM goods_receipt_lines WHERE grn_id = g.id) AS rej FROM goods_receipts g "
                         "JOIN purchase_orders po ON po.id = g.po_id WHERE g.supplier_id = ? AND g.hotel_id = ?", [s["id"], hid])
            on_time = sum(1 for g in grns if not g["expected_date"] or g["business_date"] <= g["expected_date"])
            rec, rej = sum(g["rec"] for g in grns), sum(g["rej"] for g in grns)
            s["performance"] = {"deliveries": len(grns), "on_time_pct": round(on_time * 100 / len(grns)) if grns else None,
                                "rejected_pct": round(rej * 100 / (rec + rej), 1) if rec + rej else None,
                                "orders": c.scalar("SELECT COUNT(*) FROM purchase_orders WHERE supplier_id = ? AND hotel_id = ?", [s["id"], hid])}
            if not (ctx.can("procurement.suppliers") or ctx.can("procurement.pay")):
                s["bank_account_number"] = _mask(s["bank_account_number"])
    return {"items": rows}


_SUP_FIELDS = ("name", "category", "contact_name", "phone", "email", "address", "tax_id", "bank_name", "bank_account_name", "bank_account_number")


@route("POST", "/api/hotels/{hotel_id:int}/procurement/suppliers", perm="procurement.suppliers", tag="procurement", summary="Register a supplier")
def create_supplier(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    data = {k: ctx.field(k, required=k == "name", kind=str) for k in _SUP_FIELDS}
    data["payment_terms_days"] = ctx.field("payment_terms_days", required=False, default=30, kind=int)
    data["wht_bp"] = ctx.field("wht_bp", required=False, default=0, kind=int)
    if not 0 <= data["wht_bp"] <= 2000:
        raise bad_request("Withholding tax rate must be between 0 and 2000 basis points (0–20%)")
    with get_db().tx() as c:
        code = (ctx.field("code", required=False, kind=str) or f"SUP{next_number(c, hid, 'supplier', 'S', 4).split('-')[-1]}").upper()
        sid = c.insert("suppliers", {"organisation_id": ctx.org_id, "code": code, "active": 1, "created_at": now_iso(), **data})
        audit(c, ctx, "supplier.created", "supplier", sid, code, new={**data, "bank_account_number": _mask(data["bank_account_number"])}, hotel_id=hid)
    return {"id": sid, "code": code, "_created": True}


@route("PATCH", "/api/procurement/suppliers/{supplier_id:int}", perm="procurement.suppliers", tag="procurement", summary="Edit or deactivate a supplier")
def update_supplier(ctx: Ctx):
    with get_db().tx() as c:
        s = c.one("SELECT * FROM suppliers WHERE id = ? AND organisation_id = ?", [ctx.path["supplier_id"], ctx.org_id])
        if not s:
            raise not_found("Supplier")
        b = ctx.body or {}
        data = {k: (str(b[k]).strip() or None) if b[k] is not None else None for k in _SUP_FIELDS if k in b}
        if "name" in data and not data["name"]:
            raise bad_request("Name is required")
        for k in ("payment_terms_days", "wht_bp"):
            if k in b:
                data[k] = int(b[k])
        if "wht_bp" in data and not 0 <= data["wht_bp"] <= 2000:
            raise bad_request("Withholding tax rate must be between 0 and 2000 basis points")
        if "active" in b:
            data["active"] = 1 if b["active"] else 0
        c.update("suppliers", s["id"], data)
        audit(c, ctx, "supplier.updated", "supplier", s["id"], s["code"], old={k: s.get(k) for k in data if k != "bank_account_number"},
              new={k: v for k, v in data.items() if k != "bank_account_number"})
    return {"ok": True}


def _supplier(c, ctx: Ctx, sid) -> dict:
    s = c.one("SELECT * FROM suppliers WHERE id = ? AND organisation_id = ?", [int(sid), ctx.org_id])
    if not s:
        raise bad_request("Supplier not found")
    if not s["active"]:
        raise conflict(f"Supplier {s['name']} is inactive")
    return s


# ------------------------------------------------------------------ purchase requisitions
def _preq(c, ctx: Ctx, rid) -> dict:
    r = c.one("SELECT * FROM purchase_requisitions WHERE id = ?", [int(rid)])
    if not r:
        raise not_found("Purchase requisition")
    ctx.check_hotel(r["hotel_id"])
    return r


def _preq_lines(c, rid: int) -> list[dict]:
    rows = c.all("SELECT l.*, i.code AS item_code, i.unit FROM purchase_requisition_lines l LEFT JOIN inventory_items i ON i.id = l.item_id "
                 "WHERE l.requisition_id = ? ORDER BY l.id", [rid])
    for r in rows:
        r["quantity"] = from_milli(r.pop("quantity_milli"))
    return rows


@route("GET", "/api/hotels/{hotel_id:int}/procurement/requisitions", perm="procurement.view", tag="procurement", summary="Purchase requisitions (?status)")
def list_preqs(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT r.*, u.full_name AS requested_by_name, a.full_name AS approved_by_name, s.name AS store_name, "
           "(SELECT COUNT(*) FROM supplier_quotes q WHERE q.requisition_id = r.id) AS quotes FROM purchase_requisitions r "
           "JOIN users u ON u.id = r.requested_by LEFT JOIN users a ON a.id = r.approved_by LEFT JOIN stores s ON s.id = r.store_id WHERE r.hotel_id = ?")
    params: list = [hid]
    if ctx.q("status"):
        sql += " AND r.status = ?"
        params.append(ctx.q("status"))
    with get_db().tx() as c:
        return {"items": c.all(sql + " ORDER BY r.id DESC LIMIT 200", params)}


@route("POST", "/api/hotels/{hotel_id:int}/procurement/requisitions", perm="procurement.requisition", tag="procurement",
       summary="Raise a purchase requisition: lines[{item_id or description, quantity, est_unit_cost}]")
def create_preq(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    lines = ctx.field("lines")
    if not isinstance(lines, list) or not lines:
        raise bad_request("Add at least one line")
    with get_db().tx() as c:
        store = ctx.field("store_id", required=False)
        if store:
            get_store(c, hid, store)
        number = next_number(c, hid, "purchase_requisition", "PRQ")
        needed = ctx.field("needed_by", required=False)
        rid = c.insert("purchase_requisitions", {"hotel_id": hid, "number": number, "department": ctx.field("department", kind=str),
                                                 "store_id": int(store) if store else None, "status": "submitted",
                                                 "needed_by": parse_date(needed, "needed_by").isoformat() if needed else None,
                                                 "justification": ctx.field("justification", required=False, kind=str), "requested_by": ctx.user_id,
                                                 "created_at": now_iso()})
        total = 0
        for ln in lines:
            item = get_item(c, hid, ln["item_id"]) if ln.get("item_id") else None
            desc = (ln.get("description") or (item["name"] if item else "")).strip()
            if not desc:
                raise bad_request("Each line needs an item or a description")
            q = to_milli(ln.get("quantity"))
            cost = to_minor(ln.get("est_unit_cost", item["last_cost"] if item else 0), "est_unit_cost")
            c.insert("purchase_requisition_lines", {"requisition_id": rid, "item_id": item["id"] if item else None, "description": desc[:200],
                                                    "quantity_milli": q, "est_unit_cost": cost})
            total += _val(q, cost)
        c.update("purchase_requisitions", rid, {"estimated_total": total})
        audit(c, ctx, "procurement.requisition_created", "purchase_requisition", rid, number, new=ctx.body, hotel_id=hid)
    return {"id": rid, "number": number, "estimated_total": total, "_created": True}


@route("GET", "/api/procurement/requisitions/{req_id:int}", perm="procurement.view", tag="procurement",
       summary="Requisition with lines, quotations and a price comparison (cheapest supplier per line)")
def get_preq(ctx: Ctx):
    with get_db().tx() as c:
        r = _preq(c, ctx, ctx.path["req_id"])
        r["lines"] = _preq_lines(c, r["id"])
        quotes = c.all("SELECT q.*, s.name AS supplier_name FROM supplier_quotes q JOIN suppliers s ON s.id = q.supplier_id WHERE q.requisition_id = ? "
                       "ORDER BY q.total", [r["id"]])
        for q in quotes:
            q["lines"] = {l["requisition_line_id"]: l["unit_cost"] for l in c.all("SELECT * FROM supplier_quote_lines WHERE quote_id = ?", [q["id"]])}
        r["quotes"] = quotes
        r["comparison"] = []
        for l in r["lines"]:
            offers = [{"quote_id": q["id"], "supplier": q["supplier_name"], "unit_cost": q["lines"].get(l["id"])} for q in quotes if l["id"] in q["lines"]]
            best = min(offers, key=lambda o: o["unit_cost"]) if offers else None
            r["comparison"].append({"line_id": l["id"], "description": l["description"], "quantity": l["quantity"], "offers": offers,
                                    "best_quote_id": best["quote_id"] if best else None})
        r["purchase_orders"] = c.all("SELECT id, number, status, total FROM purchase_orders WHERE requisition_id = ?", [r["id"]])
    return r


@route("POST", "/api/procurement/requisitions/{req_id:int}/decide", perm="procurement.approve", tag="procurement",
       summary="Approve or reject a purchase requisition (not your own)")
def decide_preq(ctx: Ctx):
    decision = ctx.field("decision", kind=str)
    if decision not in ("approve", "reject"):
        raise bad_request("decision must be approve or reject")
    with get_db().tx() as c:
        r = _preq(c, ctx, ctx.path["req_id"])
        if r["status"] != "submitted":
            raise conflict(f"This requisition is already {r['status']}")
        if r["requested_by"] == ctx.user_id:
            raise forbidden("You cannot approve your own requisition")
        note = ctx.field("note", required=decision == "reject", kind=str)
        c.update("purchase_requisitions", r["id"], {"status": "approved" if decision == "approve" else "rejected", "approved_by": ctx.user_id,
                                                    "decision_note": note, "decided_at": now_iso()})
        audit(c, ctx, f"procurement.requisition_{decision}d", "purchase_requisition", r["id"], r["number"], new={"note": note}, hotel_id=r["hotel_id"])
    return {"status": "approved" if decision == "approve" else "rejected"}


@route("POST", "/api/procurement/requisitions/{req_id:int}/quotes", perm="procurement.order", tag="procurement",
       summary="Record a supplier quotation against an approved requisition: lines[{requisition_line_id, unit_cost}]")
def add_quote(ctx: Ctx):
    with get_db().tx() as c:
        r = _preq(c, ctx, ctx.path["req_id"])
        if r["status"] != "approved":
            raise conflict("Quotations can only be recorded for approved requisitions")
        s = _supplier(c, ctx, ctx.field("supplier_id", kind=int))
        lines = {l["id"]: l for l in c.all("SELECT * FROM purchase_requisition_lines WHERE requisition_id = ?", [r["id"]])}
        given = ctx.field("lines") or []
        total = 0
        parsed = []
        for ln in given:
            lid = int(ln.get("requisition_line_id") or 0)
            if lid not in lines:
                raise bad_request("Quotation line does not belong to this requisition")
            cost = to_minor(ln.get("unit_cost"), "unit_cost")
            parsed.append((lid, cost))
            total += _val(lines[lid]["quantity_milli"], cost)
        if not parsed:
            raise bad_request("Enter a price for at least one line")
        vu = ctx.field("valid_until", required=False)
        qid = c.insert("supplier_quotes", {"hotel_id": r["hotel_id"], "requisition_id": r["id"], "supplier_id": s["id"],
                                           "reference": ctx.field("reference", required=False, kind=str),
                                           "valid_until": parse_date(vu, "valid_until").isoformat() if vu else None,
                                           "delivery_days": ctx.field("delivery_days", required=False, kind=int), "total": total, "status": "received",
                                           "note": ctx.field("note", required=False, kind=str), "created_by": ctx.user_id, "created_at": now_iso()})
        for lid, cost in parsed:
            c.insert("supplier_quote_lines", {"quote_id": qid, "requisition_line_id": lid, "unit_cost": cost})
        audit(c, ctx, "procurement.quote_recorded", "supplier_quote", qid, r["number"], new={"supplier": s["code"], "total": total}, hotel_id=r["hotel_id"])
    return {"id": qid, "total": total, "_created": True}


# ------------------------------------------------------------------ purchase orders
def _po(c, ctx: Ctx, po_id, lock: bool = False) -> dict:
    po = c.lock("purchase_orders", int(po_id)) if lock else c.one("SELECT * FROM purchase_orders WHERE id = ?", [int(po_id)])
    if not po:
        raise not_found("Purchase order")
    ctx.check_hotel(po["hotel_id"])
    return po


def _po_lines(c, po_id: int) -> list[dict]:
    rows = c.all("SELECT l.*, i.code AS item_code, i.unit, i.track_expiry FROM purchase_order_lines l LEFT JOIN inventory_items i ON i.id = l.item_id "
                 "WHERE l.po_id = ? ORDER BY l.id", [po_id])
    for r in rows:
        r["outstanding"] = from_milli(r["quantity_milli"] - r["received_milli"])
        r["quantity"] = from_milli(r.pop("quantity_milli"))
        r["received"] = from_milli(r.pop("received_milli"))
        r["line_total"] = round(r["quantity"] * r["unit_cost"])
    return rows


@route("GET", "/api/hotels/{hotel_id:int}/procurement/purchase-orders", perm="procurement.view", tag="procurement",
       summary="Purchase orders (?status, ?supplier_id)")
def list_pos(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT po.*, s.name AS supplier_name, st.name AS store_name, u.full_name AS created_by_name, a.full_name AS approved_by_name "
           "FROM purchase_orders po JOIN suppliers s ON s.id = po.supplier_id JOIN stores st ON st.id = po.store_id JOIN users u ON u.id = po.created_by "
           "LEFT JOIN users a ON a.id = po.approved_by WHERE po.hotel_id = ?")
    params: list = [hid]
    if ctx.q("status"):
        st = ctx.q("status").split(",")
        sql += f" AND po.status IN ({','.join('?' for _ in st)})"
        params += st
    if ctx.q("supplier_id"):
        sql += " AND po.supplier_id = ?"
        params.append(int(ctx.q("supplier_id")))
    with get_db().tx() as c:
        return {"items": c.all(sql + " ORDER BY po.id DESC LIMIT 300", params), "settings": _settings(c, hid)}


@route("POST", "/api/hotels/{hotel_id:int}/procurement/purchase-orders", perm="procurement.order", tag="procurement",
       summary="Raise a purchase order (from a quotation, a requisition, or direct lines[{item_id|description, quantity, unit_cost, expense_key}])")
def create_po(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        store = get_store(c, hid, ctx.field("store_id", kind=int))
        quote = None
        req = None
        if ctx.field("quote_id", required=False):
            quote = c.one("SELECT * FROM supplier_quotes WHERE id = ? AND hotel_id = ?", [ctx.field("quote_id", kind=int), hid])
            if not quote:
                raise bad_request("Quotation not found")
            req = c.one("SELECT * FROM purchase_requisitions WHERE id = ?", [quote["requisition_id"]])
            supplier = _supplier(c, ctx, quote["supplier_id"])
        else:
            supplier = _supplier(c, ctx, ctx.field("supplier_id", kind=int))
            if ctx.field("requisition_id", required=False):
                req = _preq(c, ctx, ctx.field("requisition_id", kind=int))
        if req and req["status"] != "approved":
            raise conflict(f"Requisition {req['number']} is {req['status']}; only approved requisitions can be ordered")
        lines: list[dict] = []
        if quote:
            for ql in c.all("SELECT q.unit_cost, l.* FROM supplier_quote_lines q JOIN purchase_requisition_lines l ON l.id = q.requisition_line_id "
                            "WHERE q.quote_id = ?", [quote["id"]]):
                lines.append({"item_id": ql["item_id"], "description": ql["description"], "quantity_milli": ql["quantity_milli"], "unit_cost": ql["unit_cost"],
                              "expense_key": None if ql["item_id"] else ctx.field("expense_key", required=False, default="exp_admin", kind=str)})
        elif req and not ctx.field("lines", required=False):
            for l in c.all("SELECT * FROM purchase_requisition_lines WHERE requisition_id = ?", [req["id"]]):
                lines.append({"item_id": l["item_id"], "description": l["description"], "quantity_milli": l["quantity_milli"], "unit_cost": l["est_unit_cost"],
                              "expense_key": None if l["item_id"] else ctx.field("expense_key", required=False, default="exp_admin", kind=str)})
        else:
            for ln in ctx.field("lines") or []:
                item = get_item(c, hid, ln["item_id"]) if ln.get("item_id") else None
                desc = (ln.get("description") or (item["name"] if item else "")).strip()
                if not desc:
                    raise bad_request("Each line needs an item or a description")
                lines.append({"item_id": item["id"] if item else None, "description": desc[:200], "quantity_milli": to_milli(ln.get("quantity")),
                              "unit_cost": to_minor(ln.get("unit_cost"), "unit_cost"), "expense_key": None if item else (ln.get("expense_key") or "exp_admin")})
        if not lines:
            raise bad_request("A purchase order needs at least one line")
        for l in lines:
            if l["expense_key"] and l["expense_key"] not in EXPENSE_KEYS:
                raise bad_request(f"expense_key must be one of {', '.join(EXPENSE_KEYS)}")
        total = sum(_val(l["quantity_milli"], l["unit_cost"]) for l in lines)
        level = "high" if total > _settings(c, hid)["high_value_threshold"] else "standard"
        number = next_number(c, hid, "purchase_order", "PO")
        exp = ctx.field("expected_date", required=False)
        po_id = c.insert("purchase_orders", {"hotel_id": hid, "number": number, "supplier_id": supplier["id"], "requisition_id": req["id"] if req else None,
                                             "quote_id": quote["id"] if quote else None, "store_id": store["id"], "status": "pending_approval",
                                             "order_date": business_date(hotel).isoformat(), "expected_date": parse_date(exp, "expected_date").isoformat() if exp else None,
                                             "total": total, "approval_level": level, "note": ctx.field("note", required=False, kind=str),
                                             "created_by": ctx.user_id, "created_at": now_iso()})
        for l in lines:
            c.insert("purchase_order_lines", {"po_id": po_id, **l})
        if req:
            c.update("purchase_requisitions", req["id"], {"status": "ordered"})
        if quote:
            c.execute("UPDATE supplier_quotes SET status = CASE WHEN id = ? THEN 'selected' ELSE 'rejected' END WHERE requisition_id = ?",
                      [quote["id"], quote["requisition_id"]])
        audit(c, ctx, "procurement.po_created", "purchase_order", po_id, number, new={"supplier": supplier["code"], "total": total, "level": level}, hotel_id=hid)
    return {"id": po_id, "number": number, "total": total, "approval_level": level, "_created": True}


@route("GET", "/api/procurement/purchase-orders/{po_id:int}", perm="procurement.view", tag="procurement",
       summary="Purchase order with lines, goods received and invoices")
def get_po(ctx: Ctx):
    with get_db().tx() as c:
        po = _po(c, ctx, ctx.path["po_id"])
        po["supplier"] = c.one("SELECT id, code, name, email, phone, wht_bp, payment_terms_days FROM suppliers WHERE id = ?", [po["supplier_id"]])
        po["store"] = c.one("SELECT id, code, name FROM stores WHERE id = ?", [po["store_id"]])
        po["lines"] = _po_lines(c, po["id"])
        po["receipts"] = c.all("SELECT g.*, u.full_name AS received_by_name FROM goods_receipts g JOIN users u ON u.id = g.received_by WHERE g.po_id = ? "
                               "ORDER BY g.id", [po["id"]])
        po["invoices"] = c.all("SELECT * FROM supplier_invoices WHERE po_id = ? ORDER BY id", [po["id"]])
        po["received_value"] = sum(g["value"] for g in po["receipts"])
        po["created_by_name"] = c.scalar("SELECT full_name FROM users WHERE id = ?", [po["created_by"]])
        po["approved_by_name"] = c.scalar("SELECT full_name FROM users WHERE id = ?", [po["approved_by"]]) if po["approved_by"] else None
    return po


@route("POST", "/api/procurement/purchase-orders/{po_id:int}/decide", perm="procurement.approve", tag="procurement",
       summary="Approve or reject a purchase order; orders above the high-value threshold need procurement.approve_high")
def decide_po(ctx: Ctx):
    decision = ctx.field("decision", kind=str)
    if decision not in ("approve", "reject"):
        raise bad_request("decision must be approve or reject")
    with get_db().tx() as c:
        po = _po(c, ctx, ctx.path["po_id"], lock=True)
        if po["status"] != "pending_approval":
            raise conflict(f"This purchase order is {po['status'].replace('_', ' ')}")
        if po["created_by"] == ctx.user_id:
            raise forbidden("You cannot approve a purchase order you raised")
        if po["approval_level"] == "high" and decision == "approve":
            ctx.require("procurement.approve_high")
        note = ctx.field("note", required=decision == "reject", kind=str)
        c.update("purchase_orders", po["id"], {"status": "approved" if decision == "approve" else "rejected", "approved_by": ctx.user_id,
                                               "approved_at": now_iso(), "decision_note": note})
        if decision == "reject" and po["requisition_id"]:
            c.update("purchase_requisitions", po["requisition_id"], {"status": "approved"})
        audit(c, ctx, f"procurement.po_{decision}d", "purchase_order", po["id"], po["number"], new={"note": note, "total": po["total"]}, hotel_id=po["hotel_id"])
    return {"status": "approved" if decision == "approve" else "rejected"}


@route("POST", "/api/procurement/purchase-orders/{po_id:int}/cancel", perm="procurement.order", tag="procurement",
       summary="Cancel a purchase order (nothing received), or close a partially received order short")
def cancel_po(ctx: Ctx):
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        po = _po(c, ctx, ctx.path["po_id"], lock=True)
        if po["status"] in ("received", "closed", "cancelled", "rejected"):
            raise conflict(f"This purchase order is already {po['status']}")
        new = "closed" if po["status"] == "partially_received" else "cancelled"
        c.update("purchase_orders", po["id"], {"status": new, "decision_note": reason})
        if new == "cancelled" and po["requisition_id"]:
            c.update("purchase_requisitions", po["requisition_id"], {"status": "approved"})
        audit(c, ctx, f"procurement.po_{new}", "purchase_order", po["id"], po["number"], new={"reason": reason}, hotel_id=po["hotel_id"])
    return {"status": new}


@route("POST", "/api/procurement/purchase-orders/{po_id:int}/receive", perm="procurement.receive", tag="procurement",
       summary="Goods received note: lines[{po_line_id, quantity, rejected, batch_no, expiry_date}] — stock lines go into the PO's store")
def receive(ctx: Ctx):
    lines = ctx.field("lines")
    if not isinstance(lines, list) or not lines:
        raise bad_request("Enter the quantities received")
    with get_db().tx() as c:
        po = _po(c, ctx, ctx.path["po_id"], lock=True)
        if po["status"] not in ("approved", "partially_received"):
            raise conflict("Goods can only be received against an approved purchase order" if po["status"] == "pending_approval"
                           else f"This purchase order is {po['status']}")
        hid = po["hotel_id"]
        hotel = get_hotel(c, hid)
        on = business_date(hotel)
        store = get_store(c, hid, po["store_id"])
        po_lines = {l["id"]: l for l in c.all("SELECT * FROM purchase_order_lines WHERE po_id = ?", [po["id"]])}
        number = next_number(c, hid, "grn", "GRN")
        grn_id = c.insert("goods_receipts", {"hotel_id": hid, "number": number, "po_id": po["id"], "supplier_id": po["supplier_id"], "store_id": store["id"],
                                             "delivery_note": ctx.field("delivery_note", required=False, kind=str), "value": 0,
                                             "note": ctx.field("note", required=False, kind=str), "received_by": ctx.user_id,
                                             "received_at": now_iso(), "business_date": on.isoformat()})
        stock_value = 0
        expense: dict[str, int] = {}
        any_qty = False
        for ln in lines:
            pl = po_lines.get(int(ln.get("po_line_id") or 0))
            if not pl:
                raise bad_request("Line does not belong to this purchase order")
            qty = to_milli(ln.get("quantity", 0), allow_zero=True)
            rej = to_milli(ln.get("rejected", 0), "rejected", allow_zero=True)
            if qty == 0 and rej == 0:
                continue
            outstanding = pl["quantity_milli"] - pl["received_milli"]
            if qty > outstanding:
                raise bad_request(f"{pl['description']}: receiving {qty / 1000:g} but only {outstanding / 1000:g} is outstanding on the order")
            value = _val(qty, pl["unit_cost"])
            batch, expiry = (ln.get("batch_no") or None), (ln.get("expiry_date") or None)
            if expiry:
                expiry = parse_date(expiry, "expiry_date").isoformat()
            if qty and pl["item_id"]:
                item = get_item(c, hid, pl["item_id"])
                if item["track_expiry"] and not expiry:
                    raise bad_request(f"{item['name']} is expiry-tracked: enter the expiry date")
                apply_movement(c, hid, item, store, "receipt", qty, value, "grn", number, ctx.user_id, on, reason=f"PO {po['number']}",
                               batch_no=batch, expiry_date=expiry)
                stock_value += value
            elif qty:
                expense[pl["expense_key"] or "exp_admin"] = expense.get(pl["expense_key"] or "exp_admin", 0) + value
            any_qty = any_qty or qty > 0
            c.insert("goods_receipt_lines", {"grn_id": grn_id, "po_line_id": pl["id"], "item_id": pl["item_id"], "received_milli": qty, "rejected_milli": rej,
                                             "unit_cost": pl["unit_cost"], "value": value, "batch_no": batch, "expiry_date": expiry})
            c.execute("UPDATE purchase_order_lines SET received_milli = received_milli + ? WHERE id = ?", [qty, pl["id"]])
        if not any_qty:
            raise bad_request("Nothing was received (all quantities are zero or rejected)")
        total = stock_value + sum(expense.values())
        org = hotel["organisation_id"]
        je = post_journal(c, hid, on, f"Goods received {number} ({po['number']})", "procurement", number,
                          [(account_id(c, org, "inventory"), stock_value, 0, None, f"GRN {number}")]
                          + [(account_id(c, org, k), v, 0, None, f"GRN {number}") for k, v in expense.items()]
                          + [(account_id(c, org, "grni"), 0, total, None, f"GRN {number}")], ctx.user_id)
        c.update("goods_receipts", grn_id, {"value": total, "journal_entry_id": je})
        left = c.scalar("SELECT COUNT(*) FROM purchase_order_lines WHERE po_id = ? AND received_milli < quantity_milli", [po["id"]])
        c.update("purchase_orders", po["id"], {"status": "partially_received" if left else "received"})
        audit(c, ctx, "procurement.goods_received", "goods_receipt", grn_id, number, new={"po": po["number"], "value": total}, hotel_id=hid)
    return {"id": grn_id, "number": number, "value": total, "po_status": "partially_received" if left else "received", "_created": True}


# ------------------------------------------------------------------ supplier invoices & payments
def _uninvoiced_receipts(c, po_id: int, exclude_invoice: int | None = None) -> int:
    received = c.scalar("SELECT COALESCE(SUM(value),0) FROM goods_receipts WHERE po_id = ?", [po_id]) or 0
    # goods returned before they were invoiced no longer await an invoice
    received -= c.scalar("SELECT COALESCE(SUM(value),0) FROM purchase_returns WHERE po_id = ? AND settlement = 'grni'", [po_id]) or 0
    sql = "SELECT COALESCE(SUM(received_value),0) FROM supplier_invoices WHERE po_id = ? AND status <> 'rejected'"
    params: list = [po_id]
    if exclude_invoice:
        sql += " AND id <> ?"
        params.append(exclude_invoice)
    return received - (c.scalar(sql, params) or 0)


@route("GET", "/api/hotels/{hotel_id:int}/procurement/invoices", perm="procurement.view", tag="procurement",
       summary="Supplier invoices (?status, ?supplier_id) with outstanding amounts")
def list_invoices(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT i.*, s.name AS supplier_name, s.wht_bp, po.number AS po_number, u.full_name AS created_by_name, a.full_name AS approved_by_name, "
           "(i.amount - i.amount_paid) AS outstanding FROM supplier_invoices i JOIN suppliers s ON s.id = i.supplier_id "
           "LEFT JOIN purchase_orders po ON po.id = i.po_id JOIN users u ON u.id = i.created_by LEFT JOIN users a ON a.id = i.approved_by WHERE i.hotel_id = ?")
    params: list = [hid]
    if ctx.q("status"):
        st = ctx.q("status").split(",")
        sql += f" AND i.status IN ({','.join('?' for _ in st)})"
        params += st
    if ctx.q("supplier_id"):
        sql += " AND i.supplier_id = ?"
        params.append(int(ctx.q("supplier_id")))
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY i.id DESC LIMIT 300", params)
        for r in rows:
            r["payments"] = c.all("SELECT p.*, pm.name AS method_name FROM supplier_payments p JOIN payment_methods pm ON pm.id = p.method_id "
                                  "WHERE p.invoice_id = ? ORDER BY p.id", [r["id"]])
    return {"items": rows}


@route("POST", "/api/hotels/{hotel_id:int}/procurement/invoices", perm="procurement.invoice", tag="procurement",
       summary="Record a supplier invoice; it is matched against the order and goods received (three-way match)")
def create_invoice(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    amount = to_minor(ctx.field("amount"), "amount")
    if amount <= 0:
        raise bad_request("Invoice amount must be greater than zero")
    with get_db().tx() as c:
        supplier = _supplier(c, ctx, ctx.field("supplier_id", kind=int))
        inv_date = parse_date(ctx.field("invoice_date"), "invoice_date")
        due = ctx.field("due_date", required=False)
        due_date = parse_date(due, "due_date") if due else inv_date + dt.timedelta(days=supplier["payment_terms_days"])
        po_id = ctx.field("po_id", required=False)
        received_value = variance = 0
        expense_key = None
        if po_id:
            po = _po(c, ctx, po_id)
            if po["supplier_id"] != supplier["id"]:
                raise bad_request("This purchase order belongs to a different supplier")
            if po["status"] in ("pending_approval", "rejected", "cancelled"):
                raise conflict(f"Purchase order {po['number']} is {po['status'].replace('_', ' ')}")
            received_value = _uninvoiced_receipts(c, po["id"])
            if received_value <= 0:
                raise conflict(f"Nothing received on {po['number']} is waiting to be invoiced. Record the goods received first.")
            variance = amount - received_value
            tol = max(100_00, received_value * _settings(c, hid)["invoice_tolerance_bp"] // 10000)
            match = "matched" if abs(variance) <= tol else "variance"
        else:
            expense_key = ctx.field("expense_key", kind=str)
            if expense_key not in EXPENSE_KEYS:
                raise bad_request(f"Invoices without a purchase order need expense_key: one of {', '.join(EXPENSE_KEYS)}")
            match = "no_po"
        number = next_number(c, hid, "supplier_invoice", "SINV")
        iid = c.insert("supplier_invoices", {"hotel_id": hid, "number": number, "supplier_id": supplier["id"], "po_id": int(po_id) if po_id else None,
                                             "invoice_no": ctx.field("invoice_no", kind=str), "invoice_date": inv_date.isoformat(), "due_date": due_date.isoformat(),
                                             "amount": amount, "received_value": received_value, "variance": variance, "match_status": match,
                                             "status": "pending_approval", "expense_key": expense_key, "note": ctx.field("note", required=False, kind=str),
                                             "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "procurement.invoice_recorded", "supplier_invoice", iid, number, new={"amount": amount, "match": match, "variance": variance}, hotel_id=hid)
    return {"id": iid, "number": number, "match_status": match, "received_value": received_value, "variance": variance, "_created": True}


@route("POST", "/api/procurement/invoices/{invoice_id:int}/decide", perm="procurement.invoice_approve", tag="procurement",
       summary="Approve a supplier invoice for payment (posts it to Accounts Payable) or reject it")
def decide_invoice(ctx: Ctx):
    decision = ctx.field("decision", kind=str)
    if decision not in ("approve", "reject"):
        raise bad_request("decision must be approve or reject")
    with get_db().tx() as c:
        inv = c.lock("supplier_invoices", int(ctx.path["invoice_id"]))
        if not inv:
            raise not_found("Supplier invoice")
        ctx.check_hotel(inv["hotel_id"])
        if inv["status"] != "pending_approval":
            raise conflict(f"This invoice is already {inv['status'].replace('_', ' ')}")
        if inv["created_by"] == ctx.user_id:
            raise forbidden("You cannot approve an invoice you recorded")
        note = ctx.field("note", required=decision == "reject" or inv["match_status"] == "variance", kind=str)
        je = None
        if decision == "approve":
            hotel = get_hotel(c, inv["hotel_id"])
            org = hotel["organisation_id"]
            on = business_date(hotel)
            if inv["po_id"]:
                still = _uninvoiced_receipts(c, inv["po_id"], exclude_invoice=inv["id"])
                if inv["received_value"] > still:
                    raise conflict("Another invoice has since been approved for these goods; reject this one or re-enter it")
                lines = [(account_id(c, org, "grni"), inv["received_value"], 0, None, f"{inv['number']} {inv['invoice_no']}")]
                if inv["variance"] > 0:
                    lines.append((account_id(c, org, "ppv"), inv["variance"], 0, None, "Price variance"))
                elif inv["variance"] < 0:
                    lines.append((account_id(c, org, "ppv"), 0, -inv["variance"], None, "Price variance"))
            else:
                lines = [(account_id(c, org, inv["expense_key"] or "exp_admin"), inv["amount"], 0, None, f"{inv['number']} {inv['invoice_no']}")]
            lines.append((account_id(c, org, "ap"), 0, inv["amount"], None, f"{inv['number']} {inv['invoice_no']}"))
            je = post_journal(c, inv["hotel_id"], on, f"Supplier invoice {inv['invoice_no']} ({inv['number']})", "procurement", inv["number"], lines, ctx.user_id)
        c.update("supplier_invoices", inv["id"], {"status": "approved" if decision == "approve" else "rejected", "approved_by": ctx.user_id,
                                                  "approved_at": now_iso(), "decision_note": note, "journal_entry_id": je})
        audit(c, ctx, f"procurement.invoice_{decision}d", "supplier_invoice", inv["id"], inv["number"], new={"note": note, "journal": je}, hotel_id=inv["hotel_id"])
    return {"status": "approved" if decision == "approve" else "rejected", "journal_entry_id": je}


@route("POST", "/api/procurement/invoices/{invoice_id:int}/payments", perm="procurement.pay", tag="procurement",
       summary="Pay an approved supplier invoice (cash or bank transfer); withholding tax is deducted at the supplier's rate")
def pay_invoice(ctx: Ctx):
    gross = to_minor(ctx.field("amount"), "amount")
    key = ctx.field("idempotency_key", kind=str)
    with get_db().tx() as c:
        dup = c.one("SELECT * FROM supplier_payments WHERE idempotency_key = ?", [key])
        if dup:
            if dup["invoice_id"] != int(ctx.path["invoice_id"]) or dup["gross_amount"] != gross:
                raise conflict("This idempotency key was already used for a different payment")
            return {"id": dup["id"], "duplicate": True}
        inv = c.lock("supplier_invoices", int(ctx.path["invoice_id"]))
        if not inv:
            raise not_found("Supplier invoice")
        ctx.check_hotel(inv["hotel_id"])
        if inv["status"] not in ("approved", "part_paid"):
            raise conflict("Only approved invoices can be paid" if inv["status"] == "pending_approval" else f"This invoice is {inv['status'].replace('_', ' ')}")
        outstanding = inv["amount"] - inv["amount_paid"]
        if gross <= 0 or gross > outstanding:
            raise bad_request(f"Payment must be between 0 and the outstanding amount ({outstanding})")
        hid = inv["hotel_id"]
        hotel = get_hotel(c, hid)
        m = c.one("SELECT * FROM payment_methods WHERE id = ? AND hotel_id = ? AND active = 1", [ctx.field("method_id", kind=int), hid])
        if not m or m["kind"] not in ("cash", "bank_transfer"):
            raise bad_request("Pay suppliers by cash or bank transfer")
        ref = ctx.field("reference", required=m["kind"] == "bank_transfer", kind=str)
        supplier = c.one("SELECT * FROM suppliers WHERE id = ?", [inv["supplier_id"]])
        wht = (gross * supplier["wht_bp"] + 5000) // 10000
        net = gross - wht
        org = hotel["organisation_id"]
        on = business_date(hotel)
        number = next_number(c, hid, "supplier_payment", "SPAY")
        je = post_journal(c, hid, on, f"Payment to {supplier['name']} for {inv['invoice_no']} ({number})", "procurement", number, [
            (account_id(c, org, "ap"), gross, 0, None, f"{inv['number']}"),
            (m["account_id"], 0, net, None, f"{m['name']} {ref or ''}".strip()),
            (account_id(c, org, "wht_payable"), 0, wht, None, f"WHT {supplier['wht_bp'] / 100:g}% on {inv['number']}")], ctx.user_id)
        pid = c.insert("supplier_payments", {"hotel_id": hid, "number": number, "supplier_id": supplier["id"], "invoice_id": inv["id"], "method_id": m["id"],
                                             "gross_amount": gross, "wht_amount": wht, "net_amount": net, "reference": ref, "idempotency_key": key,
                                             "journal_entry_id": je, "paid_by": ctx.user_id, "created_at": now_iso()})
        paid = inv["amount_paid"] + gross
        c.update("supplier_invoices", inv["id"], {"amount_paid": paid, "status": "paid" if paid >= inv["amount"] else "part_paid"})
        audit(c, ctx, "procurement.supplier_paid", "supplier_payment", pid, number, new={"invoice": inv["number"], "gross": gross, "wht": wht, "net": net}, hotel_id=hid)
    return {"id": pid, "number": number, "gross": gross, "wht": wht, "net": net, "invoice_status": "paid" if paid >= inv["amount"] else "part_paid",
            "_created": True}


@route("GET", "/api/hotels/{hotel_id:int}/procurement/summary", perm="procurement.view", tag="procurement",
       summary="Procurement dashboard: open orders, awaiting approval, payables ageing and spend by supplier (?from, ?to)")
def summary(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        frm = ctx.q("from", today.replace(day=1).isoformat())
        to = ctx.q("to", today.isoformat())
        counts = {r["status"]: r["n"] for r in c.all("SELECT status, COUNT(*) AS n FROM purchase_orders WHERE hotel_id = ? GROUP BY status", [hid])}
        open_inv = c.all("SELECT i.*, s.name AS supplier_name FROM supplier_invoices i JOIN suppliers s ON s.id = i.supplier_id WHERE i.hotel_id = ? "
                         "AND i.status IN ('approved','part_paid')", [hid])
        ageing = {"current": 0, "1_30": 0, "31_60": 0, "61_90": 0, "over_90": 0}
        for i in open_inv:
            days = (today - dt.date.fromisoformat(i["due_date"])).days
            out = i["amount"] - i["amount_paid"]
            ageing["current" if days <= 0 else "1_30" if days <= 30 else "31_60" if days <= 60 else "61_90" if days <= 90 else "over_90"] += out
        spend = c.all("SELECT s.name AS supplier, COALESCE(SUM(g.value),0) AS value, COUNT(g.id) AS deliveries FROM goods_receipts g "
                      "JOIN suppliers s ON s.id = g.supplier_id WHERE g.hotel_id = ? AND g.business_date >= ? AND g.business_date <= ? "
                      "GROUP BY s.name ORDER BY value DESC", [hid, frm, to])
        pending = {"requisitions": c.scalar("SELECT COUNT(*) FROM purchase_requisitions WHERE hotel_id = ? AND status = 'submitted'", [hid]),
                   "purchase_orders": counts.get("pending_approval", 0),
                   "invoices": c.scalar("SELECT COUNT(*) FROM supplier_invoices WHERE hotel_id = ? AND status = 'pending_approval'", [hid])}
    return {"from": frm, "to": to, "po_status": counts, "pending_approval": pending, "payables_total": sum(ageing.values()), "ageing": ageing,
            "spend_by_supplier": spend}
