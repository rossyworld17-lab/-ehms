"""Billing extensions (FR-RES-004, FR-FO-005, FR-FIN-005, FR-ADM-005, FR-PRP-005):

* cancellation policies with automatic cancellation / no-show fees (waiver needs a permission and a reason);
* exchange rates and foreign-currency payments, converted to the hotel's base currency at the day's rate;
* additional folios for a stay (e.g. a company bill) and transfers of charges between folios — append-only:
  the source gets a reversing line, the target a new line, both linked by a transfer reference;
* credit and debit notes: numbered documents approved by a second person and posted to a folio with the same
  tax split as the original charge (a closed folio is reopened so any refund or payment follows normal rules).
"""
from __future__ import annotations

import datetime as dt
import json
import secrets

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import (REVENUE_KEYS, account_id, business_date, get_hotel, next_number, parse_date, post_journal, price_breakdown,
                        to_minor)

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

FEE_TYPES = ("none", "first_night", "percent", "fixed")


# ------------------------------------------------------------------ cancellation policies
def policy_for(c, r: dict) -> dict | None:
    if r.get("cancellation_policy_id"):
        return c.one("SELECT * FROM cancellation_policies WHERE id = ?", [r["cancellation_policy_id"]])
    return c.one("SELECT * FROM cancellation_policies WHERE hotel_id = ? AND is_default = 1 AND active = 1", [r["hotel_id"]])


def _hotel_now(hotel: dict) -> dt.datetime:
    tz = None
    if ZoneInfo:
        try:
            tz = ZoneInfo(hotel.get("timezone") or "Africa/Lagos")
        except Exception:  # pragma: no cover
            tz = None
    return dt.datetime.now(tz or dt.timezone(dt.timedelta(hours=1))).replace(tzinfo=None)


def fee_for(c, hotel: dict, r: dict, kind: str, now: dt.datetime | None = None) -> dict:
    """Fee due if reservation r were cancelled now (kind='cancel') or marked no-show (kind='no_show')."""
    from ..pricing import stay_night_rate
    pol = policy_for(c, r)
    if not pol:
        return {"fee": 0, "policy": None, "explanation": "No cancellation policy applies to this booking."}
    ftype, fval = (pol["fee_type"], pol["fee_value"]) if kind == "cancel" else (pol["no_show_fee_type"], pol["no_show_fee_value"])
    arrival = dt.date.fromisoformat(r["arrival"])
    hh, mm = (hotel.get("check_in_time") or "14:00").split(":")
    arrive_at = dt.datetime.combine(arrival, dt.time(int(hh), int(mm)))
    deadline = arrive_at - dt.timedelta(hours=pol["free_until_hours"])
    now = now or _hotel_now(hotel)
    view = {"policy": {"id": pol["id"], "name": pol["name"], "free_until_hours": pol["free_until_hours"]}, "free_until": deadline.isoformat(timespec="minutes")}
    if kind == "cancel" and now <= deadline:
        return {**view, "fee": 0, "explanation": f"Free cancellation until {deadline:%d %b %Y %H:%M} (hotel time)."}
    rt = c.one("SELECT * FROM room_types WHERE id = ?", [r["room_type_id"]])
    nights = [arrival + dt.timedelta(days=i) for i in range((dt.date.fromisoformat(r["departure"]) - arrival).days)]
    if ftype == "none":
        fee, how = 0, "no fee"
    elif ftype == "first_night":
        fee, how = stay_night_rate(c, r, rt, arrival), "first night's room rate"
    elif ftype == "percent":
        total = sum(stay_night_rate(c, r, rt, n) for n in nights)
        fee, how = total * fval // 10000, f"{fval / 100:g}% of the room total"
    else:
        fee, how = fval, "fixed fee"
    label = "Cancellation" if kind == "cancel" else "No-show"
    return {**view, "fee": fee, "fee_type": ftype,
            "explanation": f"{label} fee: {how}" + (f" (the free-cancellation deadline was {deadline:%d %b %Y %H:%M})." if kind == "cancel" else ".")}


def apply_fee(c, ctx: Ctx, hotel: dict, r: dict, kind: str, waive_reason: str | None) -> dict:
    """Post the fee to the stay's folio, or record a waiver. Returns the fee view."""
    from .frontoffice import ensure_folio, post_charge
    info = fee_for(c, hotel, r, kind)
    if info["fee"] <= 0:
        return info
    if waive_reason:
        if not ctx.can("reservations.waive_fee"):
            raise forbidden("Waiving a fee requires the reservations.waive_fee permission")
        if len(waive_reason.strip()) < 5:
            raise bad_request("Give a reason for waiving the fee")
        c.update("reservations", r["id"], {"cancellation_fee": 0, "fee_waived_by": ctx.user_id, "fee_waive_reason": waive_reason.strip()[:300]})
        audit(c, ctx, "reservation.fee_waived", "reservation", r["id"], r["reference"], new={"kind": kind, "fee": info["fee"], "reason": waive_reason}, hotel_id=r["hotel_id"])
        return {**info, "waived": True}
    f = ensure_folio(c, r)
    if f["status"] != "open":
        c.update("folios", f["id"], {"status": "open", "closed_at": None})
        f = c.one("SELECT * FROM folios WHERE id = ?", [f["id"]])
    label = "Cancellation fee" if kind == "cancel" else "No-show fee"
    post_charge(c, ctx, hotel, f, "other", f"{label} — {r['reference']}", info["fee"], reference=f"FEE:{kind}:{r['id']}")
    c.update("reservations", r["id"], {"cancellation_fee": info["fee"]})
    return {**info, "posted_to_folio": f["number"]}


def _policy_view(p: dict) -> dict:
    return dict(p)


@route("GET", "/api/hotels/{hotel_id:int}/cancellation-policies", perm="reservations.view", tag="reservations", summary="Cancellation policies")
def list_policies(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": [_policy_view(p) for p in c.all("SELECT * FROM cancellation_policies WHERE hotel_id = ? ORDER BY is_default DESC, name", [hid])]}


@route("POST", "/api/hotels/{hotel_id:int}/cancellation-policies", perm="admin.settings.manage", tag="reservations",
       summary="Create a cancellation policy (name, free_until_hours, fee_type none|first_night|percent|fixed, fee_value, no_show_fee_type, no_show_fee_value, is_default)")
def create_policy(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    data = _policy_input(ctx)
    with get_db().tx() as c:
        if data.get("is_default"):
            c.execute("UPDATE cancellation_policies SET is_default = 0 WHERE hotel_id = ?", [hid])
        pid = c.insert("cancellation_policies", {"hotel_id": hid, **data, "active": 1, "created_at": now_iso()})
        audit(c, ctx, "cancellation_policy.created", "cancellation_policy", pid, data["name"], new=data, hotel_id=hid)
    return {"id": pid, "_created": True}


@route("PATCH", "/api/cancellation-policies/{policy_id:int}", perm="admin.settings.manage", tag="reservations", summary="Change a cancellation policy (applies to bookings made afterwards)")
def update_policy(ctx: Ctx):
    data = _policy_input(ctx, partial=True)
    with get_db().tx() as c:
        p = c.one("SELECT * FROM cancellation_policies WHERE id = ?", [ctx.path["policy_id"]])
        if not p:
            raise not_found("Policy")
        ctx.check_hotel(p["hotel_id"])
        if c.one("SELECT id FROM reservations WHERE cancellation_policy_id = ? LIMIT 1", [p["id"]]) and any(k.startswith(("fee", "free", "no_show")) for k in data):
            raise conflict("Bookings already use this policy; create a new policy instead so their terms do not change")
        if data.get("is_default"):
            c.execute("UPDATE cancellation_policies SET is_default = 0 WHERE hotel_id = ?", [p["hotel_id"]])
        c.update("cancellation_policies", p["id"], data)
        audit(c, ctx, "cancellation_policy.updated", "cancellation_policy", p["id"], p["name"], old=p, new=data, hotel_id=p["hotel_id"])
    return {"ok": True}


def _policy_input(ctx: Ctx, partial: bool = False) -> dict:
    b = ctx.body or {}
    out = {}
    if not partial or "name" in b:
        out["name"] = ctx.field("name", kind=str)[:100]
    for k in ("fee_type", "no_show_fee_type"):
        if k in b:
            if b[k] not in FEE_TYPES:
                raise bad_request(f"{k} must be one of {', '.join(FEE_TYPES)}")
            out[k] = b[k]
    for k in ("free_until_hours",):
        if k in b:
            v = int(b[k])
            if v < 0 or v > 24 * 60:
                raise bad_request("free_until_hours must be between 0 and 1440")
            out[k] = v
    for k in ("fee_value", "no_show_fee_value"):
        if k in b:
            out[k] = to_minor(b[k], k)
    for k, tk in (("fee_value", "fee_type"), ("no_show_fee_value", "no_show_fee_type")):
        if out.get(tk) == "percent" and not 0 < out.get(k, 0) <= 10000:
            raise bad_request(f"{k} for a percentage fee is in basis points (1–10000)")
    if "is_default" in b:
        out["is_default"] = 1 if b["is_default"] else 0
    if "active" in b:
        out["active"] = 1 if b["active"] else 0
    return out


@route("GET", "/api/reservations/{res_id:int}/cancellation-fee", perm="reservations.view", tag="reservations",
       summary="Fee that would apply if the booking were cancelled now (?kind=cancel|no_show)")
def fee_preview(ctx: Ctx):
    kind = ctx.q("kind", "cancel")
    if kind not in ("cancel", "no_show"):
        raise bad_request("kind must be cancel or no_show")
    with get_db().tx() as c:
        r = c.one("SELECT * FROM reservations WHERE id = ?", [ctx.path["res_id"]])
        if not r:
            raise not_found("Reservation")
        ctx.check_hotel(r["hotel_id"])
        return fee_for(c, get_hotel(c, r["hotel_id"]), r, kind)


# ------------------------------------------------------------------ exchange rates
def rate_for(c, org_id: int, currency: str, on: dt.date) -> dict | None:
    return c.one("SELECT * FROM exchange_rates WHERE organisation_id = ? AND currency = ? AND rate_date <= ? ORDER BY rate_date DESC LIMIT 1",
                 [org_id, currency.upper(), on.isoformat()])


def convert(foreign_minor: int, rate_micro: int) -> int:
    return (foreign_minor * rate_micro + 500_000) // 1_000_000


@route("GET", "/api/exchange-rates", perm="payments.receive", tag="finance", summary="Latest exchange rates per currency and recent history")
def list_rates(ctx: Ctx):
    with get_db().tx() as c:
        rows = c.all("SELECT x.*, u.full_name AS entered_by FROM exchange_rates x LEFT JOIN users u ON u.id = x.created_by WHERE x.organisation_id = ? "
                     "ORDER BY x.rate_date DESC, x.currency LIMIT 300", [ctx.org_id])
    latest: dict[str, dict] = {}
    for r in rows:
        latest.setdefault(r["currency"], r)
    return {"latest": list(latest.values()), "history": rows}


@route("POST", "/api/exchange-rates", perm="finance.exchange_rates", tag="finance",
       summary="Record an exchange rate (currency, rate = base units per 1 foreign unit as a decimal string, rate_date, source)")
def add_rate(ctx: Ctx):
    cur = ctx.field("currency", kind=str).upper()
    if len(cur) != 3 or not cur.isalpha():
        raise bad_request("currency must be a 3-letter ISO code")
    raw = str(ctx.field("rate")).strip()
    try:
        whole, _, frac = raw.partition(".")
        if not whole.isdigit() or (frac and not frac.isdigit()) or len(frac) > 6:
            raise ValueError
        micro = int(whole) * 1_000_000 + int((frac + "000000")[:6] or 0)
    except ValueError:
        raise bad_request("rate must be a positive decimal number with up to 6 decimals, e.g. 1550.25")
    if micro <= 0:
        raise bad_request("rate must be greater than zero")
    on = parse_date(ctx.field("rate_date", required=False) or dt.date.today().isoformat(), "rate_date")
    with get_db().tx() as c:
        base = c.scalar("SELECT currency FROM hotels WHERE organisation_id = ? ORDER BY id LIMIT 1", [ctx.org_id])
        if cur == base:
            raise bad_request(f"{cur} is the base currency")
        prev = rate_for(c, ctx.org_id, cur, on)
        if prev and str(prev["rate_date"])[:10] == on.isoformat():
            raise conflict(f"A {cur} rate for {on} already exists; rates are not edited once used — record tomorrow's rate instead")
        rid = c.insert("exchange_rates", {"organisation_id": ctx.org_id, "currency": cur, "rate_date": on.isoformat(), "rate_micro": micro,
                                          "source": ctx.field("source", required=False, kind=str), "created_by": ctx.user_id, "created_at": now_iso()})
        change = round((micro - prev["rate_micro"]) * 100 / prev["rate_micro"], 2) if prev else None
        audit(c, ctx, "exchange_rate.recorded", "exchange_rate", rid, cur, new={"rate": raw, "date": on.isoformat(), "change_pct": change})
    out = {"id": rid, "_created": True}
    if change is not None and abs(change) > 10:
        out["warning"] = f"The rate moved {change}% since the previous rate — check it was entered correctly"
    return out


# ------------------------------------------------------------------ extra folios and transfers
def linked_folios(c, r: dict) -> list[dict]:
    return c.all("SELECT * FROM folios WHERE linked_reservation_id = ? ORDER BY id", [r["id"]])


@route("POST", "/api/reservations/{res_id:int}/folios", perm="folio.transfer", tag="folio",
       summary="Open an additional folio for a stay (window_name, bill_to: guest|company, corporate_account_id)")
def open_extra_folio(ctx: Ctx):
    name = ctx.field("window_name", kind=str)[:80]
    with get_db().tx() as c:
        r = c.one("SELECT * FROM reservations WHERE id = ?", [ctx.path["res_id"]])
        if not r:
            raise not_found("Reservation")
        ctx.check_hotel(r["hotel_id"])
        if r["status"] not in ("confirmed", "checked_in"):
            raise conflict("Extra folios can be opened for confirmed or in-house reservations")
        if len(linked_folios(c, r)) >= 4:
            raise conflict("A stay can have at most four additional folios")
        acct = ctx.field("corporate_account_id", required=False)
        if acct and not c.one("SELECT id FROM corporate_accounts WHERE id = ? AND organisation_id = ? AND status = 'active'", [int(acct), ctx.org_id]):
            raise bad_request("Account not found or not active")
        number = next_number(c, r["hotel_id"], "folio", "FOL")
        fid = c.insert("folios", {"hotel_id": r["hotel_id"], "number": number, "reservation_id": None, "linked_reservation_id": r["id"], "guest_id": r["guest_id"],
                                  "window_name": name, "corporate_account_id": int(acct) if acct else r.get("corporate_account_id"), "status": "open", "opened_at": now_iso()})
        audit(c, ctx, "folio.window_opened", "folio", fid, number, new={"reservation": r["reference"], "name": name}, hotel_id=r["hotel_id"])
    return {"id": fid, "number": number, "_created": True}


def _open_folio(c, ctx: Ctx, fid: int) -> dict:
    f = c.one("SELECT * FROM folios WHERE id = ?", [fid])
    if not f:
        raise not_found("Folio")
    ctx.check_hotel(f["hotel_id"])
    if f["status"] != "open":
        raise conflict(f"Folio {f['number']} is closed")
    return f


@route("POST", "/api/folios/{folio_id:int}/transfer", perm="folio.transfer", tag="folio",
       summary="Move charges to another open folio of the same hotel (line_ids, target_folio_id, reason); optional amount to move part of one line")
def transfer(ctx: Ctx):
    ids = ctx.field("line_ids")
    if not isinstance(ids, list) or not ids:
        raise bad_request("Choose at least one charge")
    reason = ctx.field("reason", kind=str)
    part = ctx.field("amount", required=False)
    with get_db().tx() as c:
        src = _open_folio(c, ctx, ctx.path["folio_id"])
        dst = _open_folio(c, ctx, ctx.field("target_folio_id", kind=int))
        if dst["id"] == src["id"] or dst["hotel_id"] != src["hotel_id"]:
            raise bad_request("Choose a different open folio of the same hotel")
        if part is not None and len(ids) != 1:
            raise bad_request("A partial transfer moves part of one charge")
        ref = "TRF-" + secrets.token_hex(4).upper()
        moved = 0
        for lid in ids:
            ln = c.one("SELECT * FROM folio_lines WHERE id = ? AND folio_id = ?", [int(lid), src["id"]])
            if not ln or ln["kind"] != "charge":
                raise bad_request("Only charge lines on this folio can be transferred")
            if c.one("SELECT id FROM folio_lines WHERE reverses_line_id = ?", [ln["id"]]):
                raise conflict(f"“{ln['description']}” was already reversed or transferred")
            net, svc, tax, tot = ln["net_amount"], ln["service_charge"], ln["tax_amount"], ln["total_amount"]
            if part is not None:
                want = to_minor(part, "amount")
                if not 0 < want < tot:
                    raise bad_request("The amount must be more than zero and less than the charge")
                # split proportionally; the remainder stays on the source folio
                net, svc = net * want // tot, svc * want // tot
                tax, tot = want - net - svc, want
            common = {"business_date": ln["business_date"], "department": ln["department"], "quantity": ln["quantity"], "transfer_ref": ref,
                      "posted_by": ctx.user_id, "posted_at": now_iso(), "journal_entry_id": None}
            # source: reversing adjustment (no ledger effect: both folios sit on the guest / city ledger)
            c.insert("folio_lines", {**common, "folio_id": src["id"], "kind": "adjustment", "description": f"Transferred to {dst['number']}: {ln['description']}"[:300],
                                     "net_amount": -net, "service_charge": -svc, "tax_amount": -tax, "total_amount": -tot,
                                     "reference": ln["reference"], "reverses_line_id": ln["id"] if part is None else None})
            c.insert("folio_lines", {**common, "folio_id": dst["id"], "kind": "charge", "description": f"{ln['description']} (from {src['number']})"[:300],
                                     "net_amount": net, "service_charge": svc, "tax_amount": tax, "total_amount": tot, "reference": None})
            moved += tot
        # no journal entry: both folios are receivables on the guest ledger until they are settled
        audit(c, ctx, "folio.transfer", "folio", src["id"], ref, new={"to": dst["number"], "lines": ids, "amount": moved, "reason": reason}, hotel_id=src["hotel_id"])
    return {"transfer_ref": ref, "amount": moved}


# ------------------------------------------------------------------ credit / debit notes
def _note_view(n: dict) -> dict:
    return dict(n)


@route("POST", "/api/folios/{folio_id:int}/notes", perm="finance.notes.request", tag="finance",
       summary="Raise a credit or debit note on a folio (kind credit|debit, department, description, net_amount, reason) — needs approval")
def request_note(ctx: Ctx):
    kind = ctx.field("kind", kind=str)
    if kind not in ("credit", "debit"):
        raise bad_request("kind must be credit or debit")
    dept = ctx.field("department", kind=str)
    if dept not in REVENUE_KEYS:
        raise bad_request(f"department must be one of {', '.join(REVENUE_KEYS)}")
    net = to_minor(ctx.field("net_amount"), "net_amount")
    if net <= 0:
        raise bad_request("net_amount must be greater than zero")
    reason = ctx.field("reason", kind=str)
    if len(reason) < 5:
        raise bad_request("Give a reason")
    with get_db().tx() as c:
        f = c.one("SELECT * FROM folios WHERE id = ?", [ctx.path["folio_id"]])
        if not f:
            raise not_found("Folio")
        ctx.check_hotel(f["hotel_id"])
        hotel = get_hotel(c, f["hotel_id"])
        bd = price_breakdown(c, hotel, "room" if dept == "room" else ("fnb" if dept in ("fnb", "minibar") else dept), net, business_date(hotel))
        if kind == "credit":
            charged = c.scalar("SELECT COALESCE(SUM(net_amount),0) FROM folio_lines WHERE folio_id = ? AND department = ? AND kind IN ('charge','adjustment')", [f["id"], dept]) or 0
            credited = c.scalar("SELECT COALESCE(SUM(net_amount),0) FROM customer_notes WHERE folio_id = ? AND department = ? AND kind = 'credit' AND status = 'pending_approval'",
                                [f["id"], dept]) or 0
            if net + credited > charged:
                raise conflict(f"A credit note cannot exceed what was charged for {dept} on this folio")
        number = next_number(c, f["hotel_id"], "credit_note" if kind == "credit" else "debit_note", "CN" if kind == "credit" else "DN")
        nid = c.insert("customer_notes", {"hotel_id": f["hotel_id"], "number": number, "kind": kind, "folio_id": f["id"], "department": dept,
                                          "description": ctx.field("description", kind=str)[:300], "reason": reason, "net_amount": bd["net"],
                                          "service_charge": bd["service_charge"], "tax_amount": bd["tax"], "total_amount": bd["total"],
                                          "status": "pending_approval", "requested_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, f"{kind}_note.requested", "customer_note", nid, number, new={"folio": f["number"], "total": bd["total"], "reason": reason}, hotel_id=f["hotel_id"])
    return {"id": nid, "number": number, "total": bd["total"], "status": "pending_approval", "_created": True}


@route("GET", "/api/hotels/{hotel_id:int}/notes", perm="folio.view", tag="finance", summary="Credit and debit notes (?status)")
def list_notes(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        sql = ("SELECT n.*, f.number AS folio_number, g.first_name || ' ' || g.last_name AS guest, u.full_name AS requested_by_name, d.full_name AS decided_by_name "
               "FROM customer_notes n JOIN folios f ON f.id = n.folio_id JOIN guests g ON g.id = f.guest_id JOIN users u ON u.id = n.requested_by "
               "LEFT JOIN users d ON d.id = n.decided_by WHERE n.hotel_id = ?")
        params: list = [hid]
        if ctx.q("status"):
            sql += " AND n.status = ?"
            params.append(ctx.q("status"))
        if ctx.q("folio_id"):
            sql += " AND n.folio_id = ?"
            params.append(int(ctx.q("folio_id")))
        return {"items": [_note_view(n) for n in c.all(sql + " ORDER BY n.id DESC LIMIT 300", params)]}


@route("POST", "/api/notes/{note_id:int}/decide", perm="finance.notes.approve", tag="finance",
       summary="Approve or reject a credit/debit note ({decision, note}); approval posts it to the folio and the ledger")
def decide_note(ctx: Ctx):
    decision = ctx.field("decision", kind=str)
    if decision not in ("approve", "reject"):
        raise bad_request("decision must be approve or reject")
    with get_db().tx() as c:
        n = c.one("SELECT * FROM customer_notes WHERE id = ?", [ctx.path["note_id"]])
        if not n:
            raise not_found("Note")
        ctx.check_hotel(n["hotel_id"])
        if n["status"] != "pending_approval":
            raise conflict("This note has already been decided")
        if n["requested_by"] == ctx.user_id:
            raise forbidden("You cannot approve a note you raised")
        note = ctx.field("note", required=decision == "reject", kind=str)
        if decision == "reject":
            c.update("customer_notes", n["id"], {"status": "rejected", "decided_by": ctx.user_id, "decided_at": now_iso(), "decision_note": note})
            audit(c, ctx, f"{n['kind']}_note.rejected", "customer_note", n["id"], n["number"], new={"note": note}, hotel_id=n["hotel_id"])
            return {"status": "rejected"}
        hotel = get_hotel(c, n["hotel_id"])
        f = c.one("SELECT * FROM folios WHERE id = ?", [n["folio_id"]])
        reopened = f["status"] != "open"
        if reopened:
            c.update("folios", f["id"], {"status": "open", "closed_at": None})
        org, on, sign = hotel["organisation_id"], business_date(hotel), (-1 if n["kind"] == "credit" else 1)
        desc = f"{'Credit' if n['kind'] == 'credit' else 'Debit'} note {n['number']}: {n['description']}"
        rev = account_id(c, org, REVENUE_KEYS[n["department"]])
        gl = account_id(c, org, "guest_ledger")
        lines = [(gl, n["total_amount"], 0), (rev, 0, n["net_amount"]), (account_id(c, org, "vat_payable"), 0, n["tax_amount"]),
                 (account_id(c, org, "service_charge_payable"), 0, n["service_charge"])]
        if n["kind"] == "credit":
            lines = [(a, cr, dr) for a, dr, cr in lines]
        je = post_journal(c, n["hotel_id"], on, desc, "customer_note", n["number"], [(a, dr, cr, n["department"], desc) for a, dr, cr in lines], ctx.user_id)
        lid = c.insert("folio_lines", {"folio_id": f["id"], "business_date": on.isoformat(), "kind": "adjustment" if n["kind"] == "credit" else "charge",
                                       "department": n["department"], "description": desc[:300], "quantity": 1, "net_amount": sign * n["net_amount"],
                                       "tax_amount": sign * n["tax_amount"], "service_charge": sign * n["service_charge"], "total_amount": sign * n["total_amount"],
                                       "reference": n["number"], "journal_entry_id": je, "posted_by": ctx.user_id, "posted_at": now_iso()})
        c.update("customer_notes", n["id"], {"status": "approved", "decided_by": ctx.user_id, "decided_at": now_iso(), "decision_note": note,
                                             "folio_line_id": lid, "journal_entry_id": je})
        audit(c, ctx, f"{n['kind']}_note.approved", "customer_note", n["id"], n["number"], new={"folio": f["number"], "reopened": reopened}, hotel_id=n["hotel_id"])
        from .frontoffice import folio_balance
        bal = folio_balance(c, f["id"])["balance"]
    msg = ("The folio now shows a credit; request a refund from the folio if the guest is to be paid back." if n["kind"] == "credit" and bal < 0
           else "The folio now has a balance to collect." if bal > 0 else None)
    return {"status": "approved", "folio_balance": bal, "folio_reopened": reopened, "message": msg}


@route("GET", "/api/notes/{note_id:int}/pdf", perm="folio.view", tag="finance", summary="Credit or debit note as PDF")
def note_pdf(ctx: Ctx):
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from starlette.responses import Response
    with get_db().tx() as c:
        n = c.one("SELECT n.*, f.number AS folio_number, g.first_name, g.last_name, g.company FROM customer_notes n JOIN folios f ON f.id = n.folio_id "
                  "JOIN guests g ON g.id = f.guest_id WHERE n.id = ?", [ctx.path["note_id"]])
        if not n:
            raise not_found("Note")
        ctx.check_hotel(n["hotel_id"])
        hotel = get_hotel(c, n["hotel_id"])
    m = lambda v: f"{hotel['currency']} {v / 100:,.2f}"  # noqa: E731
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    y = 800
    cv.setFont("Helvetica-Bold", 15)
    cv.drawString(50, y, hotel["name"])
    cv.setFont("Helvetica", 9)
    cv.drawString(50, y - 14, " · ".join(x for x in [hotel.get("address"), hotel.get("phone"), hotel.get("tax_id") and f"TIN {hotel['tax_id']}"] if x))
    cv.setFont("Helvetica-Bold", 13)
    title = "CREDIT NOTE" if n["kind"] == "credit" else "DEBIT NOTE"
    cv.drawString(50, y - 50, f"{title} {n['number']}" + ("" if n["status"] == "approved" else f"  ({n['status'].replace('_', ' ').upper()})"))
    cv.setFont("Helvetica", 10)
    rows = [("Customer", f"{n['first_name']} {n['last_name']}" + (f" — {n['company']}" if n["company"] else "")), ("Folio / invoice", n["folio_number"]),
            ("Date", str(n["decided_at"] or n["created_at"])[:10]), ("Description", n["description"]), ("Reason", n["reason"][:90]),
            ("Net", m(n["net_amount"])), ("Service charge", m(n["service_charge"])), ("Tax", m(n["tax_amount"])), ("Total", m(n["total_amount"]))]
    for i, (k, v) in enumerate(rows):
        cv.drawString(50, y - 80 - i * 18, k)
        cv.drawString(180, y - 80 - i * 18, str(v))
    cv.showPage()
    cv.save()
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{n["number"]}.pdf"'})
