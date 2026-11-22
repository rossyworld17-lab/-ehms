"""Guest relationship management: loyalty programme (points earned on settled stays, tiers, redemption as a folio
credit), complaints with SLA, assignment, escalation and response times, post-stay surveys and feedback with
sentiment/theme analysis, consent-based marketing campaigns, and retention & satisfaction reporting.
(FR-CRM-002..005, FR-CS-001..003, FR-AI-005)"""
from __future__ import annotations

import datetime as dt
import json
import re
import secrets

from ..db import get_db, now_iso
from ..http import ApiError, Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import account_id, business_date, get_hotel, hotel_setting, next_number, post_journal, queue_notification, set_hotel_setting

DEFAULT_LOYALTY = {"earn_per_points_kobo": 100_000, "point_value_kobo": 1_000, "min_redeem_points": 500,
                   "tiers": [["bronze", 0], ["silver", 2_000], ["gold", 10_000], ["platinum", 30_000]], "tier_bonus_bp": {"silver": 1000, "gold": 2500, "platinum": 5000}}
COMPLAINT_CATEGORIES = ("room", "cleanliness", "noise", "food", "service", "staff", "billing", "maintenance", "wifi", "security", "amenities", "other")
SLA_HOURS = {"urgent": 2, "high": 8, "normal": 24, "low": 72}
CATEGORY_DEPT = {"room": "housekeeping", "cleanliness": "housekeeping", "noise": "front_office", "food": "fnb", "service": "front_office", "staff": "hr",
                 "billing": "finance", "maintenance": "maintenance", "wifi": "it", "security": "security", "amenities": "front_office", "other": "front_office"}


# ------------------------------------------------------------------ loyalty
def loyalty_rules(c, hid: int) -> dict:
    raw = hotel_setting(c, hid, "crm.loyalty")
    return {**DEFAULT_LOYALTY, **(json.loads(raw) if raw else {})}


def _tier(rules: dict, lifetime: int) -> str:
    t = rules["tiers"][0][0]
    for name, threshold in rules["tiers"]:
        if lifetime >= threshold:
            t = name
    return t


def _post_points(c, acct: dict, hid: int | None, kind: str, points: int, reference: str | None, description: str, user_id, folio_line_id=None) -> dict:
    bal = acct["points_balance"] + points
    if bal < 0:
        raise conflict(f"Not enough points: {acct['points_balance']} available")
    lifetime = acct["lifetime_points"] + (points if kind in ("earn", "bonus") and points > 0 else 0)
    rules = loyalty_rules(c, hid) if hid else DEFAULT_LOYALTY
    tier = _tier(rules, lifetime)
    c.update("loyalty_accounts", acct["id"], {"points_balance": bal, "lifetime_points": lifetime, "tier": tier})
    c.insert("loyalty_transactions", {"account_id": acct["id"], "hotel_id": hid, "kind": kind, "points": points, "balance_after": bal, "reference": reference,
                                      "description": description[:200], "folio_line_id": folio_line_id, "created_by": user_id, "created_at": now_iso()})
    return {**acct, "points_balance": bal, "lifetime_points": lifetime, "tier": tier}


def earn_for_stay(c, ctx: Ctx | None, hotel: dict, r: dict, folio_id: int) -> int:
    """Called at check-out: points on room, F&B, laundry and other net revenue of the stay (enrolled guests only)."""
    acct = c.one("SELECT * FROM loyalty_accounts WHERE guest_id = ? AND active = 1", [r["guest_id"]])
    if not acct:
        return 0
    rules = loyalty_rules(c, hotel["id"])
    spend = c.scalar("SELECT COALESCE(SUM(net_amount),0) FROM folio_lines WHERE folio_id = ? AND kind IN ('charge','adjustment') AND department <> 'other'", [folio_id]) or 0
    points = max(0, spend // rules["earn_per_points_kobo"])
    bonus = points * rules["tier_bonus_bp"].get(acct["tier"], 0) // 10000
    if points + bonus <= 0:
        return 0
    _post_points(c, acct, hotel["id"], "earn", points + bonus, r["reference"], f"Stay {r['reference']} ({r['arrival']} – {r['departure']})"
                 + (f" incl. {acct['tier']} bonus {bonus}" if bonus else ""), ctx.user_id if ctx else None)
    return points + bonus


@route("GET", "/api/hotels/{hotel_id:int}/loyalty", perm="crm.view", tag="crm", summary="Loyalty members (?q, ?tier) and programme rules")
def list_members(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT a.*, g.first_name, g.last_name, g.email, g.phone, g.vip FROM loyalty_accounts a JOIN guests g ON g.id = a.guest_id WHERE g.organisation_id = ?")
    params: list = [ctx.org_id]
    if ctx.q("tier"):
        sql += " AND a.tier = ?"
        params.append(ctx.q("tier"))
    if ctx.q("q"):
        q = f"%{ctx.q('q').lower()}%"
        sql += " AND (LOWER(g.last_name) LIKE ? OR LOWER(g.first_name) LIKE ? OR a.member_no LIKE ? OR LOWER(COALESCE(g.email,'')) LIKE ?)"
        params += [q, q, q.upper(), q]
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY a.lifetime_points DESC LIMIT 300", params)
        tiers = {r["tier"]: r["n"] for r in c.all("SELECT a.tier, COUNT(*) AS n FROM loyalty_accounts a JOIN guests g ON g.id = a.guest_id WHERE g.organisation_id = ? GROUP BY a.tier", [ctx.org_id])}
        return {"items": rows, "tiers": tiers, "rules": loyalty_rules(c, hid)}


@route("PUT", "/api/hotels/{hotel_id:int}/loyalty/rules", perm="crm.manage", tag="crm", summary="Configure earning rate, point value, minimum redemption, tiers and tier bonuses")
def set_rules(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        cur = loyalty_rules(c, hid)
        new = {**cur}
        for k in ("earn_per_points_kobo", "point_value_kobo", "min_redeem_points"):
            if k in (ctx.body or {}):
                v = int(ctx.body[k])
                if v <= 0:
                    raise bad_request(f"{k} must be positive")
                new[k] = v
        if "tiers" in (ctx.body or {}):
            t = ctx.body["tiers"]
            if not isinstance(t, list) or not t or t[0][1] != 0 or any(t[i][1] >= t[i + 1][1] for i in range(len(t) - 1)):
                raise bad_request("tiers must start at 0 points and increase")
            new["tiers"] = t
        if "tier_bonus_bp" in (ctx.body or {}):
            new["tier_bonus_bp"] = {k: int(v) for k, v in ctx.body["tier_bonus_bp"].items()}
        set_hotel_setting(c, hid, "crm.loyalty", json.dumps(new))
        audit(c, ctx, "crm.loyalty_rules", "loyalty", hid, old=cur, new=new, hotel_id=hid)
    return new


@route("POST", "/api/guests/{guest_id:int}/loyalty/enrol", perm="guests.manage", tag="crm", summary="Enrol a guest in the loyalty programme (with their agreement)")
def enrol(ctx: Ctx):
    if not ctx.field("guest_agreed", required=False, default=False):
        raise bad_request("Confirm that the guest agreed to join the programme", {"field": "guest_agreed"})
    with get_db().tx() as c:
        g = c.one("SELECT * FROM guests WHERE id = ? AND organisation_id = ?", [ctx.path["guest_id"], ctx.org_id])
        if not g:
            raise not_found("Guest")
        if c.one("SELECT id FROM loyalty_accounts WHERE guest_id = ?", [g["id"]]):
            raise conflict("This guest is already a member")
        number = f"LYL{secrets.randbelow(10**8):08d}"
        aid = c.insert("loyalty_accounts", {"guest_id": g["id"], "member_no": number, "points_balance": 0, "lifetime_points": 0, "tier": "bronze", "active": 1,
                                            "enrolled_at": now_iso(), "enrolled_by": ctx.user_id})
        welcome = int(ctx.field("welcome_points", required=False, default=0) or 0)
        if welcome:
            _post_points(c, c.one("SELECT * FROM loyalty_accounts WHERE id = ?", [aid]), None, "bonus", welcome, "WELCOME", "Welcome bonus", ctx.user_id)
        audit(c, ctx, "crm.loyalty_enrolled", "loyalty_account", aid, number)
    return {"id": aid, "member_no": number, "_created": True}


@route("GET", "/api/guests/{guest_id:int}/loyalty", perm="guests.view", tag="crm", summary="A guest's loyalty account and statement")
def guest_loyalty(ctx: Ctx):
    with get_db().tx() as c:
        a = c.one("SELECT a.* FROM loyalty_accounts a JOIN guests g ON g.id = a.guest_id WHERE a.guest_id = ? AND g.organisation_id = ?", [ctx.path["guest_id"], ctx.org_id])
        if not a:
            return {"member": False}
        a["transactions"] = c.all("SELECT * FROM loyalty_transactions WHERE account_id = ? ORDER BY id DESC LIMIT 100", [a["id"]])
        hid = next(iter(ctx.hotel_ids)) if ctx.hotel_ids else c.scalar("SELECT id FROM hotels WHERE organisation_id = ? ORDER BY id LIMIT 1", [ctx.org_id])
        rules = loyalty_rules(c, hid)
        a["redeemable_value"] = a["points_balance"] * rules["point_value_kobo"]
        nxt = [t for t in rules["tiers"] if t[1] > a["lifetime_points"]]
        a["next_tier"] = {"name": nxt[0][0], "points_needed": nxt[0][1] - a["lifetime_points"]} if nxt else None
    return {"member": True, **a}


@route("POST", "/api/folios/{folio_id:int}/loyalty-redeem", perm="payments.receive", tag="crm",
       summary="Redeem a member's points as a credit on their open folio (posted as an allowance)")
def redeem(ctx: Ctx):
    points = ctx.field("points", kind=int)
    with get_db().tx() as c:
        f = c.one("SELECT * FROM folios WHERE id = ?", [ctx.path["folio_id"]])
        if not f:
            raise not_found("Folio")
        ctx.check_hotel(f["hotel_id"])
        if f["status"] != "open":
            raise conflict("This folio is closed")
        acct = c.one("SELECT * FROM loyalty_accounts WHERE guest_id = ? AND active = 1", [f["guest_id"]])
        if not acct:
            raise conflict("This guest is not a loyalty member")
        hotel = get_hotel(c, f["hotel_id"])
        rules = loyalty_rules(c, hotel["id"])
        if points < rules["min_redeem_points"]:
            raise bad_request(f"At least {rules['min_redeem_points']} points must be redeemed at a time")
        if points > acct["points_balance"]:
            raise conflict(f"Not enough points: {acct['points_balance']} available")
        value = points * rules["point_value_kobo"]
        on = business_date(hotel)
        org = hotel["organisation_id"]
        je = post_journal(c, hotel["id"], on, f"Loyalty redemption {acct['member_no']} on {f['number']}", "folio", f["number"], [
            (account_id(c, org, "allowances"), value, 0, "other", f"Loyalty {points} pts"), (account_id(c, org, "guest_ledger"), 0, value, "other", "Loyalty redemption")], ctx.user_id)
        lid = c.insert("folio_lines", {"folio_id": f["id"], "business_date": on.isoformat(), "kind": "adjustment", "department": "other",
                                       "description": f"Loyalty redemption — {points} points ({acct['member_no']})", "quantity": 1, "net_amount": -value, "tax_amount": 0,
                                       "service_charge": 0, "total_amount": -value, "reference": f"LOYALTY:{acct['member_no']}", "journal_entry_id": je,
                                       "posted_by": ctx.user_id, "posted_at": now_iso()})
        _post_points(c, acct, hotel["id"], "redeem", -points, f["number"], f"Redeemed on folio {f['number']}", ctx.user_id, lid)
        audit(c, ctx, "crm.loyalty_redeemed", "folio", f["id"], f["number"], new={"points": points, "value": value}, hotel_id=hotel["id"])
    return {"points": points, "value": value, "_created": True}


@route("POST", "/api/guests/{guest_id:int}/loyalty/adjust", perm="crm.manage", tag="crm", summary="Manual points adjustment with a reason (audited)")
def adjust_points(ctx: Ctx):
    points = ctx.field("points", kind=int)
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        a = c.one("SELECT a.* FROM loyalty_accounts a JOIN guests g ON g.id = a.guest_id WHERE a.guest_id = ? AND g.organisation_id = ?", [ctx.path["guest_id"], ctx.org_id])
        if not a:
            raise not_found("Loyalty account")
        out = _post_points(c, a, None, "adjust" if points < 0 else "bonus", points, "ADJ", reason, ctx.user_id)
        audit(c, ctx, "crm.loyalty_adjusted", "loyalty_account", a["id"], a["member_no"], new={"points": points, "reason": reason})
    return {"points_balance": out["points_balance"], "tier": out["tier"]}


# ------------------------------------------------------------------ complaints
def _complaint(c, ctx: Ctx, cid) -> dict:
    x = c.lock("complaints", int(cid))
    if not x:
        raise not_found("Complaint")
    ctx.check_hotel(x["hotel_id"])
    return x


@route("GET", "/api/hotels/{hotel_id:int}/complaints", perm="crm.view", tag="crm", summary="Complaints (?status, ?category, ?open=1) with SLA flags")
def list_complaints(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT x.*, g.first_name || ' ' || g.last_name AS guest, r.number AS room_number, u.full_name AS assigned_to_name FROM complaints x "
           "LEFT JOIN guests g ON g.id = x.guest_id LEFT JOIN rooms r ON r.id = x.room_id LEFT JOIN users u ON u.id = x.assigned_to WHERE x.hotel_id = ?")
    params: list = [hid]
    if ctx.q("open") == "1":
        sql += " AND x.status IN ('open','in_progress')"
    for k in ("status", "category"):
        if ctx.q(k):
            sql += f" AND x.{k} = ?"
            params.append(ctx.q(k))
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY x.id DESC LIMIT 300", params)
    now = now_iso()
    for r in rows:
        r["overdue"] = r["status"] in ("open", "in_progress") and r["due_at"] < now
    return {"items": rows, "categories": COMPLAINT_CATEGORIES}


@route("POST", "/api/hotels/{hotel_id:int}/complaints", perm="crm.complaints", tag="crm",
       summary="Register a complaint (category, priority, description, guest/reservation/room); SLA due time set by priority")
def create_complaint(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    cat = ctx.field("category", kind=str)
    if cat not in COMPLAINT_CATEGORIES:
        raise bad_request(f"category must be one of {', '.join(COMPLAINT_CATEGORIES)}")
    prio = ctx.field("priority", required=False, default="normal", kind=str)
    if prio not in SLA_HOURS:
        raise bad_request("priority must be urgent, high, normal or low")
    with get_db().tx() as c:
        res = ctx.field("reservation_id", required=False, kind=int)
        guest = ctx.field("guest_id", required=False, kind=int)
        room = ctx.field("room_id", required=False, kind=int)
        if res:
            r = c.one("SELECT * FROM reservations WHERE id = ? AND hotel_id = ?", [res, hid])
            if not r:
                raise bad_request("Reservation not found")
            guest, room = guest or r["guest_id"], room or r["room_id"]
        number = next_number(c, hid, "complaint", "CMP")
        due = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=SLA_HOURS[prio])).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        dept = ctx.field("department", required=False, kind=str) or CATEGORY_DEPT[cat]
        cid = c.insert("complaints", {"hotel_id": hid, "number": number, "guest_id": guest, "reservation_id": res, "room_id": room,
                                      "channel": ctx.field("channel", required=False, default="in_person", kind=str), "category": cat, "department": dept,
                                      "priority": prio, "description": ctx.field("description", kind=str), "status": "open",
                                      "assigned_to": ctx.field("assigned_to", required=False, kind=int), "due_at": due, "reported_by": ctx.user_id, "created_at": now_iso()})
        if prio in ("urgent", "high"):
            from ..worker import _users_with
            for uid in set(_users_with(c, hid, "crm.manage")) - {ctx.user_id}:
                queue_notification(c, hid, "in_app", str(uid), f"{prio.title()} guest complaint", f"{number}: {cat} — {ctx.field('description', kind=str)[:120]}", "complaint", cid)
        audit(c, ctx, "crm.complaint_registered", "complaint", cid, number, new={"category": cat, "priority": prio}, hotel_id=hid)
    return {"id": cid, "number": number, "due_at": due, "_created": True}


@route("GET", "/api/complaints/{complaint_id:int}", perm="crm.view", tag="crm", summary="Complaint with its update trail")
def get_complaint(ctx: Ctx):
    with get_db().tx() as c:
        x = _complaint(c, ctx, ctx.path["complaint_id"])
        x["updates"] = c.all("SELECT u.*, us.full_name AS by_name FROM complaint_updates u LEFT JOIN users us ON us.id = u.created_by WHERE u.complaint_id = ? ORDER BY u.id", [x["id"]])
        x["guest"] = c.one("SELECT id, first_name, last_name, email, phone, vip FROM guests WHERE id = ?", [x["guest_id"]]) if x["guest_id"] else None
    return x


@route("POST", "/api/complaints/{complaint_id:int}/update", perm="crm.complaints", tag="crm",
       summary="Respond: note, assign, status in_progress/resolved (resolution required)/closed, compensation, guest satisfied")
def update_complaint(ctx: Ctx):
    b = ctx.body or {}
    with get_db().tx() as c:
        x = _complaint(c, ctx, ctx.path["complaint_id"])
        if x["status"] == "closed":
            raise conflict("This complaint is closed")
        data: dict = {}
        if b.get("note"):
            c.insert("complaint_updates", {"complaint_id": x["id"], "note": str(b["note"]), "created_by": ctx.user_id, "created_at": now_iso()})
            if not x["first_response_at"]:
                data["first_response_at"] = now_iso()
        if "assigned_to" in b:
            data["assigned_to"] = int(b["assigned_to"]) if b["assigned_to"] else None
            if data["assigned_to"]:
                queue_notification(c, x["hotel_id"], "in_app", str(data["assigned_to"]), "Complaint assigned to you", f"{x['number']}: {x['category']}", "complaint", x["id"])
        if "status" in b and b["status"] != x["status"]:
            st = b["status"]
            if st not in ("in_progress", "resolved", "closed"):
                raise bad_request("status must be in_progress, resolved or closed")
            if st in ("resolved", "closed"):
                data["resolution"] = ctx.field("resolution", required=not x["resolution"], kind=str) or x["resolution"]
                data["resolved_at"] = x["resolved_at"] or now_iso()
                data.setdefault("first_response_at", x["first_response_at"] or now_iso())
            data["status"] = st
        if "compensation" in b:
            from ..services import to_minor
            data["compensation"] = to_minor(b["compensation"] or 0)
        if "guest_satisfied" in b:
            data["guest_satisfied"] = 1 if b["guest_satisfied"] else 0
        if data:
            c.update("complaints", x["id"], data)
        audit(c, ctx, "crm.complaint_updated", "complaint", x["id"], x["number"], old={k: x.get(k) for k in data}, new=data, hotel_id=x["hotel_id"])
    return {"ok": True}


def escalate_overdue(c, hotel: dict) -> int:
    """Worker job: complaints past their SLA move up one escalation level (max 2) and managers are told."""
    from ..worker import _users_with
    n = 0
    for x in c.all("SELECT * FROM complaints WHERE hotel_id = ? AND status IN ('open','in_progress') AND due_at < ? AND escalation_level < 2", [hotel["id"], now_iso()]):
        level = x["escalation_level"] + 1
        due = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=SLA_HOURS[x["priority"]])).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        c.update("complaints", x["id"], {"escalation_level": level, "due_at": due, "priority": "high" if x["priority"] in ("normal", "low") else x["priority"]})
        c.insert("complaint_updates", {"complaint_id": x["id"], "note": f"Escalated to level {level}: SLA missed", "created_by": None, "created_at": now_iso()})
        for uid in _users_with(c, hotel["id"], "crm.manage" if level == 1 else "admin.settings.manage"):
            queue_notification(c, hotel["id"], "in_app", str(uid), f"Complaint escalated (level {level})", f"{x['number']}: {x['category']} — overdue", "complaint", x["id"])
        n += 1
    return n


# ------------------------------------------------------------------ feedback, surveys and sentiment
POSITIVE = {"excellent", "great", "amazing", "wonderful", "clean", "friendly", "helpful", "comfortable", "delicious", "lovely", "perfect", "good", "nice", "fantastic",
            "spotless", "welcoming", "professional", "quiet", "recommend", "beautiful", "fast"}
NEGATIVE = {"dirty", "rude", "slow", "noisy", "noise", "bad", "terrible", "poor", "broken", "cold", "smell", "smelly", "expensive", "awful", "disappointing", "late",
            "unhelpful", "worst", "stain", "leak", "leaking", "hot", "uncomfortable", "overpriced", "bugs", "wait", "waited"}
THEMES = {"cleanliness": {"clean", "dirty", "spotless", "stain", "smell", "dust", "towel", "sheets", "bathroom"}, "staff": {"staff", "friendly", "rude", "helpful", "reception", "service", "waiter"},
          "food": {"food", "breakfast", "dinner", "restaurant", "delicious", "menu", "meal", "bar"}, "noise": {"noise", "noisy", "quiet", "loud"},
          "room": {"room", "bed", "comfortable", "ac", "air", "shower", "tv", "pillow"}, "value": {"price", "expensive", "value", "overpriced", "cheap"},
          "wifi": {"wifi", "internet", "wi-fi"}, "check-in": {"check-in", "checkin", "queue", "wait", "waited", "late"}}


def analyse(text: str | None) -> tuple[str | None, str | None]:
    """Transparent lexicon-based sentiment and theme tagging (no external service); human review is expected."""
    if not text:
        return None, None
    words = set(re.findall(r"[a-z\-]+", text.lower()))
    negated = len(re.findall(r"\b(not|no|never|wasn't|wasnt|isn't|didn't)\s+(clean|good|great|friendly|helpful|comfortable|nice)", text.lower()))
    score = len(words & POSITIVE) - len(words & NEGATIVE) - 2 * negated
    themes = [t for t, kw in THEMES.items() if words & kw]
    return ("positive" if score > 0 else "negative" if score < 0 else "neutral"), ",".join(themes) or None


def invite_after_checkout(c, hotel: dict, r: dict) -> int | None:
    g = c.one("SELECT * FROM guests WHERE id = ?", [r["guest_id"]])
    token = secrets.token_urlsafe(24)
    fid = c.insert("feedback", {"hotel_id": hotel["id"], "guest_id": g["id"], "reservation_id": r["id"], "token": token, "source": "survey", "sent_at": now_iso(),
                                "created_at": now_iso()})
    import os
    base = (os.environ.get("EHMS_PUBLIC_URL") or "").rstrip("/")
    from .messaging import notify_template
    notify_template(c, hotel, "checkout_thanks", {"email": g["email"]}, {"guest": g["first_name"], "survey_link": f"{base}/#/survey/{token}"}, "feedback", fid)
    return fid


@route("GET", "/api/public/feedback/{token}", public=True, rate_limit=30, tag="booking-engine", summary="Guest survey form details")
def survey_get(ctx: Ctx):
    with get_db().tx() as c:
        f = c.one("SELECT f.*, h.name AS hotel_name, g.first_name FROM feedback f JOIN hotels h ON h.id = f.hotel_id LEFT JOIN guests g ON g.id = f.guest_id WHERE f.token = ?",
                  [ctx.path["token"]])
    if not f:
        raise not_found("Survey")
    return {"hotel": f["hotel_name"], "guest": f["first_name"], "submitted": bool(f["submitted_at"])}


@route("POST", "/api/public/feedback/{token}", public=True, rate_limit=10, tag="booking-engine", summary="Submit the post-stay survey (ratings 1–5, NPS 0–10, comments)")
def survey_submit(ctx: Ctx):
    b = ctx.body or {}
    with get_db().tx() as c:
        f = c.lock("feedback", (c.one("SELECT id FROM feedback WHERE token = ?", [ctx.path["token"]]) or {"id": 0})["id"])
        if not f:
            raise not_found("Survey")
        if f["submitted_at"]:
            raise conflict("Thank you — this survey has already been submitted")
        data = _ratings(b)
        sentiment, themes = analyse(data.get("comments"))
        c.update("feedback", f["id"], {**data, "sentiment": sentiment, "themes": themes, "submitted_at": now_iso()})
        if (data.get("overall") or 5) <= 2:
            c.insert("complaints", {"hotel_id": f["hotel_id"], "number": next_number(c, f["hotel_id"], "complaint", "CMP"), "guest_id": f["guest_id"],
                                    "reservation_id": f["reservation_id"], "channel": "survey", "category": "service", "department": "front_office", "priority": "high",
                                    "description": f"Low survey score ({data.get('overall')}/5): {data.get('comments') or 'no comment'}", "status": "open",
                                    "due_at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                                    "reported_by": c.scalar("SELECT id FROM users WHERE organisation_id = (SELECT organisation_id FROM hotels WHERE id = ?) ORDER BY id LIMIT 1",
                                                            [f["hotel_id"]]), "created_at": now_iso()})
    return {"ok": True, "message": "Thank you for your feedback."}


def _ratings(b: dict) -> dict:
    out: dict = {}
    for k in ("overall", "cleanliness", "service", "food", "value_for_money"):
        if b.get(k) not in (None, ""):
            v = int(b[k])
            if not 1 <= v <= 5:
                raise bad_request(f"{k} must be 1–5")
            out[k] = v
    if b.get("nps") not in (None, ""):
        v = int(b["nps"])
        if not 0 <= v <= 10:
            raise bad_request("nps must be 0–10")
        out["nps"] = v
    if "overall" not in out:
        raise bad_request("Please give an overall rating")
    if b.get("comments"):
        out["comments"] = str(b["comments"])[:3000]
    return out


@route("POST", "/api/hotels/{hotel_id:int}/feedback", perm="crm.complaints", tag="crm",
       summary="Record feedback received another way (comment card, online review: platform, ratings, comments)")
def add_feedback(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    b = ctx.body or {}
    data = _ratings(b)
    sentiment, themes = analyse(data.get("comments"))
    with get_db().tx() as c:
        fid = c.insert("feedback", {"hotel_id": hid, "guest_id": ctx.field("guest_id", required=False, kind=int), "reservation_id": ctx.field("reservation_id", required=False, kind=int),
                                    "source": "online_review" if b.get("platform") else "manual", "platform": b.get("platform"), **data, "sentiment": sentiment,
                                    "themes": themes, "submitted_at": now_iso(), "created_at": now_iso()})
    return {"id": fid, "sentiment": sentiment, "themes": themes, "_created": True}


@route("GET", "/api/hotels/{hotel_id:int}/feedback", perm="crm.view", tag="crm", summary="Feedback received (?from, ?to, ?sentiment)")
def list_feedback(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT f.*, g.first_name || ' ' || g.last_name AS guest, r.reference FROM feedback f LEFT JOIN guests g ON g.id = f.guest_id "
           "LEFT JOIN reservations r ON r.id = f.reservation_id WHERE f.hotel_id = ? AND f.submitted_at IS NOT NULL")
    params: list = [hid]
    if ctx.q("sentiment"):
        sql += " AND f.sentiment = ?"
        params.append(ctx.q("sentiment"))
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY f.submitted_at DESC LIMIT 300", params)
        pending = c.scalar("SELECT COUNT(*) FROM feedback WHERE hotel_id = ? AND submitted_at IS NULL", [hid])
    for r in rows:
        r.pop("token", None)
    return {"items": rows, "surveys_awaiting_reply": pending}


@route("GET", "/api/hotels/{hotel_id:int}/crm/insights", perm="crm.view", tag="crm",
       summary="Satisfaction, NPS, recurring themes, complaints by category and department, response times, repeat-guest and retention figures (?from, ?to)")
def insights(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        frm, to = ctx.q("from", (today - dt.timedelta(days=90)).isoformat()), ctx.q("to", today.isoformat())
        fb = c.all("SELECT * FROM feedback WHERE hotel_id = ? AND submitted_at >= ? AND submitted_at <= ?", [hid, frm, to + "T23:59:59Z"])
        comps = c.all("SELECT * FROM complaints WHERE hotel_id = ? AND created_at >= ? AND created_at <= ?", [hid, frm, to + "T23:59:59Z"])
        stays = c.all("SELECT guest_id, COUNT(*) AS n FROM reservations WHERE hotel_id = ? AND status = 'checked_out' GROUP BY guest_id", [hid])
        period_guests = {r["guest_id"] for r in c.all("SELECT guest_id FROM reservations WHERE hotel_id = ? AND status = 'checked_out' AND departure >= ? AND departure <= ?", [hid, frm, to])}
        members = c.scalar("SELECT COUNT(*) FROM loyalty_accounts a JOIN guests g ON g.id = a.guest_id WHERE g.organisation_id = ?", [ctx.org_id])
    def avg(k):
        v = [f[k] for f in fb if f[k] is not None]
        return round(sum(v) / len(v), 2) if v else None
    nps_v = [f["nps"] for f in fb if f["nps"] is not None]
    nps = round((sum(1 for v in nps_v if v >= 9) - sum(1 for v in nps_v if v <= 6)) * 100 / len(nps_v)) if nps_v else None
    theme_counts: dict[str, dict] = {}
    for f in fb:
        for t in (f["themes"] or "").split(","):
            if t:
                d = theme_counts.setdefault(t, {"theme": t, "mentions": 0, "negative": 0})
                d["mentions"] += 1
                d["negative"] += 1 if f["sentiment"] == "negative" else 0
    resp = [(dt.datetime.fromisoformat(x["first_response_at"].replace("Z", "+00:00")) - dt.datetime.fromisoformat(x["created_at"].replace("Z", "+00:00"))).total_seconds() / 3600
            for x in comps if x["first_response_at"]]
    reso = [(dt.datetime.fromisoformat(x["resolved_at"].replace("Z", "+00:00")) - dt.datetime.fromisoformat(x["created_at"].replace("Z", "+00:00"))).total_seconds() / 3600
            for x in comps if x["resolved_at"]]
    by_cat: dict[str, int] = {}
    by_dept: dict[str, int] = {}
    for x in comps:
        by_cat[x["category"]] = by_cat.get(x["category"], 0) + 1
        by_dept[x["department"]] = by_dept.get(x["department"], 0) + 1
    repeat = {g for g in (s["guest_id"] for s in stays if s["n"] > 1)}
    return {"from": frm, "to": to, "responses": len(fb), "averages": {k: avg(k) for k in ("overall", "cleanliness", "service", "food", "value_for_money")}, "nps": nps,
            "sentiment": {s: sum(1 for f in fb if f["sentiment"] == s) for s in ("positive", "neutral", "negative")},
            "themes": sorted(theme_counts.values(), key=lambda d: -d["mentions"]),
            "complaints": {"total": len(comps), "open": sum(1 for x in comps if x["status"] in ("open", "in_progress")), "by_category": by_cat, "by_department": by_dept,
                           "escalated": sum(1 for x in comps if x["escalation_level"]), "avg_first_response_hours": round(sum(resp) / len(resp), 1) if resp else None,
                           "avg_resolution_hours": round(sum(reso) / len(reso), 1) if reso else None,
                           "satisfied_after_resolution_pct": round(sum(1 for x in comps if x["guest_satisfied"]) * 100 / max(1, sum(1 for x in comps if x["guest_satisfied"] is not None)))
                           if any(x["guest_satisfied"] is not None for x in comps) else None},
            "retention": {"guests_with_stays": len(stays), "repeat_guests": len(repeat), "repeat_rate_pct": round(len(repeat) * 100 / len(stays), 1) if stays else None,
                          "period_guests": len(period_guests), "period_returning": len(period_guests & repeat), "loyalty_members": members}}


# ------------------------------------------------------------------ campaigns
def _segment_guests(c, org: int, hid: int, seg: dict) -> list[dict]:
    sql = ("SELECT g.*, (SELECT COUNT(*) FROM reservations r WHERE r.guest_id = g.id AND r.status = 'checked_out') AS stays, "
           "(SELECT MAX(departure) FROM reservations r WHERE r.guest_id = g.id AND r.status = 'checked_out') AS last_stay, la.tier "
           "FROM guests g LEFT JOIN loyalty_accounts la ON la.guest_id = g.id WHERE g.organisation_id = ? AND g.marketing_consent = 1")
    params: list = [org]
    if seg.get("vip"):
        sql += " AND g.vip = 1"
    if seg.get("nationality"):
        sql += " AND LOWER(COALESCE(g.nationality,'')) = ?"
        params.append(seg["nationality"].lower())
    if seg.get("tier"):
        sql += " AND la.tier = ?"
        params.append(seg["tier"])
    if seg.get("birthday_month"):
        sql += " AND CAST(g.date_of_birth AS VARCHAR(10)) LIKE ?"
        params.append(f"%-{int(seg['birthday_month']):02d}-%")
    rows = c.all(sql, params)
    out = []
    for g in rows:
        if seg.get("min_stays") and g["stays"] < int(seg["min_stays"]):
            continue
        if seg.get("not_stayed_since") and g["last_stay"] and g["last_stay"] >= seg["not_stayed_since"]:
            continue
        if seg.get("not_stayed_since") and not g["last_stay"]:
            continue
        out.append(g)
    return out


@route("GET", "/api/hotels/{hotel_id:int}/campaigns", perm="crm.view", tag="crm", summary="Marketing campaigns")
def list_campaigns(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        rows = c.all("SELECT k.*, u.full_name AS created_by_name FROM campaigns k JOIN users u ON u.id = k.created_by WHERE k.hotel_id = ? ORDER BY k.id DESC", [hid])
        for k in rows:
            k["segment"] = json.loads(k["segment"])
            if k["status"] == "sent":
                k["delivery"] = {r["status"]: r["n"] for r in c.all("SELECT n.status, COUNT(*) AS n FROM campaign_recipients cr JOIN notifications n ON n.id = cr.notification_id "
                                                                    "WHERE cr.campaign_id = ? GROUP BY n.status", [k["id"]])}
                since = k["sent_at"][:10]
                ids = [r["guest_id"] for r in c.all("SELECT guest_id FROM campaign_recipients WHERE campaign_id = ?", [k["id"]])]
                k["bookings_after"] = c.scalar(f"SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND created_at >= ? AND guest_id IN ({','.join('?' for _ in ids) or 'NULL'})",
                                               [hid, since, *ids]) if ids else 0
                k["promo_uses"] = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND promo_code = ? AND created_at >= ?", [hid, k["promo_code"], since]) if k["promo_code"] else None
    return {"items": rows}


@route("POST", "/api/hotels/{hotel_id:int}/campaigns/preview", perm="crm.campaigns", tag="crm", summary="Count consenting guests matching a segment")
def preview_segment(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        gs = _segment_guests(c, ctx.org_id, hid, ctx.field("segment", required=False) or {})
    return {"count": len(gs), "sample": [f"{g['first_name']} {g['last_name']}" for g in gs[:10]]}


@route("POST", "/api/hotels/{hotel_id:int}/campaigns", perm="crm.campaigns", tag="crm", summary="Create a draft campaign (name, channel, segment, subject, body, promo_code)")
def create_campaign(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    ch = ctx.field("channel", kind=str)
    if ch not in ("email", "sms", "whatsapp"):
        raise bad_request("channel must be email, sms or whatsapp")
    with get_db().tx() as c:
        kid = c.insert("campaigns", {"hotel_id": hid, "name": ctx.field("name", kind=str), "channel": ch, "segment": json.dumps(ctx.field("segment", required=False) or {}),
                                     "subject": ctx.field("subject", required=ch == "email", kind=str), "body": ctx.field("body", kind=str),
                                     "promo_code": ctx.field("promo_code", required=False, kind=str), "status": "draft", "created_by": ctx.user_id, "created_at": now_iso()})
    return {"id": kid, "_created": True}


@route("POST", "/api/campaigns/{campaign_id:int}/send", perm="crm.campaigns", tag="crm",
       summary="Send a draft campaign to consenting guests in its segment (queues one message each; includes an opt-out line)")
def send_campaign(ctx: Ctx):
    with get_db().tx() as c:
        k = c.lock("campaigns", int(ctx.path["campaign_id"]))
        if not k:
            raise not_found("Campaign")
        ctx.check_hotel(k["hotel_id"])
        if k["status"] != "draft":
            raise conflict(f"This campaign is {k['status']}")
        hotel = get_hotel(c, k["hotel_id"])
        guests = _segment_guests(c, ctx.org_id, k["hotel_id"], json.loads(k["segment"]))
        from .messaging import render
        n = 0
        for g in guests:
            to = g["email"] if k["channel"] == "email" else g["phone"]
            if not to:
                continue
            ctxv = {"guest": g["first_name"], "hotel": hotel["name"], "promo_code": k["promo_code"] or ""}
            body = render(k["body"], ctxv) + ("\n\nTo stop receiving offers, reply STOP or contact us." if k["channel"] != "email" else
                                               f"\n\nYou receive this because you agreed to hear from {hotel['name']}. Reply to unsubscribe.")
            nid = queue_notification(c, hotel["id"], k["channel"], to, render(k["subject"] or "", ctxv)[:200], body, "campaign", k["id"])
            c.insert("campaign_recipients", {"campaign_id": k["id"], "guest_id": g["id"], "notification_id": nid})
            n += 1
        if not n:
            raise conflict("No consenting guests in this segment have contact details for this channel")
        c.update("campaigns", k["id"], {"status": "sent", "recipients": n, "sent_by": ctx.user_id, "sent_at": now_iso()})
        audit(c, ctx, "crm.campaign_sent", "campaign", k["id"], k["name"], new={"recipients": n}, hotel_id=k["hotel_id"])
    return {"recipients": n}


@route("POST", "/api/guests/{guest_id:int}/unsubscribe", perm="guests.manage", tag="crm", summary="Record a guest's marketing opt-out")
def unsubscribe(ctx: Ctx):
    with get_db().tx() as c:
        g = c.one("SELECT * FROM guests WHERE id = ? AND organisation_id = ?", [ctx.path["guest_id"], ctx.org_id])
        if not g:
            raise not_found("Guest")
        c.update("guests", g["id"], {"marketing_consent": 0})
        audit(c, ctx, "crm.unsubscribed", "guest", g["id"], old={"marketing_consent": g["marketing_consent"]}, new={"marketing_consent": 0})
    return {"ok": True}
