"""Release 0.4: restaurant/bar POS with kitchen display, inventory & stores, procurement.
Covers FR-POS-*, FR-KIT-*, FR-INV-*, FR-PRO-* and acceptance criteria 5 (departmental charges to folios),
6 (inventory consumption reflected in stock) and 4 (financial transactions accurately recorded)."""
import uuid

import pytest

from ehms.db import IntegrityError, get_db

from test_frontoffice_finance import arrival_today, ctx_ids


# ------------------------------------------------------------------ helpers
def ids():
    with get_db().tx() as c:
        h = c.one("SELECT * FROM hotels WHERE code = 'CGL'")
        out = {"hotel": h,
               "outlet": {o["code"]: o for o in c.all("SELECT * FROM outlets WHERE hotel_id = ?", [h["id"]])},
               "store": {s["code"]: s for s in c.all("SELECT * FROM stores WHERE hotel_id = ?", [h["id"]])},
               "item": {i["code"]: i for i in c.all("SELECT * FROM inventory_items WHERE hotel_id = ?", [h["id"]])},
               "menu": {m["code"]: m for m in c.all("SELECT * FROM menu_items WHERE hotel_id = ?", [h["id"]])},
               "method": {m["code"]: m for m in c.all("SELECT * FROM payment_methods WHERE hotel_id = ?", [h["id"]])},
               "supplier": {s["code"]: s for s in c.all("SELECT * FROM suppliers")}}
        out["table"] = c.one("SELECT * FROM pos_tables WHERE outlet_id = ? AND code = 'T1'", [out["outlet"]["REST"]["id"]])
    return out


def qty(item_id, store_id):
    with get_db().tx() as c:
        return c.scalar("SELECT quantity_milli FROM stock_levels WHERE item_id = ? AND store_id = ?", [item_id, store_id]) or 0


def gl_balance(key, hotel_id):
    with get_db().tx() as c:
        return c.scalar("SELECT COALESCE(SUM(jl.debit - jl.credit),0) FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id "
                        "JOIN accounts a ON a.id = jl.account_id WHERE a.system_key = ? AND je.hotel_id = ?", [key, hotel_id])


def assert_books_balance(hotel_id):
    with get_db().tx() as c:
        dr, cr = c.one("SELECT COALESCE(SUM(jl.debit),0) AS d, COALESCE(SUM(jl.credit),0) AS c FROM journal_lines jl "
                       "JOIN journal_entries je ON je.id = jl.entry_id WHERE je.hotel_id = ?", [hotel_id]).values()
        stock = c.scalar("SELECT COALESCE(SUM(l.value),0) FROM stock_levels l JOIN stores s ON s.id = l.store_id WHERE s.hotel_id = ?", [hotel_id])
    assert dr == cr, "trial balance out of balance"
    assert stock == gl_balance("inventory", hotel_id), "stock sub-ledger does not reconcile to the Inventory GL account"


def open_order(client, d, items, table=True):
    r = client.post(f"/api/hotels/{d['hotel']['id']}/pos/orders", {"outlet_id": d["outlet"]["REST"]["id"], "order_type": "dine_in" if table else "takeaway",
                                                                   "table_id": d["table"]["id"] if table else None, "covers": 2})
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    for code, q in items:
        assert client.post(f"/api/pos/orders/{oid}/items", {"menu_item_id": d["menu"][code]["id"], "quantity": q}).status_code == 201
    return oid


# ------------------------------------------------------------------ POS
def test_pos_dine_in_full_workflow(client):
    d = ids()
    hid = d["hotel"]["id"]
    kit = d["store"]["KIT"]["id"]
    rice0, chkn0 = qty(d["item"]["RICE"]["id"], kit), qty(d["item"]["CHKN"]["id"], kit)

    client.login("waiter@demo.ehms")
    oid = open_order(client, d, [("JRC", 2), ("SDK", 2)])
    # a waiter cannot settle or discount
    assert client.post(f"/api/pos/orders/{oid}/settle", {"tenders": [{"tender": "method", "method_id": d["method"]["CASH"]["id"], "amount": 1}]}).status_code == 403
    assert client.post(f"/api/pos/orders/{oid}/discount", {"amount": 100, "reason": "x"}).status_code == 403
    sent = client.post(f"/api/pos/orders/{oid}/send", {})
    assert sent.status_code == 200 and sent.json()["sent"] == 2

    # kitchen display shows the ticket; chef works it
    client.login("chef@demo.ehms")
    tickets = client.get(f"/api/hotels/{hid}/kitchen/tickets").json()["tickets"]
    t = next(t for t in tickets if t["order_id"] == oid)
    assert t["table"] == "T1" and {i["name"] for i in t["items"]} == {"Jollof rice & chicken", "Soft drink"}
    food = next(i for i in t["items"] if i["station"] == "kitchen")
    assert client.post(f"/api/kitchen/items/{food['id']}/status", {"status": "preparing"}).status_code == 200
    assert client.post(f"/api/kitchen/items/{food['id']}/status", {"status": "ready"}).status_code == 200
    # chef cannot mark served (service staff do that)
    assert client.post(f"/api/kitchen/items/{food['id']}/status", {"status": "served"}).status_code == 403
    client.login("waiter@demo.ehms")
    assert client.post(f"/api/kitchen/items/{food['id']}/status", {"status": "served"}).status_code == 200

    # cashier settles: needs an open shift first
    client.login("cashier@demo.ehms")
    order = client.get(f"/api/pos/orders/{oid}").json()
    tot = order["totals"]
    # 2 x 8,500 + 2 x 1,000 = 19,000; SC 10% = 1,900; VAT 7.5% on 20,900 = 1,567.50
    assert (tot["subtotal"], tot["service_charge"], tot["tax"], tot["total"]) == (1900000, 190000, 156750, 2246750)
    cash = d["method"]["CASH"]["id"]
    blocked = client.post(f"/api/pos/orders/{oid}/settle", {"tenders": [{"tender": "method", "method_id": cash, "amount": 2300000}]})
    assert blocked.status_code == 409 and blocked.json()["error"]["details"]["code"] == "shift_required"
    shift = client.post(f"/api/hotels/{hid}/pos/shifts", {"outlet_id": d["outlet"]["REST"]["id"], "opening_float": 2000000}).json()
    short = client.post(f"/api/pos/orders/{oid}/settle", {"tenders": [{"tender": "method", "method_id": cash, "amount": 2000000}]})
    assert short.status_code == 400
    ok = client.post(f"/api/pos/orders/{oid}/settle", {"tenders": [{"tender": "method", "method_id": cash, "amount": 2300000}]})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["status"] == "settled" and body["change"] == 53250 and body["payments"][0]["amount"] == 2246750
    # recipe consumption: 2 portions x (0.2 kg rice, 0.3 kg chicken)
    assert rice0 - qty(d["item"]["RICE"]["id"], kit) == 400
    assert chkn0 - qty(d["item"]["CHKN"]["id"], kit) == 600
    # soft drinks come out of the bar outlet's... no: restaurant outlet issues from the kitchen store
    assert body["cost_of_sales"] > 0
    # settled orders cannot be changed
    assert client.post(f"/api/pos/orders/{oid}/items", {"menu_item_id": d["menu"]["SDK"]["id"]}).status_code == 409
    # receipt PDF
    pdf = client.get(f"/api/pos/orders/{oid}/receipt.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    # shift close: expected = float + cash sales; a variance needs a note
    summ = client.get(f"/api/pos/shifts/{shift['id']}").json()
    assert summ["expected_cash_now"] == 2000000 + 2246750
    assert client.post(f"/api/pos/shifts/{shift['id']}/close", {"counted_cash": 4240000}).status_code == 400
    closed = client.post(f"/api/pos/shifts/{shift['id']}/close", {"counted_cash": 4240000, "note": "Short by 67.50"}).json()
    assert closed["variance"] == 4240000 - 4246750
    assert_books_balance(hid)


def test_pos_charge_to_room_posts_to_folio(client):
    client.login("frontdesk@demo.ehms")
    h, _ = ctx_ids()
    res, _room = arrival_today(client, h)
    ci = client.post(f"/api/reservations/{res['id']}/check-in", {})
    assert ci.status_code == 200, ci.text
    folio_id = ci.json()["folio"]["id"]
    d = ids()
    client.login("cashier@demo.ehms")
    r = client.post(f"/api/hotels/{h['id']}/pos/orders", {"outlet_id": d["outlet"]["RSV"]["id"], "order_type": "room_service", "reservation_id": res["id"]})
    assert r.status_code == 201, r.text
    oid = r.json()["id"]
    assert r.json()["guest_name"]
    client.post(f"/api/pos/orders/{oid}/items", {"menu_item_id": d["menu"]["FRC"]["id"], "quantity": 1})
    client.post(f"/api/pos/orders/{oid}/send", {})
    total = client.get(f"/api/pos/orders/{oid}").json()["totals"]["total"]
    # charging more than the bill to a room is refused (only cash can be over-tendered)
    assert client.post(f"/api/pos/orders/{oid}/settle", {"tenders": [{"tender": "room", "amount": total + 100}]}).status_code == 400
    ok = client.post(f"/api/pos/orders/{oid}/settle", {"tenders": [{"tender": "room", "amount": total}]})
    assert ok.status_code == 200, ok.text
    client.login("frontdesk@demo.ehms")
    folio = client.get(f"/api/folios/{folio_id}").json()
    line = next(l for l in folio["lines"] if l["reference"] == ok.json()["number"])
    assert line["department"] == "fnb" and line["total_amount"] == total
    assert line["net_amount"] + line["service_charge"] + line["tax_amount"] == total
    assert folio["totals"]["balance"] >= total
    assert_books_balance(h["id"])


def test_pos_split_tender_split_bill_merge_discount_void(client):
    d = ids()
    hid = d["hotel"]["id"]
    client.login("fnbmanager@demo.ehms")
    client.post(f"/api/hotels/{hid}/pos/shifts", {"outlet_id": d["outlet"]["REST"]["id"], "opening_float": 0})
    a = open_order(client, d, [("FRC", 1), ("LGR", 2), ("DOD", 1)])
    b = open_order(client, d, [("WTR", 2)], table=False)
    # unsent items can be removed; sent items need a void with a reason
    order = client.get(f"/api/pos/orders/{a}").json()
    dod = next(i for i in order["items"] if i["name"].startswith("Fried plantain"))
    assert client.delete(f"/api/pos/order-items/{dod['id']}").status_code == 200
    client.post(f"/api/pos/orders/{a}/send", {})
    lgr = next(i for i in client.get(f"/api/pos/orders/{a}").json()["items"] if i["name"] == "Lager beer")
    assert client.post(f"/api/pos/order-items/{lgr['id']}/void", {}).status_code == 400
    v = client.post(f"/api/pos/order-items/{lgr['id']}/void", {"reason": "Guest changed mind"})
    assert v.status_code == 200 and v.json()["totals"]["subtotal"] == 900000
    # merge the takeaway order into the table, then split the water off to its own bill
    m = client.post(f"/api/pos/orders/{a}/merge", {"source_order_id": b})
    assert m.status_code == 200 and m.json()["totals"]["subtotal"] == 900000 + 160000
    water = next(i for i in m.json()["items"] if i["name"] == "Table water")
    s = client.post(f"/api/pos/orders/{a}/split", {"item_ids": [water["id"]]})
    assert s.status_code == 201
    new_id = s.json()["new_order"]["id"]
    assert s.json()["original"]["totals"]["subtotal"] == 900000 and s.json()["new_order"]["totals"]["subtotal"] == 160000
    # discount needs a reason
    assert client.post(f"/api/pos/orders/{a}/discount", {"percent": 10}).status_code == 400
    disc = client.post(f"/api/pos/orders/{a}/discount", {"percent": 10, "reason": "Loyal guest"})
    assert disc.json()["totals"]["discount"] == 90000
    tot = disc.json()["totals"]["total"]
    card, cash = d["method"]["POS"]["id"], d["method"]["CASH"]["id"]
    # card needs a terminal reference; card cannot exceed the bill
    assert client.post(f"/api/pos/orders/{a}/settle", {"tenders": [{"tender": "method", "method_id": card, "amount": tot}]}).status_code == 400
    assert client.post(f"/api/pos/orders/{a}/settle", {"tenders": [{"tender": "method", "method_id": card, "amount": tot + 1, "reference": "T1"}]}).status_code == 400
    split = client.post(f"/api/pos/orders/{a}/settle", {"tenders": [{"tender": "method", "method_id": card, "amount": 500000, "reference": "SLIP-1"},
                                                                    {"tender": "method", "method_id": cash, "amount": tot - 500000}]})
    assert split.status_code == 200, split.text
    assert sum(p["amount"] for p in split.json()["payments"]) == tot
    # whole-order void on the other bill
    client.post(f"/api/pos/orders/{new_id}/send", {})
    assert client.post(f"/api/pos/orders/{new_id}/void", {"reason": "Walked out"}).json()["status"] == "voided"
    assert_books_balance(hid)


def test_pos_blocks_sale_when_ingredients_run_out(client):
    d = ids()
    hid = d["hotel"]["id"]
    client.login("fnbmanager@demo.ehms")
    client.post(f"/api/hotels/{hid}/pos/shifts", {"outlet_id": d["outlet"]["REST"]["id"]})
    oid = open_order(client, d, [("PFS", 20)])  # 20 x 0.5 kg fish = 10 kg; kitchen holds 6 kg
    client.post(f"/api/pos/orders/{oid}/send", {})
    total = client.get(f"/api/pos/orders/{oid}").json()["totals"]["total"]
    r = client.post(f"/api/pos/orders/{oid}/settle", {"tenders": [{"tender": "method", "method_id": d["method"]["CASH"]["id"], "amount": total}]})
    assert r.status_code == 409 and r.json()["error"]["details"]["code"] == "insufficient_stock"
    # nothing was posted: order still open, stock unchanged, no payment recorded
    order = client.get(f"/api/pos/orders/{oid}").json()
    assert order["status"] == "open" and order["payments"] == []
    assert qty(d["item"]["FISH"]["id"], d["store"]["KIT"]["id"]) == 6000


def test_pos_menu_and_recipe_management(client):
    d = ids()
    hid = d["hotel"]["id"]
    client.login("cashier@demo.ehms")
    assert client.post(f"/api/hotels/{hid}/pos/menu-items", {"name": "X", "price": 1, "category_id": 1}).status_code == 403
    client.login("fnbmanager@demo.ehms")
    menu = client.get(f"/api/hotels/{hid}/pos/menu").json()
    jrc = next(m for m in menu["items"] if m["code"] == "JRC")
    assert len(jrc["recipe"]) == 4 and jrc["recipe_cost"] > 0
    cat = menu["categories"][0]["id"]
    r = client.post(f"/api/hotels/{hid}/pos/menu-items", {"name": "Chicken pepper soup", "price": 550000, "category_id": cat, "station": "kitchen"})
    assert r.status_code == 201
    mid = r.json()["id"]
    assert client.put(f"/api/pos/menu-items/{mid}/recipe", {"lines": [{"item_id": d["item"]["CHKN"]["id"], "quantity": "0.25"}]}).status_code == 200
    assert client.put(f"/api/pos/menu-items/{mid}/recipe", {"lines": [{"item_id": d["item"]["CHKN"]["id"], "quantity": "0.0001"}]}).status_code == 400
    # sold-out items cannot be ordered
    client.post(f"/api/pos/menu-items/{mid}/availability", {"available": False})
    oid = open_order(client, d, [])
    assert client.post(f"/api/pos/orders/{oid}/items", {"menu_item_id": mid}).status_code == 409


# ------------------------------------------------------------------ inventory
def test_inventory_requisition_issue_transfer_adjust_count(client):
    d = ids()
    hid = d["hotel"]["id"]
    main, kit, hsk = d["store"]["MAIN"]["id"], d["store"]["KIT"]["id"], d["store"]["HSK"]["id"]
    soap = d["item"]["SOAP"]["id"]
    rice = d["item"]["RICE"]["id"]
    # housekeeping manager requests soap for consumption; cannot approve own
    client.login("hkmanager@demo.ehms")
    r = client.post(f"/api/hotels/{hid}/inventory/requisitions", {"from_store_id": hsk, "department": "housekeeping",
                                                                  "lines": [{"item_id": soap, "quantity": 50}]})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    assert client.post(f"/api/inventory/requisitions/{rid}/decide", {"decision": "approve"}).status_code == 403  # no inventory.approve
    client.login("inventory@demo.ehms")
    assert client.post(f"/api/inventory/requisitions/{rid}/issue", {}).status_code == 409   # not approved yet
    assert client.post(f"/api/inventory/requisitions/{rid}/decide", {"decision": "approve"}).json()["status"] == "approved"
    exp_before = gl_balance("exp_supplies", hid)
    issued = client.post(f"/api/inventory/requisitions/{rid}/issue", {})
    assert issued.status_code == 200 and issued.json()["value"] == 50 * 15000
    assert gl_balance("exp_supplies", hid) - exp_before == 50 * 15000
    assert qty(soap, hsk) == 350000
    # transfer rice main -> kitchen moves value, not expense
    t = client.post(f"/api/hotels/{hid}/inventory/transfers", {"from_store_id": main, "to_store_id": kit, "lines": [{"item_id": rice, "quantity": "10.5"}]})
    assert t.status_code == 201 and qty(rice, kit) == 35500
    over = client.post(f"/api/hotels/{hid}/inventory/transfers", {"from_store_id": kit, "to_store_id": main, "lines": [{"item_id": rice, "quantity": 1000}]})
    assert over.status_code == 409 and over.json()["error"]["details"]["code"] == "insufficient_stock"
    # wastage writes off value to shrinkage
    w = client.post(f"/api/hotels/{hid}/inventory/adjustments", {"kind": "wastage", "item_id": d["item"]["BRD"]["id"], "store_id": kit, "quantity": 2,
                                                                 "reason": "Mouldy"})
    assert w.status_code == 201 and w.json()["value"] == 240000
    # storekeeper cannot adjust
    client.login("stores@demo.ehms")
    assert client.post(f"/api/hotels/{hid}/inventory/adjustments", {"kind": "wastage", "item_id": soap, "store_id": hsk, "quantity": 1, "reason": "x"}).status_code == 403
    # stock count: count 3 kg less oil in the kitchen and post the variance
    client.login("inventory@demo.ehms")
    k = client.post(f"/api/hotels/{hid}/inventory/counts", {"store_id": kit}).json()
    sheet = client.get(f"/api/inventory/counts/{k['id']}").json()
    lines = [{"item_id": l["item_id"], "counted": l["current"] - (3 if l["code"] == "OIL" else 0)} for l in sheet["lines"]]
    assert client.post(f"/api/inventory/counts/{k['id']}/post", {}).status_code == 400  # uncounted lines
    client.put(f"/api/inventory/counts/{k['id']}/lines", {"lines": lines})
    posted = client.post(f"/api/inventory/counts/{k['id']}/post", {}).json()
    assert posted["lines_adjusted"] == 1 and posted["loss"] == 3 * 250000
    assert qty(d["item"]["OIL"]["id"], kit) == 7000
    # movements are append-only at database level
    with pytest.raises(IntegrityError):
        with get_db().tx() as c:
            c.execute("UPDATE stock_movements SET quantity_milli = 0")
    assert_books_balance(hid)


def test_inventory_alerts_and_catalogue(client):
    d = ids()
    hid = d["hotel"]["id"]
    client.login("inventory@demo.ehms")
    alerts = client.get(f"/api/hotels/{hid}/inventory/alerts", params={"days": 30}).json()
    # bread & eggs were seeded with a 12-day expiry
    assert {"BRD", "EGG"} <= {e["code"] for e in alerts["expiring"]}
    r = client.post(f"/api/hotels/{hid}/inventory/items", {"name": "Toilet roll", "category": "toiletries", "unit": "roll", "reorder_level": 100})
    assert r.status_code == 201
    low = client.get(f"/api/hotels/{hid}/inventory/items", params={"low": 1}).json()["items"]
    assert any(i["name"] == "Toilet roll" for i in low)   # 0 on hand <= reorder level
    assert client.post(f"/api/hotels/{hid}/inventory/items", {"name": "Bad", "category": "nope", "unit": "x"}).status_code == 400
    # opening balance posts against equity and shows on the item
    op = client.post(f"/api/hotels/{hid}/inventory/adjustments", {"kind": "opening", "item_id": r.json()["id"], "store_id": d["store"]["HSK"]["id"],
                                                                  "quantity": 200, "unit_cost": 30000, "reason": "Opening"})
    assert op.status_code == 201 and op.json()["value"] == 6000000
    detail = client.get(f"/api/inventory/items/{r.json()['id']}").json()
    assert detail["levels"][0]["quantity"] == 200
    assert_books_balance(hid)


# ------------------------------------------------------------------ procurement
def test_procurement_requisition_quotes_po_grn_invoice_payment(client):
    d = ids()
    hid = d["hotel"]["id"]
    main = d["store"]["MAIN"]["id"]
    chkn, beer = d["item"]["CHKN"], d["item"]["BEER"]
    # 1. requisition by the inventory manager, approved by finance (not self)
    client.login("inventory@demo.ehms")
    r = client.post(f"/api/hotels/{hid}/procurement/requisitions", {"department": "kitchen", "store_id": main, "justification": "Weekend banquet",
                                                                    "lines": [{"item_id": chkn["id"], "quantity": 120}, {"item_id": beer["id"], "quantity": 48}]})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    client.login("procurement@demo.ehms")
    assert client.post(f"/api/procurement/requisitions/{rid}/quotes", {"supplier_id": d["supplier"]["SUP001"]["id"], "lines": []}).status_code == 409
    client.login("finance@demo.ehms")
    assert client.post(f"/api/procurement/requisitions/{rid}/decide", {"decision": "approve"}).status_code == 200
    # 2. two quotations; the comparison picks the cheapest per line
    client.login("procurement@demo.ehms")
    lines = client.get(f"/api/procurement/requisitions/{rid}").json()["lines"]
    q1 = client.post(f"/api/procurement/requisitions/{rid}/quotes", {"supplier_id": d["supplier"]["SUP001"]["id"], "reference": "Q-A",
                     "lines": [{"requisition_line_id": lines[0]["id"], "unit_cost": 440000}, {"requisition_line_id": lines[1]["id"], "unit_cost": 72000}]}).json()
    q2 = client.post(f"/api/procurement/requisitions/{rid}/quotes", {"supplier_id": d["supplier"]["SUP002"]["id"], "reference": "Q-B",
                     "lines": [{"requisition_line_id": lines[0]["id"], "unit_cost": 460000}, {"requisition_line_id": lines[1]["id"], "unit_cost": 68000}]}).json()
    comp = client.get(f"/api/procurement/requisitions/{rid}").json()["comparison"]
    assert comp[0]["best_quote_id"] == q1["id"] and comp[1]["best_quote_id"] == q2["id"]
    assert q1["total"] == 120 * 440000 + 48 * 72000
    # 3. PO from quote 1 → above the high-value threshold (NGN 500,000) → needs approve_high
    po = client.post(f"/api/hotels/{hid}/procurement/purchase-orders", {"quote_id": q1["id"], "store_id": main, "expected_date": d["hotel"]["business_date"]})
    assert po.status_code == 201, po.text
    po = po.json()
    assert po["approval_level"] == "high" and po["total"] == q1["total"]
    assert client.post(f"/api/procurement/purchase-orders/{po['id']}/decide", {"decision": "approve"}).status_code == 403  # maker-checker / permission
    assert client.post(f"/api/procurement/purchase-orders/{po['id']}/receive", {"lines": [{"po_line_id": 1, "quantity": 1}]}).status_code == 409
    client.login("finance@demo.ehms")
    assert client.post(f"/api/procurement/purchase-orders/{po['id']}/decide", {"decision": "approve"}).json()["status"] == "approved"
    # 4. partial GRN; chicken is expiry-tracked; over-receipt refused
    client.login("stores@demo.ehms")
    pol = client.get(f"/api/procurement/purchase-orders/{po['id']}").json()["lines"]
    chl = next(l for l in pol if l["item_id"] == chkn["id"])
    bel = next(l for l in pol if l["item_id"] == beer["id"])
    assert client.post(f"/api/procurement/purchase-orders/{po['id']}/receive", {"lines": [{"po_line_id": chl["id"], "quantity": 20}]}).status_code == 400
    assert client.post(f"/api/procurement/purchase-orders/{po['id']}/receive",
                       {"lines": [{"po_line_id": chl["id"], "quantity": 125, "expiry_date": "2030-01-01"}]}).status_code == 400
    q_before = qty(chkn["id"], main)
    g1 = client.post(f"/api/procurement/purchase-orders/{po['id']}/receive", {"delivery_note": "DN-1", "lines": [
        {"po_line_id": chl["id"], "quantity": 18, "rejected": 2, "batch_no": "B-77", "expiry_date": "2030-01-01"}]})
    assert g1.status_code == 201, g1.text
    assert g1.json()["po_status"] == "partially_received" and g1.json()["value"] == 18 * 440000
    assert qty(chkn["id"], main) - q_before == 18000
    g2 = client.post(f"/api/procurement/purchase-orders/{po['id']}/receive", {"lines": [
        {"po_line_id": chl["id"], "quantity": 102, "expiry_date": "2030-01-01"}, {"po_line_id": bel["id"], "quantity": 48, "expiry_date": "2030-06-01"}]})
    assert g2.json()["po_status"] == "received"
    received = 120 * 440000 + 48 * 72000
    assert gl_balance("grni", hid) == -received
    # 5. invoice with a price variance above tolerance → approval with a note; approver ≠ recorder
    client.login("accounts@demo.ehms")
    inv = client.post(f"/api/hotels/{hid}/procurement/invoices", {"supplier_id": d["supplier"]["SUP001"]["id"], "po_id": po["id"], "invoice_no": "LFF-9001",
                                                                  "invoice_date": d["hotel"]["business_date"], "amount": received + 500000})
    assert inv.status_code == 201 and inv.json()["match_status"] == "variance" and inv.json()["variance"] == 500000
    dup = client.post(f"/api/hotels/{hid}/procurement/invoices", {"supplier_id": d["supplier"]["SUP001"]["id"], "po_id": po["id"], "invoice_no": "LFF-9001",
                                                                  "invoice_date": d["hotel"]["business_date"], "amount": 1})
    assert dup.status_code in (409,)
    assert client.post(f"/api/procurement/invoices/{inv.json()['id']}/payments", {"amount": 1, "method_id": d["method"]["TRANSFER"]["id"],
                                                                                 "reference": "x", "idempotency_key": uuid.uuid4().hex}).status_code == 409
    client.login("finance@demo.ehms")
    assert client.post(f"/api/procurement/invoices/{inv.json()['id']}/decide", {"decision": "approve"}).status_code == 400  # variance needs a note
    ap = client.post(f"/api/procurement/invoices/{inv.json()['id']}/decide", {"decision": "approve", "note": "Price increase agreed by phone"})
    assert ap.status_code == 200
    assert gl_balance("grni", hid) == 0 and gl_balance("ppv", hid) == 500000 and gl_balance("ap", hid) == -(received + 500000)
    # 6. pay in two parts with 5% WHT withheld
    client.login("accounts@demo.ehms")
    key = uuid.uuid4().hex
    p1 = client.post(f"/api/procurement/invoices/{inv.json()['id']}/payments", {"amount": 1000000, "method_id": d["method"]["TRANSFER"]["id"],
                                                                               "reference": "TRF-1", "idempotency_key": key})
    assert p1.status_code == 201 and (p1.json()["wht"], p1.json()["net"]) == (50000, 950000) and p1.json()["invoice_status"] == "part_paid"
    again = client.post(f"/api/procurement/invoices/{inv.json()['id']}/payments", {"amount": 1000000, "method_id": d["method"]["TRANSFER"]["id"],
                                                                                  "reference": "TRF-1", "idempotency_key": key})
    assert again.json().get("duplicate") is True
    rest = received + 500000 - 1000000
    assert client.post(f"/api/procurement/invoices/{inv.json()['id']}/payments", {"amount": rest + 1, "method_id": d["method"]["TRANSFER"]["id"],
                                                                                 "reference": "TRF-2", "idempotency_key": uuid.uuid4().hex}).status_code == 400
    p2 = client.post(f"/api/procurement/invoices/{inv.json()['id']}/payments", {"amount": rest, "method_id": d["method"]["TRANSFER"]["id"],
                                                                               "reference": "TRF-2", "idempotency_key": uuid.uuid4().hex})
    assert p2.json()["invoice_status"] == "paid"
    assert gl_balance("ap", hid) == 0
    assert gl_balance("wht_payable", hid) == -(p1.json()["wht"] + p2.json()["wht"])
    # 7. supplier performance and procurement summary reflect the deliveries
    sup = next(s for s in client.get(f"/api/hotels/{hid}/procurement/suppliers").json()["items"] if s["code"] == "SUP001")
    assert sup["performance"]["deliveries"] == 2 and sup["performance"]["rejected_pct"] == round(2 * 100 / 170, 1) and sup["balance"] == 0
    # accountant cannot see full bank account... accountant has procurement.pay so can; auditor gets it masked
    client.login("auditor@demo.ehms")
    sup = next(s for s in client.get(f"/api/hotels/{hid}/procurement/suppliers").json()["items"] if s["code"] == "SUP001")
    assert sup["bank_account_number"].startswith("•")
    assert_books_balance(hid)


def test_procurement_standard_po_and_no_po_invoice(client):
    d = ids()
    hid = d["hotel"]["id"]
    client.login("procurement@demo.ehms")
    po = client.post(f"/api/hotels/{hid}/procurement/purchase-orders", {"supplier_id": d["supplier"]["SUP003"]["id"], "store_id": d["store"]["HSK"]["id"], "lines": [
        {"item_id": d["item"]["SOAP"]["id"], "quantity": 100, "unit_cost": 15000},
        {"description": "Carpet shampoo service", "quantity": 1, "unit_cost": 2500000, "expense_key": "exp_maintenance"}]}).json()
    assert po["approval_level"] == "standard"
    # the procurement officer cannot approve; the inventory manager has no approve permission either; finance can
    assert client.post(f"/api/procurement/purchase-orders/{po['id']}/decide", {"decision": "approve"}).status_code == 403
    client.login("finance@demo.ehms")
    client.post(f"/api/procurement/purchase-orders/{po['id']}/decide", {"decision": "approve"})
    client.login("stores@demo.ehms")
    lines = client.get(f"/api/procurement/purchase-orders/{po['id']}").json()["lines"]
    maint_before = gl_balance("exp_maintenance", hid)
    g = client.post(f"/api/procurement/purchase-orders/{po['id']}/receive", {"lines": [{"po_line_id": l["id"], "quantity": l["quantity"]} for l in lines]})
    assert g.status_code == 201 and g.json()["po_status"] == "received"
    assert gl_balance("exp_maintenance", hid) - maint_before == 2500000   # service line expensed at GRN
    # matched invoice within tolerance; then a utility bill without a PO
    client.login("accounts@demo.ehms")
    inv = client.post(f"/api/hotels/{hid}/procurement/invoices", {"supplier_id": d["supplier"]["SUP003"]["id"], "po_id": po["id"], "invoice_no": "CP-1",
                                                                  "invoice_date": d["hotel"]["business_date"], "amount": 4000000 + 50}).json()
    assert inv["match_status"] == "matched"
    nopo = client.post(f"/api/hotels/{hid}/procurement/invoices", {"supplier_id": d["supplier"]["SUP004"]["id"], "invoice_no": "PF-7",
                                                                   "invoice_date": d["hotel"]["business_date"], "amount": 1200000})
    assert nopo.status_code == 400   # needs an expense account
    nopo = client.post(f"/api/hotels/{hid}/procurement/invoices", {"supplier_id": d["supplier"]["SUP004"]["id"], "invoice_no": "PF-7", "expense_key": "exp_fuel",
                                                                   "invoice_date": d["hotel"]["business_date"], "amount": 1200000}).json()
    assert nopo["match_status"] == "no_po"
    assert client.post(f"/api/procurement/invoices/{inv['id']}/decide", {"decision": "approve"}).status_code == 403   # cannot approve own
    client.login("finance@demo.ehms")
    fuel_before = gl_balance("exp_fuel", hid)
    client.post(f"/api/procurement/invoices/{inv['id']}/decide", {"decision": "approve"})
    client.post(f"/api/procurement/invoices/{nopo['id']}/decide", {"decision": "approve"})
    assert gl_balance("exp_fuel", hid) - fuel_before == 1200000
    summ = client.get(f"/api/hotels/{hid}/procurement/summary").json()
    assert summ["payables_total"] == 4000050 + 1200000
    assert_books_balance(hid)


def test_permission_upgrade_grants_new_permissions_once(client):
    """Existing organisations receive 0.4 permissions on their system roles exactly once."""
    from ehms.rbac import apply_permission_upgrades
    with get_db().tx() as c:
        org = c.scalar("SELECT id FROM organisations WHERE code = 'DEMO'")
        role = c.one("SELECT id FROM roles WHERE organisation_id = ? AND code = 'restaurant_cashier'", [org])
        # simulate a pre-0.4 database: drop the marker and the cashier's POS permissions
        c.execute("DELETE FROM system_settings WHERE key LIKE ?", ["rbac.upgrade.%"])
        c.execute("DELETE FROM role_permissions WHERE role_id = ? AND permission_code LIKE ?", [role["id"], "pos.%"])
        assert apply_permission_upgrades(c, org) == ["0.4"]
        perms = {r["permission_code"] for r in c.all("SELECT permission_code FROM role_permissions WHERE role_id = ?", [role["id"]])}
        assert {"pos.order", "pos.settle", "pos.shift"} <= perms and "pos.manage" not in perms
        # an administrator then removes a permission: the upgrade does not re-add it
        c.execute("DELETE FROM role_permissions WHERE role_id = ? AND permission_code = 'pos.settle'", [role["id"]])
        assert apply_permission_upgrades(c, org) == []
        assert not c.one("SELECT 1 FROM role_permissions WHERE role_id = ? AND permission_code = 'pos.settle'", [role["id"]])


def test_reports_and_dashboard_include_new_modules(client):
    d = ids()
    hid = d["hotel"]["id"]
    client.login("fnbmanager@demo.ehms")
    client.post(f"/api/hotels/{hid}/pos/shifts", {"outlet_id": d["outlet"]["REST"]["id"]})
    oid = open_order(client, d, [("JRC", 1)])
    client.post(f"/api/pos/orders/{oid}/send", {})
    total = client.get(f"/api/pos/orders/{oid}").json()["totals"]["total"]
    client.post(f"/api/pos/orders/{oid}/settle", {"tenders": [{"tender": "method", "method_id": d["method"]["CASH"]["id"], "amount": total}]})
    client.login("gm@demo.ehms")
    dash = client.get(f"/api/hotels/{hid}/dashboard").json()
    assert any(r["department"] == "fnb_outlet" and r["amount"] == 850000 for r in dash["revenue_today"])
    assert "low_stock_items" in dash["tasks"] and dash["tasks"]["purchase_orders_pending"] == 0
    names = {r["code"] for r in client.get(f"/api/hotels/{hid}/reports").json()["items"]}
    assert {"outlet_sales", "stock_valuation", "payables", "low_stock"} <= names
    sales = client.get(f"/api/hotels/{hid}/reports/outlet_sales").json()
    assert sales["rows"][0][0] == "Savanna Restaurant" and sales["rows"][0][1] == 1
    rev = client.get(f"/api/hotels/{hid}/reports/daily_revenue").json()
    assert any(r[0].startswith("fnb (POS") for r in rev["rows"])
    xlsx = client.get(f"/api/hotels/{hid}/reports/stock_valuation", params={"format": "xlsx"})
    assert xlsx.status_code == 200
    with get_db().tx() as c:
        assert c.one("SELECT * FROM audit_logs WHERE action = 'report.exported' AND entity_id = 'stock_valuation'")
    # a receptionist cannot open inventory or payables reports
    client.login("frontdesk@demo.ehms")
    assert client.get(f"/api/hotels/{hid}/reports/payables").status_code == 403
    assert "stock_valuation" not in {r["code"] for r in client.get(f"/api/hotels/{hid}/reports").json()["items"]}
