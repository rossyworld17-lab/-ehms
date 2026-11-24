"""Release 1.3 — public hotel website managed from EHMS: draft → preview → publish, validation, images, sections,
French text, enquiries from the contact form, permissions, and the website at the main address with EHMS at /staff."""
import base64

from ehms.db import get_db

from test_frontoffice_finance import ctx_ids

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 64).decode()


def test_public_site_shows_published_content_and_live_hotel_data(client):
    h, _ = ctx_ids()
    s = client.get("/api/public/site", token=None).json()
    assert s["hotel"]["code"] == "CGL" and s["booking_url"] == "/#/book/CGL"
    assert s["content"]["text"]["en"]["hero_title"].startswith("Welcome to")
    assert s["rooms"] and all("from_rate" in r for r in s["rooms"])       # rooms and prices come from the hotel record
    assert {o["code"] for o in s["other_hotels"]} == {"CSA"}
    assert client.get("/api/public/site", params={"hotel": "CSA"}, token=None).json()["hotel"]["code"] == "CSA"
    assert client.get("/api/public/site", params={"hotel": "NOPE"}, token=None).status_code == 404


def test_edit_preview_publish_and_discard(client):
    h, _ = ctx_ids()
    client.login("frontdesk@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/website").status_code == 403
    client.login("marketing@demo.ehms")                       # marketing manager holds website.manage
    ed = client.get(f"/api/hotels/{h['id']}/website").json()
    doc = ed["draft"]
    doc["text"]["en"]["hero_title"] = "Your Lagos home away from home"
    doc["text"]["fr"]["hero_title"] = "Votre maison à Lagos"
    doc["sections"]["events"] = False
    # validation
    bad = {**doc, "map_url": "javascript:alert(1)"}
    assert client.put(f"/api/hotels/{h['id']}/website", {"content": bad}).status_code == 400
    bad = {**doc, "social": {**doc["social"], "instagram": "http://insecure.example"}}
    assert client.put(f"/api/hotels/{h['id']}/website", {"content": bad}).status_code == 400
    bad = {**doc, "text": {**doc["text"], "en": {**doc["text"]["en"], "seo_title": "x" * 200}}}
    assert client.put(f"/api/hotels/{h['id']}/website", {"content": bad}).status_code == 400
    bad = {**doc, "images": {**doc["images"], "hero": 99999}}
    assert client.put(f"/api/hotels/{h['id']}/website", {"content": bad}).status_code == 400
    # preview does not save; saving a draft does not change the public site
    pv = client.post(f"/api/hotels/{h['id']}/website/preview", {"content": doc}).json()
    assert pv["preview"] and pv["content"]["text"]["en"]["hero_title"] == "Your Lagos home away from home"
    assert client.put(f"/api/hotels/{h['id']}/website", {"content": doc}).status_code == 200
    assert client.get("/api/public/site", token=None).json()["content"]["text"]["en"]["hero_title"] != "Your Lagos home away from home"
    assert client.get(f"/api/hotels/{h['id']}/website").json()["unpublished_changes"] is True
    # publish → public
    assert client.post(f"/api/hotels/{h['id']}/website/publish", {}).json()["published"] is True
    pub = client.get("/api/public/site", token=None).json()["content"]
    assert pub["text"]["en"]["hero_title"] == "Your Lagos home away from home" and pub["text"]["fr"]["hero_title"] == "Votre maison à Lagos"
    assert pub["sections"]["events"] is False
    # discard brings the draft back to the published version
    doc["text"]["en"]["hero_title"] = "Unpublished idea"
    client.put(f"/api/hotels/{h['id']}/website", {"content": doc})
    assert client.post(f"/api/hotels/{h['id']}/website/discard", {}).json()["discarded"] is True
    assert client.get(f"/api/hotels/{h['id']}/website").json()["draft"]["text"]["en"]["hero_title"] == "Your Lagos home away from home"
    with get_db().tx() as c:
        assert c.scalar("SELECT COUNT(*) FROM audit_logs WHERE action = 'website.published'") >= 1


def test_images_gallery_and_protection_of_used_images(client):
    h, _ = ctx_ids()
    client.login("gm@demo.ehms")
    assert client.post(f"/api/hotels/{h['id']}/website/media", {"filename": "x.gif", "content_base64": PNG}).status_code == 400
    assert client.post(f"/api/hotels/{h['id']}/website/media", {"filename": "x.png", "content_base64": base64.b64encode(b"<svg/>").decode()}).status_code == 400
    m1 = client.post(f"/api/hotels/{h['id']}/website/media", {"filename": "lobby.png", "content_base64": PNG, "caption": "Lobby"}).json()
    m2 = client.post(f"/api/hotels/{h['id']}/website/media", {"filename": "pool.png", "content_base64": PNG}).json()
    img = client.get(m1["url"], token=None)
    assert img.status_code == 200 and img.content.startswith(b"\x89PNG")
    doc = client.get(f"/api/hotels/{h['id']}/website").json()["draft"]
    doc["images"]["hero"] = m1["id"]
    doc["gallery"] = [m2["id"], m1["id"], m2["id"]]
    saved = client.put(f"/api/hotels/{h['id']}/website", {"content": doc}).json()["content"]
    assert saved["gallery"] == [m2["id"], m1["id"]]                       # duplicates removed, order kept
    client.post(f"/api/hotels/{h['id']}/website/publish", {})
    pub = client.get("/api/public/site", token=None).json()
    assert pub["image_urls"]["hero"] == m1["url"] and [g["id"] for g in pub["gallery"]] == [m2["id"], m1["id"]]
    assert client.delete(f"/api/website/media/{m1['id']}").status_code == 409   # used by the published site
    doc["images"]["hero"] = None
    doc["gallery"] = [m2["id"]]
    client.put(f"/api/hotels/{h['id']}/website", {"content": doc})
    client.post(f"/api/hotels/{h['id']}/website/publish", {})
    assert client.patch(f"/api/website/media/{m1['id']}", {"caption": "Main lobby"}).status_code == 200
    assert client.delete(f"/api/website/media/{m1['id']}").status_code == 200
    assert client.get(m1["url"], token=None).status_code == 404
    # another hotel's image cannot be used
    other = client.post(f"/api/hotels/{h['id'] + 1}/website/media", {"filename": "o.png", "content_base64": PNG}).json()
    doc["images"]["about"] = other["id"]
    assert client.put(f"/api/hotels/{h['id']}/website", {"content": doc}).status_code == 400


def test_contact_form_enquiries(client):
    h, _ = ctx_ids()
    assert client.post("/api/public/site/enquiries", {"name": "A", "email": "bad", "message": "hello there"}, token=None).status_code == 400
    assert client.post("/api/public/site/enquiries", {"name": "Bot", "email": "b@example.com", "message": "spam spam", "website": "http://spam"}, token=None).json()["ok"]
    r = client.post("/api/public/site/enquiries", {"kind": "event", "name": "Ada Eze", "email": "ada@example.com", "message": "Wedding for 200 guests in March",
                                                     "event_date": "2027-03-14", "guests": 200}, token=None)
    assert r.status_code == 201
    client.post("/api/public/site/enquiries", {"kind": "rooms", "name": "Bayo", "email": "bayo@example.com", "message": "Rates for a week?"}, token=None)
    with get_db().tx() as c:
        assert c.scalar("SELECT COUNT(*) FROM website_enquiries WHERE name = 'Bot'") == 0          # honeypot dropped silently
        ev = c.one("SELECT * FROM website_enquiries WHERE email = 'ada@example.com'")
        assert ev["kind"] == "event" and ev["guests"] == 200
        sales = c.scalar("SELECT id FROM users WHERE email = 'sales@demo.ehms'")
        assert c.scalar("SELECT COUNT(*) FROM notifications WHERE recipient = ? AND related_entity = 'website_enquiry' AND related_id = ?", [str(sales), str(ev["id"])]) == 1
    client.login("guestservice@demo.ehms")                    # guest relations sees all enquiries
    items = client.get(f"/api/hotels/{h['id']}/website/enquiries", params={"status": "new"}).json()["items"]
    assert {"ada@example.com", "bayo@example.com"} <= {e["email"] for e in items}
    client.login("fnbmanager@demo.ehms")                      # events-only staff (no guest relations) see event enquiries only
    items = client.get(f"/api/hotels/{h['id']}/website/enquiries").json()["items"]
    assert items and all(e["kind"] == "event" for e in items)
    with get_db().tx() as c:
        rooms_id = c.scalar("SELECT id FROM website_enquiries WHERE email = 'bayo@example.com'")
    assert client.post(f"/api/website/enquiries/{rooms_id}/status", {"status": "replied"}).status_code == 403
    assert client.post(f"/api/website/enquiries/{ev['id']}/status", {"status": "replied", "note": "Sent packages"}).json()["status"] == "replied"
    client.login("housekeeper@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/website/enquiries").status_code == 403


def test_website_at_main_address_and_ehms_at_staff(client):
    home = client.get("/", token=None)
    assert home.status_code == 200
    # the main address carries the hotel's own title and description for search engines
    if "<div id=\"root\">" in home.text:
        assert "<title>Crestview Grand Lagos (Demo) — Official website</title>" in home.text and 'name="description"' in home.text
        staff = client.get("/staff", token=None)
        assert staff.status_code == 200 and "<title>EHMS — Enterprise Hotel Management System</title>" in staff.text
