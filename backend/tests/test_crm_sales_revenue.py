"""Release 0.8: loyalty, complaints, feedback & surveys, campaigns, corporate accounts & negotiated rates,
seasons, approval-controlled dynamic pricing with locked quotes, competitor rates, targets and the revenue dashboard."""
import datetime as dt
import uuid

from ehms.db import get_db

from test_frontoffice_finance import arrival_today, ctx_ids, pay
from test_pos_inventory_procurement import assert_books_balance, gl_balance


def rt_id(h, code):
    with get_db().tx() as c:
        return c.one("SELECT * FROM room_types WHERE hotel_id = ? AND code = ?", [h["id"], code])


def test_loyalty_earn_on_checkout_redeem_and_survey(client):
    client.login("frontdesk@demo.ehms")
    h, methods = ctx_ids()
    res, _ = arrival_today(client, h)
    gid = res["guest"]["id"]
    assert client.post(f"/api/guests/{gid}/loyalty/enrol", {}).status_code == 400            # guest agreement needed
    en = client.post(f"/api/guests/{gid}/loyalty/enrol", {"guest_agreed": True, "welcome_points": 600})
    assert en.status_code == 201
    folio = client.post(f"/api/reservations/{res['id']}/check-in", {}).json()["folio"]["id"]
    client.post(f"/api/folios/{folio}/charges", {"department": "fnb", "description": "Dinner", "amount": 2000000})
    # redeem 500 points = ₦5,000 credit (posted as an allowance)
    before = gl_balance("allowances", h["id"])
    assert client.post(f"/api/folios/{folio}/loyalty-redeem", {"points": 100}).status_code == 400   # below minimum
    r = client.post(f"/api/folios/{folio}/loyalty-redeem", {"points": 500})
    assert r.status_code == 201 and r.json()["value"] == 500000
    assert gl_balance("allowances", h["id"]) - before == 500000
    due = client.get(f"/api/reservations/{res['id']}/checkout-preview").json()["balance_due"]
    pay(client, folio, methods["CASH"], due)
    out = client.post(f"/api/reservations/{res['id']}/check-out", {})
    assert out.status_code == 200, out.text
    assert out.json()["loyalty_points_earned"] > 0                 # 1 point per ₦1,000 of net spend
    acct = client.get(f"/api/guests/{gid}/loyalty").json()
    assert acct["member"] and acct["points_balance"] == 100 + out.json()["loyalty_points_earned"]
    # a survey invitation was created and can be answered once via the public link
    with get_db().tx() as c:
        token = c.scalar("SELECT token FROM feedback WHERE reservation_id = ?", [res["id"]])
        email = c.one("SELECT * FROM notifications WHERE related_entity = 'feedback' ORDER BY id DESC")
    assert token in email["body"]
    assert client.get(f"/api/public/feedback/{token}", token=None).json()["submitted"] is False
    assert client.post(f"/api/public/feedback/{token}", {"nps": 9}, token=None).status_code == 400     # overall required
    ok = client.post(f"/api/public/feedback/{token}", {"overall": 2, "cleanliness": 1, "nps": 3, "comments": "The room was dirty and the AC was noisy"}, token=None)
    assert ok.status_code == 200
    assert client.post(f"/api/public/feedback/{token}", {"overall": 5}, token=None).status_code == 409
    client.login("guestservice@demo.ehms")
    fb = next(f for f in client.get(f"/api/hotels/{h['id']}/feedback").json()["items"] if f["reservation_id"] == res["id"])
    assert fb["sentiment"] == "negative" and "cleanliness" in fb["themes"] and "noise" in fb["themes"]
    # a low score opens a complaint automatically
    assert any("Low survey score" in x["description"] for x in client.get(f"/api/hotels/{h['id']}/complaints").json()["items"])
    assert_books_balance(h["id"])


def test_complaints_sla_response_escalation_and_insights(client):
    h, _ = ctx_ids()
    client.login("frontdesk@demo.ehms")
    r = client.post(f"/api/hotels/{h['id']}/complaints", {"category": "noise", "priority": "urgent", "description": "Party next door"})
    assert r.status_code == 201
    cid = r.json()["id"]
    assert client.get(f"/api/hotels/{h['id']}/complaints").status_code == 403            # can register, cannot browse
    client.login("fom@demo.ehms")
    assert any(n["subject"] == "Urgent guest complaint" for n in client.get("/api/notifications/mine").json()["items"])
    assert client.post(f"/api/complaints/{cid}/update", {"status": "resolved"}).status_code == 400    # resolution needed
    assert client.post(f"/api/complaints/{cid}/update", {"note": "Security sent to the room"}).status_code == 200
    # force the SLA to lapse on another complaint and run escalation
    c2 = client.post(f"/api/hotels/{h['id']}/complaints", {"category": "wifi", "description": "No internet"}).json()["id"]
    with get_db().tx() as c:
        c.execute("UPDATE complaints SET due_at = '2000-01-01T00:00:00Z' WHERE id = ?", [c2])
    from ehms.worker import run_jobs
    assert run_jobs()["complaints_escalated"] >= 1
    x = client.get(f"/api/complaints/{c2}").json()
    assert x["escalation_level"] == 1 and x["priority"] == "high" and "Escalated" in x["updates"][-1]["note"]
    assert client.post(f"/api/complaints/{cid}/update", {"status": "resolved", "resolution": "Neighbours moved; drinks offered", "guest_satisfied": True}).status_code == 200
    ins = client.get(f"/api/hotels/{h['id']}/crm/insights").json()
    assert ins["complaints"]["total"] >= 2 and ins["complaints"]["avg_first_response_hours"] is not None
    assert ins["responses"] >= 5 and ins["nps"] is not None and ins["themes"][0]["mentions"] >= 1
    assert ins["retention"]["loyalty_members"] >= 6


def test_campaign_only_to_consenting_guests(client):
    h, _ = ctx_ids()
    client.login("marketing@demo.ehms")
    prev = client.post(f"/api/hotels/{h['id']}/campaigns/preview", {"segment": {}}).json()
    with get_db().tx() as c:
        consenting = c.scalar("SELECT COUNT(*) FROM guests WHERE marketing_consent = 1 AND email IS NOT NULL")
    assert 0 < prev["count"] <= consenting
    k = client.post(f"/api/hotels/{h['id']}/campaigns", {"name": "Test", "channel": "email", "subject": "Hi {guest}", "body": "Code {promo_code}", "promo_code": "WELCOME10",
                                                         "segment": {}}).json()
    sent = client.post(f"/api/campaigns/{k['id']}/send", {})
    assert sent.status_code == 200 and sent.json()["recipients"] == prev["count"]
    assert client.post(f"/api/campaigns/{k['id']}/send", {}).status_code == 409
    with get_db().tx() as c:
        n = c.one("SELECT * FROM notifications WHERE related_entity = 'campaign' ORDER BY id DESC")
        no_consent = c.scalar("SELECT COUNT(*) FROM campaign_recipients cr JOIN guests g ON g.id = cr.guest_id WHERE g.marketing_consent = 0")
    assert "WELCOME10" in n["body"] and "unsubscribe" in n["body"] and no_consent == 0
    camp = next(x for x in client.get(f"/api/hotels/{h['id']}/campaigns").json()["items"] if x["id"] == k["id"])
    assert camp["delivery"]
    client.login("frontdesk@demo.ehms")
    assert client.post(f"/api/hotels/{h['id']}/campaigns", {"name": "x", "channel": "sms", "body": "y"}).status_code == 403


def test_negotiated_rate_season_and_locked_dynamic_pricing(client):
    h, _ = ctx_ids()
    bd = dt.date.fromisoformat(h["business_date"])
    std = rt_id(h, "STD")
    client.login("sales@demo.ehms")
    acct = next(a for a in client.get(f"/api/hotels/{h['id']}/accounts/corporate").json()["items"] if a["code"] == "DELTA")
    # a corporate booking for the account gets the negotiated rate
    arr = bd + dt.timedelta(days=40)
    assert client.post(f"/api/accounts/corporate/{acct['id']}/rates", {"hotel_id": h["id"], "room_type_id": std["id"], "rate": 3800000,
                                                                       "valid_from": arr.isoformat(), "valid_to": (arr + dt.timedelta(days=10)).isoformat()}).status_code == 201
    client.login("reservations@demo.ehms")
    b = client.post(f"/api/hotels/{h['id']}/reservations", {"arrival": arr.isoformat(), "departure": (arr + dt.timedelta(days=2)).isoformat(), "room_type_id": std["id"],
                                                            "booking_type": "corporate", "corporate_account_id": acct["id"], "source": "corporate",
                                                            "guest": {"first_name": "Corp", "last_name": f"Guest{uuid.uuid4().hex[:4]}", "force": True}})
    assert b.status_code == 201, b.text
    assert {n["room_rate"] for n in b.json()["quote"]["nights"]} == {3800000} and b.json()["company_name"].startswith("Delta")
    # season: +25 % for a window
    client.login("sales@demo.ehms")
    s_from = bd + dt.timedelta(days=60)
    assert client.post(f"/api/hotels/{h['id']}/revenue/seasons", {"name": "Conference week", "start_date": s_from.isoformat(),
                                                                  "end_date": (s_from + dt.timedelta(days=6)).isoformat(), "adjustment_bp": 2500}).status_code == 201
    q = client.post(f"/api/hotels/{h['id']}/quote", {"arrival": s_from.isoformat(), "departure": (s_from + dt.timedelta(days=1)).isoformat(), "room_type_id": std["id"]}).json()
    base = std["weekend_rate"] if s_from.weekday() in (4, 5) and std["weekend_rate"] else std["base_rate"]
    assert q["nights"][0]["room_rate"] == base * 125 // 100 and "Conference week" in q["nights"][0]["applied"][-1]
    # dynamic rule: 0–100 % occupancy band so it applies; needs a second person's approval before it takes effect
    rule = client.post(f"/api/hotels/{h['id']}/revenue/rules", {"name": "Test uplift", "min_occupancy_pct": 0, "max_occupancy_pct": 100, "adjustment_bp": 1000}).json()
    d2 = bd + dt.timedelta(days=80)
    body = {"arrival": d2.isoformat(), "departure": (d2 + dt.timedelta(days=1)).isoformat(), "room_type_id": std["id"]}
    plain = client.post(f"/api/hotels/{h['id']}/quote", body).json()["nights"][0]["room_rate"]
    assert client.post(f"/api/revenue/rules/{rule['id']}/decide", {"decision": "approve"}).status_code == 403   # sales cannot approve
    client.login("finance@demo.ehms")
    assert client.post(f"/api/revenue/rules/{rule['id']}/decide", {"decision": "approve"}).json()["status"] == "active"
    client.login("reservations@demo.ehms")
    up = client.post(f"/api/hotels/{h['id']}/reservations", {**body, "guest": {"first_name": "Dyn", "last_name": f"P{uuid.uuid4().hex[:4]}", "force": True}})
    assert up.json()["quote"]["nights"][0]["room_rate"] == plain * 110 // 100
    # deactivating the rule later does not change what that guest was quoted (locked rate)
    client.login("finance@demo.ehms")
    client.post(f"/api/revenue/rules/{rule['id']}/decide", {"decision": "deactivate"})
    from ehms.pricing import stay_night_rate
    with get_db().tx() as c:
        r = c.one("SELECT * FROM reservations WHERE id = ?", [up.json()["id"]])
        assert stay_night_rate(c, r, std, d2) == plain * 110 // 100
    # corporate account statement and negotiated-rate discount
    client.login("sales@demo.ehms")
    det = client.get(f"/api/accounts/corporate/{acct['id']}").json()
    assert det["rates"] and any(x["reference"] == b.json()["reference"] for x in det["bookings"])
    nr = client.post(f"/api/accounts/corporate/{acct['id']}/rates", {"hotel_id": h["id"], "room_type_id": std["id"], "rate": 3000000, "valid_from": "2027-01-01", "valid_to": "2027-12-31"})
    assert nr.status_code == 201 and nr.json()["discount_vs_rack_pct"] > 0


def test_targets_competitors_and_revenue_dashboard(client):
    h, _ = ctx_ids()
    bd = dt.date.fromisoformat(h["business_date"])
    client.login("sales@demo.ehms")
    t = client.get(f"/api/hotels/{h['id']}/sales/targets").json()
    room = next(x for x in t["items"] if x["metric"] == "room_revenue")
    assert room["target"] > 0 and room["actual"] >= 0 and room["achieved_pct"] is not None
    assert client.put(f"/api/hotels/{h['id']}/sales/targets", {"period": bd.strftime("%Y-%m"), "metric": "rooms_sold", "target": 500}).status_code == 200
    assert client.post(f"/api/hotels/{h['id']}/revenue/competitor-rates", {"rows": [{"competitor": "X Hotel", "stay_date": bd.isoformat(), "room_category": "Std", "rate": 4000000}]}).status_code == 201
    d = client.get(f"/api/hotels/{h['id']}/revenue/dashboard").json()
    assert len(d["forward"]) == 30 and d["forward"][0]["rooms_on_books"] >= 1 and d["forward"][0]["competitor_avg"]
    assert d["period"]["rooms_sold"] >= 1 and d["period"]["adr"] > 0 and d["year_on_year"][-1]["this_year"]["room_revenue"] >= 0
    pr = client.get(f"/api/hotels/{h['id']}/revenue/pricing").json()
    assert pr["seasons"] and pr["rules"] and pr["competitors"]
    client.login("frontdesk@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/revenue/dashboard").status_code == 403
