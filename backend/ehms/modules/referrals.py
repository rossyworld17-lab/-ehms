"""Guest referral programme (release 1.2): every guest can have a personal referral code; a new guest who books with it
is linked to the referrer, and when that first stay is checked out the referrer (a loyalty member) earns the configured
bonus points. Self-referral, repeat guests and double rewards are refused."""
from __future__ import annotations

import json
import secrets

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, not_found, route
from ..services import hotel_setting, set_hotel_setting

DEFAULT_RULES = {"enabled": True, "points_referrer": 500}
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def referral_rules(c, hid: int) -> dict:
    raw = hotel_setting(c, hid, "crm.referral")
    return {**DEFAULT_RULES, **(json.loads(raw) if raw else {})}


def code_for(c, guest_id: int, create: bool = True) -> str | None:
    row = c.one("SELECT code FROM referral_codes WHERE guest_id = ?", [guest_id])
    if row or not create:
        return row["code"] if row else None
    for _ in range(20):
        code = "REF-" + "".join(secrets.choice(ALPHABET) for _ in range(6))
        if not c.one("SELECT id FROM referral_codes WHERE code = ?", [code]):
            c.insert("referral_codes", {"guest_id": guest_id, "code": code, "created_at": now_iso()})
            return code
    raise conflict("Could not generate a referral code; try again")  # pragma: no cover


def link(c, ctx: Ctx | None, r: dict, code: str) -> dict:
    """Link a reservation to the referrer who owns `code`. Used by the front desk and the booking engine."""
    rules = referral_rules(c, r["hotel_id"])
    if not rules["enabled"]:
        raise conflict("The referral programme is switched off")
    row = c.one("SELECT * FROM referral_codes WHERE upper(code) = ?", [str(code or "").strip().upper()])
    if not row:
        raise bad_request("Unknown referral code")
    if row["guest_id"] == r["guest_id"]:
        raise bad_request("Guests cannot refer themselves")
    if c.one("SELECT id FROM referrals WHERE referred_guest_id = ? AND status <> 'void'", [r["guest_id"]]):
        raise conflict("This guest was already referred")
    if c.one("SELECT id FROM reservations WHERE guest_id = ? AND status = 'checked_out'", [r["guest_id"]]):
        raise conflict("Referrals are for new guests; this guest has stayed before")
    rid = c.insert("referrals", {"hotel_id": r["hotel_id"], "referrer_guest_id": row["guest_id"], "referred_guest_id": r["guest_id"],
                                 "reservation_id": r["id"], "status": "pending", "points": 0, "created_at": now_iso()})
    if ctx:
        audit(c, ctx, "crm.referral_linked", "reservation", r["id"], r["reference"], new={"code": row["code"]}, hotel_id=r["hotel_id"])
    return {"id": rid, "referrer_guest_id": row["guest_id"]}


def reward_on_checkout(c, ctx: Ctx | None, hotel: dict, r: dict) -> int:
    """Called at check-out: credit the referrer's loyalty account once."""
    ref = c.one("SELECT * FROM referrals WHERE reservation_id = ? AND status = 'pending'", [r["id"]])
    if not ref:
        return 0
    rules = referral_rules(c, hotel["id"])
    acct = c.one("SELECT * FROM loyalty_accounts WHERE guest_id = ? AND active = 1", [ref["referrer_guest_id"]])
    if not rules["enabled"] or not acct or rules["points_referrer"] <= 0:
        c.update("referrals", ref["id"], {"status": "void", "rewarded_at": now_iso()})
        return 0
    from .crm import _post_points
    _post_points(c, acct, hotel["id"], "bonus", int(rules["points_referrer"]), r["reference"], f"Referral bonus: guest stay {r['reference']}",
                 ctx.user_id if ctx else None)
    c.update("referrals", ref["id"], {"status": "rewarded", "points": int(rules["points_referrer"]), "rewarded_at": now_iso()})
    return int(rules["points_referrer"])


@route("GET", "/api/guests/{guest_id:int}/referral", perm="guests.view", tag="crm", summary="A guest's referral code and the guests they referred")
def guest_referral(ctx: Ctx):
    with get_db().tx() as c:
        g = c.one("SELECT * FROM guests WHERE id = ? AND organisation_id = ?", [ctx.path["guest_id"], ctx.org_id])
        if not g:
            raise not_found("Guest")
        return {"code": code_for(c, g["id"], create=False),
                "referred": c.all("SELECT f.*, g.first_name, g.last_name, r.reference FROM referrals f JOIN guests g ON g.id = f.referred_guest_id "
                                  "JOIN reservations r ON r.id = f.reservation_id WHERE f.referrer_guest_id = ? ORDER BY f.id DESC", [g["id"]])}


@route("POST", "/api/guests/{guest_id:int}/referral", perm="guests.manage", tag="crm", summary="Create (or return) the guest's personal referral code")
def create_code(ctx: Ctx):
    with get_db().tx() as c:
        g = c.one("SELECT * FROM guests WHERE id = ? AND organisation_id = ?", [ctx.path["guest_id"], ctx.org_id])
        if not g:
            raise not_found("Guest")
        code = code_for(c, g["id"])
        audit(c, ctx, "crm.referral_code", "guest", g["id"], new={"code": code})
    return {"code": code}


@route("POST", "/api/reservations/{res_id:int}/referral", perm="reservations.modify", tag="crm", summary="Record that a booking was referred: code")
def link_reservation(ctx: Ctx):
    with get_db().tx() as c:
        r = c.one("SELECT * FROM reservations WHERE id = ?", [ctx.path["res_id"]])
        if not r:
            raise not_found("Reservation")
        ctx.check_hotel(r["hotel_id"])
        if r["status"] in ("checked_out", "cancelled", "no_show"):
            raise conflict("Referrals are recorded on open bookings")
        out = link(c, ctx, r, ctx.field("code", kind=str))
    return {**out, "_created": True}


@route("GET", "/api/hotels/{hotel_id:int}/referrals", perm="crm.view", tag="crm", summary="Referral programme rules and referrals")
def list_referrals(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        rows = c.all("SELECT f.*, a.first_name AS referrer_first, a.last_name AS referrer_last, b.first_name AS referred_first, b.last_name AS referred_last, "
                     "r.reference FROM referrals f JOIN guests a ON a.id = f.referrer_guest_id JOIN guests b ON b.id = f.referred_guest_id "
                     "JOIN reservations r ON r.id = f.reservation_id WHERE f.hotel_id = ? ORDER BY f.id DESC LIMIT 300", [hid])
        return {"rules": referral_rules(c, hid), "items": rows,
                "summary": {"total": len(rows), "rewarded": sum(1 for x in rows if x["status"] == "rewarded"),
                            "points": sum(x["points"] for x in rows)}}


@route("PUT", "/api/hotels/{hotel_id:int}/referrals/rules", perm="crm.manage", tag="crm", summary="Configure the referral programme: enabled, points_referrer")
def set_rules(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    pts = int(ctx.field("points_referrer", kind=int))
    if pts < 0 or pts > 1_000_000:
        raise bad_request("points_referrer must be 0–1,000,000")
    rules = {"enabled": bool(ctx.field("enabled", required=False, default=True)), "points_referrer": pts}
    with get_db().tx() as c:
        old = referral_rules(c, hid)
        set_hotel_setting(c, hid, "crm.referral", json.dumps(rules))
        audit(c, ctx, "crm.referral_rules", "hotel", hid, old=old, new=rules, hotel_id=hid)
    return rules
