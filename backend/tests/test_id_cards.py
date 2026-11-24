"""Staff ID cards (release 1.4): automatic card on hiring, photo, printing, issue, reissue, revocation, QR verification."""
from __future__ import annotations

import base64
import datetime as dt
import io

from ehms.db import get_db
from test_frontoffice_finance import ctx_ids


def _png() -> str:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (60, 80), (120, 140, 160)).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def _hire(client, h) -> int:
    oid = client.post(f"/api/hotels/{h['id']}/recruitment", {"title": "Concierge", "department": "front_office", "positions": 1}).json()["id"]
    a = client.post(f"/api/recruitment/{oid}/applicants", {"first_name": "Ifeoma", "last_name": "Nwosu", "email": "ifeoma@example.com"}).json()["id"]
    for s in ("screening", "interview"):
        client.post(f"/api/applicants/{a}/stage", {"stage": s})
    start = (dt.date.fromisoformat(h["business_date"]) + dt.timedelta(days=7)).isoformat()
    client.post(f"/api/applicants/{a}/stage", {"stage": "offer", "offered_salary": 12000000, "start_date": start})
    r = client.post(f"/api/applicants/{a}/hire", {})
    assert r.status_code == 200, r.text
    return r.json()["employee_id"]


def test_card_generated_on_hire_printed_issued_and_verified(client):
    h, _ = ctx_ids()
    client.login("waiter@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/id-cards").status_code == 403
    client.login("hrofficer@demo.ehms")
    eid = _hire(client, h)
    q = client.get(f"/api/hotels/{h['id']}/id-cards", params={"status": "pending"}).json()
    card = next(k for k in q["items"] if k["employee_id"] == eid)
    assert card["reason"] == "new_hire" and card["card_no"].endswith("-01") and not card["has_photo"] and "verify_token" not in card
    # photo: type and content checks, then accepted
    assert client.post(f"/api/employees/{eid}/photo", {"filename": "me.gif", "content_base64": _png()}).status_code == 400
    assert client.post(f"/api/employees/{eid}/photo", {"filename": "me.png", "content_base64": base64.b64encode(b"\x89PNGnot-an-image").decode()}).status_code == 400
    assert client.post(f"/api/employees/{eid}/photo", {"filename": "me.png", "content_base64": _png()}).status_code == 200
    assert client.get(f"/api/employees/{eid}/photo").status_code == 200
    assert client.get(f"/api/employees/{eid}").json()["has_photo"] is True
    # not valid before it is printed
    with get_db().tx() as c:
        token = c.scalar("SELECT verify_token FROM staff_id_cards WHERE id = ?", [card["id"]])
    v = client.get(f"/api/public/staff-cards/{token}", token=None).json()
    assert v["valid"] is False and v["photo_url"] is None
    # cannot hand over an unprinted card
    assert client.post(f"/api/id-cards/{card['id']}/issue").status_code == 409
    # print on A4 and on a card printer
    pdf = client.get(f"/api/hotels/{h['id']}/id-cards/print", params={"ids": str(card["id"])})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"
    assert client.get(f"/api/hotels/{h['id']}/id-cards/print", params={"ids": str(card["id"]), "layout": "card"}).content.startswith(b"%PDF")
    k = next(x for x in client.get(f"/api/hotels/{h['id']}/id-cards").json()["items"] if x["id"] == card["id"])
    assert k["status"] == "printed" and k["print_count"] == 2 and k["issue_date"]
    assert client.post(f"/api/id-cards/{card['id']}/issue").json()["status"] == "issued"
    v = client.get(f"/api/public/staff-cards/{token}", token=None).json()
    assert v["valid"] is True and v["name"] == "Ifeoma Nwosu" and v["position"] == "Concierge" and v["photo_url"]
    assert client.get(v["photo_url"], token=None).status_code == 200
    page = client.get(f"/verify/staff/{token}", token=None)
    assert page.status_code == 200 and "Valid staff ID card" in page.text and "Ifeoma Nwosu" in page.text
    assert client.get("/api/public/staff-cards/not-a-real-token-123456789", token=None).status_code == 404
    assert client.get("/verify/staff/not-a-real-token-123456789", token=None).status_code == 404


def test_reissue_change_and_exit(client):
    h, _ = ctx_ids()
    client.login("hrofficer@demo.ehms")
    eid = _hire(client, h)
    first = next(k for k in client.get(f"/api/hotels/{h['id']}/id-cards").json()["items"] if k["employee_id"] == eid)
    client.get(f"/api/hotels/{h['id']}/id-cards/print", params={"ids": str(first["id"])})
    client.post(f"/api/id-cards/{first['id']}/issue")
    # promotion: a replacement is queued automatically; the old card stays valid until the new one is handed over
    assert client.patch(f"/api/employees/{eid}", {"position": "Head Concierge"}).status_code == 200
    cards = [k for k in client.get(f"/api/hotels/{h['id']}/id-cards").json()["items"] if k["employee_id"] == eid]
    new = next(k for k in cards if k["status"] == "pending")
    assert new["reason"] == "details_changed" and new["card_no"].endswith("-02")
    assert client.post(f"/api/employees/{eid}/id-cards", {"reason": "renewal"}).status_code == 409   # one in the queue already
    client.get(f"/api/hotels/{h['id']}/id-cards/print", params={"ids": str(new["id"])})
    assert client.post(f"/api/id-cards/{new['id']}/issue").json()["replaced"] == 1
    # lost: the current card is cancelled at once and a new one queued
    r = client.post(f"/api/employees/{eid}/id-cards", {"reason": "lost", "note": "Lost at the market"})
    assert r.status_code == 201
    states = {k["card_no"]: k for k in client.get(f"/api/hotels/{h['id']}/id-cards").json()["items"] if k["employee_id"] == eid}
    assert states[new["card_no"]]["status"] == "revoked" and "Lost" in states[new["card_no"]]["revoke_reason"]
    # cancelled cards cannot be printed
    assert client.get(f"/api/hotels/{h['id']}/id-cards/print", params={"ids": str(new["id"])}).status_code == 400
    # leaving revokes everything
    assert client.patch(f"/api/employees/{eid}", {"status": "resigned", "exit_reason": "Relocated"}).status_code == 200
    assert all(k["status"] == "revoked" for k in client.get(f"/api/hotels/{h['id']}/id-cards").json()["items"] if k["employee_id"] == eid)
    assert client.post(f"/api/employees/{eid}/id-cards", {"reason": "other"}).status_code == 409


def test_card_design_editable_by_administrators(client):
    import json as _json
    h, _ = ctx_ids()
    client.login("hrofficer@demo.ehms")                            # prints cards, but cannot change the design
    assert client.put(f"/api/hotels/{h['id']}/id-cards/design", {"colour": "#000000"}).status_code == 403
    client.login("admin@demo.ehms")                                # administrators design the card
    d = client.get(f"/api/hotels/{h['id']}/id-cards/design").json()
    assert d["orientation"] == "landscape" and d["show_signature"] is True and d["defaults"]["title"] == "STAFF IDENTITY CARD"
    for bad in ({"colour": "blue"}, {"valid_years": 20}, {"orientation": "round"}, {"title": "x" * 41}, {"back_note": "y" * 301}):
        assert client.put(f"/api/hotels/{h['id']}/id-cards/design", bad).status_code == 400, bad
    new = {"orientation": "portrait", "colour": "#7a1f2b", "band_text": "#fff8e1", "accent": "#7A1F2B", "title": "Employee ID",
           "footer_label": "CREW", "valid_years": 3, "show_department": False, "show_blood_group": False, "signature_label": "General Manager",
           "back_note": "Property of the hotel.", "unknown_key": "ignored"}
    s = client.put(f"/api/hotels/{h['id']}/id-cards/design", new).json()
    assert s["orientation"] == "portrait" and s["colour"] == "#7A1F2B" and s["band_text"] == "#FFF8E1" and s["valid_years"] == 3
    assert s["show_department"] is False and s["title"] == "Employee ID" and "unknown_key" not in s
    # a partial change keeps the rest
    assert client.put(f"/api/hotels/{h['id']}/id-cards/design", {"show_logo": False}).json()["orientation"] == "portrait"
    # signature image: checked, stored, printed, removable
    from test_id_cards import _png
    assert client.post(f"/api/hotels/{h['id']}/id-cards/signature", {"filename": "s.gif", "content_base64": _png()}).status_code == 400
    assert client.post(f"/api/hotels/{h['id']}/id-cards/signature", {"filename": "s.png", "content_base64": _png()}).status_code == 200
    assert client.get(f"/api/hotels/{h['id']}/id-cards/design").json()["has_signature"] is True
    assert client.get(f"/api/hotels/{h['id']}/id-cards/signature").status_code == 200
    # preview of an unsaved design, both sizes; nothing is printed or saved
    with get_db().tx() as c:
        printed_before = c.scalar("SELECT COUNT(*) FROM staff_id_cards WHERE status <> 'pending'")
    for lay in ("card", "a4"):
        for orient in ("portrait", "landscape"):
            r = client.post(f"/api/hotels/{h['id']}/id-cards/preview", {"layout": lay, "design": {"orientation": orient, "title": "Preview"}})
            assert r.status_code == 200 and r.content.startswith(b"%PDF"), r.text
    assert client.get(f"/api/hotels/{h['id']}/id-cards/design").json()["title"] == "Employee ID"
    with get_db().tx() as c:
        assert c.scalar("SELECT COUNT(*) FROM staff_id_cards WHERE status <> 'pending'") == printed_before
    # HR prints with the saved design (portrait: 9 cards per A4 sheet)
    client.login("hrmanager@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/id-cards").json()["settings"]["orientation"] == "portrait"
    with get_db().tx() as c:
        c.execute("UPDATE staff_id_cards SET status = 'revoked' WHERE hotel_id = ?", [h["id"]])
    n = client.post(f"/api/hotels/{h['id']}/id-cards/generate-missing").json()["created"]
    assert n > 9 and client.get(f"/api/hotels/{h['id']}/id-cards").json()["counts"]["pending"] == n
    pdf = client.get(f"/api/hotels/{h['id']}/id-cards/print")
    assert pdf.status_code == 200 and pdf.content.count(b"/Type /Page") >= 4
    # expiry follows the design's validity
    with get_db().tx() as c:
        k = c.one("SELECT issue_date, expiry_date FROM staff_id_cards WHERE status = 'printed' ORDER BY id DESC LIMIT 1")
    assert int(str(k["expiry_date"])[:4]) - int(str(k["issue_date"])[:4]) == 3
    client.login("admin@demo.ehms")
    assert client.delete(f"/api/hotels/{h['id']}/id-cards/signature").status_code == 200
    assert client.post(f"/api/hotels/{h['id']}/id-cards/design/reset").json()["orientation"] == "landscape"
    with get_db().tx() as c:
        assert _json.loads(c.scalar("SELECT value FROM system_settings WHERE key = 'idcards.design' AND hotel_id = ?", [h["id"]]))["title"] == "STAFF IDENTITY CARD"


def test_blood_group_validated(client):
    client.login("hrofficer@demo.ehms")
    with get_db().tx() as c:
        eid = c.scalar("SELECT id FROM employees WHERE status = 'active' ORDER BY id LIMIT 1")
    assert client.patch(f"/api/employees/{eid}", {"blood_group": "Z"}).status_code == 400
    assert client.patch(f"/api/employees/{eid}", {"blood_group": "o +"}).status_code == 200
    assert client.get(f"/api/employees/{eid}").json()["blood_group"] == "O+"


def test_promotion_from_job_history_queues_card(client):
    h, _ = ctx_ids()
    client.login("hrmanager@demo.ehms")
    with get_db().tx() as c:
        eid = c.scalar("SELECT employee_id FROM staff_id_cards WHERE status = 'issued' ORDER BY id LIMIT 1")
    r = client.post(f"/api/employees/{eid}/history", {"kind": "promotion", "effective_date": h["business_date"], "position": "Senior Supervisor"})
    assert r.status_code == 201, r.text
    cards = [k for k in client.get(f"/api/hotels/{h['id']}/id-cards", params={"status": "pending"}).json()["items"] if k["employee_id"] == eid]
    assert len(cards) == 1 and cards[0]["reason"] == "details_changed"
