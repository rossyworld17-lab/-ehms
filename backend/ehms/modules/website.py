"""Public hotel website managed from EHMS (release 1.3).

Administrators with `website.manage` edit the website's text (English and French), images, sections, social links,
map link and search-engine title/description under Administration → Website. Changes are saved as a draft, previewed,
then published; the public site at the main address only ever shows the published version. Room categories, prices,
photos and contact details come from the live hotel record, so they never go out of date. The contact form creates
an enquiry that guest relations (or events, for event enquiries) answer in EHMS.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import secrets

from starlette.responses import Response

from ..db import get_db, now_iso
from ..http import ApiError, Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import queue_notification

LANGS = ("en", "fr")
SECTIONS = ("about", "highlights", "rooms", "dining", "events", "facilities", "gallery", "location", "contact")
IMAGE_SLOTS = ("hero", "about", "dining", "events")
SOCIAL = ("facebook", "instagram", "x", "tiktok", "tripadvisor", "whatsapp")
MAX_IMAGE = 5 * 1024 * 1024
IMAGE_TYPES = {"jpg": ("image/jpeg", b"\xff\xd8\xff"), "jpeg": ("image/jpeg", b"\xff\xd8\xff"), "png": ("image/png", b"\x89PNG"), "webp": ("image/webp", b"RIFF")}
URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?(/[^\s<>\"']*)?$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# text fields per language: (max length, multiline)
TEXT_FIELDS = {
    "hero_title": 90, "hero_subtitle": 220, "about_title": 90, "about_body": 2500, "rooms_title": 90, "rooms_intro": 600,
    "dining_title": 90, "dining_body": 1500, "dining_hours": 300, "events_title": 90, "events_body": 1500,
    "facilities_title": 90, "gallery_title": 90, "location_title": 90, "directions": 800, "contact_title": 90, "contact_intro": 400,
    "contact_hours": 200, "seo_title": 70, "seo_description": 170, "footer_note": 300, "announcement": 200,
}
LIST_FIELDS = {"highlights": (6, {"title": 60, "text": 220}), "facilities": (24, None)}


def default_content(hotel: dict) -> dict:
    name = hotel["name"]
    city = hotel.get("city") or ""
    return {
        "sections": {s: True for s in SECTIONS},
        "images": {s: None for s in IMAGE_SLOTS},
        "gallery": [],
        "social": {k: "" for k in SOCIAL},
        "map_url": "",
        "text": {
            "en": {
                "hero_title": f"Welcome to {name}", "hero_subtitle": f"Comfortable rooms, warm Nigerian hospitality and great food{(' in ' + city) if city else ''}.",
                "about_title": "About us", "about_body": f"{name} offers well-appointed rooms, a restaurant and bar, meeting and event spaces, and a team that looks after every detail of your stay.",
                "rooms_title": "Rooms & suites", "rooms_intro": "Choose the room that suits your stay. Prices include taxes and service charge.",
                "dining_title": "Restaurant & bar", "dining_body": "Enjoy local and continental dishes, freshly prepared, in our restaurant, at the bar or in your room.",
                "dining_hours": "Breakfast 06:30–10:30 · Lunch 12:00–15:00 · Dinner 18:30–22:30",
                "events_title": "Meetings & events", "events_body": "From board meetings to weddings, our venues, catering and event team make your occasion a success.",
                "facilities_title": "Facilities", "gallery_title": "Gallery", "location_title": "Find us", "directions": "",
                "contact_title": "Contact us", "contact_intro": "Questions, special requests or event enquiries — send us a message and we will reply quickly.",
                "contact_hours": "Reception is open 24 hours.", "seo_title": f"{name} — Official website", "seo_description": f"Book directly with {name}{(', ' + city) if city else ''}: rooms, dining, meetings and events.",
                "footer_note": "", "announcement": "",
                "highlights": [{"title": "Best rate when you book direct", "text": "Book on our website for our best available price."},
                               {"title": "Free Wi-Fi", "text": "Fast internet throughout the hotel."},
                               {"title": "24-hour reception", "text": "We are here day and night."}],
                "facilities": ["Restaurant & bar", "Room service", "Free Wi-Fi", "Conference & event halls", "Secure parking", "Laundry service", "Airport transfer on request", "24-hour security"],
            },
            "fr": {},
        },
    }


def _content_row(c, hid: int) -> dict | None:
    return c.one("SELECT * FROM website_content WHERE hotel_id = ?", [hid])


def _load(raw: str | None) -> dict | None:
    return json.loads(raw) if raw else None


def _clean_text(v, limit: int, field: str) -> str:
    s = str(v or "").replace("\r\n", "\n").strip()
    if len(s) > limit:
        raise bad_request(f"{field} is too long (at most {limit} characters)")
    return s


def validate(c, hid: int, body: dict, hotel: dict) -> dict:
    """Return a clean content document or raise a readable error. Unknown keys are dropped."""
    if not isinstance(body, dict):
        raise bad_request("content must be an object")
    out = default_content(hotel)
    secs = body.get("sections") or {}
    out["sections"] = {s: bool(secs.get(s, True)) for s in SECTIONS}
    media_ids = {m["id"] for m in c.all("SELECT id FROM website_media WHERE hotel_id = ?", [hid])}
    imgs = body.get("images") or {}
    for slot in IMAGE_SLOTS:
        v = imgs.get(slot)
        if v in (None, "", 0):
            out["images"][slot] = None
        elif int(v) in media_ids:
            out["images"][slot] = int(v)
        else:
            raise bad_request(f"The {slot} image is not one of this hotel's website images")
    gallery = body.get("gallery") or []
    if not isinstance(gallery, list) or len(gallery) > 40:
        raise bad_request("The gallery can hold up to 40 images")
    out["gallery"] = []
    for g in gallery:
        if int(g) not in media_ids:
            raise bad_request("A gallery image is not one of this hotel's website images")
        if int(g) not in out["gallery"]:
            out["gallery"].append(int(g))
    social = body.get("social") or {}
    for k in SOCIAL:
        v = str(social.get(k) or "").strip()
        if v and k == "whatsapp":
            if not re.fullmatch(r"\+?[0-9 ]{7,20}", v):
                raise bad_request("WhatsApp must be a phone number, e.g. +234 803 000 0000")
        elif v and not URL_RE.match(v):
            raise bad_request(f"The {k} link must start with https://")
        out["social"][k] = v[:300]
    m = str(body.get("map_url") or "").strip()
    if m and not URL_RE.match(m):
        raise bad_request("The map link must start with https:// (e.g. a Google Maps share link)")
    out["map_url"] = m[:500]
    text = body.get("text") or {}
    for lang in LANGS:
        src = text.get(lang) or {}
        dst: dict = {}
        for f, limit in TEXT_FIELDS.items():
            if f in src and src[f] is not None:
                dst[f] = _clean_text(src[f], limit, f"{f.replace('_', ' ')} ({lang})")
        hl = src.get("highlights")
        if hl is not None:
            if not isinstance(hl, list) or len(hl) > 6:
                raise bad_request("Up to 6 highlights")
            dst["highlights"] = [{"title": _clean_text(h.get("title"), 60, "highlight title"), "text": _clean_text(h.get("text"), 220, "highlight text")}
                                 for h in hl if isinstance(h, dict) and (h.get("title") or h.get("text"))]
        fac = src.get("facilities")
        if fac is not None:
            if not isinstance(fac, list) or len(fac) > 24:
                raise bad_request("Up to 24 facilities")
            dst["facilities"] = [_clean_text(x, 60, "facility") for x in fac if str(x or "").strip()]
        out["text"][lang] = dst if lang != "en" else {**out["text"]["en"], **dst}
    if not out["text"]["en"].get("hero_title"):
        raise bad_request("The English headline (hero title) is required")
    return out


def _hotel_for_site(c, code: str | None) -> dict:
    if code:
        h = c.one("SELECT * FROM hotels WHERE upper(code) = ? AND active = 1", [code.upper()])
    else:
        env = os.environ.get("EHMS_WEBSITE_HOTEL", "").strip()
        h = c.one("SELECT * FROM hotels WHERE upper(code) = ? AND active = 1", [env.upper()]) if env else None
        h = h or c.one("SELECT * FROM hotels WHERE active = 1 ORDER BY id")
    if not h:
        raise not_found("Hotel")
    return h


def site_payload(c, hotel: dict, content: dict, published_at=None) -> dict:
    """Everything the public site needs: content plus live hotel facts, rooms and image URLs."""
    from .booking import public_hotel_data
    pub = public_hotel_data(c, hotel)
    url = lambda mid: f"/api/public/website-media/{mid}" if mid else None  # noqa: E731
    captions = {m["id"]: m["caption"] for m in c.all("SELECT id, caption FROM website_media WHERE hotel_id = ?", [hotel["id"]])}
    others = c.all("SELECT code, name, city FROM hotels WHERE organisation_id = ? AND active = 1 AND id <> ? ORDER BY name", [hotel["organisation_id"], hotel["id"]])
    return {"hotel": {"id": hotel["id"], "code": hotel["code"], "name": hotel["name"], "address": hotel.get("address"), "city": hotel.get("city"),
                      "state": hotel.get("state"), "country": hotel.get("country"), "phone": hotel.get("phone"), "email": hotel.get("email"),
                      "star_rating": hotel.get("star_rating"), "check_in_time": hotel["check_in_time"], "check_out_time": hotel["check_out_time"],
                      "currency": hotel["currency"], "logo_url": pub.get("logo_url"), "cancellation_policy": hotel.get("cancellation_policy")},
            "content": content,
            "image_urls": {k: url(v) for k, v in content["images"].items()},
            "gallery": [{"id": g, "url": url(g), "caption": captions.get(g)} for g in content["gallery"] if g in captions],
            "rooms": [{"id": t["id"], "code": t["code"], "name": t["name"], "description": t["description"], "max_occupancy": t["max_occupancy"],
                       "beds": t["beds"], "bed_config": t["bed_config"], "size_sqm": t["size_sqm"], "amenities": t["amenities"], "from_rate": t["base_rate"],
                       "media": t.get("media", []), "image_url": t.get("image_url")} for t in pub["room_types"]],
            "other_hotels": others, "published_at": published_at, "booking_url": f"/#/book/{hotel['code']}"}


# ------------------------------------------------------------------ public
@route("GET", "/api/public/site", public=True, rate_limit=120, tag="website", summary="Published website of the main hotel (?hotel=CODE for another property)")
def public_site(ctx: Ctx):
    with get_db().tx() as c:
        hotel = _hotel_for_site(c, ctx.q("hotel"))
        row = _content_row(c, hotel["id"])
        content = _load(row["published"]) if row and row["published"] else default_content(hotel)
        return site_payload(c, hotel, content, row["published_at"] if row else None)


@route("GET", "/api/public/website-media/{media_id:int}", public=True, rate_limit=600, tag="website", summary="A website image")
def public_media(ctx: Ctx):
    from .media import media_dir
    with get_db().tx() as c:
        m = c.one("SELECT * FROM website_media WHERE id = ?", [ctx.path["media_id"]])
    if not m:
        raise not_found("Image")
    path = os.path.join(media_dir(), os.path.basename(m["filename"]))
    if not os.path.isfile(path):
        raise not_found("Image")
    with open(path, "rb") as fh:
        return Response(fh.read(), media_type=m["content_type"], headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"})


@route("POST", "/api/public/site/enquiries", public=True, rate_limit=5, tag="website",
       summary="Contact form: hotel (code, optional), kind general|rooms|dining|event, name, email, phone, subject, message, event_date, guests, marketing_consent")
def send_enquiry(ctx: Ctx):
    b = ctx.body or {}
    if str(b.get("website") or "").strip():          # honeypot field: real visitors never fill it
        return {"ok": True}
    kind = str(b.get("kind") or "general")
    if kind not in ("general", "rooms", "dining", "event"):
        raise bad_request("kind must be general, rooms, dining or event")
    name = str(b.get("name") or "").strip()
    email = str(b.get("email") or "").strip().lower()
    message = str(b.get("message") or "").strip()
    if not (2 <= len(name) <= 150):
        raise bad_request("Please enter your name")
    if not EMAIL_RE.match(email) or len(email) > 200:
        raise bad_request("Please enter a valid email address")
    if not (5 <= len(message) <= 3000):
        raise bad_request("Please write your message (5–3000 characters)")
    guests = b.get("guests")
    try:
        guests = int(guests) if guests not in (None, "") else None
    except (TypeError, ValueError):
        raise bad_request("guests must be a number")
    ev_date = str(b.get("event_date") or "").strip() or None
    if ev_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", ev_date):
        raise bad_request("event_date must be YYYY-MM-DD")
    with get_db().tx() as c:
        hotel = _hotel_for_site(c, b.get("hotel"))
        eid = c.insert("website_enquiries", {"hotel_id": hotel["id"], "kind": kind, "name": name, "email": email,
                                             "phone": str(b.get("phone") or "").strip()[:50] or None, "subject": str(b.get("subject") or "").strip()[:200] or None,
                                             "message": message, "event_date": ev_date, "guests": guests, "marketing_consent": 1 if b.get("marketing_consent") else 0,
                                             "status": "new", "ip": ctx.ip, "created_at": now_iso()})
        from ..worker import _users_with
        perm = "events.manage" if kind == "event" else "crm.complaints"
        for uid in _users_with(c, hotel["id"], perm) or _users_with(c, hotel["id"], "website.manage"):
            queue_notification(c, hotel["id"], "in_app", str(uid), f"Website enquiry from {name}", f"{label_kind(kind)}: {message[:160]}", "website_enquiry", eid)
        audit(c, None, "website.enquiry", "website_enquiry", eid, new={"kind": kind, "email": email, "ip": ctx.ip}, hotel_id=hotel["id"])
    return {"ok": True, "message": "Thank you — your message has been sent. We will reply soon.", "_created": True}


def label_kind(kind: str) -> str:
    return {"general": "General enquiry", "rooms": "Rooms", "dining": "Restaurant", "event": "Event enquiry"}[kind]


# ------------------------------------------------------------------ administration
def _can_see_enquiries(ctx: Ctx) -> bool:
    return any(ctx.can(p) for p in ("website.manage", "crm.view", "events.view"))


@route("GET", "/api/hotels/{hotel_id:int}/website", perm="website.manage", tag="website",
       summary="Website editor: draft and published content, images, status and the editable fields")
def get_website(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [hid])
        row = _content_row(c, hid)
        draft = _load(row["draft"]) if row else default_content(hotel)
        published = _load(row["published"]) if row and row["published"] else None
        media = c.all("SELECT m.*, u.full_name AS uploaded_by FROM website_media m JOIN users u ON u.id = m.created_by WHERE m.hotel_id = ? ORDER BY m.id DESC", [hid])
        for m in media:
            m["url"] = f"/api/public/website-media/{m['id']}"
        names = {u["id"]: u["full_name"] for u in c.all("SELECT id, full_name FROM users WHERE id IN (?, ?)",
                                                         [(row or {}).get("updated_by") or 0, (row or {}).get("published_by") or 0])}
        new_enquiries = c.scalar("SELECT COUNT(*) FROM website_enquiries WHERE hotel_id = ? AND status = 'new'", [hid])
    return {"draft": draft, "published": published, "media": media, "unpublished_changes": (row is None) or row["published"] != row["draft"],
            "updated_at": row["updated_at"] if row else None, "updated_by": names.get((row or {}).get("updated_by")),
            "published_at": row["published_at"] if row else None, "published_by": names.get((row or {}).get("published_by")),
            "fields": {"text": TEXT_FIELDS, "sections": SECTIONS, "images": IMAGE_SLOTS, "social": SOCIAL, "languages": LANGS},
            "new_enquiries": new_enquiries, "public_url": "/" if hid == _main_hotel_id() else f"/?hotel={hotel['code']}"}


def _main_hotel_id() -> int | None:
    with get_db().tx() as c:
        try:
            return _hotel_for_site(c, None)["id"]
        except ApiError:
            return None


@route("PUT", "/api/hotels/{hotel_id:int}/website", perm="website.manage", tag="website", summary="Save the website draft (content document; validated)")
def save_draft(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [hid])
        clean = validate(c, hid, ctx.field("content"), hotel)
        raw = json.dumps(clean, ensure_ascii=False, sort_keys=True)
        row = _content_row(c, hid)
        if row:
            c.update("website_content", row["id"], {"draft": raw, "updated_by": ctx.user_id, "updated_at": now_iso()})
        else:
            c.insert("website_content", {"hotel_id": hid, "draft": raw, "updated_by": ctx.user_id, "updated_at": now_iso()})
        audit(c, ctx, "website.draft_saved", "website", hid, hotel_id=hid)
    return {"saved": True, "content": clean, "unpublished_changes": True if not row else row.get("published") != raw}


@route("POST", "/api/hotels/{hotel_id:int}/website/publish", perm="website.manage", tag="website", summary="Publish the saved draft to the public website")
def publish(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        row = _content_row(c, hid)
        if not row:
            hotel = c.one("SELECT * FROM hotels WHERE id = ?", [hid])
            raw = json.dumps(default_content(hotel), ensure_ascii=False, sort_keys=True)
            rid = c.insert("website_content", {"hotel_id": hid, "draft": raw, "updated_by": ctx.user_id, "updated_at": now_iso()})
            row = c.one("SELECT * FROM website_content WHERE id = ?", [rid])
        old = row["published"]
        c.update("website_content", row["id"], {"published": row["draft"], "published_by": ctx.user_id, "published_at": now_iso()})
        audit(c, ctx, "website.published", "website", hid, old={"had_published": bool(old)}, new={"published_at": now_iso()}, hotel_id=hid)
    return {"published": True}


@route("POST", "/api/hotels/{hotel_id:int}/website/discard", perm="website.manage", tag="website", summary="Throw away unpublished changes (draft goes back to the published version)")
def discard(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        row = _content_row(c, hid)
        if not row or not row["published"]:
            raise conflict("Nothing has been published yet")
        c.update("website_content", row["id"], {"draft": row["published"], "updated_by": ctx.user_id, "updated_at": now_iso()})
        audit(c, ctx, "website.draft_discarded", "website", hid, hotel_id=hid)
    return {"discarded": True}


@route("POST", "/api/hotels/{hotel_id:int}/website/preview", perm="website.manage", tag="website",
       summary="What the public site would look like with this content (not saved)")
def preview(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [hid])
        clean = validate(c, hid, ctx.field("content"), hotel)
        return {**site_payload(c, hotel, clean), "preview": True}


@route("POST", "/api/hotels/{hotel_id:int}/website/media", perm="website.manage", tag="website",
       summary="Upload a website image: filename, content_base64 (JPEG/PNG/WebP up to 5 MB), caption")
def upload_media(ctx: Ctx):
    from .media import media_dir
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    name = str(ctx.field("filename", kind=str))
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in IMAGE_TYPES:
        raise bad_request("Images must be JPEG, PNG or WebP")
    try:
        data = base64.b64decode(str(ctx.field("content_base64", kind=str)), validate=True)
    except (binascii.Error, ValueError):
        raise bad_request("content_base64 is not valid base64")
    ctype, sig = IMAGE_TYPES[ext]
    if not data.startswith(sig) or (ext == "webp" and data[8:12] != b"WEBP"):
        raise bad_request("The file content is not a valid image of that type")
    if len(data) > MAX_IMAGE:
        raise ApiError(413, "file_too_large", "Images must be 5 MB or smaller")
    with get_db().tx() as c:
        if c.scalar("SELECT COUNT(*) FROM website_media WHERE hotel_id = ?", [hid]) >= 200:
            raise bad_request("The website can hold up to 200 images; remove some first")
        stored = f"site-h{hid}-{secrets.token_hex(8)}.{'jpg' if ext == 'jpeg' else ext}"
        with open(os.path.join(media_dir(), stored), "wb") as fh:
            fh.write(data)
        mid = c.insert("website_media", {"hotel_id": hid, "filename": stored, "content_type": ctype,
                                         "caption": (ctx.field("caption", required=False, kind=str) or "")[:150] or None, "size_bytes": len(data),
                                         "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "website.image_added", "website_media", mid, new={"size": len(data)}, hotel_id=hid)
    return {"id": mid, "url": f"/api/public/website-media/{mid}", "_created": True}


@route("PATCH", "/api/website/media/{media_id:int}", perm="website.manage", tag="website", summary="Change an image's caption")
def caption_media(ctx: Ctx):
    with get_db().tx() as c:
        m = c.one("SELECT * FROM website_media WHERE id = ?", [ctx.path["media_id"]])
        if not m:
            raise not_found("Image")
        ctx.check_hotel(m["hotel_id"])
        c.update("website_media", m["id"], {"caption": (ctx.field("caption", required=False, kind=str) or "")[:150] or None})
    return {"ok": True}


@route("DELETE", "/api/website/media/{media_id:int}", perm="website.manage", tag="website",
       summary="Remove an image (refused while the published website or the draft uses it)")
def delete_media(ctx: Ctx):
    from .media import media_dir
    with get_db().tx() as c:
        m = c.one("SELECT * FROM website_media WHERE id = ?", [ctx.path["media_id"]])
        if not m:
            raise not_found("Image")
        ctx.check_hotel(m["hotel_id"])
        row = _content_row(c, m["hotel_id"])
        for which in ("draft", "published"):
            doc = _load(row[which]) if row and row[which] else None
            if doc and (m["id"] in doc["gallery"] or m["id"] in doc["images"].values()):
                raise conflict(f"This image is used by the {'published website' if which == 'published' else 'draft'}; remove it there first")
        c.execute("DELETE FROM website_media WHERE id = ?", [m["id"]])
        audit(c, ctx, "website.image_removed", "website_media", m["id"], hotel_id=m["hotel_id"])
    try:
        os.remove(os.path.join(media_dir(), os.path.basename(m["filename"])))
    except OSError:
        pass
    return {"ok": True}


@route("GET", "/api/hotels/{hotel_id:int}/website/enquiries", tag="website", summary="Enquiries sent from the website (?status)")
def list_enquiries(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    if not _can_see_enquiries(ctx):
        raise forbidden("Website enquiries need website, guest relations or events access")
    sql, params = "SELECT e.*, u.full_name AS handled_by_name FROM website_enquiries e LEFT JOIN users u ON u.id = e.handled_by WHERE e.hotel_id = ?", [hid]
    if not (ctx.can("website.manage") or ctx.can("crm.view")):
        sql += " AND e.kind = 'event'"        # events staff see event enquiries only
    if ctx.q("status"):
        sql += " AND e.status = ?"
        params.append(ctx.q("status"))
    with get_db().tx() as c:
        return {"items": c.all(sql + " ORDER BY e.id DESC LIMIT 300", params)}


@route("POST", "/api/website/enquiries/{enquiry_id:int}/status", tag="website", summary="Record handling of an enquiry: status replied | closed | spam, note")
def enquiry_status(ctx: Ctx):
    status = ctx.field("status", kind=str)
    if status not in ("replied", "closed", "spam", "new"):
        raise bad_request("status must be new, replied, closed or spam")
    if not _can_see_enquiries(ctx):
        raise forbidden("Website enquiries need website, guest relations or events access")
    with get_db().tx() as c:
        e = c.one("SELECT * FROM website_enquiries WHERE id = ?", [ctx.path["enquiry_id"]])
        if not e:
            raise not_found("Enquiry")
        ctx.check_hotel(e["hotel_id"])
        if e["kind"] != "event" and not (ctx.can("website.manage") or ctx.can("crm.view")):
            raise forbidden("Only event enquiries are open to events staff")
        c.update("website_enquiries", e["id"], {"status": status, "note": (ctx.field("note", required=False, kind=str) or "")[:500] or e["note"],
                                                "handled_by": ctx.user_id, "handled_at": now_iso()})
        audit(c, ctx, f"website.enquiry_{status}", "website_enquiry", e["id"], old={"status": e["status"]}, new={"status": status}, hotel_id=e["hotel_id"])
    return {"status": status}


def seo_for_index() -> tuple[str, str, str] | None:
    """(title, description, lang) of the main hotel's published site, for the page <head>; None if unavailable."""
    try:
        with get_db().tx() as c:
            hotel = _hotel_for_site(c, None)
            row = _content_row(c, hotel["id"])
            content = _load(row["published"]) if row and row["published"] else default_content(hotel)
    except Exception:
        return None
    en = content["text"]["en"]
    return en.get("seo_title") or hotel["name"], en.get("seo_description") or "", hotel["name"]

