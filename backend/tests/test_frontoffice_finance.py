"""End-to-end reservation-to-check-out workflow, folio, payments, refunds, accounting and housekeeping
(Workflow 9.1, FR-FO-*, FR-FIN-*, FR-PAY-*, FR-HSK-*)."""
import datetime as dt
import uuid

import pytest

from ehms.db import IntegrityError, get_db


def ctx_ids():
    with get_db().tx() as c:
        h = c.one("SELECT * FROM hotels WHERE code = 'CGL'")
        methods = {m["code"]: m["id"] for m in c.all("SELECT * FROM payment_methods WHERE hotel_id = ?", [h["id"]])}
        return h, methods


def arrival_today(client, h, code="STD"):
    """Book a walk-in for today in a ready room."""
    av = client.get(f"/api/hotels/{h['id']}/availability", params={"arrival": h["business_date"],
                    "departure": (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=2)).isoformat()}).json()
    with get_db().tx() as c:
        rt = c.one("SELECT * FROM room_types WHERE hotel_id = ? AND code = ?", [h["id"], code])
    room = next(r for r in av["free_rooms"] if r["room_type_id"] == rt["id"] and r["hk_status"] == "inspected")
    r = client.post(f"/api/hotels/{h['id']}/reservations", {
        "arrival": h["business_date"], "departure": (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=2)).isoformat(),
        "room_type_id": rt["id"], "room_id": room["id"], "booking_type": "walk_in", "source": "walk_in",
        "guest": {"first_name": "Walk", "last_name": f"In{uuid.uuid4().hex[:6]}", "email": f"{uuid.uuid4().hex[:8]}@example.com", "force": True}})
    assert r.status_code == 201, r.text
    return r.json(), room


def pay(client, folio_id, method_id, amount, ref=None):
    return client.post(f"/api/folios/{folio_id}/payments", {"amount": amount, "method_id": method_id, "reference": ref or uuid.uuid4().hex[:10],
                                                            "idempotency_key": uuid.uuid4().hex})


def test_full_stay_workflow(client):
    client.login("frontdesk@demo.ehms")
    h, methods = ctx_ids()
    res, room = arrival_today(client, h)
    rid = res["id"]
    ci = client.post(f"/api/reservations/{rid}/check-in", {})
    assert ci.status_code == 200, ci.text
    assert ci.json()["status"] == "checked_in"
    folio_id = ci.json()["folio"]["id"]
    # restaurant charge to room (F&B: 10% service charge + 7.5% VAT)
    r = client.post(f"/api/folios/{folio_id}/charges", {"department": "fnb", "description": "Dinner", "amount": 1000000})
    assert r.status_code == 201
    folio = client.get(f"/api/folios/{folio_id}").json()
    line = folio["lines"][0]
    assert (line["net_amount"], line["service_charge"], line["tax_amount"], line["total_amount"]) == (1000000, 100000, 82500, 1182500)
    # cannot check out with an unpaid balance
    preview = client.get(f"/api/reservations/{rid}/checkout-preview").json()
    assert preview["balance_due"] > 0
    blocked = client.post(f"/api/reservations/{rid}/check-out", {})
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "balance_outstanding"
    # settle exactly and check out
    assert pay(client, folio_id, methods["POS"], preview["balance_due"]).status_code == 201
    out = client.post(f"/api/reservations/{rid}/check-out", {})
    assert out.status_code == 200, out.text
    assert out.json()["status"] == "checked_out"
    assert client.get(f"/api/folios/{folio_id}").json()["status"] == "closed"
    # room is now dirty with a housekeeping task; not sellable until cleaned and inspected
    rooms = {r["id"]: r for r in client.get(f"/api/hotels/{h['id']}/rooms").json()["items"]}
    assert rooms[room["id"]]["display_status"] == "dirty"
    client.login("housekeeper@demo.ehms")
    client.login("hkmanager@demo.ehms")
    tasks = client.get(f"/api/hotels/{h['id']}/housekeeping/tasks").json()["items"]
    task = next(t for t in tasks if t["room_id"] == room["id"] and t["status"] == "pending")
    hk_user = next(s["id"] for s in client.get(f"/api/hotels/{h['id']}/housekeeping/tasks").json()["staff"] if "Mary" in s["full_name"])
    assert client.post(f"/api/housekeeping/tasks/{task['id']}/assign", {"user_id": hk_user}).status_code == 200
    client.login("housekeeper@demo.ehms")
    assert client.post(f"/api/housekeeping/tasks/{task['id']}/inspect", {"passed": True}).status_code == 403  # staff cannot inspect
    assert client.post(f"/api/housekeeping/tasks/{task['id']}/start").status_code == 200
    assert client.post(f"/api/housekeeping/tasks/{task['id']}/complete", {}).status_code == 200
    client.login("hkmanager@demo.ehms")
    assert client.post(f"/api/housekeeping/tasks/{task['id']}/inspect", {"passed": True}).status_code == 200
    rooms = {r["id"]: r for r in client.get(f"/api/hotels/{h['id']}/rooms").json()["items"]}
    assert rooms[room["id"]]["display_status"] == "available"
    # accounting stays balanced
    client.login("finance@demo.ehms")
    tb = client.get("/api/reports/trial-balance", params={"hotel_id": h["id"], "as_at": "2099-12-31"}).json()
    assert tb["balanced"]
    bs = client.get("/api/reports/balance-sheet", params={"hotel_id": h["id"], "as_at": "2099-12-31"}).json()
    assert bs["balanced"]


def test_check_in_requires_inspected_room(client):
    client.login("frontdesk@demo.ehms")
    h, _ = ctx_ids()
    res, room = arrival_today(client, h)
    with get_db().tx() as c:
        c.execute("UPDATE rooms SET hk_status = 'dirty' WHERE id = ?", [room["id"]])
    r = client.post(f"/api/reservations/{res['id']}/check-in", {})
    assert r.status_code == 409 and r.json()["error"]["details"]["code"] == "room_not_ready"


def test_payment_idempotency_and_duplicate_reference(client):
    client.login("frontdesk@demo.ehms")
    h, methods = ctx_ids()
    res, _ = arrival_today(client, h)
    folio_id = client.post(f"/api/reservations/{res['id']}/check-in", {}).json()["folio"]["id"]
    body = {"amount": 500000, "method_id": methods["TRANSFER"], "reference": "TRF-778899", "idempotency_key": "same-key-1"}
    first = client.post(f"/api/folios/{folio_id}/payments", body)
    again = client.post(f"/api/folios/{folio_id}/payments", body)
    assert first.status_code == 201 and again.json()["duplicate"] is True
    dup = client.post(f"/api/folios/{folio_id}/payments", {**body, "idempotency_key": "other-key"})
    assert dup.status_code == 409
    totals = client.get(f"/api/folios/{folio_id}").json()["totals"]
    assert totals["payments"] == 500000


def test_online_payment_not_faked(client):
    client.login("admin@demo.ehms")
    h, _ = ctx_ids()
    with get_db().tx() as c:
        acc = c.scalar("SELECT id FROM accounts WHERE system_key = 'online_clearing'")
    mid = client.post(f"/api/hotels/{h['id']}/payment-methods", {"code": "PAYSTACK", "name": "Paystack", "kind": "online", "account_id": acc}).json()["id"]
    client.login("frontdesk@demo.ehms")
    res, _ = arrival_today(client, h)
    folio_id = client.post(f"/api/reservations/{res['id']}/check-in", {}).json()["folio"]["id"]
    r = client.post(f"/api/folios/{folio_id}/payments", {"amount": 1000, "method_id": mid, "idempotency_key": "x1"})
    assert r.status_code == 501


def test_refund_maker_checker(client):
    client.login("frontdesk@demo.ehms")
    h, methods = ctx_ids()
    res, _ = arrival_today(client, h)
    folio_id = client.post(f"/api/reservations/{res['id']}/check-in", {}).json()["folio"]["id"]
    pay(client, folio_id, methods["CASH"], 5000000)
    assert client.post(f"/api/folios/{folio_id}/refund-requests", {"amount": 6000000, "method_id": methods["CASH"], "reason": "x"}).status_code == 400
    req = client.post(f"/api/folios/{folio_id}/refund-requests", {"amount": 2000000, "method_id": methods["CASH"], "reason": "Overpayment"})
    assert req.status_code == 201
    aid = req.json()["id"]
    client.login("fom@demo.ehms")
    assert client.post(f"/api/approvals/{aid}/decide", {"decision": "approve"}).status_code == 200
    totals = client.get(f"/api/folios/{folio_id}").json()["totals"]
    assert totals["refunds"] == 2000000 and totals["balance"] == -3000000
    assert client.post(f"/api/approvals/{aid}/decide", {"decision": "approve"}).status_code == 409


def test_requester_cannot_approve_own_refund(client):
    client.login("fom@demo.ehms")
    h, methods = ctx_ids()
    res, _ = arrival_today(client, h)
    folio_id = client.post(f"/api/reservations/{res['id']}/check-in", {}).json()["folio"]["id"]
    pay(client, folio_id, methods["CASH"], 1000000)
    aid = client.post(f"/api/folios/{folio_id}/refund-requests", {"amount": 1000000, "method_id": methods["CASH"], "reason": "test"}).json()["id"]
    assert client.post(f"/api/approvals/{aid}/decide", {"decision": "approve"}).status_code == 403


def test_charge_reversal_and_ledger_immutability(client):
    client.login("fom@demo.ehms")
    h, _ = ctx_ids()
    res, _ = arrival_today(client, h)
    folio_id = client.post(f"/api/reservations/{res['id']}/check-in", {}).json()["folio"]["id"]
    line_id = client.post(f"/api/folios/{folio_id}/charges", {"department": "minibar", "description": "Minibar", "amount": 300000}).json()["id"]
    r = client.post(f"/api/folios/{folio_id}/adjustments", {"line_id": line_id, "reason": "Posted to wrong room"})
    assert r.status_code == 201
    assert client.post(f"/api/folios/{folio_id}/adjustments", {"line_id": line_id, "reason": "again"}).status_code == 409
    assert client.get(f"/api/folios/{folio_id}").json()["totals"]["balance"] == 0
    with pytest.raises(IntegrityError):
        with get_db().tx() as c:
            c.execute("UPDATE journal_lines SET debit = debit + 1")
    with pytest.raises(IntegrityError):
        with get_db().tx() as c:
            c.execute("DELETE FROM audit_logs")


def test_night_audit_posts_room_charges_and_rolls_date(client):
    client.login("fom@demo.ehms")
    h, _ = ctx_ids()
    inhouse = client.get(f"/api/hotels/{h['id']}/reservations", params={"view": "in_house"}).json()["items"]
    r = client.post(f"/api/hotels/{h['id']}/night-audit")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["room_charges_posted"] == len(inhouse)
    assert s["new_business_date"] == (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=1)).isoformat()
    assert client.post(f"/api/hotels/{h['id']}/night-audit").status_code == 409  # cannot run ahead of the calendar


def test_room_move_and_block(client):
    client.login("fom@demo.ehms")
    h, _ = ctx_ids()
    res, room = arrival_today(client, h)
    client.post(f"/api/reservations/{res['id']}/check-in", {})
    av = client.get(f"/api/hotels/{h['id']}/availability", params={"arrival": h["business_date"], "departure": res["departure"],
                                                                    "room_type_id": res["room_type_id"]}).json()
    target = next(r for r in av["free_rooms"] if r["hk_status"] == "inspected" and r["id"] != room["id"])
    mv = client.post(f"/api/reservations/{res['id']}/room-move", {"room_id": target["id"], "reason": "Noise complaint"})
    assert mv.status_code == 200 and mv.json()["room"]["id"] == target["id"]
    assert client.post(f"/api/rooms/{target['id']}/service-status", {"service_status": "out_of_order", "note": "x"}).status_code == 409
    assert client.post(f"/api/rooms/{room['id']}/service-status", {"service_status": "out_of_order", "note": "Leak"}).status_code == 200


def test_manual_journal_must_balance(client):
    client.login("finance@demo.ehms")
    h, _ = ctx_ids()
    accts = {a["system_key"]: a["id"] for a in client.get("/api/accounts").json()["items"]}
    bad = client.post(f"/api/hotels/{h['id']}/journal", {"description": "Diesel", "lines": [
        {"account_id": accts["exp_fuel"], "debit": 1000}, {"account_id": accts["cash"], "credit": 900}]})
    assert bad.status_code == 400
    pl0 = client.get("/api/reports/profit-and-loss", params={"hotel_id": h["id"], "from": "2000-01-01", "to": "2099-12-31"}).json()
    fuel0 = sum(e["amount"] for e in pl0["expenses"] if e["code"] == "5200")
    ok = client.post(f"/api/hotels/{h['id']}/journal", {"description": "Diesel for generator", "lines": [
        {"account_id": accts["exp_fuel"], "debit": 25000000}, {"account_id": accts["cash"], "credit": 25000000}]})
    assert ok.status_code == 201
    pl = client.get("/api/reports/profit-and-loss", params={"hotel_id": h["id"], "from": "2000-01-01", "to": "2099-12-31"}).json()
    assert sum(e["amount"] for e in pl["expenses"] if e["code"] == "5200") - fuel0 == 25000000
