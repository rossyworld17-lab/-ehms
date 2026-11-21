"""Public booking engine, reports/exports, tax calculation and API documentation."""
import datetime as dt

from ehms.db import get_db
from ehms.services import price_breakdown


def test_booking_engine_flow(client):
    hotel = client.get("/api/public/hotels/CGL", token=None).json()
    assert hotel["online_payment_available"] is False
    a = (dt.date.today() + dt.timedelta(days=20)).isoformat()
    d = (dt.date.today() + dt.timedelta(days=22)).isoformat()
    av = client.get("/api/public/hotels/CGL/availability", params={"arrival": a, "departure": d, "adults": 2}, token=None).json()
    opt = next(o for o in av["options"] if o["code"] == "PRS")
    body = {"arrival": a, "departure": d, "room_type_id": opt["room_type_id"], "first_name": "Online", "last_name": "Guest",
            "email": "online.guest@example.com", "phone": "+2348000000000", "adults": 2}
    assert client.post("/api/public/hotels/CGL/bookings", body, token=None).status_code == 400  # terms not accepted
    assert client.post("/api/public/hotels/CGL/bookings", {**body, "accept_terms": True, "payment_option": "card"}, token=None).status_code == 501
    ok = client.post("/api/public/hotels/CGL/bookings", {**body, "accept_terms": True}, token=None)
    assert ok.status_code == 201, ok.text
    ref = ok.json()["reference"]
    assert ok.json()["total"] == opt["price"]["total"]
    # sold out now (one presidential suite)
    again = client.post("/api/public/hotels/CGL/bookings", {**body, "email": "x@example.com", "accept_terms": True}, token=None)
    assert again.status_code == 409
    look = client.get(f"/api/public/bookings/{ref}", params={"email": "online.guest@example.com"}, token=None)
    assert look.status_code == 200 and look.json()["status"] == "tentative"
    assert client.get(f"/api/public/bookings/{ref}", params={"email": "wrong@example.com"}, token=None).status_code == 404
    assert client.post(f"/api/public/bookings/{ref}/cancel", {"email": "online.guest@example.com"}, token=None).json()["status"] == "cancelled"


def test_reports_and_exports(client, hotel_id):
    client.login("gm@demo.ehms")
    names = [r["code"] for r in client.get(f"/api/hotels/{hotel_id}/reports").json()["items"]]
    assert {"arrivals", "daily_revenue", "occupancy"} <= set(names)
    j = client.get(f"/api/hotels/{hotel_id}/reports/in_house").json()
    assert len(j["rows"]) == 5
    x = client.get(f"/api/hotels/{hotel_id}/reports/occupancy", params={"format": "xlsx"})
    assert x.status_code == 200 and x.content[:2] == b"PK"
    p = client.get(f"/api/hotels/{hotel_id}/reports/arrivals", params={"format": "pdf"})
    assert p.content[:4] == b"%PDF"
    cs = client.get(f"/api/hotels/{hotel_id}/reports/daily_revenue", params={"format": "csv"})
    assert cs.text.startswith("Department")
    with get_db().tx() as c:
        fid = c.scalar("SELECT id FROM folios WHERE hotel_id = ? ORDER BY id LIMIT 1", [hotel_id])
    inv = client.get(f"/api/folios/{fid}/invoice.pdf")
    assert inv.status_code == 200 and inv.content[:4] == b"%PDF"
    client.login("housekeeper@demo.ehms")
    assert client.get(f"/api/hotels/{hotel_id}/reports/daily_revenue").status_code == 403


def test_dashboard_kpis(client, hotel_id):
    client.login("gm@demo.ehms")
    d = client.get(f"/api/hotels/{hotel_id}/dashboard").json()
    assert d["room_status"]["occupied"] == 5
    assert d["front_office"]["arrivals_expected"] == 4
    assert len(d["trend"]) == 30 and len(d["forecast"]) == 14
    assert d["today"]["total_rooms"] == 27


def test_tax_breakdown_exclusive_and_inclusive(client, hotel_id):
    with get_db().tx() as c:
        h = c.one("SELECT * FROM hotels WHERE id = ?", [hotel_id])
        b = price_breakdown(c, h, "room", 10000000, dt.date.today())
        assert (b["net"], b["service_charge"], b["tax"], b["total"]) == (10000000, 1000000, 825000, 11825000)
        c.execute("UPDATE tax_rules SET is_inclusive = 1 WHERE hotel_id = ?", [hotel_id])
        h["service_charge_bp"] = 0
        b = price_breakdown(c, h, "room", 10750000, dt.date.today())
        assert (b["net"], b["tax"], b["total"]) == (10000000, 750000, 10750000)
        c.execute("UPDATE tax_rules SET is_inclusive = 0 WHERE hotel_id = ?", [hotel_id])


def test_openapi_and_health(client):
    spec = client.get("/api/openapi.json", token=None).json()
    assert spec["openapi"].startswith("3.") and len(spec["paths"]) > 60
    assert client.get("/api/health", token=None).json()["status"] == "ok"
    r = client.get("/api/health", token=None)
    assert r.headers.get("x-frame-options") == "DENY"
