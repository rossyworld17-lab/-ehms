"""Release 0.95: cancellation policies and fees, group blocks and rooming lists (availability holds, release, master
folio billing), additional folios and charge transfers, credit / debit notes, exchange rates and foreign-currency
payments, FIFO costing, recruitment."""
import datetime as dt
import uuid

from ehms.db import get_db

from test_frontoffice_finance import arrival_today, ctx_ids, pay
from test_pos_inventory_procurement import assert_books_balance, gl_balance


def book(client, h, days_ahead=0, nights=2, code="STD", **extra):
    a = dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=days_ahead)
    with get_db().tx() as c:
        rt = c.one("SELECT * FROM room_types WHERE hotel_id = ? AND code = ?", [h["id"], code])
    r = client.post(f"/api/hotels/{h['id']}/reservations", {"arrival": a.isoformat(), "departure": (a + dt.timedelta(days=nights)).isoformat(), "room_type_id": rt["id"],
                    "guest": {"first_name": "Test", "last_name": uuid.uuid4().hex[:6], "email": f"{uuid.uuid4().hex[:8]}@example.com", "force": True}, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def avail(client, h, a, d, code="STD"):
    rows = client.get(f"/api/hotels/{h['id']}/availability", params={"arrival": a, "departure": d}).json()["room_types"]
    return next(t["available"] for t in rows if t["code"] == code)


def test_cancellation_and_no_show_fees(client):
    h, _ = ctx_ids()
    client.login("frontdesk@demo.ehms")
    late = book(client, h, 0)                                                         # arriving today: past the 24-hour free window
    prev = client.get(f"/api/reservations/{late['id']}/cancellation-fee").json()
    assert prev["fee"] > 0 and "first night" in prev["explanation"]
    assert client.post(f"/api/reservations/{late['id']}/cancel", {"reason": "Plans changed", "waive_fee_reason": "Loyal guest"}).status_code == 403
    out = client.post(f"/api/reservations/{late['id']}/cancel", {"reason": "Plans changed"}).json()
    assert out["cancellation_fee"]["fee"] == prev["fee"] and out["cancellation_fee"]["posted_to_folio"]
    folio = client.get(f"/api/reservations/{late['id']}/folio").json()
    assert any(l["description"].startswith("Cancellation fee") for l in folio["lines"]) and folio["totals"]["balance"] > 0
    early = book(client, h, 10)
    assert client.post(f"/api/reservations/{early['id']}/cancel", {"reason": "Plans changed"}).json()["cancellation_fee"]["fee"] == 0
    # front office manager may waive with a reason
    client.login("fom@demo.ehms")
    w = book(client, h, 0)
    o = client.post(f"/api/reservations/{w['id']}/cancel", {"reason": "Flight cancelled", "waive_fee_reason": "Airline strike, documented"}).json()
    assert o["cancellation_fee"]["waived"] and o["fee_waive_reason"]
    # non-refundable policy: 100 % of the stay, also for no-shows
    with get_db().tx() as c:
        nr = c.scalar("SELECT id FROM cancellation_policies WHERE hotel_id = ? AND name LIKE ?", [h["id"], "Non-refundable%"])
    ns = book(client, h, 0, nights=2, cancellation_policy_id=nr)
    fee = client.post(f"/api/reservations/{ns['id']}/no-show", {}).json()["cancellation_fee"]
    assert fee["fee"] == 2 * ns["quote"]["nights"][0]["room_rate"]
    # a policy in use cannot be re-priced
    client.login("admin@demo.ehms")
    assert client.patch(f"/api/cancellation-policies/{nr}", {"fee_value": 5000}).status_code == 409
    # the booking engine allows online cancellation only inside the free window
    with get_db().tx() as c:
        email = c.scalar("SELECT g.email FROM reservations r JOIN guests g ON g.id = r.guest_id WHERE r.id = ?", [early["id"]])
    tomorrow = book(client, h, 1, nights=1, cancellation_policy_id=nr)       # non-refundable: never free, whatever the time of day
    with get_db().tx() as c:
        email2 = c.scalar("SELECT g.email FROM reservations r JOIN guests g ON g.id = r.guest_id WHERE r.id = ?", [tomorrow["id"]])
    r = client.post(f"/api/public/bookings/{tomorrow['reference']}/cancel", {"email": email2}, token=None)
    assert r.status_code == 409 and "free-cancellation" in r.text
    assert_books_balance(h["id"])


def test_group_block_holds_rooms_rooming_list_and_release(client):
    h, _ = ctx_ids()
    client.login("sales@demo.ehms")
    a = (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=30)).isoformat()
    d = (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=32)).isoformat()
    with get_db().tx() as c:
        std = c.one("SELECT * FROM room_types WHERE hotel_id = ? AND code = 'STD'", [h["id"]])
    before = avail(client, h, a, d)
    n = min(3, before)
    assert client.post(f"/api/hotels/{h['id']}/groups", {"name": "Too big", "arrival": a, "departure": d, "cutoff_date": a,
                       "rooms": [{"room_type_id": std["id"], "rooms": before + 5}]}).status_code == 409
    g = client.post(f"/api/hotels/{h['id']}/groups", {"name": "NNPC retreat", "arrival": a, "departure": d, "cutoff_date": a, "status": "definite",
                    "rooms": [{"room_type_id": std["id"], "rooms": n, "rate": 3000000}]})
    assert g.status_code == 201, g.text
    gid = g.json()["id"]
    assert avail(client, h, a, d) == before - n                                         # held rooms are not sold to others
    csv = "first_name,last_name,email,room_type\nAda,Obi,ada@example.com,STD\nBola,Ade,,STD\n,Missing,,STD\n"
    rl = client.post(f"/api/groups/{gid}/rooming-list", {"csv": csv}).json()
    assert rl["created"] == 2 and rl["failed"] == 1
    det = client.get(f"/api/groups/{gid}").json()
    assert det["rooms"][0]["picked_up_max"] == 2 and len(det["reservations"]) == 2
    res = client.get(f"/api/reservations/{det['reservations'][0]['id']}").json()
    assert res["nightly_rate"] == 3000000 and res["booking_type"] == "group" and res["group_block_id"] == gid
    assert avail(client, h, a, d) == before - n                                         # pickup uses the block, not general stock
    assert client.patch(f"/api/groups/{gid}", {"rooms": [{"room_type_id": std["id"], "rooms": 1}]}).status_code == 409   # below pickup
    rel = client.post(f"/api/groups/{gid}/release").json()
    assert rel["rooms_released"] == n - 2 and avail(client, h, a, d) == before - 2
    assert "Ada" in client.get(f"/api/groups/{gid}/rooming-list.csv").text
    # worker releases unpicked rooms after the cut-off date
    g2 = client.post(f"/api/hotels/{h['id']}/groups", {"name": "Late group", "arrival": a, "departure": d, "cutoff_date": h["business_date"],
                     "rooms": [{"room_type_id": std["id"], "rooms": 1}]}).json()
    from ehms.modules.groups import release_after_cutoff
    with get_db().tx() as c:
        c.execute("UPDATE group_blocks SET cutoff_date = ? WHERE id = ?", [(dt.date.fromisoformat(h["business_date"]) - dt.timedelta(days=1)).isoformat(), g2["id"]])
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [h["id"]])
        assert release_after_cutoff(c, hotel) == 1
        assert c.scalar("SELECT status FROM group_blocks WHERE id = ?", [g2["id"]]) == "released"
    client.login("frontdesk@demo.ehms")                                                  # no reservations.groups
    assert client.post(f"/api/hotels/{h['id']}/groups", {"name": "x", "arrival": a, "departure": d, "cutoff_date": a, "rooms": []}).status_code == 403


def test_group_master_folio_billing(client):
    h, methods = ctx_ids()
    client.login("fom@demo.ehms")
    with get_db().tx() as c:
        std = c.one("SELECT * FROM room_types WHERE hotel_id = ? AND code = 'STD'", [h["id"]])
    d = (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=1)).isoformat()
    g = client.post(f"/api/hotels/{h['id']}/groups", {"name": "Board meeting", "arrival": h["business_date"], "departure": d, "cutoff_date": h["business_date"],
                    "status": "definite", "billing": "master_room", "rooms": [{"room_type_id": std["id"], "rooms": 1, "rate": 2500000}]}).json()
    rl = client.post(f"/api/groups/{g['id']}/rooming-list", {"rows": [{"first_name": "Uche", "last_name": "Nwosu", "room_type": "STD"}]}).json()
    assert rl["created"] == 1
    master = client.post(f"/api/groups/{g['id']}/master-folio").json()
    rid = client.get(f"/api/groups/{g['id']}").json()["reservations"][0]["id"]
    av = client.get(f"/api/hotels/{h['id']}/availability", params={"arrival": h["business_date"], "departure": d}).json()
    room = next(r for r in av["free_rooms"] if r["room_type_id"] == std["id"] and r["hk_status"] == "inspected")
    client.patch(f"/api/reservations/{rid}", {"room_id": room["id"]})
    assert client.post(f"/api/reservations/{rid}/check-in", {"room_id": room["id"]}).status_code == 200
    assert client.get(f"/api/reservations/{rid}/checkout-preview").json()["balance_due"] == 0     # room billed to the master folio
    out = client.post(f"/api/reservations/{rid}/check-out", {})
    assert out.status_code == 200, out.text
    mf = client.get(f"/api/folios/{master['id']}").json()
    assert any(l["reference"] and l["reference"].startswith("ROOM:") for l in mf["lines"]) and mf["totals"]["balance"] > 0
    assert_books_balance(h["id"])


def test_extra_folio_transfer_and_checkout(client):
    h, methods = ctx_ids()
    client.login("frontdesk@demo.ehms")
    res, _ = arrival_today(client, h)
    fid = client.post(f"/api/reservations/{res['id']}/check-in", {}).json()["folio"]["id"]
    l1 = client.post(f"/api/folios/{fid}/charges", {"department": "fnb", "description": "Business dinner", "amount": 4000000}).json()["id"]
    l2 = client.post(f"/api/folios/{fid}/charges", {"department": "laundry", "description": "Shirts", "amount": 500000}).json()["id"]
    ledger = gl_balance("guest_ledger", h["id"])
    xf = client.post(f"/api/reservations/{res['id']}/folios", {"window_name": "Company — Delta Energy"})
    assert xf.status_code == 201
    xid = xf.json()["id"]
    before = client.get(f"/api/folios/{fid}").json()["totals"]["balance"]
    t = client.post(f"/api/folios/{fid}/transfer", {"line_ids": [l1], "target_folio_id": xid, "reason": "Company pays dinner"})
    assert t.status_code == 200, t.text
    src, dst = client.get(f"/api/folios/{fid}").json(), client.get(f"/api/folios/{xid}").json()
    assert before - src["totals"]["balance"] == t.json()["amount"] == dst["totals"]["balance"]
    assert any(o["id"] == xid for o in src["other_folios"])
    assert client.post(f"/api/folios/{fid}/transfer", {"line_ids": [l1], "target_folio_id": xid, "reason": "again"}).status_code == 409
    part = client.post(f"/api/folios/{fid}/transfer", {"line_ids": [l2], "target_folio_id": xid, "reason": "half", "amount": 200000})
    assert part.status_code == 200 and part.json()["amount"] == 200000
    assert gl_balance("guest_ledger", h["id"]) == ledger                                 # transfers do not change the ledger
    due = client.get(f"/api/reservations/{res['id']}/checkout-preview").json()["balance_due"]
    pay(client, fid, methods["CASH"], due)
    blocked = client.post(f"/api/reservations/{res['id']}/check-out", {})
    assert blocked.status_code == 409 and "Company" in blocked.text                     # the company folio is still open with a balance
    pay(client, xid, methods["CASH"], client.get(f"/api/folios/{xid}").json()["totals"]["balance"])
    assert client.post(f"/api/reservations/{res['id']}/check-out", {}).status_code == 200
    assert client.get(f"/api/folios/{xid}").json()["status"] == "closed"
    assert_books_balance(h["id"])


def test_credit_and_debit_notes_maker_checker(client):
    h, methods = ctx_ids()
    client.login("frontdesk@demo.ehms")
    res, _ = arrival_today(client, h)
    fid = client.post(f"/api/reservations/{res['id']}/check-in", {}).json()["folio"]["id"]
    due = client.get(f"/api/reservations/{res['id']}/checkout-preview").json()["balance_due"]
    pay(client, fid, methods["CASH"], due)
    assert client.post(f"/api/reservations/{res['id']}/check-out", {}).status_code == 200
    client.login("fom@demo.ehms")
    too_big = client.post(f"/api/folios/{fid}/notes", {"kind": "credit", "department": "room", "description": "x", "net_amount": 999999999, "reason": "Too much credit"})
    assert too_big.status_code == 409
    cn = client.post(f"/api/folios/{fid}/notes", {"kind": "credit", "department": "room", "description": "Goodwill — noisy room", "net_amount": 1000000,
                     "reason": "Construction noise all night"})
    assert cn.status_code == 201 and cn.json()["number"].startswith("CN")
    assert client.post(f"/api/notes/{cn.json()['id']}/decide", {"decision": "approve"}).status_code == 403   # FOM cannot approve
    client.login("finance@demo.ehms")
    own = client.post(f"/api/folios/{fid}/notes", {"kind": "debit", "department": "fnb", "description": "Minibar found after departure", "net_amount": 300000,
                      "reason": "Housekeeping report after departure"}).json()
    assert client.post(f"/api/notes/{own['id']}/decide", {"decision": "approve"}).status_code == 403          # not your own note
    rev_before, vat_before = gl_balance("rev_room", h["id"]), gl_balance("vat_payable", h["id"])
    ok = client.post(f"/api/notes/{cn.json()['id']}/decide", {"decision": "approve"}).json()
    assert ok["folio_reopened"] and ok["folio_balance"] < 0 and "refund" in ok["message"]
    assert gl_balance("rev_room", h["id"]) - rev_before == 1000000                      # revenue reduced (debit)
    assert gl_balance("vat_payable", h["id"]) > vat_before                              # output VAT reduced
    assert client.post(f"/api/notes/{cn.json()['id']}/decide", {"decision": "approve"}).status_code == 409
    client.login("fom@demo.ehms")
    assert client.post(f"/api/notes/{own['id']}/decide", {"decision": "reject"}).status_code == 403
    client.login("gm@demo.ehms")
    assert client.post(f"/api/notes/{own['id']}/decide", {"decision": "reject"}).status_code == 400            # note required
    d = client.post(f"/api/notes/{own['id']}/decide", {"decision": "approve", "note": "Confirmed by housekeeping"}).json()
    assert d["status"] == "approved"
    pdf = client.get(f"/api/notes/{own['id']}/pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert len(client.get(f"/api/hotels/{h['id']}/notes").json()["items"]) >= 2
    assert_books_balance(h["id"])


def test_exchange_rates_and_foreign_currency_payment(client):
    h, methods = ctx_ids()
    client.login("frontdesk@demo.ehms")
    assert client.post("/api/exchange-rates", {"currency": "CHF", "rate": "1700"}).status_code == 403
    client.login("finance@demo.ehms")
    assert client.post("/api/exchange-rates", {"currency": "NGN", "rate": "1"}).status_code == 400
    assert client.post("/api/exchange-rates", {"currency": "CHF", "rate": "abc"}).status_code == 400
    tomorrow = (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=1)).isoformat()
    r = client.post("/api/exchange-rates", {"currency": "USD", "rate": "1500.5", "rate_date": h["business_date"]})
    assert r.status_code in (201, 409)       # the demo already records today's USD rate
    w = client.post("/api/exchange-rates", {"currency": "USD", "rate": "2100", "rate_date": tomorrow})
    assert w.status_code == 201 and "warning" in w.json()
    client.login("frontdesk@demo.ehms")
    res, _ = arrival_today(client, h)
    fid = client.post(f"/api/reservations/{res['id']}/check-in", {}).json()["folio"]["id"]
    with get_db().tx() as c:
        rate = c.scalar("SELECT rate_micro FROM exchange_rates WHERE currency = 'USD' AND rate_date <= ? ORDER BY rate_date DESC LIMIT 1", [h["business_date"]])
    key = uuid.uuid4().hex
    p = client.post(f"/api/folios/{fid}/payments", {"currency": "USD", "foreign_amount": 10000, "method_id": methods["CASH"], "idempotency_key": key})
    assert p.status_code == 201, p.text
    assert p.json()["amount"] == (10000 * rate + 500000) // 1000000                     # US$100.00 at today's rate
    dup = client.post(f"/api/folios/{fid}/payments", {"currency": "USD", "foreign_amount": 10000, "method_id": methods["CASH"], "idempotency_key": key})
    assert dup.json()["duplicate"] is True
    with get_db().tx() as c:
        row = c.one("SELECT * FROM payments WHERE id = ?", [p.json()["id"]])
    assert row["foreign_currency"] == "USD" and row["foreign_amount"] == 10000 and row["exchange_rate_micro"] == rate
    assert client.post(f"/api/folios/{fid}/payments", {"currency": "JPY", "foreign_amount": 10000, "method_id": methods["CASH"],
                       "idempotency_key": uuid.uuid4().hex}).status_code == 409
    assert_books_balance(h["id"])


def test_fifo_costing_option(client):
    h, _ = ctx_ids()
    from ehms.stock import apply_movement, outflow_value
    with get_db().tx() as c:
        store = c.one("SELECT * FROM stores WHERE hotel_id = ? ORDER BY id", [h["id"]])
        iid = c.insert("inventory_items", {"hotel_id": h["id"], "code": "FIFO1", "name": "Test oil", "unit": "l", "category": "food", "last_cost": 0,
                                           "reorder_level_milli": 0, "reorder_qty_milli": 0, "active": 1, "created_at": "2026-01-01T00:00:00Z"})
        item = c.one("SELECT * FROM inventory_items WHERE id = ?", [iid])
        on = dt.date.fromisoformat(h["business_date"])
        apply_movement(c, h["id"], item, store, "receipt", 10000, 100000, "test", None, None, on)    # 10 l at 100.00
        apply_movement(c, h["id"], item, store, "receipt", 10000, 200000, "test", None, None, on)    # 10 l at 200.00
        assert outflow_value(c, item, store, 12000) == 180000                          # weighted average: 12 l x 150.00
    client.login("gm@demo.ehms")
    assert client.put(f"/api/hotels/{h['id']}/inventory/costing", {"method": "lifo", "reason": "x"}).status_code == 400
    assert client.put(f"/api/hotels/{h['id']}/inventory/costing", {"method": "fifo", "reason": "Auditor recommendation"}).json()["method"] == "fifo"
    with get_db().tx() as c:
        item = c.one("SELECT * FROM inventory_items WHERE id = ?", [iid])
        assert outflow_value(c, item, store, 12000) == 140000                          # FIFO: 10 l x 100 + 2 l x 200
        _, v = apply_movement(c, h["id"], item, store, "issue", -12000, None, "test", None, None, dt.date.fromisoformat(h["business_date"]))
        assert v == -140000
        lvl = c.one("SELECT * FROM stock_levels WHERE item_id = ? AND store_id = ?", [iid, store["id"]])
        assert lvl["quantity_milli"] == 8000 and lvl["value"] == 160000                # what remains is the dearer batch


def test_recruitment_pipeline_and_hire(client):
    h, _ = ctx_ids()
    client.login("sales@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/recruitment").status_code == 403
    client.login("hrofficer@demo.ehms")
    o = client.post(f"/api/hotels/{h['id']}/recruitment", {"title": "Night Auditor", "department": "finance", "positions": 1, "salary_min": 18000000, "salary_max": 15000000})
    assert o.status_code == 400
    oid = client.post(f"/api/hotels/{h['id']}/recruitment", {"title": "Night Auditor", "department": "finance", "positions": 1}).json()["id"]
    a = client.post(f"/api/recruitment/{oid}/applicants", {"first_name": "Zainab", "last_name": "Ali", "email": "zainab@example.com", "source": "Referral"}).json()["id"]
    assert client.post(f"/api/recruitment/{oid}/applicants", {"first_name": "Z", "last_name": "A", "email": "ZAINAB@example.com"}).status_code == 409
    b = client.post(f"/api/recruitment/{oid}/applicants", {"first_name": "Femi", "last_name": "Kuti", "email": "femi@example.com"}).json()["id"]
    assert client.post(f"/api/applicants/{a}/stage", {"stage": "offer"}).status_code == 409                   # cannot skip stages
    for s in ("screening", "interview"):
        assert client.post(f"/api/applicants/{a}/stage", {"stage": s}).status_code == 200
    assert client.post(f"/api/applicants/{a}/notes", {"kind": "interview", "note": "Strong reconciliation skills", "score": 5}).status_code == 201
    assert client.post(f"/api/applicants/{a}/stage", {"stage": "offer"}).status_code == 400                   # offer needs salary and start date
    start = (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=14)).isoformat()
    assert client.post(f"/api/applicants/{a}/stage", {"stage": "offer", "offered_salary": 16000000, "start_date": start}).status_code == 200
    assert client.post(f"/api/applicants/{b}/stage", {"stage": "rejected"}).status_code == 400                # rejection needs a note
    assert client.post(f"/api/applicants/{b}/stage", {"stage": "rejected", "note": "Not available for night shifts"}).status_code == 200
    cv = client.post("/api/documents", {"entity_type": "applicant", "entity_id": a, "category": "hr_record", "confidentiality": "internal", "filename": "cv.pdf",
                     "content_base64": "JVBERi0xLjQKJSVFT0YK"})
    assert cv.status_code == 201, cv.text
    hired = client.post(f"/api/applicants/{a}/hire", {})
    assert hired.status_code == 200, hired.text
    emp = client.get(f"/api/employees/{hired.json()['employee_id']}").json()
    assert emp["position"] == "Night Auditor" and emp["hire_date"] == start and hired.json()["opening_filled"]
    docs = client.get("/api/documents", params={"entity_type": "employee", "entity_id": emp["id"]}).json()["items"]
    assert any(d["filename"] == "cv.pdf" for d in docs)                                 # the CV moved to the employee file
    assert client.get(f"/api/applicants/{a}").json()["average_score"] == 5
    an = client.post(f"/api/recruitment/{oid}/anonymise").json()
    assert an["anonymised"] == 1
    assert client.get(f"/api/applicants/{b}").json()["email"] is None
