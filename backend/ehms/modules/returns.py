"""Purchase returns (release 1.2): send received goods back to the supplier. Stock leaves the store at the GRN cost
through a traceable 'return' movement. If the goods are not yet invoiced the goods-received-not-invoiced balance is
reduced (Dr GRNI / Cr inventory) and the order line reopens for a replacement delivery; if the supplier has already
invoiced them, the return is a supplier credit against that invoice (Dr accounts payable / Cr inventory)."""
from __future__ import annotations

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, not_found, route
from ..services import account_id, business_date, get_hotel, next_number, post_journal, to_milli
from ..stock import apply_movement, get_item, get_store


def _val(qty_milli: int, unit_cost: int) -> int:
    return (qty_milli * unit_cost + 500) // 1000


@route("GET", "/api/procurement/grns/{grn_id:int}", perm="procurement.view", tag="procurement",
       summary="Goods received note with lines, quantities already returned and returns made")
def grn_detail(ctx: Ctx):
    with get_db().tx() as c:
        g = c.one("SELECT g.*, s.name AS supplier, p.number AS po_number FROM goods_receipts g JOIN suppliers s ON s.id = g.supplier_id "
                  "JOIN purchase_orders p ON p.id = g.po_id WHERE g.id = ?", [ctx.path["grn_id"]])
        if not g:
            raise not_found("Goods received note")
        ctx.check_hotel(g["hotel_id"])
        lines = c.all("SELECT l.*, pl.description FROM goods_receipt_lines l JOIN purchase_order_lines pl ON pl.id = l.po_line_id WHERE l.grn_id = ? ORDER BY l.id", [g["id"]])
        for l in lines:
            l["returned_milli"] = c.scalar("SELECT COALESCE(SUM(quantity_milli),0) FROM purchase_return_lines WHERE grn_line_id = ?", [l["id"]]) or 0
        g["lines"] = lines
        g["returns"] = c.all("SELECT * FROM purchase_returns WHERE grn_id = ? ORDER BY id DESC", [g["id"]])
        g["invoices"] = c.all("SELECT id, number, invoice_no, amount, amount_paid, status FROM supplier_invoices WHERE po_id = ? AND status IN ('approved','part_paid')",
                              [g["po_id"]])
        return g


@route("GET", "/api/hotels/{hotel_id:int}/procurement/grns", perm="procurement.view", tag="procurement", summary="Goods received notes (?q = GRN or PO number)")
def list_grns(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT g.id, g.number, g.business_date, g.value, s.name AS supplier, p.number AS po_number, "
           "(SELECT COALESCE(SUM(value),0) FROM purchase_returns r WHERE r.grn_id = g.id) AS returned_value "
           "FROM goods_receipts g JOIN suppliers s ON s.id = g.supplier_id JOIN purchase_orders p ON p.id = g.po_id WHERE g.hotel_id = ?")
    params: list = [hid]
    if ctx.q("q"):
        sql += " AND (upper(g.number) LIKE ? OR upper(p.number) LIKE ?)"
        params += [f"%{ctx.q('q').upper()}%"] * 2
    with get_db().tx() as c:
        return {"items": c.all(sql + " ORDER BY g.id DESC LIMIT 200", params)}


@route("GET", "/api/hotels/{hotel_id:int}/procurement/returns", perm="procurement.view", tag="procurement", summary="Purchase returns")
def list_returns(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": c.all("SELECT r.*, s.name AS supplier, g.number AS grn_number, p.number AS po_number FROM purchase_returns r "
                               "JOIN suppliers s ON s.id = r.supplier_id JOIN goods_receipts g ON g.id = r.grn_id JOIN purchase_orders p ON p.id = r.po_id "
                               "WHERE r.hotel_id = ? ORDER BY r.id DESC LIMIT 200", [hid])}


@route("POST", "/api/procurement/grns/{grn_id:int}/returns", perm="procurement.return", tag="procurement",
       summary="Return goods to the supplier: lines[{grn_line_id, quantity}], reason, invoice_id (if the supplier already invoiced them)")
def create_return(ctx: Ctx):
    lines = ctx.field("lines")
    reason = str(ctx.field("reason", kind=str)).strip()
    if not isinstance(lines, list) or not lines:
        raise bad_request("Enter the quantities to return")
    if len(reason) < 3:
        raise bad_request("Give the reason for the return")
    with get_db().tx() as c:
        g = c.lock("goods_receipts", int(ctx.path["grn_id"]))
        if not g:
            raise not_found("Goods received note")
        hid = ctx.check_hotel(g["hotel_id"])
        hotel = get_hotel(c, hid)
        on = business_date(hotel)
        store = get_store(c, hid, g["store_id"])
        inv = None
        if ctx.field("invoice_id", required=False):
            inv = c.lock("supplier_invoices", int(ctx.field("invoice_id")))
            if not inv or inv["po_id"] != g["po_id"] or inv["status"] not in ("approved", "part_paid"):
                raise bad_request("Choose an approved, unpaid invoice of this purchase order")
        grni_open = None if inv else _grni_open(c, g["po_id"])
        number = next_number(c, hid, "purchase_return", "PRN")
        grn_lines = {l["id"]: l for l in c.all("SELECT * FROM goods_receipt_lines WHERE grn_id = ?", [g["id"]])}
        rid = c.insert("purchase_returns", {"hotel_id": hid, "number": number, "grn_id": g["id"], "po_id": g["po_id"], "supplier_id": g["supplier_id"],
                                            "invoice_id": inv["id"] if inv else None, "settlement": "invoice_credit" if inv else "grni",
                                            "value": 1, "reason": reason[:300], "created_by": ctx.user_id, "created_at": now_iso()})
        stock_value, expense, total = 0, {}, 0
        for ln in lines:
            gl = grn_lines.get(int(ln.get("grn_line_id") or 0))
            if not gl:
                raise bad_request("Line does not belong to this goods received note")
            qty = to_milli(ln.get("quantity", 0), allow_zero=True)
            if qty == 0:
                continue
            done = c.scalar("SELECT COALESCE(SUM(quantity_milli),0) FROM purchase_return_lines WHERE grn_line_id = ?", [gl["id"]]) or 0
            if qty > gl["received_milli"] - done:
                raise bad_request(f"Returning {qty / 1000:g} but only {(gl['received_milli'] - done) / 1000:g} of that line can still be returned")
            value = _val(qty, gl["unit_cost"])
            if gl["item_id"]:
                item = get_item(c, hid, gl["item_id"])
                apply_movement(c, hid, item, store, "return", -qty, value, "purchase_return", number, ctx.user_id, on, reason=reason)
                stock_value += value
            else:
                pl = c.one("SELECT expense_key FROM purchase_order_lines WHERE id = ?", [gl["po_line_id"]])
                k = pl["expense_key"] or "exp_admin"
                expense[k] = expense.get(k, 0) + value
            total += value
            c.insert("purchase_return_lines", {"return_id": rid, "grn_line_id": gl["id"], "item_id": gl["item_id"], "quantity_milli": qty,
                                               "unit_cost": gl["unit_cost"], "value": value})
            if not inv:
                # not yet invoiced: the order line reopens so a replacement can be received
                c.execute("UPDATE purchase_order_lines SET received_milli = received_milli - ? WHERE id = ?", [qty, gl["po_line_id"]])
        if total <= 0:
            raise bad_request("Nothing to return (all quantities are zero)")
        org = hotel["organisation_id"]
        if inv:
            outstanding = inv["amount"] - inv["amount_paid"]
            if total > outstanding:
                raise conflict(f"The return ({total}) is more than the invoice's unpaid balance ({outstanding}); record a supplier refund instead")
            debit = account_id(c, org, "ap")
            paid = inv["amount_paid"] + total
            c.update("supplier_invoices", inv["id"], {"amount_paid": paid, "status": "paid" if paid >= inv["amount"] else "part_paid"})
        else:
            if total > grni_open:
                raise conflict("The return is more than the uninvoiced value of this order; choose the supplier invoice it was billed on")
            debit = account_id(c, org, "grni")
            c.update("purchase_orders", g["po_id"], {"status": "partially_received"})
        je = post_journal(c, hid, on, f"Purchase return {number} ({g['number']}): {reason[:80]}", "procurement", number,
                          [(debit, total, 0, None, f"Return {number}")]
                          + ([(account_id(c, org, "inventory"), 0, stock_value, None, f"Return {number}")] if stock_value else [])
                          + [(account_id(c, org, k), 0, v, None, f"Return {number}") for k, v in expense.items()], ctx.user_id)
        c.update("purchase_returns", rid, {"value": total, "journal_entry_id": je})
        audit(c, ctx, "procurement.goods_returned", "purchase_return", rid, number,
              new={"grn": g["number"], "value": total, "settlement": "invoice_credit" if inv else "grni", "reason": reason}, hotel_id=hid)
    return {"id": rid, "number": number, "value": total, "settlement": "invoice_credit" if inv else "grni", "_created": True}


def _grni_open(c, po_id: int) -> int:
    from .procurement import _uninvoiced_receipts
    return _uninvoiced_receipts(c, po_id)
