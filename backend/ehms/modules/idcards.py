"""Staff ID cards (release 1.4).

Every employee gets an ID card automatically: registering an employee (directly or by hiring an applicant from
recruitment) puts a card in HR's print queue. HR adds the staff photo, prints the queue on an A4 sheet (10 cards, front
and back pages for duplex printing) or on a PVC card printer (CR80 size), hands the card over, and reissues it when
the person's name, position or department changes, or when a card is lost or damaged. Cards are revoked automatically
when someone leaves.

Each card carries a random verification token printed as a QR code. Scanning it opens /verify/staff/<token>, which
shows whether the card is valid now (printed or issued, not revoked, not expired, and the person still employed),
with the name, photo, position and hotel, so security staff and partners can check a card at the gate.
"""
from __future__ import annotations

import base64
import binascii
import datetime as dt
import io
import os
import re
import secrets

from starlette.responses import Response

from ..db import get_db, now_iso
from ..http import ApiError, Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import business_date, get_hotel, hotel_setting, set_hotel_setting

REASONS = ("new_hire", "details_changed", "lost", "damaged", "renewal", "other")
REASON_LABELS = {"new_hire": "New employee", "details_changed": "Details changed", "lost": "Lost card", "damaged": "Damaged card",
                 "renewal": "Renewal", "other": "Other"}
STATUSES = ("pending", "printed", "issued", "revoked")
PHOTO_TYPES = {"jpg": ("image/jpeg", b"\xff\xd8\xff"), "jpeg": ("image/jpeg", b"\xff\xd8\xff"), "png": ("image/png", b"\x89PNG"),
               "webp": ("image/webp", b"RIFF")}
MAX_PHOTO = 5 * 1024 * 1024
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
CARD_W_MM, CARD_H_MM = 85.6, 53.98          # ISO/IEC 7810 ID-1 (CR80), the size of a bank card


# ------------------------------------------------------------------ settings and helpers
def card_settings(c, hid: int) -> dict:
    hotel = get_hotel(c, hid)
    years = hotel_setting(c, hid, "idcards.valid_years") or "2"
    colour = hotel_setting(c, hid, "idcards.colour") or "#0F1F3D"
    note = hotel_setting(c, hid, "idcards.back_note") or ""
    return {"valid_years": int(years), "colour": colour, "back_note": note,
            "default_back_note": f"This card is the property of {hotel['name']}. It must be worn on duty and returned when you leave. "
                                 f"If found, please return it to the hotel{(' or call ' + hotel['phone']) if hotel.get('phone') else ''}."}


def _photo_dir() -> str:
    from .documents import storage_dir
    d = os.path.join(storage_dir(), "staff-photos")
    os.makedirs(d, exist_ok=True)
    return d


def _photo_path(e: dict) -> str | None:
    if not e.get("photo_filename"):
        return None
    p = os.path.join(_photo_dir(), os.path.basename(e["photo_filename"]))
    return p if os.path.isfile(p) else None


def _expiry(c, e: dict, start: dt.date) -> dt.date:
    years = card_settings(c, e["hotel_id"])["valid_years"]
    try:
        exp = start.replace(year=start.year + years)
    except ValueError:  # 29 February
        exp = start.replace(year=start.year + years, day=28)
    end = e.get("contract_end_date")
    if end and e.get("employment_type") in ("contract", "intern", "casual"):
        end = dt.date.fromisoformat(str(end)[:10])
        if start < end < exp:
            exp = end
    return exp


def generate_card(c, employee_id: int, reason: str, user_id: int | None) -> dict:
    """Queue a new card for printing. Called automatically for new employees and when card details change."""
    e = c.one("SELECT * FROM employees WHERE id = ?", [employee_id])
    version = (c.scalar("SELECT COALESCE(MAX(version), 0) FROM staff_id_cards WHERE employee_id = ?", [e["id"]]) or 0) + 1
    today = business_date(get_hotel(c, e["hotel_id"]))
    row = {"hotel_id": e["hotel_id"], "employee_id": e["id"], "card_no": f"{e['employee_no']}-{version:02d}", "version": version, "reason": reason,
           "status": "pending", "verify_token": secrets.token_urlsafe(24), "expiry_date": _expiry(c, e, today).isoformat(),
           "created_by": user_id, "created_at": now_iso()}
    row["id"] = c.insert("staff_id_cards", row)
    return row


def revoke_cards(c, employee_id: int, reason: str, user_id: int | None, keep_id: int | None = None) -> int:
    rows = c.all("SELECT id FROM staff_id_cards WHERE employee_id = ? AND status <> 'revoked'" + (" AND id <> ?" if keep_id else ""),
                 [employee_id] + ([keep_id] if keep_id else []))
    for r in rows:
        c.update("staff_id_cards", r["id"], {"status": "revoked", "revoked_at": now_iso(), "revoked_by": user_id, "revoke_reason": reason[:200]})
    return len(rows)


def on_employee_changed(c, before: dict, after: dict, user_id: int | None) -> None:
    """Hook from the employee update: revoke on exit, queue a replacement when printed details change."""
    if after["status"] in ("terminated", "resigned", "retired") and before["status"] != after["status"]:
        revoke_cards(c, after["id"], f"Left employment ({after['status']})", user_id)
        return
    if after["status"] != "active":
        return
    changed = [k for k in ("first_name", "last_name", "position", "department") if before.get(k) != after.get(k)]
    if not changed:
        return
    if c.one("SELECT id FROM staff_id_cards WHERE employee_id = ? AND status = 'pending'", [after["id"]]):
        return  # the queued card prints the current details anyway
    if c.one("SELECT id FROM staff_id_cards WHERE employee_id = ? AND status IN ('printed','issued')", [after["id"]]):
        generate_card(c, after["id"], "details_changed", user_id)


def _card(c, ctx: Ctx, card_id) -> dict:
    r = c.one("SELECT * FROM staff_id_cards WHERE id = ?", [int(card_id)])
    if not r:
        raise not_found("ID card")
    ctx.check_hotel(r["hotel_id"])
    return r


def _employee(c, ctx: Ctx, eid) -> dict:
    e = c.one("SELECT * FROM employees WHERE id = ?", [int(eid)])
    if not e:
        raise not_found("Employee")
    ctx.check_hotel(e["hotel_id"])
    return e


def verify_url(token: str, request=None) -> str:
    base = os.environ.get("EHMS_PUBLIC_URL", "").rstrip("/")
    if not base and request is not None:
        base = str(request.base_url).rstrip("/")
    return f"{base}/verify/staff/{token}"


def card_state(card: dict, employee: dict, today: dt.date) -> tuple[bool, str]:
    if card["status"] == "revoked":
        return False, "This card has been cancelled" + (f": {card['revoke_reason']}" if card.get("revoke_reason") else "")
    if card["status"] == "pending":
        return False, "This card has not been issued yet"
    if employee["status"] != "active":
        return False, "This person is not currently on duty with the hotel"
    if dt.date.fromisoformat(str(card["expiry_date"])[:10]) < today:
        return False, "This card has expired"
    return True, "Valid staff ID card"


# ------------------------------------------------------------------ queue and settings
@route("GET", "/api/hotels/{hotel_id:int}/id-cards", perm="hr.id_cards", tag="hr",
       summary="Staff ID cards: print queue and register (?status pending|printed|issued|revoked, ?q name or staff number)")
def list_cards(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    status = ctx.query.get("status") or ""
    q = (ctx.query.get("q") or "").strip().lower()
    sql = ("SELECT k.*, e.employee_no, e.first_name, e.last_name, e.department, e.position, e.status AS employee_status, "
           "e.photo_filename IS NOT NULL AS has_photo FROM staff_id_cards k JOIN employees e ON e.id = k.employee_id WHERE k.hotel_id = ?")
    params: list = [hid]
    if status:
        if status not in STATUSES:
            raise bad_request(f"status must be one of {', '.join(STATUSES)}")
        sql += " AND k.status = ?"
        params.append(status)
    if q:
        sql += " AND (LOWER(e.first_name) LIKE ? OR LOWER(e.last_name) LIKE ? OR LOWER(e.employee_no) LIKE ? OR LOWER(k.card_no) LIKE ?)"
        params += [f"%{q}%"] * 4
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY CASE k.status WHEN 'pending' THEN 0 WHEN 'printed' THEN 1 WHEN 'issued' THEN 2 ELSE 3 END, k.created_at DESC LIMIT 500", params)
        counts = {r["status"]: r["n"] for r in c.all("SELECT status, COUNT(*) AS n FROM staff_id_cards WHERE hotel_id = ? GROUP BY status", [hid])}
        without = c.scalar("SELECT COUNT(*) FROM employees WHERE hotel_id = ? AND status = 'active' AND id NOT IN "
                           "(SELECT employee_id FROM staff_id_cards WHERE status <> 'revoked')", [hid])
        settings = card_settings(c, hid)
    for r in rows:
        r["has_photo"] = bool(r["has_photo"])
        r["reason_label"] = REASON_LABELS.get(r["reason"], r["reason"])
        r.pop("verify_token", None)
    return {"items": rows, "counts": {s: counts.get(s, 0) for s in STATUSES}, "active_without_card": without, "settings": settings,
            "reasons": [{"code": k, "label": v} for k, v in REASON_LABELS.items() if k != "new_hire"]}


@route("PUT", "/api/hotels/{hotel_id:int}/id-cards/settings", perm="hr.id_cards", tag="hr",
       summary="Card design: valid_years (1-10), colour (#RRGGBB), back_note (text on the back; empty = standard wording)")
def save_settings(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    b = ctx.body or {}
    with get_db().tx() as c:
        if "valid_years" in b:
            y = int(ctx.field("valid_years"))
            if not 1 <= y <= 10:
                raise bad_request("Cards can be valid for 1 to 10 years")
            set_hotel_setting(c, hid, "idcards.valid_years", str(y))
        if "colour" in b:
            col = str(b["colour"] or "").strip()
            if not HEX_RE.match(col):
                raise bad_request("The colour must be a hex code such as #0F1F3D")
            set_hotel_setting(c, hid, "idcards.colour", col.upper())
        if "back_note" in b:
            note = str(b["back_note"] or "").strip()
            if len(note) > 300:
                raise bad_request("The back text can be at most 300 characters")
            set_hotel_setting(c, hid, "idcards.back_note", note)
        audit(c, ctx, "hr.id_card_settings", "hotel", hid, new={k: b[k] for k in ("valid_years", "colour", "back_note") if k in b}, hotel_id=hid)
        return card_settings(c, hid)


@route("POST", "/api/hotels/{hotel_id:int}/id-cards/generate-missing", perm="hr.id_cards", tag="hr",
       summary="Queue a card for every active employee who has none (first roll-out of ID cards)")
def generate_missing(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        ids = [r["id"] for r in c.all("SELECT id FROM employees WHERE hotel_id = ? AND status = 'active' AND id NOT IN "
                                      "(SELECT employee_id FROM staff_id_cards WHERE status <> 'revoked') ORDER BY id", [hid])]
        for eid in ids:
            generate_card(c, eid, "new_hire", ctx.user_id)
        audit(c, ctx, "hr.id_cards_generated", "hotel", hid, new={"count": len(ids)}, hotel_id=hid)
    return {"created": len(ids)}


@route("POST", "/api/employees/{employee_id:int}/id-cards", perm="hr.id_cards", tag="hr",
       summary="Request a replacement card: reason lost|damaged|renewal|details_changed|other, note. Lost and damaged cards are cancelled at once")
def request_card(ctx: Ctx):
    reason = ctx.field("reason", kind=str)
    if reason not in REASONS or reason == "new_hire":
        raise bad_request("reason must be lost, damaged, renewal, details_changed or other")
    note = (ctx.field("note", required=False, kind=str) or "").strip()
    with get_db().tx() as c:
        e = _employee(c, ctx, ctx.path["employee_id"])
        if e["status"] != "active":
            raise conflict("Cards are only issued to active employees")
        if c.one("SELECT id FROM staff_id_cards WHERE employee_id = ? AND status = 'pending'", [e["id"]]):
            raise conflict("A card for this employee is already waiting to be printed")
        if reason in ("lost", "damaged"):
            revoke_cards(c, e["id"], f"{REASON_LABELS[reason]}{(': ' + note) if note else ''}", ctx.user_id)
        card = generate_card(c, e["id"], reason, ctx.user_id)
        audit(c, ctx, "hr.id_card_requested", "staff_id_card", card["id"], card["card_no"], new={"reason": reason, "note": note or None}, hotel_id=e["hotel_id"])
    return {"id": card["id"], "card_no": card["card_no"], "_created": True}


@route("POST", "/api/id-cards/{card_id:int}/issue", perm="hr.id_cards", tag="hr",
       summary="Record that a printed card was handed to the employee; earlier cards of that person are cancelled")
def issue_card(ctx: Ctx):
    with get_db().tx() as c:
        k = _card(c, ctx, ctx.path["card_id"])
        if k["status"] != "printed":
            raise conflict("Only a printed card can be handed over" if k["status"] == "pending" else f"This card is already {k['status']}")
        c.update("staff_id_cards", k["id"], {"status": "issued", "issued_at": now_iso(), "issued_by": ctx.user_id})
        replaced = revoke_cards(c, k["employee_id"], f"Replaced by card {k['card_no']}", ctx.user_id, keep_id=k["id"])
        audit(c, ctx, "hr.id_card_issued", "staff_id_card", k["id"], k["card_no"], new={"replaced": replaced}, hotel_id=k["hotel_id"])
    return {"status": "issued", "replaced": replaced}


@route("POST", "/api/id-cards/{card_id:int}/revoke", perm="hr.id_cards", tag="hr", summary="Cancel a card (reason required); scanning it then shows it is not valid")
def revoke_card(ctx: Ctx):
    reason = (ctx.field("reason", kind=str) or "").strip()
    if not reason:
        raise bad_request("Give the reason for cancelling the card")
    with get_db().tx() as c:
        k = _card(c, ctx, ctx.path["card_id"])
        if k["status"] == "revoked":
            raise conflict("This card is already cancelled")
        c.update("staff_id_cards", k["id"], {"status": "revoked", "revoked_at": now_iso(), "revoked_by": ctx.user_id, "revoke_reason": reason[:200]})
        audit(c, ctx, "hr.id_card_revoked", "staff_id_card", k["id"], k["card_no"], new={"reason": reason}, hotel_id=k["hotel_id"])
    return {"status": "revoked"}


# ------------------------------------------------------------------ staff photo
@route("POST", "/api/employees/{employee_id:int}/photo", perm="hr.view", tag="hr",
       summary="Upload the staff photo for the ID card: filename, content_base64 (JPEG/PNG/WebP, up to 5 MB); needs hr.manage or hr.id_cards")
def upload_photo(ctx: Ctx):
    if not (ctx.can("hr.manage") or ctx.can("hr.id_cards")):
        raise forbidden("You need permission to manage employees or ID cards")
    name = str(ctx.field("filename", kind=str))
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in PHOTO_TYPES:
        raise bad_request("The photo must be JPEG, PNG or WebP")
    try:
        data = base64.b64decode(str(ctx.field("content_base64", kind=str)), validate=True)
    except (binascii.Error, ValueError):
        raise bad_request("content_base64 is not valid base64")
    ctype, sig = PHOTO_TYPES[ext]
    if not data.startswith(sig) or (ext == "webp" and data[8:12] != b"WEBP"):
        raise bad_request("The file content is not a valid image of that type")
    if len(data) > MAX_PHOTO:
        raise ApiError(413, "file_too_large", "The photo must be 5 MB or smaller")
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except Exception:
        raise bad_request("The image could not be read; take or export the photo again")
    with get_db().tx() as c:
        e = _employee(c, ctx, ctx.path["employee_id"])
        stored = f"emp{e['id']}-{secrets.token_hex(8)}.{'jpg' if ext == 'jpeg' else ext}"
        with open(os.path.join(_photo_dir(), stored), "wb") as fh:
            fh.write(data)
        old = _photo_path(e)
        c.update("employees", e["id"], {"photo_filename": stored, "photo_content_type": ctype})
        audit(c, ctx, "hr.photo_uploaded", "employee", e["id"], e["employee_no"], hotel_id=e["hotel_id"])
    if old:
        try:
            os.remove(old)
        except OSError:
            pass
    return {"ok": True}


def _photo_response(e: dict, cache: str) -> Response:
    p = _photo_path(e)
    if not p:
        raise not_found("Photo")
    with open(p, "rb") as fh:
        return Response(fh.read(), media_type=e["photo_content_type"] or "image/jpeg",
                        headers={"Cache-Control": cache, "X-Content-Type-Options": "nosniff"})


@route("GET", "/api/employees/{employee_id:int}/photo", perm="hr.view", tag="hr", summary="The staff photo")
def get_photo(ctx: Ctx):
    with get_db().tx() as c:
        e = _employee(c, ctx, ctx.path["employee_id"])
    return _photo_response(e, "private, no-cache")


# ------------------------------------------------------------------ public verification (QR code on the card)
def verify_token(token: str) -> dict | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,48}", token or ""):
        return None
    with get_db().tx() as c:
        k = c.one("SELECT * FROM staff_id_cards WHERE verify_token = ?", [token])
        if not k:
            return None
        e = c.one("SELECT * FROM employees WHERE id = ?", [k["employee_id"]])
        hotel = get_hotel(c, k["hotel_id"])
        valid, text = card_state(k, e, business_date(hotel))
    return {"valid": valid, "message": text, "name": f"{e['first_name']} {e['last_name']}", "position": e["position"],
            "department": e["department"].replace("_", " ").title(), "hotel": hotel["name"], "card_no": k["card_no"],
            "expiry_date": str(k["expiry_date"])[:10], "has_photo": bool(e.get("photo_filename")) and valid}


@route("GET", "/api/public/staff-cards/{token}", public=True, rate_limit=30, tag="hr", summary="Check a staff ID card from its QR code")
def public_verify(ctx: Ctx):
    out = verify_token(ctx.path["token"])
    if not out:
        raise not_found("Card")
    out["photo_url"] = f"/api/public/staff-cards/{ctx.path['token']}/photo" if out.pop("has_photo") else None
    return out


@route("GET", "/api/public/staff-cards/{token}/photo", public=True, rate_limit=30, tag="hr", summary="Photo of the holder of a valid staff card")
def public_photo(ctx: Ctx):
    token = ctx.path["token"]
    out = verify_token(token)
    if not out or not out["valid"]:
        raise not_found("Photo")
    with get_db().tx() as c:
        e = c.one("SELECT e.* FROM employees e JOIN staff_id_cards k ON k.employee_id = e.id WHERE k.verify_token = ?", [token])
    return _photo_response(e, "private, max-age=300")


# ------------------------------------------------------------------ printing
@route("GET", "/api/hotels/{hotel_id:int}/id-cards/print", perm="hr.id_cards", tag="hr",
       summary="Print cards as PDF (?ids=1,2,3 or ?status=pending; ?layout=a4 (10 per sheet, fronts then backs for duplex) | card (one CR80 card per page, for card printers)); marks them printed")
def print_cards(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    layout = ctx.query.get("layout") or "a4"
    if layout not in ("a4", "card"):
        raise bad_request("layout must be a4 or card")
    ids_raw = ctx.query.get("ids") or ""
    with get_db().tx() as c:
        if ids_raw:
            try:
                ids = [int(x) for x in ids_raw.split(",") if x.strip()][:200]
            except ValueError:
                raise bad_request("ids must be a comma-separated list of card ids")
            cards = c.all(f"SELECT * FROM staff_id_cards WHERE hotel_id = ? AND id IN ({','.join('?' * len(ids))}) ORDER BY id", [hid] + ids) if ids else []
        else:
            cards = c.all("SELECT * FROM staff_id_cards WHERE hotel_id = ? AND status = 'pending' ORDER BY id LIMIT 200", [hid])
        cards = [k for k in cards if k["status"] != "revoked"]
        if not cards:
            raise bad_request("No cards to print (cancelled cards cannot be printed)")
        hotel = get_hotel(c, hid)
        settings = card_settings(c, hid)
        emps = {k["employee_id"]: c.one("SELECT * FROM employees WHERE id = ?", [k["employee_id"]]) for k in cards}
        logo = hotel_setting(c, hid, "hotel.logo")
        today = business_date(hotel).isoformat()
        for k in cards:
            upd = {"print_count": (k["print_count"] or 0) + 1, "printed_at": now_iso(), "printed_by": ctx.user_id}
            if k["status"] == "pending":
                upd["status"] = "printed"
            if not k["issue_date"]:
                upd["issue_date"] = today
                k["issue_date"] = today
            c.update("staff_id_cards", k["id"], upd)
        audit(c, ctx, "hr.id_cards_printed", "hotel", hid, new={"cards": [k["card_no"] for k in cards], "layout": layout}, hotel_id=hid)
    logo_path = None
    if logo:
        from .media import media_dir
        p = os.path.join(media_dir(), os.path.basename(logo.split("|")[0]))
        logo_path = p if os.path.isfile(p) else None
    pdf = render_pdf(cards, emps, hotel, settings, logo_path, layout, ctx.request)
    name = f"staff-id-cards-{today}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


def _rgb(hexcode: str):
    from reportlab.lib.colors import Color
    h = hexcode.lstrip("#")
    return Color(int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


def _fit_photo(path: str):
    from PIL import Image, ImageOps
    from reportlab.lib.utils import ImageReader
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im = ImageOps.fit(im, (330, 413), Image.LANCZOS, centering=(0.5, 0.35))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
    buf.seek(0)
    return ImageReader(buf)


def _draw_front(cv, x, y, k, e, hotel, settings, logo_path):
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.units import mm
    from reportlab.lib.utils import simpleSplit
    W, H = CARD_W_MM * mm, CARD_H_MM * mm
    col = _rgb(settings["colour"])
    cv.saveState()
    cv.setStrokeColor(HexColor("#BBBBBB"))
    cv.setLineWidth(0.3)
    cv.roundRect(x, y, W, H, 3 * mm, stroke=1, fill=0)
    # header band
    p = cv.beginPath()
    p.roundRect(x, y, W, H, 3 * mm)
    cv.clipPath(p, stroke=0, fill=0)
    cv.setFillColor(col)
    cv.rect(x, y + H - 12 * mm, W, 12 * mm, stroke=0, fill=1)
    cv.rect(x, y, W, 4.2 * mm, stroke=0, fill=1)
    tx = x + 4 * mm
    if logo_path:
        try:
            from reportlab.lib.utils import ImageReader
            cv.drawImage(ImageReader(logo_path), x + 3 * mm, y + H - 10.5 * mm, 9 * mm, 9 * mm, preserveAspectRatio=True, mask="auto")
            tx = x + 14 * mm
        except Exception:
            pass
    cv.setFillColor(white)
    name_lines = simpleSplit(hotel["name"], "Helvetica-Bold", 9, W - (tx - x) - 4 * mm)[:2]
    ty = y + H - (5.2 if len(name_lines) == 1 else 4.6) * mm
    for line in name_lines:
        cv.setFont("Helvetica-Bold", 9 if len(name_lines) == 1 else 8)
        cv.drawString(tx, ty, line)
        ty -= 3.4 * mm
    if len(name_lines) == 1:
        cv.setFont("Helvetica", 6.5)
        cv.drawString(tx, y + H - 9.2 * mm, "STAFF IDENTITY CARD")
    cv.setFont("Helvetica-Bold", 6.5)
    cv.drawString(x + 4 * mm, y + 1.4 * mm, k["card_no"])
    cv.drawRightString(x + W - 4 * mm, y + 1.4 * mm, "STAFF")
    # photo
    px, py, pw, ph = x + 4 * mm, y + 8.5 * mm, 22 * mm, 27.5 * mm
    cv.setFillColor(HexColor("#EEF0F3"))
    cv.rect(px, py, pw, ph, stroke=0, fill=1)
    path = _photo_path(e)
    if path:
        try:
            cv.drawImage(_fit_photo(path), px, py, pw, ph)
        except Exception:
            path = None
    if not path:
        cv.setFillColor(HexColor("#8A94A6"))
        cv.setFont("Helvetica", 6.5)
        cv.drawCentredString(px + pw / 2, py + ph / 2, "PHOTO")
    # details
    dx, dw = x + 29.5 * mm, W - 33.5 * mm
    yy = y + H - 17 * mm
    cv.setFillColor(HexColor("#111827"))
    for i, line in enumerate(simpleSplit(f"{e['first_name']} {e['last_name']}".upper(), "Helvetica-Bold", 9.5, dw)[:2]):
        cv.setFont("Helvetica-Bold", 9.5)
        cv.drawString(dx, yy, line)
        yy -= 4 * mm
    cv.setFillColor(col)
    cv.setFont("Helvetica-Bold", 7.5)
    for line in simpleSplit(e["position"], "Helvetica-Bold", 7.5, dw)[:2]:
        cv.drawString(dx, yy, line)
        yy -= 3.3 * mm
    cv.setFillColor(HexColor("#4B5563"))
    cv.setFont("Helvetica", 6.8)
    cv.drawString(dx, yy, e["department"].replace("_", " ").title())
    yy -= 4.6 * mm
    for label, value in (("Staff No.", e["employee_no"]), ("Issued", str(k["issue_date"] or "")[:10]), ("Expires", str(k["expiry_date"])[:10])):
        cv.setFont("Helvetica", 6.2)
        cv.setFillColor(HexColor("#6B7280"))
        cv.drawString(dx, yy, label)
        cv.setFont("Helvetica-Bold", 6.8)
        cv.setFillColor(HexColor("#111827"))
        cv.drawString(dx + 13 * mm, yy, value)
        yy -= 3.3 * mm
    cv.restoreState()


def _draw_back(cv, x, y, k, e, hotel, settings, request):
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib.colors import HexColor
    from reportlab.lib.units import mm
    from reportlab.lib.utils import simpleSplit
    W, H = CARD_W_MM * mm, CARD_H_MM * mm
    col = _rgb(settings["colour"])
    cv.saveState()
    cv.setStrokeColor(HexColor("#BBBBBB"))
    cv.setLineWidth(0.3)
    cv.roundRect(x, y, W, H, 3 * mm, stroke=1, fill=0)
    p = cv.beginPath()
    p.roundRect(x, y, W, H, 3 * mm)
    cv.clipPath(p, stroke=0, fill=0)
    cv.setFillColor(col)
    cv.rect(x, y + H - 3 * mm, W, 3 * mm, stroke=0, fill=1)
    # QR code
    size = 25 * mm
    qr = QrCodeWidget(verify_url(k["verify_token"], request), barLevel="M")
    b = qr.getBounds()
    d = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0])
    d.add(qr)
    renderPDF.draw(d, cv, x + W - size - 3.5 * mm, y + H - size - 6 * mm)
    cv.setFillColor(HexColor("#4B5563"))
    cv.setFont("Helvetica", 5.6)
    cv.drawCentredString(x + W - size / 2 - 3.5 * mm, y + H - size - 8 * mm, "Scan to verify this card")
    # text
    tw = W - size - 11 * mm
    yy = y + H - 8 * mm
    cv.setFillColor(HexColor("#111827"))
    cv.setFont("Helvetica-Bold", 7)
    cv.drawString(x + 4 * mm, yy, hotel["name"][:42])
    yy -= 3.6 * mm
    cv.setFont("Helvetica", 6)
    cv.setFillColor(HexColor("#4B5563"))
    for line in simpleSplit(", ".join(v for v in (hotel.get("address"), hotel.get("city")) if v), "Helvetica", 6, tw)[:2]:
        cv.drawString(x + 4 * mm, yy, line)
        yy -= 2.9 * mm
    if hotel.get("phone"):
        cv.drawString(x + 4 * mm, yy, f"Tel: {hotel['phone']}")
        yy -= 2.9 * mm
    yy -= 1.2 * mm
    cv.setFillColor(HexColor("#111827"))
    note = settings["back_note"] or settings["default_back_note"]
    for line in simpleSplit(note, "Helvetica", 5.8, tw)[:6]:
        cv.drawString(x + 4 * mm, yy, line)
        yy -= 2.8 * mm
    if e.get("blood_group"):
        cv.setFont("Helvetica-Bold", 6.2)
        cv.drawString(x + 4 * mm, yy - 0.6 * mm, f"Blood group: {e['blood_group']}")
    # signature
    cv.setStrokeColor(HexColor("#9CA3AF"))
    cv.line(x + 4 * mm, y + 7 * mm, x + 4 * mm + tw * 0.75, y + 7 * mm)
    cv.setFont("Helvetica", 5.4)
    cv.setFillColor(HexColor("#6B7280"))
    cv.drawString(x + 4 * mm, y + 4.6 * mm, "Authorised signature (Human Resources)")
    cv.drawRightString(x + W - 3.5 * mm, y + 4.6 * mm, k["card_no"])
    cv.restoreState()


def render_pdf(cards, emps, hotel, settings, logo_path, layout, request=None) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    W, H = CARD_W_MM * mm, CARD_H_MM * mm
    if layout == "card":
        cv = canvas.Canvas(buf, pagesize=(W, H))
        cv.setTitle(f"Staff ID cards — {hotel['name']}")
        for k in cards:
            _draw_front(cv, 0, 0, k, emps[k["employee_id"]], hotel, settings, logo_path)
            cv.showPage()
            _draw_back(cv, 0, 0, k, emps[k["employee_id"]], hotel, settings, request)
            cv.showPage()
    else:
        cv = canvas.Canvas(buf, pagesize=A4)
        cv.setTitle(f"Staff ID cards — {hotel['name']}")
        pw, ph = A4
        gap = 6 * mm
        left = (pw - 2 * W - gap) / 2
        vgap = 3 * mm
        top = ph - (ph - 5 * H - 4 * vgap) / 2
        for start in range(0, len(cards), 10):
            batch = cards[start:start + 10]
            slots = []
            for i in range(len(batch)):
                row, colno = divmod(i, 2)
                slots.append((colno, top - (row + 1) * H - row * vgap))
            for (colno, yy), k in zip(slots, batch):
                _draw_front(cv, left + colno * (W + gap), yy, k, emps[k["employee_id"]], hotel, settings, logo_path)
            cv.setFont("Helvetica", 7)
            cv.drawString(left, 4 * mm, f"Fronts — print this page, then the next page on the back (duplex, flip on long edge). Cut along the grey outlines.")
            cv.showPage()
            for (colno, yy), k in zip(slots, batch):
                mirrored = 1 - colno                      # long-edge duplex mirrors the columns
                _draw_back(cv, left + mirrored * (W + gap), yy, k, emps[k["employee_id"]], hotel, settings, request)
            cv.setFont("Helvetica", 7)
            cv.drawString(left, 4 * mm, "Backs")
            cv.showPage()
    cv.save()
    return buf.getvalue()
