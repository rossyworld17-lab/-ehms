"""Security & compliance: incident register with investigation notes and restricted cases, visitor and contractor
log, lost-and-found with claim verification and disposal dates, emergency contacts, and an access-control /
key-card event intake for lock systems. (FR-SEC-001..003, master prompt section 19)"""
from __future__ import annotations

import datetime as dt
import hmac
import os

from ..db import get_db, now_iso
from ..http import ApiError, Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import business_date, get_hotel, next_number, parse_date, queue_notification

CATEGORIES = ("theft", "assault", "fire", "medical", "trespass", "damage", "fraud", "harassment", "suspicious", "safety_hazard", "noise", "other")
LF_CATEGORIES = ("electronics", "jewellery", "documents", "clothing", "cash", "keys", "bags", "toiletries", "other")


def _mask(v: str | None) -> str | None:
    return None if not v else "•" * max(0, len(v) - 3) + v[-3:]


# ------------------------------------------------------------------ incidents
def _incident(c, ctx: Ctx, iid) -> dict:
    i = c.lock("security_incidents", int(iid))
    if not i:
        raise not_found("Incident")
    ctx.check_hotel(i["hotel_id"])
    if i["restricted"] and not ctx.can("security.sensitive") and i["reported_by"] != ctx.user_id:
        raise forbidden("This incident is restricted")
    return i


@route("GET", "/api/hotels/{hotel_id:int}/incidents", perm="security.view", tag="security",
       summary="Security incidents (?status, ?category); restricted cases only for security.sensitive")
def list_incidents(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT i.*, u.full_name AS reported_by_name, a.full_name AS assigned_to_name, r.number AS room_number FROM security_incidents i "
           "JOIN users u ON u.id = i.reported_by LEFT JOIN users a ON a.id = i.assigned_to LEFT JOIN rooms r ON r.id = i.room_id WHERE i.hotel_id = ?")
    params: list = [hid]
    if not ctx.can("security.sensitive"):
        sql += " AND (i.restricted = 0 OR i.reported_by = ?)"
        params.append(ctx.user_id)
    for k in ("status", "category"):
        if ctx.q(k):
            sql += f" AND i.{k} = ?"
            params.append(ctx.q(k))
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY i.occurred_at DESC LIMIT 300", params)
        counts = {r["category"]: r["n"] for r in c.all("SELECT category, COUNT(*) AS n FROM security_incidents WHERE hotel_id = ? GROUP BY category", [hid])}
    return {"items": rows, "categories": CATEGORIES, "by_category": counts}


@route("POST", "/api/hotels/{hotel_id:int}/incidents", perm="security.report", tag="security",
       summary="Record an incident (occurred_at, location, category, severity, description, persons_involved, actions_taken, restricted)")
def create_incident(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    cat, sev = ctx.field("category", kind=str), ctx.field("severity", kind=str)
    if cat not in CATEGORIES:
        raise bad_request(f"category must be one of {', '.join(CATEGORIES)}")
    if sev not in ("low", "medium", "high", "critical"):
        raise bad_request("severity must be low, medium, high or critical")
    occurred = ctx.field("occurred_at", kind=str)
    try:
        dt.datetime.fromisoformat(occurred.replace("Z", "+00:00"))
    except ValueError:
        raise bad_request("occurred_at must be an ISO date-time")
    with get_db().tx() as c:
        room = ctx.field("room_id", required=False, kind=int)
        if room and not c.one("SELECT id FROM rooms WHERE id = ? AND hotel_id = ?", [room, hid]):
            raise bad_request("Room not found")
        number = next_number(c, hid, "incident", "INC")
        iid = c.insert("security_incidents", {"hotel_id": hid, "number": number, "occurred_at": occurred, "location": ctx.field("location", kind=str),
                                              "category": cat, "severity": sev, "description": ctx.field("description", kind=str),
                                              "persons_involved": ctx.field("persons_involved", required=False, kind=str),
                                              "actions_taken": ctx.field("actions_taken", required=False, kind=str),
                                              "police_reference": ctx.field("police_reference", required=False, kind=str), "room_id": room,
                                              "guest_id": ctx.field("guest_id", required=False, kind=int),
                                              "restricted": 1 if ctx.field("restricted", required=False, default=False) or cat in ("assault", "harassment") else 0,
                                              "status": "open", "reported_by": ctx.user_id, "created_at": now_iso()})
        if sev in ("high", "critical"):
            from ..worker import _users_with
            for uid in set(_users_with(c, hid, "security.manage")) - {ctx.user_id}:
                queue_notification(c, hid, "in_app", str(uid), f"{sev.title()} security incident", f"{number}: {cat.replace('_', ' ')} at {ctx.field('location', kind=str)}",
                                   "security_incident", iid)
        audit(c, ctx, "security.incident_recorded", "security_incident", iid, number, new={"category": cat, "severity": sev}, hotel_id=hid)
    return {"id": iid, "number": number, "_created": True}


@route("GET", "/api/incidents/{incident_id:int}", perm="security.view", tag="security", summary="Incident with investigation notes")
def get_incident(ctx: Ctx):
    with get_db().tx() as c:
        i = _incident(c, ctx, ctx.path["incident_id"])
        i["notes"] = c.all("SELECT n.*, u.full_name AS by_name FROM incident_notes n JOIN users u ON u.id = n.created_by WHERE n.incident_id = ? ORDER BY n.id", [i["id"]])
        i["reported_by_name"] = c.scalar("SELECT full_name FROM users WHERE id = ?", [i["reported_by"]])
        i["assigned_to_name"] = c.scalar("SELECT full_name FROM users WHERE id = ?", [i["assigned_to"]]) if i["assigned_to"] else None
    return i


@route("POST", "/api/incidents/{incident_id:int}/update", perm="security.manage", tag="security",
       summary="Investigate: add a note, assign, set status (investigating / resolved needs resolution / closed)")
def update_incident(ctx: Ctx):
    with get_db().tx() as c:
        i = _incident(c, ctx, ctx.path["incident_id"])
        if i["status"] == "closed":
            raise conflict("This incident is closed")
        data: dict = {}
        b = ctx.body or {}
        if "assigned_to" in b:
            data["assigned_to"] = int(b["assigned_to"]) if b["assigned_to"] else None
        if "police_reference" in b:
            data["police_reference"] = b["police_reference"] or None
        if "status" in b and b["status"] != i["status"]:
            st = b["status"]
            if st not in ("investigating", "resolved", "closed"):
                raise bad_request("status must be investigating, resolved or closed")
            if st in ("resolved", "closed"):
                data["resolution"] = ctx.field("resolution", required=not i["resolution"], kind=str) or i["resolution"]
                data["resolved_at"] = i["resolved_at"] or now_iso()
            data["status"] = st
        if b.get("note"):
            c.insert("incident_notes", {"incident_id": i["id"], "note": str(b["note"]), "created_by": ctx.user_id, "created_at": now_iso()})
        if data:
            c.update("security_incidents", i["id"], data)
        audit(c, ctx, "security.incident_updated", "security_incident", i["id"], i["number"], old={k: i.get(k) for k in data}, new={**data, "note": bool(b.get("note"))},
              hotel_id=i["hotel_id"])
    return {"ok": True}


# ------------------------------------------------------------------ visitors & contractors
@route("GET", "/api/hotels/{hotel_id:int}/visitors", perm="security.view", tag="security", summary="Visitor & contractor log (?date, ?on_site=1)")
def list_visitors(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql, params = "SELECT v.*, u.full_name AS recorded_by_name FROM visitors v JOIN users u ON u.id = v.recorded_by WHERE v.hotel_id = ?", [hid]
    if ctx.q("on_site") == "1":
        sql += " AND v.time_out IS NULL"
    elif ctx.q("date"):
        sql += " AND v.time_in >= ? AND v.time_in < ?"
        d = parse_date(ctx.q("date"), "date")
        params += [d.isoformat(), (d + dt.timedelta(days=1)).isoformat()]
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY v.time_in DESC LIMIT 300", params)
    if not ctx.can("security.manage"):
        for r in rows:
            r["id_number"] = _mask(r["id_number"])
    return {"items": rows, "on_site": sum(1 for r in rows if not r["time_out"])}


@route("POST", "/api/hotels/{hotel_id:int}/visitors", perm="security.manage", tag="security", summary="Sign a visitor, contractor or delivery in")
def sign_in(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    kind = ctx.field("kind", required=False, default="visitor", kind=str)
    if kind not in ("visitor", "contractor", "delivery"):
        raise bad_request("kind must be visitor, contractor or delivery")
    with get_db().tx() as c:
        vid = c.insert("visitors", {"hotel_id": hid, "kind": kind, "name": ctx.field("name", kind=str), "phone": ctx.field("phone", required=False, kind=str),
                                    "company": ctx.field("company", required=False, kind=str), "id_type": ctx.field("id_type", required=False, kind=str),
                                    "id_number": ctx.field("id_number", required=False, kind=str), "host": ctx.field("host", required=False, kind=str),
                                    "purpose": ctx.field("purpose", required=False, kind=str), "badge_no": ctx.field("badge_no", required=False, kind=str),
                                    "vehicle_plate": ctx.field("vehicle_plate", required=False, kind=str), "time_in": now_iso(), "recorded_by": ctx.user_id})
        audit(c, ctx, "security.visitor_in", "visitor", vid, ctx.field("name", kind=str), hotel_id=hid)
    return {"id": vid, "_created": True}


@route("POST", "/api/visitors/{visitor_id:int}/sign-out", perm="security.manage", tag="security", summary="Sign a visitor out")
def sign_out(ctx: Ctx):
    with get_db().tx() as c:
        v = c.one("SELECT * FROM visitors WHERE id = ?", [ctx.path["visitor_id"]])
        if not v:
            raise not_found("Visitor")
        ctx.check_hotel(v["hotel_id"])
        if v["time_out"]:
            raise conflict("Already signed out")
        c.update("visitors", v["id"], {"time_out": now_iso()})
    return {"ok": True}


# ------------------------------------------------------------------ lost & found
@route("GET", "/api/hotels/{hotel_id:int}/lost-found", perm="lostfound.manage", tag="security", summary="Lost & found register (?status, ?q)")
def list_lost_found(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT l.*, u.full_name AS found_by_name, r.number AS room_number, rb.full_name AS released_by_name FROM lost_found l JOIN users u ON u.id = l.found_by "
           "LEFT JOIN rooms r ON r.id = l.room_id LEFT JOIN users rb ON rb.id = l.released_by WHERE l.hotel_id = ?")
    params: list = [hid]
    if ctx.q("status"):
        sql += " AND l.status = ?"
        params.append(ctx.q("status"))
    if ctx.q("q"):
        sql += " AND LOWER(l.description) LIKE ?"
        params.append(f"%{ctx.q('q').lower()}%")
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY l.found_at DESC LIMIT 300", params)
        today = business_date(get_hotel(c, hid)).isoformat()
    for r in rows:
        r["due_for_disposal"] = r["status"] == "stored" and r["dispose_after"] <= today
    return {"items": rows, "categories": LF_CATEGORIES}


@route("POST", "/api/hotels/{hotel_id:int}/lost-found", perm="lostfound.manage", tag="security",
       summary="Log a found item (description, category, location, room_id, valuable, stored_location); kept 90 days (180 if valuable)")
def log_found(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    cat = ctx.field("category", kind=str)
    if cat not in LF_CATEGORIES:
        raise bad_request(f"category must be one of {', '.join(LF_CATEGORIES)}")
    valuable = 1 if ctx.field("valuable", required=False, default=False) or cat in ("jewellery", "cash", "documents", "electronics") else 0
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        room = ctx.field("room_id", required=False, kind=int)
        guest = None
        if room:
            r = c.one("SELECT guest_id FROM reservations WHERE room_id = ? AND hotel_id = ? AND status IN ('checked_in','checked_out') ORDER BY departure DESC LIMIT 1", [room, hid])
            guest = r["guest_id"] if r else None
        number = next_number(c, hid, "lost_found", "LF")
        lid = c.insert("lost_found", {"hotel_id": hid, "number": number, "found_at": now_iso(), "location": ctx.field("location", kind=str), "room_id": room,
                                      "description": ctx.field("description", kind=str)[:300], "category": cat, "valuable": valuable,
                                      "stored_location": ctx.field("stored_location", required=False, kind=str) or ("Security safe" if valuable else "Lost property store"),
                                      "found_by": ctx.user_id, "guest_id": guest, "status": "stored",
                                      "dispose_after": (today + dt.timedelta(days=180 if valuable else 90)).isoformat(), "notes": ctx.field("notes", required=False, kind=str)})
        audit(c, ctx, "lostfound.logged", "lost_found", lid, number, new=ctx.body, hotel_id=hid)
    return {"id": lid, "number": number, "likely_owner_guest_id": guest, "_created": True}


@route("POST", "/api/lost-found/{item_id:int}/release", perm="lostfound.manage", tag="security",
       summary="Return an item to its owner (claimant name & contact, ID checked required for valuables) or dispose/donate after the holding period")
def release(ctx: Ctx):
    outcome = ctx.field("outcome", kind=str)
    if outcome not in ("returned", "disposed", "donated"):
        raise bad_request("outcome must be returned, disposed or donated")
    with get_db().tx() as c:
        l = c.lock("lost_found", int(ctx.path["item_id"]))
        if not l:
            raise not_found("Item")
        ctx.check_hotel(l["hotel_id"])
        if l["status"] != "stored":
            raise conflict(f"This item was already {l['status']}")
        data = {"status": outcome, "released_by": ctx.user_id, "released_at": now_iso()}
        if outcome == "returned":
            data["claimant_name"] = ctx.field("claimant_name", kind=str)
            data["claimant_contact"] = ctx.field("claimant_contact", kind=str)
            checked = bool(ctx.field("claimant_id_checked", required=False, default=False))
            if l["valuable"] and not checked:
                raise bad_request("Check and record the claimant's ID before releasing a valuable item")
            data["claimant_id_checked"] = 1 if checked else 0
        else:
            today = business_date(get_hotel(c, l["hotel_id"])).isoformat()
            if l["dispose_after"] > today:
                raise conflict(f"This item must be kept until {l['dispose_after']}")
            if l["valuable"]:
                ctx.require("security.manage")
        c.update("lost_found", l["id"], data)
        audit(c, ctx, f"lostfound.{outcome}", "lost_found", l["id"], l["number"], new=data, hotel_id=l["hotel_id"])
    return {"status": outcome}


# ------------------------------------------------------------------ emergency contacts
@route("GET", "/api/hotels/{hotel_id:int}/emergency-contacts", tag="security", summary="Emergency contacts (any signed-in staff member)")
def emergency_contacts(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": c.all("SELECT * FROM emergency_contacts WHERE hotel_id = ? ORDER BY sort_order, id", [hid]),
                "hotel_emergency": get_hotel(c, hid).get("emergency_contact")}


@route("PUT", "/api/hotels/{hotel_id:int}/emergency-contacts", perm="security.manage", tag="security", summary="Replace the emergency contact list: items[{name, role, phone, notes}]")
def save_emergency_contacts(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    items = ctx.field("items", required=False) or []
    with get_db().tx() as c:
        c.execute("DELETE FROM emergency_contacts WHERE hotel_id = ?", [hid])
        for i, x in enumerate(items):
            if not (x.get("name") and x.get("role") and x.get("phone")):
                raise bad_request("Each contact needs a name, role and phone")
            c.insert("emergency_contacts", {"hotel_id": hid, "name": x["name"][:150], "role": x["role"][:100], "phone": x["phone"][:50], "notes": (x.get("notes") or "")[:200] or None,
                                            "sort_order": i})
        audit(c, ctx, "security.emergency_contacts", "emergency_contacts", hid, new={"count": len(items)}, hotel_id=hid)
    return {"ok": True}


# ------------------------------------------------------------------ access control / key cards (integration intake)
@route("POST", "/api/integrations/access-events", public=True, rate_limit=600, tag="security",
       summary="Door-lock, key-card, access-control and CCTV systems push events here (header X-EHMS-Integration-Token); "
               "CCTV sends source=cctv, door=camera name, event=motion|tamper|alarm and an optional https clip_url")
def access_events_in(ctx: Ctx):
    token = os.environ.get("EHMS_ACCESS_API_TOKEN", "")
    if not token or not hmac.compare_digest(token, ctx.request.headers.get("x-ehms-integration-token", "")):
        raise ApiError(401, "invalid_token", "Invalid or missing integration token")
    events = ctx.field("events")
    if not isinstance(events, list) or not events or len(events) > 500:
        raise bad_request("Send 1–500 events")
    with get_db().tx() as c:
        hotel = c.one("SELECT id FROM hotels WHERE upper(code) = ?", [str(ctx.field("hotel_code", kind=str)).upper()])
        if not hotel:
            raise bad_request("Unknown hotel_code")
        for e in events:
            if not e.get("door") or not e.get("event") or not e.get("occurred_at"):
                raise bad_request("Each event needs door, event and occurred_at")
            c.insert("access_events", {"hotel_id": hotel["id"], "source": str(ctx.field("source", required=False, default="lock-system"))[:40], "door": str(e["door"])[:80],
                                       "credential": (str(e.get("credential") or ""))[:80] or None, "person": (str(e.get("person") or ""))[:150] or None,
                                       "event": str(e["event"])[:30], "occurred_at": str(e["occurred_at"]), "received_at": now_iso(),
                                       "clip_url": (str(e.get("clip_url") or "")[:500] if str(e.get("clip_url") or "").startswith("https://") else None)})
    return {"accepted": len(events)}


@route("GET", "/api/hotels/{hotel_id:int}/access-events", perm="security.view", tag="security", summary="Access-control event log (?door, ?date)")
def access_events(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql, params = "SELECT * FROM access_events WHERE hotel_id = ?", [hid]
    if ctx.q("door"):
        sql += " AND door = ?"
        params.append(ctx.q("door"))
    if ctx.q("date"):
        sql += " AND occurred_at >= ? AND occurred_at < ?"
        d = parse_date(ctx.q("date"), "date")
        params += [d.isoformat(), (d + dt.timedelta(days=1)).isoformat()]
    with get_db().tx() as c:
        return {"items": c.all(sql + " ORDER BY occurred_at DESC LIMIT 500", params), "integration_configured": bool(os.environ.get("EHMS_ACCESS_API_TOKEN"))}
