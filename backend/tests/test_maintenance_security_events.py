"""Release 0.7: maintenance & assets, security & lost property, events & banqueting."""
import datetime as dt

from ehms.db import get_db

from test_frontoffice_finance import arrival_today, ctx_ids
from test_pos_inventory_procurement import assert_books_balance, gl_balance, ids, qty


def test_fault_to_verified_repair_with_parts_and_room_block(client):
    d = ids()
    h = d["hotel"]
    with get_db().tx() as c:
        room = c.one("SELECT * FROM rooms WHERE hotel_id = ? AND number = '301'", [h["id"]])
    # housekeeping reports a fault while completing a task → work order raised automatically
    client.login("hkmanager@demo.ehms")
    t = client.post(f"/api/hotels/{h['id']}/housekeeping/tasks", {"room_id": room["id"], "task_type": "deep_clean"}).json()
    client.post(f"/api/housekeeping/tasks/{t['id']}/start", {})
    done = client.post(f"/api/housekeeping/tasks/{t['id']}/complete", {"issues": "Shower mixer leaking", "report_maintenance": True}).json()
    assert done["work_order"].startswith("WO-")
    # receptionist reports a room fault that blocks the room
    client.login("frontdesk@demo.ehms")
    wo = client.post(f"/api/hotels/{h['id']}/work-orders", {"room_id": room["id"], "title": "Door lock battery dead", "priority": "urgent", "blocks_room": True})
    assert wo.status_code == 201
    wid = wo.json()["id"]
    with get_db().tx() as c:
        assert c.scalar("SELECT service_status FROM rooms WHERE id = ?", [room["id"]]) == "maintenance"
    # technician cannot assign; manager assigns; technician is notified
    client.login("technician@demo.ehms")
    assert client.post(f"/api/work-orders/{wid}/assign", {"user_id": 1}).status_code == 403
    client.login("maintenance@demo.ehms")
    with get_db().tx() as c:
        tech = c.scalar("SELECT id FROM users WHERE email = 'technician@demo.ehms'")
    assert client.post(f"/api/work-orders/{wid}/assign", {"user_id": tech}).status_code == 200
    client.login("technician@demo.ehms")
    assert any(n["subject"] == "Work order assigned to you" for n in client.get("/api/notifications/mine").json()["items"])
    assert client.post(f"/api/work-orders/{wid}/status", {"status": "completed"}).status_code == 409    # must start first
    assert client.post(f"/api/work-orders/{wid}/status", {"status": "in_progress"}).status_code == 200
    # spare part from the main store: stock down, repairs expense up
    before = gl_balance("exp_maintenance", h["id"])
    q0 = qty(d["item"]["DSL"]["id"], d["store"]["MAIN"]["id"])
    p = client.post(f"/api/work-orders/{wid}/parts", {"item_id": d["item"]["DSL"]["id"], "store_id": d["store"]["MAIN"]["id"], "quantity": 2})
    assert p.status_code == 201 and p.json()["cost"] == 240000
    assert gl_balance("exp_maintenance", h["id"]) - before == 240000 and q0 - qty(d["item"]["DSL"]["id"], d["store"]["MAIN"]["id"]) == 2000
    assert client.post(f"/api/work-orders/{wid}/status", {"status": "completed"}).status_code == 400   # resolution required
    assert client.post(f"/api/work-orders/{wid}/status", {"status": "completed", "resolution": "Replaced battery", "vendor_cost": 0}).status_code == 200
    assert client.post(f"/api/work-orders/{wid}/status", {"status": "verified"}).status_code == 403     # technician cannot verify own work
    client.login("maintenance@demo.ehms")
    assert client.post(f"/api/work-orders/{wid}/status", {"status": "verified"}).json()["status"] == "verified"
    with get_db().tx() as c:
        r = c.one("SELECT * FROM rooms WHERE id = ?", [room["id"]])
        assert r["service_status"] == "in_service" and r["hk_status"] == "dirty"
        assert c.one("SELECT id FROM housekeeping_tasks WHERE room_id = ? AND notes LIKE ?", [room["id"], "%maintenance%"])
    summ = client.get(f"/api/hotels/{h['id']}/maintenance/summary").json()
    assert summ["completed"] >= 1
    assert_books_balance(h["id"])


def test_assets_preventive_and_depreciation(client):
    h, methods = ctx_ids()
    client.login("maintenance@demo.ehms")
    a = client.post(f"/api/hotels/{h['id']}/assets", {"name": "Laundry washer 30kg", "category": "laundry_equipment", "purchase_cost": 1200000000,
                                                      "useful_life_months": 60, "purchase_date": "2026-01-15"})
    assert a.status_code == 201
    aid = a.json()["id"]
    bd = dt.date.fromisoformat(h["business_date"])
    assert client.post(f"/api/assets/{aid}/schedules", {"title": "Drum bearing check", "frequency_days": 30, "next_due": bd.isoformat()}).status_code == 201
    r = client.post(f"/api/hotels/{h['id']}/maintenance/raise-preventive", {}).json()
    assert r["created"] >= 1
    assert client.post(f"/api/hotels/{h['id']}/maintenance/raise-preventive", {}).json()["created"] == 0   # one open order per schedule
    wo = next(w for w in client.get(f"/api/hotels/{h['id']}/work-orders", params={"open": 1}).json()["items"] if w["asset_id"] == aid)
    client.post(f"/api/work-orders/{wo['id']}/status", {"status": "in_progress"})
    client.post(f"/api/work-orders/{wo['id']}/status", {"status": "completed", "resolution": "Bearings fine"})
    client.login("hkmanager@demo.ehms")   # verifier: a manager other than the worker — use admin
    client.login("admin@demo.ehms")
    client.post(f"/api/work-orders/{wo['id']}/status", {"status": "verified"})
    sched = client.get(f"/api/assets/{aid}").json()["schedules"][0]
    assert sched["last_done"] == bd.isoformat() and sched["next_due"] == (bd + dt.timedelta(days=30)).isoformat()
    # capitalise an existing asset as opening balance and depreciate it once per month
    cap = client.post(f"/api/hotels/{h['id']}/assets", {"name": "Delivery van", "category": "vehicle", "purchase_cost": 600000000, "salvage_value": 0,
                                                        "useful_life_months": 60, "funding": "opening"}).json()
    assert gl_balance("fixed_assets", h["id"]) == 600000000
    client.login("finance@demo.ehms")
    period = bd.strftime("%Y-%m")
    dep = client.post(f"/api/hotels/{h['id']}/assets/depreciate", {"period": period}).json()
    assert dep["total"] >= 10000000 and gl_balance("accum_depreciation", h["id"]) == -dep["total"]
    assert client.post(f"/api/hotels/{h['id']}/assets/depreciate", {"period": period}).json()["total"] == 0   # once per month
    client.login("maintenance@demo.ehms")
    assert client.patch(f"/api/assets/{cap['id']}", {"purchase_cost": 1}).status_code == 409
    v = client.get(f"/api/assets/{cap['id']}").json()
    assert v["accumulated_depreciation"] == 10000000
    assert_books_balance(h["id"])


def test_security_incidents_visitors_lost_found(client):
    h, _ = ctx_ids()
    client.login("frontdesk@demo.ehms")
    inc = client.post(f"/api/hotels/{h['id']}/incidents", {"occurred_at": "2026-11-20T22:15", "location": "Car park", "category": "theft", "severity": "high",
                                                           "description": "Guest reports phone stolen from car"})
    assert inc.status_code == 201
    restricted = client.post(f"/api/hotels/{h['id']}/incidents", {"occurred_at": "2026-11-20T23:00", "location": "Bar", "category": "harassment", "severity": "medium",
                                                                  "description": "Sensitive complaint"}).json()
    assert client.get(f"/api/hotels/{h['id']}/incidents").status_code == 403   # receptionist can report but not browse
    client.login("security@demo.ehms")
    assert any(n["subject"] == "High security incident" for n in client.get("/api/notifications/mine").json()["items"])
    assert client.post(f"/api/incidents/{inc.json()['id']}/update", {"status": "resolved"}).status_code == 400    # resolution needed
    assert client.post(f"/api/incidents/{inc.json()['id']}/update", {"note": "CCTV reviewed", "status": "investigating", "police_reference": "VI/123"}).status_code == 200
    assert client.post(f"/api/incidents/{inc.json()['id']}/update", {"status": "resolved", "resolution": "Police report filed; guest informed"}).status_code == 200
    detail = client.get(f"/api/incidents/{inc.json()['id']}").json()
    assert detail["notes"][0]["note"] == "CCTV reviewed" and detail["status"] == "resolved"
    assert client.get(f"/api/incidents/{restricted['id']}").status_code == 200        # security has sensitive access
    client.login("fom@demo.ehms")
    listed = client.get(f"/api/hotels/{h['id']}/incidents").json()["items"]
    assert all(i["id"] != restricted["id"] for i in listed)                              # hidden without security.sensitive
    assert client.get(f"/api/incidents/{restricted['id']}").status_code == 403
    # visitors: ID numbers masked for non-managers
    client.login("security@demo.ehms")
    v = client.post(f"/api/hotels/{h['id']}/visitors", {"kind": "contractor", "name": "Tunde Electric", "company": "Sparks Ltd", "id_type": "NIN", "id_number": "12345678901",
                                                        "host": "Maintenance", "purpose": "Generator wiring"}).json()
    assert client.get(f"/api/hotels/{h['id']}/visitors", params={"on_site": 1}).json()["on_site"] >= 1
    client.login("fom@demo.ehms")
    vis = next(x for x in client.get(f"/api/hotels/{h['id']}/visitors", params={"on_site": 1}).json()["items"] if x["id"] == v["id"])
    assert vis["id_number"].endswith("901") and vis["id_number"].startswith("•")
    client.login("security@demo.ehms")
    assert client.post(f"/api/visitors/{v['id']}/sign-out", {}).status_code == 200
    assert client.post(f"/api/visitors/{v['id']}/sign-out", {}).status_code == 409
    # lost & found: valuables need an ID check; disposal only after the holding period
    client.login("housekeeper@demo.ehms")
    lf = client.post(f"/api/hotels/{h['id']}/lost-found", {"description": "Gold bracelet", "category": "jewellery", "location": "Room 107"}).json()
    item = next(x for x in client.get(f"/api/hotels/{h['id']}/lost-found").json()["items"] if x["id"] == lf["id"])
    assert item["valuable"] == 1 and item["stored_location"] == "Security safe"
    assert client.post(f"/api/lost-found/{lf['id']}/release", {"outcome": "disposed"}).status_code == 409
    assert client.post(f"/api/lost-found/{lf['id']}/release", {"outcome": "returned", "claimant_name": "Ada", "claimant_contact": "080"}).status_code == 400
    assert client.post(f"/api/lost-found/{lf['id']}/release", {"outcome": "returned", "claimant_name": "Ada", "claimant_contact": "080",
                                                              "claimant_id_checked": True}).json()["status"] == "returned"
    # emergency contacts visible to all staff
    assert len(client.get(f"/api/hotels/{h['id']}/emergency-contacts").json()["items"]) >= 3


def test_access_control_integration(client, monkeypatch):
    h, _ = ctx_ids()
    body = {"hotel_code": "CGL", "source": "assa-abloy", "events": [{"door": "Room 204", "event": "unlock", "credential": "CARD-9", "occurred_at": "2026-11-21T08:00:00"}]}
    assert client.post("/api/integrations/access-events", body, token=None).status_code == 401
    monkeypatch.setenv("EHMS_ACCESS_API_TOKEN", "lock-token")
    assert client.request("POST", "/api/integrations/access-events", json_body=body, headers={"x-ehms-integration-token": "nope"}, token=None).status_code == 401
    ok = client.request("POST", "/api/integrations/access-events", json_body=body, headers={"x-ehms-integration-token": "lock-token"}, token=None)
    assert ok.json()["accepted"] == 1
    client.login("security@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/access-events").json()["items"][0]["door"] == "Room 204"


def test_events_quotation_clash_deposit_invoice(client):
    h, methods = ctx_ids()
    client.login("sales@demo.ehms")
    venues = {v["code"]: v for v in client.get(f"/api/hotels/{h['id']}/venues").json()["items"]}
    wedding = next(e for e in client.get(f"/api/hotels/{h['id']}/events").json()["items"] if e["status"] == "confirmed")
    slot = client.get(f"/api/events/{wedding['id']}").json()["venues"][0]
    # a second booking for the ballroom at an overlapping time cannot be held
    ev = client.post(f"/api/hotels/{h['id']}/events", {"title": "Product launch", "event_type": "conference", "client_name": "Ngozi Eze", "client_email": "ngozi@example.com",
                                                       "start_at": slot["start_at"], "end_at": slot["end_at"], "expected_guests": 150,
                                                       "venues": [{"venue_id": venues["BALL"]["id"], "start_at": slot["start_at"], "end_at": slot["end_at"]}]})
    assert ev.status_code == 201 and ev.json()["status"] == "enquiry"   # enquiries never block
    eid = ev.json()["id"]
    r = client.post(f"/api/events/{eid}/status", {"status": "tentative"})
    assert r.status_code == 409 and r.json()["error"]["details"]["code"] == "venue_clash"
    # move it to the boardroom: capacity is checked
    client.delete(f"/api/event-venues/{ev.json()['venues'][0]['id']}")
    client.post(f"/api/events/{eid}/venues", {"venue_id": venues["BOARD"]["id"], "start_at": slot["start_at"], "end_at": slot["end_at"]})
    assert client.post(f"/api/events/{eid}/status", {"status": "confirmed"}).status_code == 409      # 150 guests > 16
    client.patch(f"/api/events/{eid}", {"expected_guests": 14})
    conf = client.post(f"/api/events/{eid}/status", {"status": "confirmed"})
    assert conf.status_code == 200 and conf.json()["folio_id"]
    client.post(f"/api/events/{eid}/items", {"kind": "venue", "description": "Boardroom full day", "quantity": 1, "unit_price": 18000000})
    det = client.post(f"/api/events/{eid}/items", {"kind": "catering", "description": "Lunch", "quantity": 14, "unit_price": 650000}).json()
    t = det["totals"]
    assert t["net"] == 18000000 + 14 * 650000 and t["total"] > t["net"]
    assert client.get(f"/api/events/{eid}/quotation.pdf").content[:4] == b"%PDF"
    # deposit on the event folio, then invoice (sales cannot invoice; finance can)
    client.login("frontdesk@demo.ehms")
    import uuid
    assert client.post(f"/api/folios/{det['folio_id']}/payments", {"amount": 10000000, "method_id": methods["TRANSFER"], "reference": "DEP-1",
                                                                   "idempotency_key": uuid.uuid4().hex}).status_code == 201
    client.login("sales@demo.ehms")
    assert client.post(f"/api/events/{eid}/invoice", {}).status_code == 403
    assert client.post(f"/api/events/{eid}/status", {"status": "completed"}).status_code == 409   # invoice first
    client.post(f"/api/events/{eid}/costs", {"description": "Outsourced AV technician", "amount": 3000000})
    client.login("finance@demo.ehms")
    inv = client.post(f"/api/events/{eid}/invoice", {}).json()
    assert inv["invoiced_at"] and inv["totals"]["paid"] == 10000000 and inv["totals"]["profit"] == t["net"] - 3000000
    folio = client.get(f"/api/folios/{det['folio_id']}").json()
    assert {l["department"] for l in folio["lines"] if l["kind"] == "charge"} == {"events", "fnb"}
    assert folio["totals"]["balance"] == t["total"] - 10000000
    assert client.post(f"/api/events/{eid}/invoice", {}).status_code == 409
    client.login("sales@demo.ehms")
    assert client.post(f"/api/events/{eid}/items", {"kind": "other", "description": "x", "unit_price": 1}).status_code == 409
    assert client.post(f"/api/events/{eid}/status", {"status": "completed"}).json()["status"] == "completed"
    summ = client.get(f"/api/hotels/{h['id']}/events/summary").json()
    assert summ["pipeline"]["completed"] >= 1
    cal = client.get(f"/api/hotels/{h['id']}/venues/calendar", params={"from": h["business_date"], "to": "2030-01-01"}).json()
    assert len(cal["bookings"]) >= 2
    assert_books_balance(h["id"])
