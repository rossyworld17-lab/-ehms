"""Hotels/branches, departments, taxes, payment methods and notification log. (FR-ADM-004/005, FR-PRP-001..005)"""
from __future__ import annotations

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import account_id, business_date, parse_date

HOTEL_FIELDS = ("name", "legal_name", "registration_number", "category", "star_rating", "address", "city", "state", "country",
                "phone", "email", "website", "emergency_contact", "floors", "timezone", "currency", "check_in_time", "check_out_time",
                "cancellation_policy", "reservation_policy", "terms", "amenities", "service_charge_bp")

DEFAULT_DEPARTMENTS = [("FO", "Front Office"), ("HK", "Housekeeping"), ("FNB", "Food & Beverage"), ("KIT", "Kitchen"),
                       ("ACC", "Accounts"), ("HR", "Human Resources"), ("MNT", "Maintenance"), ("SEC", "Security"),
                       ("SAL", "Sales & Marketing"), ("IT", "IT"), ("STR", "Stores & Procurement"), ("LDY", "Laundry")]


def seed_hotel_defaults(c, hotel_id: int, organisation_id: int) -> None:
    for code, name in DEFAULT_DEPARTMENTS:
        if not c.one("SELECT id FROM departments WHERE hotel_id = ? AND code = ?", [hotel_id, code]):
            c.insert("departments", {"hotel_id": hotel_id, "code": code, "name": name})
    methods = [("CASH", "Cash", "cash", "cash"), ("TRANSFER", "Bank Transfer", "bank_transfer", "bank"),
               ("POS", "Card (POS Terminal)", "card_pos", "card_clearing"), ("CITY", "City Ledger (Company Account)", "city_ledger", "city_ledger")]
    for code, name, kind, key in methods:
        if not c.one("SELECT id FROM payment_methods WHERE hotel_id = ? AND code = ?", [hotel_id, code]):
            c.insert("payment_methods", {"hotel_id": hotel_id, "code": code, "name": name, "kind": kind,
                                         "account_id": account_id(c, organisation_id, key), "active": 1})


def _hotel_out(c, h: dict) -> dict:
    h = dict(h)
    h["business_date"] = business_date(h).isoformat()
    h["room_count"] = c.scalar("SELECT COUNT(*) FROM rooms WHERE hotel_id = ? AND active = 1", [h["id"]])
    h["active"] = bool(h["active"])
    return h


@route("GET", "/api/hotels", tag="property", summary="Hotels the current user can access")
def list_hotels(ctx: Ctx):
    with get_db().tx() as c:
        rows = c.all("SELECT * FROM hotels WHERE organisation_id = ? ORDER BY name", [ctx.org_id])
        if ctx.hotel_ids is not None:
            rows = [r for r in rows if r["id"] in ctx.hotel_ids]
        return {"items": [_hotel_out(c, h) for h in rows]}


@route("GET", "/api/hotels/{hotel_id:int}", tag="property", summary="Hotel profile and configuration")
def get_hotel(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        h = c.one("SELECT * FROM hotels WHERE id = ? AND organisation_id = ?", [hid, ctx.org_id])
        if not h:
            raise not_found("Hotel")
        out = _hotel_out(c, h)
        out["departments"] = c.all("SELECT * FROM departments WHERE hotel_id = ? ORDER BY name", [hid])
        return out


@route("POST", "/api/hotels", perm="property.manage", tag="property", summary="Register a hotel or branch")
def create_hotel(ctx: Ctx):
    if ctx.hotel_ids is not None:
        raise forbidden("Only organisation-wide administrators can register new properties")
    code = ctx.field("code", kind=str).upper()
    data = {f: ctx.body.get(f) for f in HOTEL_FIELDS if f in ctx.body}
    data.setdefault("name", ctx.field("name", kind=str))
    with get_db().tx() as c:
        if c.one("SELECT id FROM hotels WHERE organisation_id = ? AND code = ?", [ctx.org_id, code]):
            raise conflict("A hotel with this code already exists")
        hid = c.insert("hotels", {"organisation_id": ctx.org_id, "code": code, "created_at": now_iso(), **data})
        seed_hotel_defaults(c, hid, ctx.org_id)
        audit(c, ctx, "hotel.created", "hotel", hid, code, new=data, hotel_id=hid)
        out = _hotel_out(c, c.one("SELECT * FROM hotels WHERE id = ?", [hid]))
    out["_created"] = True
    return out


@route("PATCH", "/api/hotels/{hotel_id:int}", perm="admin.settings.manage", tag="property", summary="Update hotel profile and policies")
def update_hotel(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    data = {f: ctx.body.get(f) for f in HOTEL_FIELDS if isinstance(ctx.body, dict) and f in ctx.body}
    if "service_charge_bp" in data and not (0 <= int(data["service_charge_bp"] or 0) <= 5000):
        raise bad_request("service_charge_bp must be between 0 and 5000 (0–50%)")
    with get_db().tx() as c:
        h = c.one("SELECT * FROM hotels WHERE id = ? AND organisation_id = ?", [hid, ctx.org_id])
        if not h:
            raise not_found("Hotel")
        c.update("hotels", hid, data)
        audit(c, ctx, "hotel.updated", "hotel", hid, h["code"], old={k: h[k] for k in data}, new=data, hotel_id=hid)
        return _hotel_out(c, c.one("SELECT * FROM hotels WHERE id = ?", [hid]))


@route("POST", "/api/hotels/{hotel_id:int}/departments", perm="admin.settings.manage", tag="property", summary="Add a department")
def add_department(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        did = c.insert("departments", {"hotel_id": hid, "code": ctx.field("code", kind=str).upper(), "name": ctx.field("name", kind=str)})
        audit(c, ctx, "department.created", "department", did, hotel_id=hid)
    return {"id": did, "_created": True}


# ------------------------------------------------------------- taxes
@route("GET", "/api/hotels/{hotel_id:int}/taxes", tag="finance", summary="Tax and levy rules")
def list_taxes(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": c.all("SELECT * FROM tax_rules WHERE hotel_id = ? ORDER BY effective_from DESC, code", [hid])}


@route("POST", "/api/hotels/{hotel_id:int}/taxes", perm="admin.settings.manage", tag="finance",
       summary="Add a tax rule (rate in basis points, e.g. 750 = 7.5%)")
def add_tax(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    rate = ctx.field("rate_bp", kind=int)
    if not 0 <= rate <= 10000:
        raise bad_request("rate_bp must be between 0 and 10000")
    applies = ctx.field("applies_to", required=False, default="all")
    if applies not in ("all", "room", "fnb", "laundry", "events", "other"):
        raise bad_request("applies_to must be all, room, fnb, laundry, events or other")
    eff_from = parse_date(ctx.field("effective_from"), "effective_from").isoformat()
    eff_to = ctx.field("effective_to", required=False)
    with get_db().tx() as c:
        tid = c.insert("tax_rules", {"hotel_id": hid, "code": ctx.field("code", kind=str).upper(), "name": ctx.field("name", kind=str),
                                     "rate_bp": rate, "applies_to": applies, "is_inclusive": 1 if ctx.field("is_inclusive", required=False) else 0,
                                     "effective_from": eff_from, "effective_to": parse_date(eff_to, "effective_to").isoformat() if eff_to else None, "active": 1})
        audit(c, ctx, "tax.created", "tax_rule", tid, new=ctx.body, hotel_id=hid)
    return {"id": tid, "_created": True}


@route("PATCH", "/api/taxes/{tax_id:int}", perm="admin.settings.manage", tag="finance", summary="End-date or deactivate a tax rule")
def update_tax(ctx: Ctx):
    with get_db().tx() as c:
        t = c.one("SELECT * FROM tax_rules WHERE id = ?", [ctx.path["tax_id"]])
        if not t:
            raise not_found("Tax rule")
        ctx.check_hotel(t["hotel_id"])
        data = {}
        if "effective_to" in (ctx.body or {}):
            v = ctx.body["effective_to"]
            data["effective_to"] = parse_date(v, "effective_to").isoformat() if v else None
        if "active" in (ctx.body or {}):
            data["active"] = 1 if ctx.body["active"] else 0
        c.update("tax_rules", t["id"], data)
        audit(c, ctx, "tax.updated", "tax_rule", t["id"], old={k: t[k] for k in data}, new=data, hotel_id=t["hotel_id"])
    return {"ok": True}


# ------------------------------------------------------------- payment methods
@route("GET", "/api/hotels/{hotel_id:int}/payment-methods", tag="finance", summary="Payment methods")
def list_payment_methods(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": c.all("SELECT pm.*, a.code AS account_code, a.name AS account_name FROM payment_methods pm "
                               "JOIN accounts a ON a.id = pm.account_id WHERE pm.hotel_id = ? ORDER BY pm.name", [hid])}


@route("POST", "/api/hotels/{hotel_id:int}/payment-methods", perm="admin.settings.manage", tag="finance", summary="Add a payment method")
def add_payment_method(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    kind = ctx.field("kind", kind=str)
    if kind not in ("cash", "bank_transfer", "card_pos", "online", "city_ledger"):
        raise bad_request("Invalid payment method kind")
    with get_db().tx() as c:
        acc = c.one("SELECT id FROM accounts WHERE id = ? AND organisation_id = ? AND type = 'asset'", [ctx.field("account_id", kind=int), ctx.org_id])
        if not acc:
            raise bad_request("account_id must be an asset account in your chart of accounts")
        pid = c.insert("payment_methods", {"hotel_id": hid, "code": ctx.field("code", kind=str).upper(), "name": ctx.field("name", kind=str),
                                           "kind": kind, "account_id": acc["id"], "active": 1})
        audit(c, ctx, "payment_method.created", "payment_method", pid, hotel_id=hid)
    return {"id": pid, "_created": True}


@route("GET", "/api/hotels/{hotel_id:int}/notifications", perm="admin.settings.manage", tag="admin",
       summary="Outgoing notification log with delivery status")
def list_notifications(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": c.all("SELECT * FROM notifications WHERE hotel_id = ? OR hotel_id IS NULL ORDER BY id DESC LIMIT 200", [hid])}
