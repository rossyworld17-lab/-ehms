"""Reservations, availability and double-booking prevention (FR-RES-*, FR-PMS-004)."""
import datetime as dt

from ehms.db import get_db


def _ids(code="DLX"):
    with get_db().tx() as c:
        h = c.one("SELECT * FROM hotels WHERE code = 'CGL'")
        rt = c.one("SELECT * FROM room_types WHERE hotel_id = ? AND code = ?", [h["id"], code])
        rooms = c.all("SELECT * FROM rooms WHERE room_type_id = ? ORDER BY number", [rt["id"]])
        return h, rt, rooms


def _future(days=30):
    return (dt.date.today() + dt.timedelta(days=days)).isoformat()


def _book(client, h, rt, arrival, nights=2, room_id=None, **extra):
    body = {"arrival": arrival, "departure": (dt.date.fromisoformat(arrival) + dt.timedelta(days=nights)).isoformat(),
            "room_type_id": rt["id"], "guest": {"first_name": "Test", "last_name": f"Guest{dt.datetime.now().microsecond}",
                                                "email": f"t{dt.datetime.now().microsecond}@x.com", "force": True}, **extra}
    if room_id:
        body["room_id"] = room_id
    return client.post(f"/api/hotels/{h['id']}/reservations", body)


def test_create_and_quote(client):
    client.login("frontdesk@demo.ehms")
    h, rt, rooms = _ids()
    r = _book(client, h, rt, _future(), 3, rooms[0]["id"])
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["reference"].startswith("RES-CGL-")
    assert data["status"] == "confirmed"
    q = data["quote"]
    assert len(q["nights"]) == 3
    # 10% service charge then 7.5% VAT on net + service charge
    assert q["service_charge"] == q["net"] // 10
    assert q["tax"] == round((q["net"] + q["service_charge"]) * 0.075)
    assert q["total"] == q["net"] + q["service_charge"] + q["tax"]
    # confirmation queued but honestly marked not_configured (no SMTP in tests)
    detail = client.get(f"/api/reservations/{data['id']}").json()
    assert detail["notifications"][0]["status"] == "not_configured"


def test_same_room_cannot_be_double_booked(client):
    client.login("frontdesk@demo.ehms")
    h, rt, rooms = _ids()
    a = _future(40)
    assert _book(client, h, rt, a, 3, rooms[1]["id"]).status_code == 201
    overlap = _book(client, h, rt, (dt.date.fromisoformat(a) + dt.timedelta(days=1)).isoformat(), 2, rooms[1]["id"])
    assert overlap.status_code == 409
    assert overlap.json()["error"]["details"]["code"] == "room_clash"
    # back-to-back stays are fine (departure day = next arrival day)
    assert _book(client, h, rt, (dt.date.fromisoformat(a) + dt.timedelta(days=3)).isoformat(), 1, rooms[1]["id"]).status_code == 201


def test_category_cannot_be_oversold_without_authorisation(client):
    client.login("frontdesk@demo.ehms")
    h, rt, rooms = _ids("PRS")  # one presidential suite
    a = _future(50)
    assert _book(client, h, rt, a, 2).status_code == 201
    r = _book(client, h, rt, a, 2)
    assert r.status_code == 409
    r = _book(client, h, rt, a, 2, overbook_reason="VIP request")
    assert r.status_code == 403  # receptionist lacks reservations.overbook
    client.login("fom@demo.ehms")
    r = _book(client, h, rt, a, 2, overbook_reason="GM approved VIP overbooking")
    assert r.status_code == 201 and "overbooked_category" in r.json()["warnings"]


def test_rate_override_requires_permission_and_occupancy_limit(client):
    client.login("frontdesk@demo.ehms")
    h, rt, rooms = _ids("STD")
    assert _book(client, h, rt, _future(60), 1, nightly_rate=1000000).status_code == 403
    r = _book(client, h, rt, _future(60), 1, adults=3)
    assert r.status_code == 400
    client.login("fom@demo.ehms")
    r = _book(client, h, rt, _future(60), 2, nightly_rate=4000000)
    assert r.status_code == 201
    assert r.json()["quote"]["room_total"] == 8000000


def test_modify_cancel_and_no_show_rules(client):
    client.login("frontdesk@demo.ehms")
    h, rt, rooms = _ids()
    res = _book(client, h, rt, _future(70), 2).json()
    r = client.patch(f"/api/reservations/{res['id']}", {"departure": _future(74)})
    assert r.status_code == 200 and r.json()["nights"] == 4
    assert client.post(f"/api/reservations/{res['id']}/no-show").status_code == 409  # arrival in future
    assert client.post(f"/api/reservations/{res['id']}/cancel", {}).status_code == 400  # reason required
    assert client.post(f"/api/reservations/{res['id']}/cancel", {"reason": "Change of plans"}).json()["status"] == "cancelled"
    assert client.patch(f"/api/reservations/{res['id']}", {"adults": 1}).status_code == 409


def test_availability_reflects_bookings(client):
    client.login("frontdesk@demo.ehms")
    h, rt, rooms = _ids("JST")
    a, d = _future(80), _future(82)
    before = client.get(f"/api/hotels/{h['id']}/availability", params={"arrival": a, "departure": d}).json()
    n0 = next(t["available"] for t in before["room_types"] if t["id"] == rt["id"])
    _book(client, h, rt, a, 2)
    after = client.get(f"/api/hotels/{h['id']}/availability", params={"arrival": a, "departure": d}).json()
    assert next(t["available"] for t in after["room_types"] if t["id"] == rt["id"]) == n0 - 1


def test_duplicate_guest_detection(client):
    client.login("frontdesk@demo.ehms")
    r = client.post("/api/guests", {"first_name": "Adaeze", "last_name": "Okonkwo"})
    assert r.status_code == 409 and r.json()["error"]["details"]["duplicates"]
    assert client.post("/api/guests", {"first_name": "Adaeze", "last_name": "Okonkwo", "force": True}).status_code == 201


def test_identity_fields_are_masked_without_permission(client):
    client.login("reservations@demo.ehms")
    g = client.post("/api/guests", {"first_name": "Zainab", "last_name": "Lawal", "force": True}).json()
    assert client.patch(f"/api/guests/{g['id']}", {"id_number": "A1234567"}).status_code == 403
    client.login("frontdesk@demo.ehms")
    assert client.patch(f"/api/guests/{g['id']}", {"id_type": "passport", "id_number": "A1234567"}).status_code == 200
    client.login("reservations@demo.ehms")
    assert client.get(f"/api/guests/{g['id']}").json()["id_number"] == "•••• restricted"
