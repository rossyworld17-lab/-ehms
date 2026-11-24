"""Release 1.2 — requirements completion: wake-up calls, early check-in / late check-out, registration card, table
reservations, purchase returns, guest referrals, staff welfare, petty cash and payment vouchers, room photos and
videos, CCTV event links, list pagination, interface language, and backups with verification and restore."""
import base64
import datetime as dt
import os
import uuid
import zipfile

from ehms.db import Database, get_db

from test_frontoffice_finance import arrival_today, ctx_ids, pay
from test_pos_inventory_procurement import assert_books_balance, gl_balance, ids, qty

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()


# ------------------------------------------------------------------ front office
def test_wake_up_calls_early_late_and_registration_card(client):
    h, methods = ctx_ids()
    client.login("frontdesk@demo.ehms")
    res, _ = arrival_today(client, h)
    rid = res["id"]
    # registration card prints before check-in
    card = client.get(f"/api/reservations/{rid}/registration-card.pdf")
    assert card.status_code == 200 and card.content.startswith(b"%PDF")
    # fees configured by an administrator
    client.login("gm@demo.ehms")
    assert client.put(f"/api/hotels/{h['id']}/stay-fees", {"early_check_in": 1000000, "late_check_out": 1500000}).status_code == 200
    client.login("frontdesk@demo.ehms")
    assert client.post(f"/api/reservations/{rid}/early-late", {"kind": "late_check_out", "until": "16:00"}).status_code == 409  # not in-house yet
    e = client.post(f"/api/reservations/{rid}/early-late", {"kind": "early_check_in"})
    assert e.status_code == 200 and e.json()["fee_posted"] == 1000000
    assert client.post(f"/api/reservations/{rid}/early-late", {"kind": "early_check_in"}).status_code == 409   # only once
    folio = client.post(f"/api/reservations/{rid}/check-in", {}).json()["folio"]["id"]
    lines = client.get(f"/api/folios/{folio}").json()["lines"]
    assert any(l["description"].startswith("Early check-in") and l["net_amount"] == 1000000 for l in lines)
    # waiving the late check-out fee needs reservations.waive_fee (the receptionist does not hold it)
    assert client.post(f"/api/reservations/{rid}/early-late", {"kind": "late_check_out", "until": "11:00"}).status_code == 400
    assert client.post(f"/api/reservations/{rid}/early-late", {"kind": "late_check_out", "until": "16:00", "waive_reason": "VIP"}).status_code == 403
    client.login("fom@demo.ehms")
    w = client.post(f"/api/reservations/{rid}/early-late", {"kind": "late_check_out", "until": "16:00", "waive_reason": "Loyal guest"})
    assert w.status_code == 200 and w.json()["fee_posted"] == 0 and w.json()["late_check_out_until"] == "16:00"
    # wake-up calls
    client.login("frontdesk@demo.ehms")
    assert client.post(f"/api/reservations/{rid}/wake-up-calls", {"call_time": "6:30"}).status_code == 400
    tomorrow = (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=1)).isoformat()
    wid = client.post(f"/api/reservations/{rid}/wake-up-calls", {"call_date": tomorrow, "call_time": "06:30", "note": "Airport run"}).json()["id"]
    assert client.post(f"/api/reservations/{rid}/wake-up-calls", {"call_date": tomorrow, "call_time": "06:30"}).status_code == 409
    calls = client.get(f"/api/hotels/{h['id']}/wake-up-calls", params={"date": tomorrow}).json()["items"]
    assert any(x["id"] == wid and x["room_number"] for x in calls)
    assert client.post(f"/api/wake-up-calls/{wid}/status", {"status": "done"}).json()["status"] == "done"
    assert client.post(f"/api/wake-up-calls/{wid}/status", {"status": "missed"}).status_code == 409
    # the worker alerts the desk for calls due within 10 minutes (once)
    from ehms.modules.guestservices import _hotel_clock, wakeup_alerts
    with get_db().tx() as c:
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [h["id"]])
        now = _hotel_clock(hotel)
        c.execute("UPDATE wake_up_calls SET status = 'cancelled' WHERE hotel_id = ?", [h["id"]])
        # one call due in 5 minutes (may fall after midnight), one far in the future that must not alert yet
        for when in (now + dt.timedelta(minutes=5), now + dt.timedelta(hours=5)):
            c.insert("wake_up_calls", {"hotel_id": h["id"], "reservation_id": rid, "call_date": when.date().isoformat(), "call_time": when.strftime("%H:%M"),
                                       "status": "pending", "created_by": 1, "created_at": now.isoformat()})
        assert wakeup_alerts(c, hotel) == 1 and wakeup_alerts(c, hotel) == 0
    client.login("housekeeper@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/wake-up-calls").status_code == 403


def test_table_reservations(client):
    d = ids()
    hid, rest = d["hotel"]["id"], d["outlet"]["REST"]["id"]
    t1 = d["table"]
    day = (dt.date.fromisoformat(d["hotel"]["business_date"]) + dt.timedelta(days=1)).isoformat()
    client.login("waiter@demo.ehms")
    with get_db().tx() as c:   # start from an empty evening for this table (the demo data books some tables)
        c.execute("DELETE FROM table_reservations WHERE hotel_id = ?", [hid])
    base = {"outlet_id": rest, "table_id": t1["id"], "guest_name": "Mrs Okafor", "phone": "0803", "party_size": 2, "reserved_date": day, "reserved_time": "19:00"}
    assert client.post(f"/api/hotels/{hid}/table-reservations", {**base, "party_size": 9}).status_code == 400        # table too small
    b1 = client.post(f"/api/hotels/{hid}/table-reservations", base)
    assert b1.status_code == 201, b1.text
    clash = client.post(f"/api/hotels/{hid}/table-reservations", {**base, "guest_name": "Mr Bello", "reserved_time": "20:00"})
    assert clash.status_code == 409                                                                                    # overlaps 19:00–20:30
    assert client.post(f"/api/hotels/{hid}/table-reservations", {**base, "guest_name": "Mr Bello", "reserved_time": "20:30"}).status_code == 201
    walk = client.post(f"/api/hotels/{hid}/table-reservations", {**base, "table_id": None, "guest_name": "Party of 3", "party_size": 3})
    lst = [x for x in client.get(f"/api/hotels/{hid}/table-reservations", params={"date": day}).json()["items"] if x["guest_name"] in ("Mrs Okafor", "Mr Bello", "Party of 3")]
    assert len(lst) == 3 and lst[0]["reserved_time"] == "19:00"
    bid = b1.json()["id"]
    assert client.post(f"/api/table-reservations/{bid}/status", {"status": "completed"}).status_code == 409
    assert client.post(f"/api/table-reservations/{bid}/status", {"status": "seated"}).json()["status"] == "seated"
    # seating an unassigned booking needs a table that is free at that time
    assert client.post(f"/api/table-reservations/{walk.json()['id']}/status", {"status": "seated", "table_id": t1["id"]}).status_code == 409
    assert client.post(f"/api/table-reservations/{bid}/status", {"status": "completed"}).json()["status"] == "completed"
    assert client.post(f"/api/table-reservations/{walk.json()['id']}/status", {"status": "seated", "table_id": t1["id"]}).json()["status"] == "seated"
    client.login("chef@demo.ehms")
    assert client.post(f"/api/hotels/{hid}/table-reservations", base).status_code == 403


# ------------------------------------------------------------------ procurement returns
def _po_received(client, d, qty_beer=24):
    hid, main, beer = d["hotel"]["id"], d["store"]["MAIN"]["id"], d["item"]["BEER"]
    client.login("inventory@demo.ehms")
    rid = client.post(f"/api/hotels/{hid}/procurement/requisitions", {"department": "bar", "store_id": main, "justification": "Restock",
                                                                     "lines": [{"item_id": beer["id"], "quantity": qty_beer}]}).json()["id"]
    client.login("finance@demo.ehms")
    client.post(f"/api/procurement/requisitions/{rid}/decide", {"decision": "approve"})
    client.login("procurement@demo.ehms")
    line = client.get(f"/api/procurement/requisitions/{rid}").json()["lines"][0]
    q = client.post(f"/api/procurement/requisitions/{rid}/quotes", {"supplier_id": d["supplier"]["SUP002"]["id"], "lines": [{"requisition_line_id": line["id"], "unit_cost": 70000}]}).json()
    po = client.post(f"/api/hotels/{hid}/procurement/purchase-orders", {"quote_id": q["id"], "store_id": main, "expected_date": d["hotel"]["business_date"]}).json()
    client.login("finance@demo.ehms")
    assert client.post(f"/api/procurement/purchase-orders/{po['id']}/decide", {"decision": "approve"}).json()["status"] == "approved"
    client.login("stores@demo.ehms")
    pl = client.get(f"/api/procurement/purchase-orders/{po['id']}").json()["lines"][0]
    g = client.post(f"/api/procurement/purchase-orders/{po['id']}/receive", {"lines": [{"po_line_id": pl["id"], "quantity": qty_beer, "expiry_date": "2030-06-01"}]})
    assert g.status_code == 201, g.text
    return po, g.json()


def test_purchase_returns_before_and_after_invoice(client):
    d = ids()
    hid, main, beer = d["hotel"]["id"], d["store"]["MAIN"]["id"], d["item"]["BEER"]
    po, grn = _po_received(client, d)
    gd = client.get(f"/api/procurement/grns/{grn['id']}").json()
    line = gd["lines"][0]
    before_qty, before_grni = qty(beer["id"], main), gl_balance("grni", hid)
    client.login("waiter@demo.ehms")
    assert client.post(f"/api/procurement/grns/{grn['id']}/returns", {"lines": [{"grn_line_id": line["id"], "quantity": 1}], "reason": "Broken"}).status_code == 403
    client.login("stores@demo.ehms")
    assert client.post(f"/api/procurement/grns/{grn['id']}/returns", {"lines": [{"grn_line_id": line["id"], "quantity": 30}], "reason": "Broken"}).status_code == 400
    r1 = client.post(f"/api/procurement/grns/{grn['id']}/returns", {"lines": [{"grn_line_id": line["id"], "quantity": 4}], "reason": "Four bottles broken"})
    assert r1.status_code == 201, r1.text
    assert r1.json()["settlement"] == "grni" and r1.json()["value"] == 4 * 70000
    assert qty(beer["id"], main) == before_qty - 4000
    assert gl_balance("grni", hid) == before_grni + 4 * 70000
    assert client.get(f"/api/procurement/purchase-orders/{po['id']}").json()["status"] == "partially_received"   # replacement can be received
    assert_books_balance(hid)
    # the supplier invoices the 20 kept; a later return becomes a credit on that invoice
    client.login("accounts@demo.ehms")
    inv = client.post(f"/api/hotels/{hid}/procurement/invoices", {"supplier_id": d["supplier"]["SUP002"]["id"], "po_id": po["id"], "invoice_no": f"INV-{uuid.uuid4().hex[:6]}",
                                                                  "invoice_date": d["hotel"]["business_date"], "amount": 20 * 70000})
    assert inv.status_code == 201, inv.text
    assert inv.json()["match_status"] == "matched"
    client.login("finance@demo.ehms")
    assert client.post(f"/api/procurement/invoices/{inv.json()['id']}/decide", {"decision": "approve"}).status_code == 200
    client.login("stores@demo.ehms")
    r2 = client.post(f"/api/procurement/grns/{grn['id']}/returns", {"lines": [{"grn_line_id": line["id"], "quantity": 2}], "reason": "Expired on arrival",
                                                                       "invoice_id": inv.json()["id"]})
    assert r2.status_code == 201 and r2.json()["settlement"] == "invoice_credit"
    with get_db().tx() as c:
        i = c.one("SELECT * FROM supplier_invoices WHERE id = ?", [inv.json()["id"]])
    assert i["amount"] - i["amount_paid"] == 18 * 70000
    assert client.get(f"/api/procurement/grns/{grn['id']}").json()["lines"][0]["returned_milli"] == 6000
    assert len(client.get(f"/api/hotels/{hid}/procurement/returns").json()["items"]) == 2
    assert_books_balance(hid)


# ------------------------------------------------------------------ CRM referrals
def test_referral_programme(client):
    h, methods = ctx_ids()
    client.login("frontdesk@demo.ehms")
    res, _ = arrival_today(client, h)
    referrer = res["guest"]["id"]
    assert client.post(f"/api/guests/{referrer}/loyalty/enrol", {"guest_agreed": True}).status_code == 201
    code = client.post(f"/api/guests/{referrer}/referral", {}).json()["code"]
    assert client.post(f"/api/guests/{referrer}/referral", {}).json()["code"] == code              # stable
    assert client.post(f"/api/reservations/{res['id']}/referral", {"code": code}).status_code == 400  # self-referral
    # a new guest books online with the code
    a = (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=30)).isoformat()
    dep = (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=31)).isoformat()
    av = client.get("/api/public/hotels/CGL/availability", params={"arrival": a, "departure": dep, "adults": 1}, token=None).json()
    opt = next(o for o in av["options"] if o["code"] == "STD")
    body = {"arrival": a, "departure": dep, "room_type_id": opt["room_type_id"], "first_name": "Ref", "last_name": "Friend", "email": "ref.friend@example.com",
            "phone": "0809", "adults": 1, "accept_terms": True}
    assert client.post("/api/public/hotels/CGL/bookings", {**body, "referral_code": "REF-NOPE99"}, token=None).status_code == 400
    ok = client.post("/api/public/hotels/CGL/bookings", {**body, "referral_code": code.lower()}, token=None)
    assert ok.status_code == 201, ok.text
    client.login("marketing@demo.ehms")
    refs = client.get(f"/api/hotels/{h['id']}/referrals").json()
    assert refs["items"][0]["status"] == "pending"
    # reward on the referred guest's check-out
    client.login("frontdesk@demo.ehms")
    with get_db().tx() as c:
        new_res = c.one("SELECT * FROM reservations WHERE reference = ?", [ok.json()["reference"]])
        c.update("reservations", new_res["id"], {"arrival": h["business_date"], "departure": (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=1)).isoformat(),
                                                 "status": "confirmed"})
    av = client.get(f"/api/hotels/{h['id']}/availability", params={"arrival": h["business_date"],
                    "departure": (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=1)).isoformat()}).json()
    room = next(r for r in av["free_rooms"] if r["hk_status"] == "inspected")
    with get_db().tx() as c:
        c.update("reservations", new_res["id"], {"room_id": room["id"], "room_type_id": room["room_type_id"]})
    folio = client.post(f"/api/reservations/{new_res['id']}/check-in", {}).json()["folio"]["id"]
    due = client.get(f"/api/reservations/{new_res['id']}/checkout-preview").json()["balance_due"]
    pay(client, folio, methods["CASH"], due)
    out = client.post(f"/api/reservations/{new_res['id']}/check-out", {}).json()
    assert out["referral_points_awarded"] == 500
    acct = client.get(f"/api/guests/{referrer}/loyalty").json()
    assert any(t["kind"] == "bonus" and t["points"] == 500 for t in acct["transactions"])
    client.login("marketing@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/referrals").json()["summary"]["rewarded"] == 1
    assert client.put(f"/api/hotels/{h['id']}/referrals/rules", {"enabled": True, "points_referrer": 750}).json()["points_referrer"] == 750


# ------------------------------------------------------------------ HR welfare
def test_staff_welfare_register(client):
    h, _ = ctx_ids()
    with get_db().tx() as c:
        emp = c.one("SELECT e.id FROM employees e JOIN users u ON u.id = e.user_id WHERE u.email = 'waiter@demo.ehms'")
    client.login("hrofficer@demo.ehms")
    assert client.post(f"/api/employees/{emp['id']}/welfare", {"kind": "medical", "description": "Hospital bill support", "amount": 5000000}).status_code == 403
    client.login("hrmanager@demo.ehms")
    assert client.post(f"/api/employees/{emp['id']}/welfare", {"kind": "lottery", "description": "x"}).status_code == 400
    assert client.post(f"/api/employees/{emp['id']}/welfare", {"kind": "medical", "description": "Hospital bill support", "amount": 5000000}).status_code == 201
    reg = client.get(f"/api/hotels/{h['id']}/hr/welfare").json()
    mine = [w for w in reg["items"] if w["description"] == "Hospital bill support"]
    assert mine and mine[0]["kind"] == "medical" and mine[0]["amount"] == 5000000 and reg["total_amount"] >= 5000000
    assert any(w["amount"] == 5000000 for w in client.get(f"/api/employees/{emp['id']}").json()["welfare"])
    client.login("hrofficer@demo.ehms")
    assert client.get(f"/api/employees/{emp['id']}").json()["welfare"] is None


# ------------------------------------------------------------------ petty cash & vouchers
def test_petty_cash_and_payment_vouchers(client):
    h, methods = ctx_ids()
    hid = h["id"]
    with get_db().tx() as c:
        accounts_user = c.scalar("SELECT id FROM users WHERE email = 'accounts@demo.ehms'")
        fuel = c.scalar("SELECT id FROM accounts WHERE organisation_id = ? AND system_key = 'exp_fuel'", [h["organisation_id"]])
    cash_before = gl_balance("cash", hid)
    client.login("frontdesk@demo.ehms")
    assert client.get(f"/api/hotels/{hid}/petty-cash").status_code == 403
    client.login("finance@demo.ehms")
    f = client.post(f"/api/hotels/{hid}/petty-cash/funds", {"name": "Banqueting", "custodian_id": accounts_user, "imprest": 5000000, "voucher_limit": 1000000,
                                                           "source_method_id": methods["CASH"]})
    assert f.status_code == 201, f.text
    fid = f.json()["id"]
    assert gl_balance("cash", hid) == cash_before - 5000000
    client.login("accounts@demo.ehms")
    small = client.post(f"/api/petty-cash/funds/{fid}/vouchers", {"payee": "Fuel station", "description": "Generator diesel", "expense_account_id": fuel,
                                                                  "department": "maintenance", "amount": 800000})
    assert small.status_code == 201 and small.json()["status"] == "posted"
    big = client.post(f"/api/petty-cash/funds/{fid}/vouchers", {"payee": "Plumber", "description": "Emergency repair", "expense_account_id": fuel,
                                                                "department": "maintenance", "amount": 3000000})
    assert big.json()["status"] == "pending"
    assert client.post(f"/api/petty-cash/funds/{fid}/vouchers", {"description": "Too much", "expense_account_id": fuel, "department": "admin", "amount": 2000000}).status_code == 409
    client.login("finance@demo.ehms")
    assert client.post(f"/api/petty-cash/vouchers/{big.json()['id']}/decide", {"decision": "approve"}).json()["status"] == "posted"
    ov = client.get(f"/api/hotels/{hid}/petty-cash").json()
    fund = next(x for x in ov["funds"] if x["id"] == fid)
    assert fund["balance"] == 1200000 and fund["to_replenish"] == 3800000
    assert client.post(f"/api/petty-cash/funds/{fid}/top-up", {"source_method_id": methods["CASH"]}).json()["balance"] == 5000000
    pdf = client.get(f"/api/vouchers/petty_cash/{small.json()['id']}.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    client.login("waiter@demo.ehms")
    assert client.get(f"/api/vouchers/petty_cash/{small.json()['id']}.pdf").status_code == 403
    assert_books_balance(hid)


def test_own_petty_cash_voucher_cannot_be_self_approved(client):
    h, methods = ctx_ids()
    with get_db().tx() as c:
        fin = c.scalar("SELECT id FROM users WHERE email = 'finance@demo.ehms'")
        acc = c.scalar("SELECT id FROM accounts WHERE organisation_id = ? AND system_key = 'exp_admin'", [h["organisation_id"]])
    client.login("finance@demo.ehms")
    fid = client.post(f"/api/hotels/{h['id']}/petty-cash/funds", {"name": "Admin", "custodian_id": fin, "imprest": 2000000, "voucher_limit": 100000,
                                                                  "source_method_id": methods["CASH"]}).json()["id"]
    v = client.post(f"/api/petty-cash/funds/{fid}/vouchers", {"description": "Stationery", "expense_account_id": acc, "department": "admin", "amount": 500000}).json()
    assert client.post(f"/api/petty-cash/vouchers/{v['id']}/decide", {"decision": "approve"}).status_code == 403


# ------------------------------------------------------------------ room media, CCTV, pagination, language
def test_room_photos_videos_on_booking_engine(client):
    h, _ = ctx_ids()
    with get_db().tx() as c:
        rt = c.one("SELECT * FROM room_types WHERE hotel_id = ? AND code = 'DLX'", [h["id"]])
    client.login("frontdesk@demo.ehms")
    assert client.post(f"/api/room-types/{rt['id']}/media", {"filename": "a.png", "content_base64": PNG}).status_code == 403
    client.login("gm@demo.ehms")
    assert client.post(f"/api/room-types/{rt['id']}/media", {"filename": "a.png", "content_base64": base64.b64encode(b"not an image").decode()}).status_code == 400
    assert client.post(f"/api/room-types/{rt['id']}/media", {"filename": "a.exe", "content_base64": PNG}).status_code == 400
    p = client.post(f"/api/room-types/{rt['id']}/media", {"filename": "deluxe.png", "content_base64": PNG, "caption": "King bed"})
    assert p.status_code == 201, p.text
    assert client.post(f"/api/room-types/{rt['id']}/media", {"kind": "video", "url": "javascript:alert(1)"}).status_code == 400
    assert client.post(f"/api/room-types/{rt['id']}/media", {"kind": "video", "url": "https://www.youtube.com/watch?v=abc"}).status_code == 201
    pub = client.get("/api/public/hotels/CGL", token=None).json()
    dlx = next(t for t in pub["room_types"] if t["code"] == "DLX")
    assert [m["kind"] for m in dlx["media"]] == ["photo", "video"]
    img = client.get(dlx["media"][0]["url"], token=None)
    assert img.status_code == 200 and img.content.startswith(b"\x89PNG")
    assert client.delete(f"/api/media/{p.json()['id']}").status_code == 200
    assert client.get(dlx["media"][0]["url"], token=None).status_code == 404


def test_cctv_clip_pagination_and_language(client, monkeypatch):
    h, _ = ctx_ids()
    monkeypatch.setenv("EHMS_ACCESS_API_TOKEN", "cam-token")
    body = {"hotel_code": "CGL", "source": "cctv", "events": [{"door": "Camera 3 lobby", "event": "motion", "occurred_at": "2026-11-23T01:02:03Z",
                                                                "clip_url": "https://nvr.example.com/clips/123"}, {"door": "Camera 4", "event": "tamper",
                                                                "occurred_at": "2026-11-23T01:03:00Z", "clip_url": "http://insecure/clip"}]}
    assert client.request("POST", "/api/integrations/access-events", json_body=body, headers={"x-ehms-integration-token": "cam-token"}, token=None).json()["accepted"] == 2
    client.login("security@demo.ehms")
    ev = {e["door"]: e for e in client.get(f"/api/hotels/{h['id']}/access-events").json()["items"]}
    assert ev["Camera 3 lobby"]["clip_url"] == "https://nvr.example.com/clips/123" and ev["Camera 4"]["clip_url"] is None
    # pagination reports the total instead of silently cutting the list
    client.login("frontdesk@demo.ehms")
    p1 = client.get(f"/api/hotels/{h['id']}/reservations", params={"page_size": 5}).json()
    assert len(p1["items"]) == 5 and p1["total"] > 5 and p1["pages"] == -(-p1["total"] // 5)
    p2 = client.get(f"/api/hotels/{h['id']}/reservations", params={"page_size": 5, "page": 2}).json()
    assert {r["id"] for r in p1["items"]}.isdisjoint({r["id"] for r in p2["items"]})
    assert client.get("/api/guests", params={"page_size": 3}).json()["page_size"] == 3
    # interface language
    assert client.get("/api/me/preferences").json()["language"] == "en"
    assert client.put("/api/me/preferences", {"language": "de"}).status_code == 400
    assert client.put("/api/me/preferences", {"language": "fr"}).json()["language"] == "fr"
    assert client.get("/api/auth/me").json()["language"] == "fr"


# ------------------------------------------------------------------ backups
def test_backup_verify_download_and_restore(client, tmp_path):
    client.login("frontdesk@demo.ehms")
    assert client.post("/api/admin/backups", {}).status_code == 403
    client.login("admin@demo.ehms")
    b = client.post("/api/admin/backups", {})
    assert b.status_code == 201, b.text
    bid = b.json()["id"]
    assert b.json()["status"] == "ok" and b.json()["rows_count"] > 500
    v = client.post(f"/api/admin/backups/{bid}/verify", {}).json()
    assert v["ok"] is True and v["result"]["tables"] > 100, v
    lst = client.get("/api/admin/backups").json()
    assert lst["items"][0]["verified"] == 1 and lst["items"][0]["file_present"]
    dl = client.get(f"/api/admin/backups/{bid}/download")
    assert dl.status_code == 200 and dl.content[:8] == b"EHMSENC1"          # 1.4: archives are encrypted
    assert client.put("/api/admin/backups/schedule", {"enabled": True, "hour_utc": 25, "retention_days": 7}).status_code == 400
    assert client.put("/api/admin/backups/schedule", {"enabled": True, "hour_utc": 2, "retention_days": 7}).json()["retention_days"] == 7
    # restore the archive into a brand-new database and compare
    from ehms import backup as bk
    path = os.path.join(bk.backup_dir(), b.json()["filename"])
    target = Database(f"sqlite:///{tmp_path}/restored.db")
    out = bk.restore(path, target)
    assert out["rows"] == b.json()["rows_count"]
    with get_db().tx() as c, target.tx() as t:
        for table in ("reservations", "journal_lines", "audit_logs", "employees", "stock_movements"):
            assert t.scalar(f"SELECT COUNT(*) FROM {table}") <= c.scalar(f"SELECT COUNT(*) FROM {table}")
        assert t.scalar("SELECT COUNT(*) FROM journal_lines") > 0
        assert t.scalar("SELECT SUM(debit) - SUM(credit) FROM journal_lines") == 0
    # restoring over a database that has data is refused
    try:
        bk.restore(path, target)
        raise AssertionError("restore into a non-empty database must be refused")
    except ValueError as e:
        assert "not empty" in str(e)
    target.close()
    # a flipped byte in the encrypted file is detected
    from ehms import crypto
    raw = bytearray(open(path, "rb").read())
    raw[200] ^= 0xFF
    flipped = tmp_path / "flipped.zip.enc"
    flipped.write_bytes(bytes(raw))
    try:
        bk.verify(str(flipped))
        raise AssertionError("an altered encrypted backup must fail")
    except ValueError as e:
        assert "cannot be decrypted" in str(e)
    # a tampered table inside the archive fails verification
    plain = tmp_path / "plain.zip"
    crypto.decrypt_file(path, str(plain))
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(plain) as zin, zipfile.ZipFile(bad, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "tables/reservations.jsonl":
                data = data.replace(b'"status":"confirmed"', b'"status":"cancelled"', 1)
            zout.writestr(item, data)
    try:
        bk.verify(str(bad))
        raise AssertionError("tampered archive must fail")
    except ValueError as e:
        assert "Checksum mismatch" in str(e)


def test_scheduled_backup_runs_once_and_alerts_on_failure(client, monkeypatch):
    from ehms import backup as bk
    from ehms.modules import backups as mod
    with get_db().tx() as c:
        c.execute("INSERT INTO system_settings (hotel_id, key, value) VALUES (NULL, 'backup.schedule', ?)", ['{"enabled": true, "hour_utc": 0, "retention_days": 14}'])
    assert mod.scheduled_backup() == "ok"
    assert mod.scheduled_backup() is None                      # once a day
    with get_db().tx() as c:
        row = c.one("SELECT * FROM backups ORDER BY id DESC")
        assert row["kind"] == "scheduled" and row["verified"] == 1
        c.execute("DELETE FROM job_runs WHERE job = 'scheduled_backup'")
    monkeypatch.setattr(bk, "_tables", lambda c: (_ for _ in ()).throw(RuntimeError("disk full")))
    assert mod.scheduled_backup() == "failed"
    with get_db().tx() as c:
        assert c.one("SELECT * FROM backups ORDER BY id DESC")["status"] == "failed"
        admin = c.scalar("SELECT id FROM users WHERE email = 'admin@demo.ehms'")
        assert c.scalar("SELECT COUNT(*) FROM notifications WHERE recipient = ? AND subject = 'Automatic backup FAILED'", [str(admin)]) == 1


# ------------------------------------------------------------------ predictions, summary, reminders, receipt, logo, biometric clock
def test_predictions_and_daily_summary(client):
    h, _ = ctx_ids()
    client.login("fom@demo.ehms")
    risk = client.get(f"/api/hotels/{h['id']}/insights/cancellation-risk", params={"days": 60}).json()
    assert risk["items"] and all(0 <= r["risk"] <= 100 and r["reasons"] for r in risk["items"])
    assert risk["items"] == sorted(risk["items"], key=lambda r: -r["risk"])
    summ = client.get(f"/api/hotels/{h['id']}/insights/daily-summary").json()
    assert len(summ["summary"]) >= 4 and "occupancy" in summ["summary"][0]
    # maintenance prediction from repeated repairs of one asset
    with get_db().tx() as c:
        asset = c.one("SELECT * FROM assets WHERE hotel_id = ? ORDER BY id", [h["id"]])
        uid = c.scalar("SELECT id FROM users WHERE email = 'maintenance@demo.ehms'")
        today = dt.date.fromisoformat(h["business_date"])
        for i, ago in enumerate((90, 60, 30)):
            c.insert("work_orders", {"hotel_id": h["id"], "number": f"WO-T-{i}", "asset_id": asset["id"], "title": "Repeated fault", "kind": "corrective", "priority": "normal",
                                     "status": "completed", "reported_by": uid, "created_at": (today - dt.timedelta(days=ago)).isoformat() + "T08:00:00Z"})
    client.login("maintenance@demo.ehms")
    mr = client.get(f"/api/hotels/{h['id']}/insights/maintenance-risk").json()["items"]
    mine = next(x for x in mr if x["asset_id"] == asset["id"])
    assert mine["mean_days_between_failures"] == 30 and mine["days_left"] <= 1 and mine["advice"] == "Inspect now"
    client.login("marketing@demo.ehms")
    gi = client.get(f"/api/hotels/{h['id']}/insights/guests").json()
    assert gi["stays"] > 0 and gi["nationality"] and gi["room_categories"] and gi["average_length_of_stay"]
    client.login("housekeeper@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/insights/cancellation-risk").status_code == 403


def test_checkout_reminders_booking_receipt_and_logo(client):
    h, _ = ctx_ids()
    from ehms.modules.predictive import checkout_reminders
    with get_db().tx() as c:
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [h["id"]])
        dep = c.one("SELECT r.*, g.email FROM reservations r JOIN guests g ON g.id = r.guest_id WHERE r.hotel_id = ? AND r.status = 'checked_in' ORDER BY r.id", [h["id"]])
        c.update("reservations", dep["id"], {"departure": h["business_date"]})
        n = checkout_reminders(c, hotel)
        assert n >= 1 and checkout_reminders(c, hotel) == 0
        msg = c.one("SELECT * FROM notifications WHERE related_entity = 'reservation' AND related_id = ? AND subject LIKE ?", [str(dep["id"]), "Your departure today%"])
        assert msg and "balance" in msg["body"].lower()
    # public booking confirmation needs the right email
    a = (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=40)).isoformat()
    d2 = (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=42)).isoformat()
    av = client.get("/api/public/hotels/CGL/availability", params={"arrival": a, "departure": d2, "adults": 1}, token=None).json()
    opt = next(o for o in av["options"] if o["code"] == "STD")
    ok = client.post("/api/public/hotels/CGL/bookings", {"arrival": a, "departure": d2, "room_type_id": opt["room_type_id"], "first_name": "Rec", "last_name": "Eipt",
                                                         "email": "rec.eipt@example.com", "phone": "080", "adults": 1, "accept_terms": True}, token=None).json()
    ref = ok["reference"]
    assert client.get(f"/api/public/bookings/{ref}/confirmation.pdf", params={"email": "wrong@example.com"}, token=None).status_code == 404
    pdf = client.get(f"/api/public/bookings/{ref}/confirmation.pdf", params={"email": "Rec.Eipt@example.com"}, token=None)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # hotel logo
    assert client.get(f"/api/public/hotels/{h['id']}/logo", token=None).status_code == 404
    client.login("gm@demo.ehms")
    assert client.post(f"/api/hotels/{h['id']}/logo", {"filename": "logo.gif", "content_base64": PNG}).status_code == 400
    up = client.post(f"/api/hotels/{h['id']}/logo", {"filename": "logo.png", "content_base64": PNG})
    assert up.status_code == 200
    assert client.get(f"/api/public/hotels/{h['id']}/logo", token=None).content.startswith(b"\x89PNG")
    assert client.get("/api/public/hotels/CGL", token=None).json()["logo_url"].startswith(f"/api/public/hotels/{h['id']}/logo")
    assert client.get("/api/auth/me").json()["hotels"][0]["logo_url"]


def test_biometric_attendance_intake(client, monkeypatch):
    h, _ = ctx_ids()
    with get_db().tx() as c:
        e = c.one("SELECT e.* FROM employees e JOIN users u ON u.id = e.user_id WHERE u.email = 'waiter@demo.ehms'")
    body = {"hotel_code": "CGL", "events": [{"employee_no": e["employee_no"], "action": "in", "occurred_at": "2026-12-01T07:02:00+01:00"},
                                             {"employee_no": e["employee_no"], "action": "in", "occurred_at": "2026-12-01T07:05:00+01:00"},
                                             {"employee_no": e["employee_no"], "action": "out", "occurred_at": "2026-12-01T15:10:00+01:00"},
                                             {"employee_no": "NOPE", "action": "in", "occurred_at": "2026-12-01T07:00:00+01:00"}]}
    assert client.post("/api/integrations/attendance-events", body, token=None).status_code == 401
    monkeypatch.setenv("EHMS_ATTENDANCE_API_TOKEN", "clock-token")
    r = client.request("POST", "/api/integrations/attendance-events", json_body=body, headers={"x-ehms-integration-token": "clock-token"}, token=None).json()
    assert r["applied"] == 2 and r["skipped"] == ["NOPE"]
    with get_db().tx() as c:
        a = c.one("SELECT * FROM attendance WHERE employee_id = ? AND work_date = '2026-12-01'", [e["id"]])
    assert a["clock_in"] == "07:02" and a["clock_out"] == "15:10" and a["note"] == "Biometric clock"
