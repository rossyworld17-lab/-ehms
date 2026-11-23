"""Release 1.2 completion of the intelligence and guest-facing items:
- cancellation-risk prediction for upcoming bookings (explainable points, never acts on its own);
- preventive-maintenance prediction from each asset's repair history (mean time between failures);
- guest insights: nationality mix, preferred room categories, booking sources, stay length, repeat guests;
- an automated plain-language daily management summary;
- check-out-day reminders to guests (with the balance due) — a worker job;
- the booking confirmation / pro-forma receipt that online guests download;
- the hotel logo (shown on the booking engine and in the staff header);
- an attendance intake for biometric / fingerprint clocks (integration token)."""
from __future__ import annotations

import base64
import binascii
import datetime as dt
import hmac
import io
import os
import secrets
from collections import Counter

from starlette.responses import Response

from ..db import get_db, now_iso
from ..http import ApiError, Ctx, audit, bad_request, not_found, route
from ..services import business_date, get_hotel, hotel_setting, hotel_today, price_breakdown, set_hotel_setting

# ------------------------------------------------------------------ cancellation risk
RISK_RULES = [
    # (points, explanation, test)
    (25, "booked online and not yet paid", lambda r, x: r["source"] in ("booking_engine", "website", "ota") and x["paid"] == 0),
    (20, "no deposit received", lambda r, x: x["paid"] == 0 and r["source"] not in ("booking_engine", "website", "ota")),
    (15, "booked more than 45 days ahead", lambda r, x: x["lead"] > 45),
    (15, "still tentative", lambda r, x: r["status"] == "tentative"),
    (20, "guest cancelled or did not show before", lambda r, x: x["past_cancels"] > 0),
    (10, "first-time guest", lambda r, x: x["past_stays"] == 0),
    (-15, "repeat guest", lambda r, x: x["past_stays"] >= 2),
    (-10, "corporate or group booking", lambda r, x: r["booking_type"] in ("corporate", "group")),
]


def cancellation_risk(c, hotel: dict, days: int = 30) -> list[dict]:
    today = business_date(hotel)
    rows = c.all("SELECT r.*, g.first_name, g.last_name FROM reservations r JOIN guests g ON g.id = r.guest_id WHERE r.hotel_id = ? "
                 "AND r.status IN ('confirmed','tentative') AND r.arrival >= ? AND r.arrival <= ? ORDER BY r.arrival", [hotel["id"], today.isoformat(),
                                                                                                                       (today + dt.timedelta(days=days)).isoformat()])
    out = []
    for r in rows:
        paid = c.scalar("SELECT COALESCE(SUM(l.total_amount),0) FROM folio_lines l JOIN folios f ON f.id = l.folio_id WHERE f.reservation_id = ? AND l.kind = 'payment'", [r["id"]]) or 0
        x = {"paid": abs(paid), "lead": (dt.date.fromisoformat(r["arrival"]) - dt.date.fromisoformat(str(r["created_at"])[:10])).days,
             "past_cancels": c.scalar("SELECT COUNT(*) FROM reservations WHERE guest_id = ? AND id <> ? AND status IN ('cancelled','no_show')", [r["guest_id"], r["id"]]),
             "past_stays": c.scalar("SELECT COUNT(*) FROM reservations WHERE guest_id = ? AND status = 'checked_out'", [r["guest_id"]])}
        score, reasons = 10, []
        for pts, why, test in RISK_RULES:
            if test(r, x):
                score += pts
                reasons.append(f"{'+' if pts > 0 else ''}{pts} {why}")
        score = max(0, min(100, score))
        out.append({"id": r["id"], "reference": r["reference"], "guest": f"{r['first_name']} {r['last_name']}", "arrival": r["arrival"], "status": r["status"],
                    "source": r["source"], "risk": score, "level": "high" if score >= 60 else "medium" if score >= 35 else "low", "reasons": reasons})
    return sorted(out, key=lambda o: -o["risk"])


@route("GET", "/api/hotels/{hotel_id:int}/insights/cancellation-risk", perm="reservations.view", tag="ai",
       summary="Upcoming bookings scored for cancellation risk with the reasons (?days=30). A prediction only — nothing is changed")
def cancellation_risk_ep(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        items = cancellation_risk(c, get_hotel(c, hid), min(120, max(1, int(ctx.q("days", 30)))))
    return {"items": items, "method": "Starts at 10 points and adds or removes points for each factor shown; 60+ is high risk. "
                                        "Use it to confirm deposits or call the guest — EHMS never cancels or overbooks on its own."}


# ------------------------------------------------------------------ preventive maintenance prediction
def maintenance_risk(c, hotel: dict) -> list[dict]:
    today = hotel_today(hotel)
    out = []
    for a in c.all("SELECT * FROM assets WHERE hotel_id = ? AND status <> 'retired'", [hotel["id"]]):
        fails = [dt.date.fromisoformat(str(w["created_at"])[:10]) for w in c.all(
            "SELECT created_at FROM work_orders WHERE asset_id = ? AND kind = 'corrective' AND status <> 'cancelled' ORDER BY created_at", [a["id"]])]
        if len(fails) < 2:
            continue
        gaps = [(b - a_).days for a_, b in zip(fails, fails[1:]) if (b - a_).days > 0]
        if not gaps:
            continue
        mtbf = sum(gaps) / len(gaps)
        nxt = fails[-1] + dt.timedelta(days=round(mtbf))
        days_left = (nxt - today).days
        out.append({"asset_id": a["id"], "asset": a["name"], "category": a["category"], "repairs": len(fails), "mean_days_between_failures": round(mtbf),
                    "last_failure": fails[-1].isoformat(), "predicted_next_failure": nxt.isoformat(), "days_left": days_left,
                    "advice": "Inspect now" if days_left <= 7 else "Plan preventive service" if days_left <= 30 else "Monitor"})
    return sorted(out, key=lambda o: o["days_left"])


@route("GET", "/api/hotels/{hotel_id:int}/insights/maintenance-risk", perm="maintenance.view", tag="ai",
       summary="Assets likely to fail next, from their repair history (mean time between failures)")
def maintenance_risk_ep(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": maintenance_risk(c, get_hotel(c, hid)),
                "method": "For assets with two or more corrective repairs: the average number of days between repairs, counted from the last one. "
                          "A planning aid — create a preventive schedule or work order to act on it."}


# ------------------------------------------------------------------ guest insights (demographics & preferences)
@route("GET", "/api/hotels/{hotel_id:int}/insights/guests", perm="crm.view", tag="ai",
       summary="Guest demographics and preferences: nationality mix, preferred room categories, booking sources, stay length, repeat guests (?from, ?to)")
def guest_insights(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        to = ctx.q("to") or business_date(hotel).isoformat()
        frm = ctx.q("from") or (dt.date.fromisoformat(to) - dt.timedelta(days=365)).isoformat()
        rows = c.all("SELECT r.guest_id, r.source, r.booking_type, r.arrival, r.departure, rt.name AS room_type, g.nationality, g.vip FROM reservations r "
                     "JOIN guests g ON g.id = r.guest_id JOIN room_types rt ON rt.id = r.room_type_id WHERE r.hotel_id = ? AND r.status IN ('checked_in','checked_out') "
                     "AND r.arrival >= ? AND r.arrival <= ?", [hid, frm, to])
    def top(counter: Counter, n=8):
        total = sum(counter.values()) or 1
        return [{"label": k or "Not recorded", "count": v, "pct": round(v * 100 / total, 1)} for k, v in counter.most_common(n)]
    stays_per_guest = Counter(r["guest_id"] for r in rows)
    nights = [(dt.date.fromisoformat(r["departure"]) - dt.date.fromisoformat(r["arrival"])).days for r in rows]
    return {"from": frm, "to": to, "stays": len(rows), "guests": len(stays_per_guest),
            "nationality": top(Counter((r["nationality"] or "").strip().title() for r in rows)),
            "room_categories": top(Counter(r["room_type"] for r in rows)), "sources": top(Counter(r["source"] for r in rows)),
            "booking_types": top(Counter(r["booking_type"] for r in rows)),
            "average_length_of_stay": round(sum(nights) / len(nights), 1) if nights else None,
            "repeat_guests": sum(1 for v in stays_per_guest.values() if v > 1), "vip_stays": sum(1 for r in rows if r["vip"])}


# ------------------------------------------------------------------ automated daily summary
@route("GET", "/api/hotels/{hotel_id:int}/insights/daily-summary", perm="dashboard.view", tag="ai",
       summary="Plain-language management summary of yesterday's business date and today's outlook, from recorded data")
def daily_summary_ep(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        today = business_date(hotel)
        y = (today - dt.timedelta(days=1)).isoformat()
        rooms = c.scalar("SELECT COUNT(*) FROM rooms WHERE hotel_id = ? AND active = 1 AND service_status NOT IN ('out_of_order','out_of_service')", [hid]) or 1
        occ_last = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND status IN ('checked_in','checked_out') AND arrival <= ? AND departure > ?", [hid, y, y]) or 0
        occ_tonight = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND status IN ('checked_in','confirmed') AND arrival <= ? AND departure > ?",
                               [hid, today.isoformat(), today.isoformat()]) or 0
        rev = {r["department"]: r["net"] for r in c.all(
            "SELECT l.department, SUM(l.net_amount) AS net FROM folio_lines l JOIN folios f ON f.id = l.folio_id WHERE f.hotel_id = ? AND l.business_date = ? "
            "AND l.kind IN ('charge','adjustment') GROUP BY l.department", [hid, y])}
        pos = c.scalar("SELECT COALESCE(SUM(net_amount),0) FROM pos_orders WHERE hotel_id = ? AND status = 'settled' AND settled_at >= ? AND settled_at < ?",
                       [hid, f"{y}T00:00:00", f"{today.isoformat()}T00:00:00"]) or 0
        arrivals = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND arrival = ? AND status IN ('confirmed','tentative')", [hid, today.isoformat()]) or 0
        departures = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND departure = ? AND status = 'checked_in'", [hid, today.isoformat()]) or 0
        balances = c.scalar("SELECT COALESCE(SUM(l.total_amount),0) FROM folio_lines l JOIN folios f ON f.id = l.folio_id WHERE f.hotel_id = ? AND f.status = 'open'", [hid]) or 0
        open_wo = c.scalar("SELECT COUNT(*) FROM work_orders WHERE hotel_id = ? AND status IN ('open','assigned','in_progress','on_hold')", [hid]) or 0
        complaints = c.scalar("SELECT COUNT(*) FROM complaints WHERE hotel_id = ? AND status NOT IN ('resolved','closed')", [hid]) or 0
        risky = [r for r in cancellation_risk(c, hotel, 7) if r["level"] == "high"]
    cur = hotel["currency"]
    room_rev = rev.get("room", 0)
    total = sum(rev.values())
    lines = [f"{y}: occupancy was {occ_last * 100 // rooms}% ({occ_last} of {rooms} rooms); room revenue {cur} {room_rev / 100:,.2f} and total folio revenue "
             f"{cur} {total / 100:,.2f}" + (f", restaurant and bar sales {cur} {pos / 100:,.2f}." if pos else "."),
             f"Today: {arrivals} arrival(s) and {departures} departure(s); occupancy tonight is {occ_tonight * 100 // rooms}% on the books.",
             f"Open guest balances total {cur} {balances / 100:,.2f}.",
             f"{open_wo} maintenance work order(s) and {complaints} complaint(s) are open."]
    if risky:
        lines.append(f"{len(risky)} booking(s) in the next 7 days have a high cancellation risk (e.g. {risky[0]['reference']}); consider confirming deposits.")
    return {"date": y, "summary": lines, "source": "Calculated from posted folio lines, reservations, work orders and complaints — no estimates."}


def _has(c, table: str, column: str) -> bool:
    try:
        c.execute(f"SELECT {column} FROM {c._ident(table)} WHERE 1 = 0")
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ check-out-day reminders (worker)
def checkout_reminders(c, hotel: dict) -> int:
    from ..worker import _once
    from .frontoffice import folio_balance
    from .messaging import notify_template
    today = business_date(hotel).isoformat()
    n = 0
    for r in c.all("SELECT r.*, g.first_name, g.email, g.phone FROM reservations r JOIN guests g ON g.id = r.guest_id WHERE r.hotel_id = ? AND r.departure = ? "
                   "AND r.status = 'checked_in'", [hotel["id"], today]):
        if not _once(c, "checkout_reminder", str(r["id"])):
            continue
        f = c.one("SELECT id FROM folios WHERE reservation_id = ?", [r["id"]])
        bal = folio_balance(c, f["id"])["balance"] if f else 0
        notify_template(c, hotel, "checkout_reminder", {"email": r["email"], "phone": r["phone"]},
                        {"guest": r["first_name"], "reference": r["reference"], "checkout_time": r.get("late_check_out_until") or hotel["check_out_time"],
                         "balance": f"{hotel['currency']} {max(0, bal) / 100:,.2f}"}, "reservation", r["id"])
        n += 1
    return n


# ------------------------------------------------------------------ booking confirmation / receipt (public)
@route("GET", "/api/public/bookings/{reference}/confirmation.pdf", public=True, rate_limit=20, tag="booking-engine",
       summary="Booking confirmation and pro-forma receipt (PDF) for a guest: ?email=")
def booking_confirmation(ctx: Ctx):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    email = str(ctx.q("email") or "").strip().lower()
    with get_db().tx() as c:
        r = c.one("SELECT r.*, g.first_name, g.last_name, g.email, rt.name AS room_type FROM reservations r JOIN guests g ON g.id = r.guest_id "
                  "JOIN room_types rt ON rt.id = r.room_type_id WHERE r.reference = ?", [ctx.path["reference"]])
        if not r or not email or (r["email"] or "").lower() != email:
            raise not_found("Booking")
        hotel = get_hotel(c, r["hotel_id"])
        a, d = dt.date.fromisoformat(r["arrival"]), dt.date.fromisoformat(r["departure"])
        nights = (d - a).days
        price = price_breakdown(c, hotel, "room", r["nightly_rate"] * nights - (r.get("discount_amount") or 0), a)
        paid = abs(c.scalar("SELECT COALESCE(SUM(l.total_amount),0) FROM folio_lines l JOIN folios f ON f.id = l.folio_id WHERE f.reservation_id = ? AND l.kind = 'payment'", [r["id"]]) or 0)
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    cv.setFont("Helvetica-Bold", 16)
    cv.drawString(50, 795, hotel["name"])
    cv.setFont("Helvetica", 9)
    cv.drawString(50, 781, " · ".join(x for x in [hotel.get("address"), hotel.get("phone"), hotel.get("email")] if x))
    cv.setFont("Helvetica-Bold", 13)
    cv.drawString(50, 748, "BOOKING CONFIRMATION / PRO-FORMA RECEIPT")
    cv.setFont("Helvetica", 10.5)
    rows = [("Reference", r["reference"]), ("Status", r["status"].replace("_", " ").title()), ("Guest", f"{r['first_name']} {r['last_name']}"),
            ("Arrival", f"{r['arrival']} (from {hotel['check_in_time']})"), ("Departure", f"{r['departure']} (by {hotel['check_out_time']})"),
            ("Room", f"{r['room_type']} · {nights} night(s) · {r['adults']} adult(s), {r['children']} child(ren)"),
            ("Room charges", f"{hotel['currency']} {price['net'] / 100:,.2f}"), ("Service charge", f"{hotel['currency']} {price['service_charge'] / 100:,.2f}"),
            ("Taxes", f"{hotel['currency']} {price['tax'] / 100:,.2f}"), ("Estimated total", f"{hotel['currency']} {price['total'] / 100:,.2f}"),
            ("Paid so far", f"{hotel['currency']} {paid / 100:,.2f}"), ("Balance", f"{hotel['currency']} {max(0, price['total'] - paid) / 100:,.2f} (payable at the hotel)")]
    y = 718
    for k, v in rows:
        cv.setFont("Helvetica-Bold", 10.5)
        cv.drawString(50, y, k)
        cv.setFont("Helvetica", 10.5)
        cv.drawString(190, y, v)
        y -= 21
    cv.setFont("Helvetica", 8.5)
    cv.drawString(50, y - 10, "This is not a tax invoice. Extras, final taxes and payments appear on the invoice issued at check-out.")
    if hotel.get("cancellation_policy"):
        cv.drawString(50, y - 24, f"Cancellation policy: {hotel['cancellation_policy'][:120]}")
    cv.showPage()
    cv.save()
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="booking-{r["reference"]}.pdf"'})


# ------------------------------------------------------------------ hotel logo
LOGO_TYPES = {"png": ("image/png", b"\x89PNG"), "jpg": ("image/jpeg", b"\xff\xd8\xff"), "jpeg": ("image/jpeg", b"\xff\xd8\xff"), "webp": ("image/webp", b"RIFF")}


@route("POST", "/api/hotels/{hotel_id:int}/logo", perm="admin.settings.manage", tag="admin", summary="Upload the hotel logo: filename, content_base64 (PNG/JPEG/WebP, up to 1 MB)")
def upload_logo(ctx: Ctx):
    from .media import media_dir
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    name = str(ctx.field("filename", kind=str))
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in LOGO_TYPES:
        raise bad_request("The logo must be PNG, JPEG or WebP")
    try:
        data = base64.b64decode(str(ctx.field("content_base64", kind=str)), validate=True)
    except (binascii.Error, ValueError):
        raise bad_request("content_base64 is not valid base64")
    ctype, sig = LOGO_TYPES[ext]
    if not data.startswith(sig):
        raise bad_request("The file content is not a valid image of that type")
    if len(data) > 1024 * 1024:
        raise ApiError(413, "file_too_large", "The logo must be 1 MB or smaller")
    stored = f"logo-h{hid}-{secrets.token_hex(6)}.{'jpg' if ext == 'jpeg' else ext}"
    with open(os.path.join(media_dir(), stored), "wb") as fh:
        fh.write(data)
    with get_db().tx() as c:
        set_hotel_setting(c, hid, "hotel.logo", f"{stored}|{ctype}")
        audit(c, ctx, "settings.logo", "hotel", hid, new={"file": stored}, hotel_id=hid)
    return {"url": f"/api/public/hotels/{hid}/logo?v={stored[-10:]}"}


@route("GET", "/api/public/hotels/{hotel_id:int}/logo", public=True, rate_limit=300, tag="booking-engine", summary="The hotel logo (404 when none is set)")
def get_logo(ctx: Ctx):
    from .media import media_dir
    with get_db().tx() as c:
        v = hotel_setting(c, int(ctx.path["hotel_id"]), "hotel.logo")
    if not v:
        raise not_found("Logo")
    stored, ctype = v.split("|", 1)
    path = os.path.join(media_dir(), os.path.basename(stored))
    if not os.path.isfile(path):
        raise not_found("Logo")
    with open(path, "rb") as fh:
        return Response(fh.read(), media_type=ctype, headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"})


def logo_url(c, hid: int) -> str | None:
    v = hotel_setting(c, hid, "hotel.logo")
    return f"/api/public/hotels/{hid}/logo?v={v.split('|')[0][-10:]}" if v else None


# ------------------------------------------------------------------ biometric attendance intake
@route("POST", "/api/integrations/attendance-events", public=True, rate_limit=600, tag="hr",
       summary="Fingerprint / biometric clocks push clock-ins and outs (header X-EHMS-Integration-Token): hotel_code, events[{employee_no, action in|out, occurred_at}]")
def attendance_events_in(ctx: Ctx):
    token = os.environ.get("EHMS_ATTENDANCE_API_TOKEN", "")
    if not token or not hmac.compare_digest(token, ctx.request.headers.get("x-ehms-integration-token", "")):
        raise ApiError(401, "invalid_token", "Invalid or missing integration token")
    events = ctx.field("events")
    if not isinstance(events, list) or not events or len(events) > 500:
        raise bad_request("Send 1–500 events")
    from .hr import _upsert_attendance
    done, skipped = 0, []
    with get_db().tx() as c:
        hotel = c.one("SELECT * FROM hotels WHERE upper(code) = ?", [str(ctx.field("hotel_code", kind=str)).upper()])
        if not hotel:
            raise bad_request("Unknown hotel_code")
        for ev in sorted(events, key=lambda e: str(e.get("occurred_at", ""))):
            e = c.one("SELECT * FROM employees WHERE hotel_id = ? AND employee_no = ? AND status = 'active'", [hotel["id"], str(ev.get("employee_no", ""))])
            try:
                when = dt.datetime.fromisoformat(str(ev.get("occurred_at", "")).replace("Z", "+00:00"))
            except ValueError:
                when = None
            if not e or ev.get("action") not in ("in", "out") or not when:
                skipped.append(str(ev.get("employee_no", "?")))
                continue
            try:
                from zoneinfo import ZoneInfo
                local = when.astimezone(ZoneInfo(hotel["timezone"])) if when.tzinfo else when
            except Exception:  # pragma: no cover
                local = when
            d, hhmm = local.date().isoformat(), local.strftime("%H:%M")
            row = c.one("SELECT * FROM attendance WHERE employee_id = ? AND work_date = ?", [e["id"], d])
            if ev["action"] == "in":
                if row and row["clock_in"]:
                    continue                       # repeated punch: keep the first clock-in
                shift = c.one("SELECT s.* FROM shift_assignments a JOIN shift_templates s ON s.id = a.shift_id WHERE a.employee_id = ? AND a.work_date = ?", [e["id"], d])
                late = bool(shift) and local.replace(tzinfo=None) > dt.datetime.combine(local.date(), dt.time.fromisoformat(shift["start_time"])) + dt.timedelta(minutes=15)
                _upsert_attendance(c, e["id"], d, {"status": "late" if late else "present", "clock_in": hhmm, "note": "Biometric clock"}, None)
            else:
                if not row or not row["clock_in"]:
                    skipped.append(str(e["employee_no"]))
                    continue
                c.update("attendance", row["id"], {"clock_out": hhmm, "recorded_at": now_iso()})
            done += 1
        c.insert("integration_logs", {"hotel_id": hotel["id"], "integration": "attendance", "direction": "inbound", "endpoint": "/api/integrations/attendance-events",
                                      "status_code": 200, "ok": 1, "summary": f"{done} applied, {len(skipped)} skipped", "created_at": now_iso()})
    return {"applied": done, "skipped": skipped}
