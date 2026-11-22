"""Sales & revenue management: corporate / travel-agent / government accounts with negotiated rates and statements,
sales targets with achievement, seasonal rate adjustments, occupancy-based (dynamic) pricing rules that only take
effect after approval by a second person, competitor rate shopping records, and the revenue dashboard (on-the-books
forecast with pickup, ADR, RevPAR, occupancy, ALOS, booking window, cancellations, year-on-year comparison).
(FR-SAL-001..004, FR-AI-004 rate recommendations)"""
from __future__ import annotations

import calendar
import datetime as dt

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import business_date, get_hotel, parse_date, to_minor

ACCOUNT_KINDS = ("corporate", "travel_agent", "government", "ngo")
METRICS = ("room_revenue", "rooms_sold", "fnb_revenue", "event_revenue", "total_revenue")


# ------------------------------------------------------------------ accounts
@route("GET", "/api/hotels/{hotel_id:int}/accounts/corporate", perm="sales.view", tag="sales", summary="Corporate, travel-agent and government accounts with production")
def list_accounts(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        rows = c.all("SELECT a.*, u.full_name AS account_manager_name FROM corporate_accounts a LEFT JOIN users u ON u.id = a.account_manager "
                     "WHERE a.organisation_id = ? ORDER BY a.status, a.name", [ctx.org_id])
        year = business_date(get_hotel(c, hid)).year
        for a in rows:
            p = c.one("SELECT COUNT(*) AS bookings, COALESCE(SUM(CASE WHEN status IN ('checked_in','checked_out') THEN 1 ELSE 0 END),0) AS stays FROM reservations "
                      "WHERE corporate_account_id = ? AND hotel_id = ? AND arrival >= ?", [a["id"], hid, f"{year}-01-01"])
            rev = c.scalar("SELECT COALESCE(SUM(fl.net_amount),0) FROM folio_lines fl JOIN folios f ON f.id = fl.folio_id JOIN reservations r ON r.id = f.reservation_id "
                           "WHERE r.corporate_account_id = ? AND r.hotel_id = ? AND fl.kind IN ('charge','adjustment') AND fl.business_date >= ?", [a["id"], hid, f"{year}-01-01"]) or 0
            a.update({"ytd_bookings": p["bookings"], "ytd_stays": p["stays"], "ytd_revenue": rev,
                      "commission_due": rev * a["commission_bp"] // 10000 if a["kind"] == "travel_agent" else 0})
    return {"items": rows, "kinds": ACCOUNT_KINDS}


def _acct_payload(ctx: Ctx, partial: bool) -> dict:
    b = ctx.body or {}
    data: dict = {}
    if "name" in b or not partial:
        data["name"] = ctx.field("name", kind=str)
    if "kind" in b:
        if b["kind"] not in ACCOUNT_KINDS:
            raise bad_request("Unknown account kind")
        data["kind"] = b["kind"]
    for k in ("contact_name", "email", "phone", "address", "tax_id", "notes"):
        if k in b:
            data[k] = (str(b[k]).strip() or None) if b[k] is not None else None
    if "credit_limit" in b:
        data["credit_limit"] = to_minor(b["credit_limit"] or 0)
    for k in ("payment_terms_days", "commission_bp"):
        if k in b:
            data[k] = int(b[k] or 0)
    if "status" in b:
        if b["status"] not in ("lead", "prospect", "active", "suspended"):
            raise bad_request("Unknown status")
        data["status"] = b["status"]
    if "account_manager" in b:
        data["account_manager"] = int(b["account_manager"]) if b["account_manager"] else None
    return data


@route("GET", "/api/hotels/{hotel_id:int}/accounts/active", perm="reservations.create", tag="sales", summary="Active accounts for booking (id, name, kind)")
def active_accounts(ctx: Ctx):
    ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": c.all("SELECT id, code, name, kind FROM corporate_accounts WHERE organisation_id = ? AND status = 'active' ORDER BY name", [ctx.org_id])}


@route("POST", "/api/hotels/{hotel_id:int}/accounts/corporate", perm="sales.manage", tag="sales", summary="Create an account (lead, prospect or active)")
def create_account(ctx: Ctx):
    ctx.check_hotel(ctx.path["hotel_id"])
    data = _acct_payload(ctx, partial=False)
    with get_db().tx() as c:
        code = (ctx.field("code", required=False, kind=str) or "".join(w[0] for w in data["name"].split()[:3]).upper() + str(c.scalar("SELECT COUNT(*) FROM corporate_accounts") + 1)).upper()
        if c.one("SELECT id FROM corporate_accounts WHERE organisation_id = ? AND code = ?", [ctx.org_id, code]):
            raise conflict("An account with this code exists")
        aid = c.insert("corporate_accounts", {"organisation_id": ctx.org_id, "code": code, "status": data.pop("status", "active"), "created_at": now_iso(),
                                              "account_manager": data.pop("account_manager", ctx.user_id), **data})
        audit(c, ctx, "sales.account_created", "corporate_account", aid, code, new=ctx.body)
    return {"id": aid, "code": code, "_created": True}


@route("PATCH", "/api/accounts/corporate/{account_id:int}", perm="sales.manage", tag="sales", summary="Edit an account")
def update_account(ctx: Ctx):
    with get_db().tx() as c:
        a = c.one("SELECT * FROM corporate_accounts WHERE id = ? AND organisation_id = ?", [ctx.path["account_id"], ctx.org_id])
        if not a:
            raise not_found("Account")
        data = _acct_payload(ctx, partial=True)
        c.update("corporate_accounts", a["id"], data)
        audit(c, ctx, "sales.account_updated", "corporate_account", a["id"], a["code"], old={k: a[k] for k in data}, new=data)
    return {"ok": True}


@route("GET", "/api/accounts/corporate/{account_id:int}", perm="sales.view", tag="sales", summary="Account with negotiated rates, recent bookings and city-ledger balance")
def get_account(ctx: Ctx):
    with get_db().tx() as c:
        a = c.one("SELECT * FROM corporate_accounts WHERE id = ? AND organisation_id = ?", [ctx.path["account_id"], ctx.org_id])
        if not a:
            raise not_found("Account")
        a["rates"] = c.all("SELECT cr.*, rt.name AS room_type, h.code AS hotel_code FROM corporate_rates cr JOIN room_types rt ON rt.id = cr.room_type_id JOIN hotels h ON h.id = cr.hotel_id "
                           "WHERE cr.account_id = ? ORDER BY cr.valid_to DESC", [a["id"]])
        a["bookings"] = c.all("SELECT r.id, r.reference, r.status, r.arrival, r.departure, g.first_name || ' ' || g.last_name AS guest FROM reservations r JOIN guests g ON g.id = r.guest_id "
                              "WHERE r.corporate_account_id = ? ORDER BY r.arrival DESC LIMIT 50", [a["id"]])
        a["city_ledger"] = c.scalar("SELECT COALESCE(SUM(p.amount),0) FROM payments p JOIN payment_methods pm ON pm.id = p.method_id JOIN folios f ON f.id = p.folio_id "
                                    "JOIN reservations r ON r.id = f.reservation_id WHERE pm.kind = 'city_ledger' AND r.corporate_account_id = ? AND p.kind = 'payment'", [a["id"]]) or 0
        a["over_credit_limit"] = bool(a["credit_limit"] and a["city_ledger"] > a["credit_limit"])
    return a


@route("POST", "/api/accounts/corporate/{account_id:int}/rates", perm="sales.manage", tag="sales",
       summary="Add a negotiated rate (hotel_id, room_type_id, rate, valid_from, valid_to)")
def add_rate(ctx: Ctx):
    with get_db().tx() as c:
        a = c.one("SELECT * FROM corporate_accounts WHERE id = ? AND organisation_id = ?", [ctx.path["account_id"], ctx.org_id])
        if not a:
            raise not_found("Account")
        hid = ctx.check_hotel(ctx.field("hotel_id", kind=int))
        rt = c.one("SELECT * FROM room_types WHERE id = ? AND hotel_id = ?", [ctx.field("room_type_id", kind=int), hid])
        if not rt:
            raise bad_request("Room category not found")
        vf, vt = parse_date(ctx.field("valid_from"), "valid_from"), parse_date(ctx.field("valid_to"), "valid_to")
        if vt < vf:
            raise bad_request("valid_to must be after valid_from")
        rate = to_minor(ctx.field("rate"), "rate")
        rid = c.insert("corporate_rates", {"account_id": a["id"], "hotel_id": hid, "room_type_id": rt["id"], "rate": rate, "valid_from": vf.isoformat(), "valid_to": vt.isoformat()})
        audit(c, ctx, "sales.rate_added", "corporate_rate", rid, a["code"], new={"room_type": rt["code"], "rate": rate, "from": vf.isoformat(), "to": vt.isoformat()}, hotel_id=hid)
    return {"id": rid, "discount_vs_rack_pct": round((rt["base_rate"] - rate) * 100 / rt["base_rate"], 1) if rt["base_rate"] else None, "_created": True}


# ------------------------------------------------------------------ targets
def _actual(c, hid: int, metric: str, first: str, last: str) -> int:
    if metric == "rooms_sold":
        return c.scalar("SELECT COUNT(*) FROM folio_lines fl JOIN folios f ON f.id = fl.folio_id WHERE f.hotel_id = ? AND fl.reference LIKE ? AND fl.kind = 'charge' "
                        "AND fl.business_date >= ? AND fl.business_date <= ?", [hid, "ROOM:%", first, last]) or 0
    dept = {"room_revenue": "= 'room'", "fnb_revenue": "IN ('fnb','minibar')", "event_revenue": "= 'events'", "total_revenue": "IS NOT NULL"}[metric]
    v = c.scalar(f"SELECT COALESCE(SUM(fl.net_amount),0) FROM folio_lines fl JOIN folios f ON f.id = fl.folio_id WHERE f.hotel_id = ? AND fl.kind IN ('charge','adjustment') "
                 f"AND fl.department {dept} AND fl.business_date >= ? AND fl.business_date <= ?", [hid, first, last]) or 0
    if metric in ("fnb_revenue", "total_revenue"):
        from .pos import pos_direct_revenue
        v += pos_direct_revenue(c, hid, first, last)["net"]
    return v


@route("GET", "/api/hotels/{hotel_id:int}/sales/targets", perm="sales.view", tag="sales", summary="Sales targets and achievement for a year (?year)")
def list_targets(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        year = int(ctx.q("year", today.year))
        rows = c.all("SELECT t.*, u.full_name AS owner_name FROM sales_targets t LEFT JOIN users u ON u.id = t.owner_id WHERE t.hotel_id = ? AND t.period LIKE ? ORDER BY t.period, t.metric",
                     [hid, f"{year}-%"])
        for t in rows:
            y, m = int(t["period"][:4]), int(t["period"][5:])
            first, last = dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])
            t["actual"] = _actual(c, hid, t["metric"], first.isoformat(), min(last, today).isoformat())
            t["achieved_pct"] = round(t["actual"] * 100 / t["target"], 1) if t["target"] else None
    return {"year": year, "items": rows, "metrics": METRICS}


@route("PUT", "/api/hotels/{hotel_id:int}/sales/targets", perm="sales.manage", tag="sales", summary="Set a target (period YYYY-MM, metric, target, owner_id)")
def set_target(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    metric = ctx.field("metric", kind=str)
    if metric not in METRICS:
        raise bad_request(f"metric must be one of {', '.join(METRICS)}")
    period = ctx.field("period", kind=str)
    try:
        dt.date.fromisoformat(period + "-01")
    except ValueError:
        raise bad_request("period must be YYYY-MM")
    target = int(ctx.field("target")) if metric == "rooms_sold" else to_minor(ctx.field("target"), "target")
    with get_db().tx() as c:
        row = c.one("SELECT id FROM sales_targets WHERE hotel_id = ? AND period = ? AND metric = ?", [hid, period, metric])
        data = {"target": target, "owner_id": ctx.field("owner_id", required=False, kind=int)}
        if row:
            c.update("sales_targets", row["id"], data)
        else:
            c.insert("sales_targets", {"hotel_id": hid, "period": period, "metric": metric, **data})
        audit(c, ctx, "sales.target_set", "sales_target", f"{period}/{metric}", period, new=data, hotel_id=hid)
    return {"ok": True}


# ------------------------------------------------------------------ seasons & dynamic rules
@route("GET", "/api/hotels/{hotel_id:int}/revenue/pricing", perm="sales.view", tag="sales", summary="Seasons, dynamic pricing rules and competitor rates")
def pricing(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        return {"seasons": c.all("SELECT s.*, rt.name AS room_type FROM rate_seasons s LEFT JOIN room_types rt ON rt.id = s.room_type_id WHERE s.hotel_id = ? ORDER BY s.start_date DESC", [hid]),
                "rules": c.all("SELECT r.*, rt.name AS room_type, u.full_name AS created_by_name, a.full_name AS approved_by_name FROM rate_rules r LEFT JOIN room_types rt ON rt.id = r.room_type_id "
                               "JOIN users u ON u.id = r.created_by LEFT JOIN users a ON a.id = r.approved_by WHERE r.hotel_id = ? ORDER BY r.id DESC", [hid]),
                "competitors": c.all("SELECT cr.*, u.full_name AS recorded_by_name FROM competitor_rates cr JOIN users u ON u.id = cr.recorded_by WHERE cr.hotel_id = ? AND cr.stay_date >= ? "
                                     "ORDER BY cr.stay_date, cr.competitor", [hid, (today - dt.timedelta(days=7)).isoformat()]),
                "room_types": c.all("SELECT id, code, name, base_rate, weekend_rate FROM room_types WHERE hotel_id = ? AND active = 1 ORDER BY base_rate", [hid])}


@route("POST", "/api/hotels/{hotel_id:int}/revenue/seasons", perm="sales.pricing", tag="sales",
       summary="Add a seasonal adjustment (name, start_date, end_date, adjustment_bp e.g. 2000 = +20 %, optional room_type_id)")
def add_season(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    adj = ctx.field("adjustment_bp", kind=int)
    if not -5000 <= adj <= 20000:
        raise bad_request("adjustment_bp must be between −5000 (−50 %) and 20000 (+200 %)")
    a, b = parse_date(ctx.field("start_date"), "start_date"), parse_date(ctx.field("end_date"), "end_date")
    if b < a:
        raise bad_request("end_date must be on or after start_date")
    with get_db().tx() as c:
        sid = c.insert("rate_seasons", {"hotel_id": hid, "name": ctx.field("name", kind=str), "start_date": a.isoformat(), "end_date": b.isoformat(),
                                        "room_type_id": ctx.field("room_type_id", required=False, kind=int), "adjustment_bp": adj, "active": 1, "created_by": ctx.user_id})
        audit(c, ctx, "revenue.season_added", "rate_season", sid, new=ctx.body, hotel_id=hid)
    return {"id": sid, "_created": True}


@route("POST", "/api/revenue/seasons/{season_id:int}/toggle", perm="sales.pricing", tag="sales", summary="Activate or deactivate a season")
def toggle_season(ctx: Ctx):
    with get_db().tx() as c:
        s = c.one("SELECT * FROM rate_seasons WHERE id = ?", [ctx.path["season_id"]])
        if not s:
            raise not_found("Season")
        ctx.check_hotel(s["hotel_id"])
        c.update("rate_seasons", s["id"], {"active": 0 if s["active"] else 1})
        audit(c, ctx, "revenue.season_toggled", "rate_season", s["id"], new={"active": not s["active"]}, hotel_id=s["hotel_id"])
    return {"active": not s["active"]}


@route("POST", "/api/hotels/{hotel_id:int}/revenue/rules", perm="sales.pricing", tag="sales",
       summary="Propose an occupancy-based rule (name, min/max_occupancy_pct, adjustment_bp, room_type_id); a second person must approve it")
def propose_rule(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    lo, hi, adj = ctx.field("min_occupancy_pct", kind=int), ctx.field("max_occupancy_pct", required=False, default=100, kind=int), ctx.field("adjustment_bp", kind=int)
    if not (0 <= lo <= hi <= 100):
        raise bad_request("Occupancy range must be within 0–100 %")
    if not -3000 <= adj <= 5000:
        raise bad_request("Dynamic adjustments are limited to −30 % … +50 %")
    with get_db().tx() as c:
        rid = c.insert("rate_rules", {"hotel_id": hid, "name": ctx.field("name", kind=str), "room_type_id": ctx.field("room_type_id", required=False, kind=int),
                                      "min_occupancy_pct": lo, "max_occupancy_pct": hi, "adjustment_bp": adj, "status": "pending_approval", "created_by": ctx.user_id,
                                      "created_at": now_iso()})
        audit(c, ctx, "revenue.rule_proposed", "rate_rule", rid, new=ctx.body, hotel_id=hid)
    return {"id": rid, "status": "pending_approval", "_created": True}


@route("POST", "/api/revenue/rules/{rule_id:int}/decide", perm="sales.pricing_approve", tag="sales",
       summary="Approve (activate), reject, or deactivate a dynamic pricing rule — never your own proposal")
def decide_rule(ctx: Ctx):
    decision = ctx.field("decision", kind=str)
    with get_db().tx() as c:
        r = c.lock("rate_rules", int(ctx.path["rule_id"]))
        if not r:
            raise not_found("Rule")
        ctx.check_hotel(r["hotel_id"])
        if decision in ("approve", "reject"):
            if r["status"] != "pending_approval":
                raise conflict(f"This rule is {r['status']}")
            if r["created_by"] == ctx.user_id:
                raise forbidden("A pricing rule must be approved by someone other than its author")
            new = "active" if decision == "approve" else "rejected"
        elif decision == "deactivate":
            if r["status"] != "active":
                raise conflict("Only active rules can be deactivated")
            new = "inactive"
        else:
            raise bad_request("decision must be approve, reject or deactivate")
        c.update("rate_rules", r["id"], {"status": new, "approved_by": ctx.user_id, "approved_at": now_iso()})
        audit(c, ctx, f"revenue.rule_{decision}", "rate_rule", r["id"], r["name"], new={"status": new}, hotel_id=r["hotel_id"])
    return {"status": new}


@route("POST", "/api/hotels/{hotel_id:int}/revenue/competitor-rates", perm="sales.pricing", tag="sales",
       summary="Record competitor rates: rows[{competitor, stay_date, room_category, rate, source}]")
def add_competitor_rates(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    rows = ctx.field("rows")
    if not isinstance(rows, list) or not rows:
        raise bad_request("Add at least one rate")
    with get_db().tx() as c:
        for r in rows:
            if not r.get("competitor") or not r.get("room_category"):
                raise bad_request("Each row needs a competitor and room category")
            c.insert("competitor_rates", {"hotel_id": hid, "competitor": str(r["competitor"])[:150], "stay_date": parse_date(r.get("stay_date"), "stay_date").isoformat(),
                                          "room_category": str(r["room_category"])[:100], "rate": to_minor(r.get("rate"), "rate"), "source": (r.get("source") or "")[:60] or None,
                                          "recorded_by": ctx.user_id, "recorded_at": now_iso()})
    return {"recorded": len(rows), "_created": True}


# ------------------------------------------------------------------ revenue dashboard
@route("GET", "/api/hotels/{hotel_id:int}/revenue/dashboard", perm="sales.view", tag="sales",
       summary="Forward 30 days on the books with pickup and recommendations; KPIs for the period and year-on-year by month")
def revenue_dashboard(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    from ..pricing import card_rate, occupancy_pct
    from .dashboard import kpis_for
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        today = business_date(hotel)
        sellable = c.scalar("SELECT COUNT(*) FROM rooms WHERE hotel_id = ? AND active = 1 AND service_status IN ('in_service','vip_hold')", [hid]) or 1
        std = c.one("SELECT * FROM room_types WHERE hotel_id = ? AND active = 1 ORDER BY base_rate LIMIT 1", [hid])
        week_ago = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
        forward = []
        for i in range(30):
            d = today + dt.timedelta(days=i)
            ds = d.isoformat()
            res = c.all("SELECT r.*, rt.base_rate FROM reservations r JOIN room_types rt ON rt.id = r.room_type_id WHERE r.hotel_id = ? AND r.status IN ('confirmed','tentative','checked_in') "
                        "AND r.arrival <= ? AND r.departure > ?", [hid, ds, ds])
            from ..pricing import stay_night_rate
            rev = 0
            for r in res:
                rt = c.one("SELECT * FROM room_types WHERE id = ?", [r["room_type_id"]])
                rev += stay_night_rate(c, r, rt, d)
            pickup = sum(1 for r in res if r["created_at"] >= week_ago[:19])
            occ = round(len(res) * 100 / sellable, 1)
            comp = c.one("SELECT AVG(rate) AS avg_rate, COUNT(*) AS n FROM competitor_rates WHERE hotel_id = ? AND stay_date = ?", [hid, ds])
            bar = card_rate(c, hid, std, "individual", d)[0] if std else None
            rec = None
            if occ >= 85:
                rec = "High demand: consider raising rates / closing discounts"
            elif occ <= 30 and i <= 14:
                rec = "Low demand: consider a promotion or targeted campaign"
            if comp and comp["n"] and bar and comp["avg_rate"] and bar > comp["avg_rate"] * 1.15 and occ < 60:
                rec = "Priced >15 % above competitors with soft demand: review the rate"
            forward.append({"date": ds, "rooms_on_books": len(res), "occupancy_pct": occ, "adr_on_books": rev // len(res) if res else 0, "revenue_on_books": rev,
                            "pickup_7d": pickup, "our_rate": bar, "competitor_avg": int(comp["avg_rate"]) if comp and comp["avg_rate"] else None, "recommendation": rec})
        # period KPIs
        frm = parse_date(ctx.q("from", (today - dt.timedelta(days=30)).isoformat()), "from")
        to = parse_date(ctx.q("to", (today - dt.timedelta(days=1)).isoformat()), "to")
        days = [kpis_for(c, hid, frm + dt.timedelta(days=i)) for i in range((to - frm).days + 1)] if to >= frm else []
        sold = sum(k["rooms_sold"] for k in days)
        rev = sum(k["room_revenue"] for k in days)
        avail = sum(k["sellable_rooms"] for k in days)
        stays = c.all("SELECT arrival, departure, created_at FROM reservations WHERE hotel_id = ? AND status IN ('checked_in','checked_out') AND arrival >= ? AND arrival <= ?",
                      [hid, frm.isoformat(), to.isoformat()])
        alos = round(sum((dt.date.fromisoformat(s["departure"]) - dt.date.fromisoformat(s["arrival"])).days for s in stays) / len(stays), 2) if stays else None
        window = round(sum(max(0, (dt.date.fromisoformat(s["arrival"]) - dt.date.fromisoformat(s["created_at"][:10])).days) for s in stays) / len(stays), 1) if stays else None
        made = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND created_at >= ? AND created_at <= ?", [hid, frm.isoformat(), to.isoformat() + "T23:59:59"]) or 0
        cancelled = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND status IN ('cancelled','no_show') AND created_at >= ? AND created_at <= ?",
                             [hid, frm.isoformat(), to.isoformat() + "T23:59:59"]) or 0
        mix = c.all("SELECT source, COUNT(*) AS bookings FROM reservations WHERE hotel_id = ? AND created_at >= ? AND status NOT IN ('enquiry') GROUP BY source ORDER BY bookings DESC",
                    [hid, frm.isoformat()])
        # year-on-year by month (this year vs last year)
        yoy = []
        for m in range(1, today.month + 1):
            row = {"month": f"{today.year}-{m:02d}"}
            for label_, y in (("this_year", today.year), ("last_year", today.year - 1)):
                first = dt.date(y, m, 1)
                last = min(dt.date(y, m, calendar.monthrange(y, m)[1]), today if y == today.year else dt.date(y, m, calendar.monthrange(y, m)[1]))
                r = c.one("SELECT COALESCE(SUM(fl.net_amount),0) AS rev, COUNT(CASE WHEN fl.reference LIKE ? AND fl.kind = 'charge' THEN 1 END) AS n FROM folio_lines fl "
                          "JOIN folios f ON f.id = fl.folio_id WHERE f.hotel_id = ? AND fl.department = 'room' AND fl.kind IN ('charge','adjustment') AND fl.business_date >= ? AND fl.business_date <= ?",
                          ["ROOM:%", hid, first.isoformat(), last.isoformat()])
                nights = (last - first).days + 1
                row[label_] = {"room_revenue": r["rev"], "rooms_sold": r["n"], "adr": r["rev"] // r["n"] if r["n"] else 0,
                               "occupancy_pct": round(r["n"] * 100 / (sellable * nights), 1) if nights > 0 else 0, "revpar": r["rev"] // (sellable * nights) if nights > 0 else 0}
            yoy.append(row)
    return {"business_date": today.isoformat(), "forward": forward,
            "period": {"from": frm.isoformat(), "to": to.isoformat(), "rooms_sold": sold, "room_revenue": rev, "occupancy_pct": round(sold * 100 / avail, 1) if avail else 0,
                       "adr": rev // sold if sold else 0, "revpar": rev // avail if avail else 0, "alos": alos, "booking_window_days": window,
                       "cancellation_rate_pct": round(cancelled * 100 / made, 1) if made else None, "source_mix": mix},
            "year_on_year": yoy}
