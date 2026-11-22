"""Maintenance & facilities: asset register (with capitalisation and straight-line depreciation), preventive
schedules that raise work orders automatically, fault reporting, work orders with assignment, spare parts
issued from stores, vendor costs, downtime, room blocking and completion verification. (FR-MNT-001..004)"""
from __future__ import annotations

import calendar
import datetime as dt

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import account_id, business_date, get_hotel, next_number, parse_date, post_journal, queue_notification, to_milli, to_minor
from ..stock import apply_movement, get_item, get_store

CATEGORIES = ("generator", "air_conditioner", "elevator", "water_system", "pump", "kitchen_equipment", "refrigeration", "electrical", "plumbing",
              "fire_safety", "security_system", "laundry_equipment", "furniture", "vehicle", "it", "building", "other")
PRIORITIES = ("urgent", "high", "normal", "low")
NEXT = {"open": ("assigned", "in_progress", "on_hold", "cancelled"), "assigned": ("in_progress", "on_hold", "cancelled"),
        "in_progress": ("on_hold", "completed"), "on_hold": ("in_progress", "cancelled"), "completed": ("verified", "in_progress")}


def _users_with(c, hotel_id: int, perm: str) -> list[int]:
    from ..worker import _users_with as uw
    return uw(c, hotel_id, perm)


# ------------------------------------------------------------------ assets
@route("GET", "/api/hotels/{hotel_id:int}/assets", perm="maintenance.view", tag="maintenance", summary="Asset register (?category, ?status, ?q)")
def list_assets(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT a.*, r.number AS room_number, s.name AS supplier_name, "
           "(SELECT COUNT(*) FROM work_orders w WHERE w.asset_id = a.id AND w.status NOT IN ('verified','cancelled')) AS open_work_orders, "
           "(SELECT MIN(next_due) FROM maintenance_schedules m WHERE m.asset_id = a.id AND m.active = 1) AS next_service "
           "FROM assets a LEFT JOIN rooms r ON r.id = a.room_id LEFT JOIN suppliers s ON s.id = a.supplier_id WHERE a.hotel_id = ?")
    params: list = [hid]
    for k in ("category", "status"):
        if ctx.q(k):
            sql += f" AND a.{k} = ?"
            params.append(ctx.q(k))
    if ctx.q("q"):
        q = f"%{ctx.q('q').lower()}%"
        sql += " AND (LOWER(a.name) LIKE ? OR LOWER(a.code) LIKE ? OR LOWER(COALESCE(a.location,'')) LIKE ?)"
        params += [q, q, q]
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY a.category, a.name", params)
        today = business_date(get_hotel(c, hid)).isoformat()
    for r in rows:
        r["book_value"] = r["purchase_cost"] - r["accumulated_depreciation"] if r["capitalised"] else None
        r["warranty_active"] = bool(r["warranty_until"] and r["warranty_until"] >= today)
    return {"items": rows, "categories": CATEGORIES}


def _asset_payload(ctx: Ctx, partial: bool) -> dict:
    b = ctx.body or {}
    data: dict = {}
    if "name" in b or not partial:
        data["name"] = ctx.field("name", kind=str)
    if "category" in b or not partial:
        data["category"] = ctx.field("category", kind=str)
        if data["category"] not in CATEGORIES:
            raise bad_request(f"category must be one of {', '.join(CATEGORIES)}")
    for k in ("location", "serial_no", "manufacturer", "notes"):
        if k in b:
            data[k] = ctx.field(k, required=False, kind=str)
    for k in ("purchase_date", "warranty_until"):
        if k in b:
            data[k] = parse_date(b[k], k).isoformat() if b[k] else None
    for k in ("purchase_cost", "salvage_value"):
        if k in b:
            data[k] = to_minor(b[k] or 0, k)
    if "useful_life_months" in b:
        data["useful_life_months"] = int(b["useful_life_months"])
        if not 1 <= data["useful_life_months"] <= 600:
            raise bad_request("useful_life_months must be 1–600")
    for k in ("room_id", "supplier_id"):
        if k in b:
            data[k] = int(b[k]) if b[k] else None
    if "status" in b:
        if b["status"] not in ("operational", "under_repair", "out_of_service", "retired"):
            raise bad_request("Unknown status")
        data["status"] = b["status"]
    return data


@route("POST", "/api/hotels/{hotel_id:int}/assets", perm="maintenance.manage", tag="maintenance",
       summary="Register an asset; optionally capitalise it (funding: method_id paid now, or 'opening' for existing assets)")
def create_asset(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    data = _asset_payload(ctx, partial=False)
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        code = (ctx.field("code", required=False, kind=str) or f"AST{next_number(c, hid, 'asset', 'A', 4).split('-')[-1]}").upper()
        if data.get("room_id") and not c.one("SELECT id FROM rooms WHERE id = ? AND hotel_id = ?", [data["room_id"], hid]):
            raise bad_request("Room not found")
        aid = c.insert("assets", {"hotel_id": hid, "code": code, "created_at": now_iso(), **data})
        funding = ctx.field("funding", required=False)
        if funding and data.get("purchase_cost", 0) > 0:
            org = hotel["organisation_id"]
            if funding == "opening":
                contra = account_id(c, org, "equity")
            else:
                m = c.one("SELECT * FROM payment_methods WHERE id = ? AND hotel_id = ? AND active = 1 AND kind IN ('cash','bank_transfer')", [int(funding), hid])
                if not m:
                    raise bad_request("funding must be 'opening' or a cash/bank payment method id")
                contra = m["account_id"]
            post_journal(c, hid, business_date(hotel), f"Capitalise asset {code} {data['name']}", "asset", code, [
                (account_id(c, org, "fixed_assets"), data["purchase_cost"], 0, None, data["name"]), (contra, 0, data["purchase_cost"], None, data["name"])], ctx.user_id)
            c.update("assets", aid, {"capitalised": 1})
        audit(c, ctx, "asset.created", "asset", aid, code, new={**data, "funding": funding}, hotel_id=hid)
    return {"id": aid, "code": code, "_created": True}


@route("PATCH", "/api/assets/{asset_id:int}", perm="maintenance.manage", tag="maintenance", summary="Edit an asset")
def update_asset(ctx: Ctx):
    with get_db().tx() as c:
        a = c.one("SELECT * FROM assets WHERE id = ?", [ctx.path["asset_id"]])
        if not a:
            raise not_found("Asset")
        ctx.check_hotel(a["hotel_id"])
        data = _asset_payload(ctx, partial=True)
        if a["capitalised"] and any(k in data and data[k] != a[k] for k in ("purchase_cost",)):
            raise conflict("The cost of a capitalised asset cannot be edited; post an adjustment journal instead")
        c.update("assets", a["id"], data)
        audit(c, ctx, "asset.updated", "asset", a["id"], a["code"], old={k: a[k] for k in data}, new=data, hotel_id=a["hotel_id"])
    return {"ok": True}


@route("GET", "/api/assets/{asset_id:int}", perm="maintenance.view", tag="maintenance", summary="Asset with schedules, maintenance history, costs and depreciation")
def get_asset(ctx: Ctx):
    with get_db().tx() as c:
        a = c.one("SELECT * FROM assets WHERE id = ?", [ctx.path["asset_id"]])
        if not a:
            raise not_found("Asset")
        ctx.check_hotel(a["hotel_id"])
        a["schedules"] = c.all("SELECT m.*, u.full_name AS assigned_to_name FROM maintenance_schedules m LEFT JOIN users u ON u.id = m.assigned_to WHERE m.asset_id = ? ORDER BY m.next_due", [a["id"]])
        a["work_orders"] = c.all("SELECT w.*, u.full_name AS assigned_to_name FROM work_orders w LEFT JOIN users u ON u.id = w.assigned_to WHERE w.asset_id = ? ORDER BY w.id DESC", [a["id"]])
        a["depreciation"] = c.all("SELECT * FROM asset_depreciation WHERE asset_id = ? ORDER BY period DESC", [a["id"]])
        a["maintenance_cost"] = sum(w["parts_cost"] + w["vendor_cost"] for w in a["work_orders"])
        done = [w for w in a["work_orders"] if w["completed_at"] and w["started_at"]]
        a["downtime_hours"] = round(sum((dt.datetime.fromisoformat(w["completed_at"].replace("Z", "+00:00")) - dt.datetime.fromisoformat(w["started_at"].replace("Z", "+00:00"))).total_seconds()
                                        for w in done) / 3600, 1)
    return a


@route("POST", "/api/assets/{asset_id:int}/schedules", perm="maintenance.manage", tag="maintenance",
       summary="Add a preventive maintenance schedule (title, frequency_days, next_due, checklist, assigned_to)")
def add_schedule(ctx: Ctx):
    freq = ctx.field("frequency_days", kind=int)
    if not 1 <= freq <= 3650:
        raise bad_request("frequency_days must be 1–3650")
    with get_db().tx() as c:
        a = c.one("SELECT * FROM assets WHERE id = ?", [ctx.path["asset_id"]])
        if not a:
            raise not_found("Asset")
        ctx.check_hotel(a["hotel_id"])
        sid = c.insert("maintenance_schedules", {"asset_id": a["id"], "title": ctx.field("title", kind=str), "frequency_days": freq,
                                                 "next_due": parse_date(ctx.field("next_due"), "next_due").isoformat(), "checklist": ctx.field("checklist", required=False, kind=str),
                                                 "assigned_to": ctx.field("assigned_to", required=False, kind=int), "active": 1})
        audit(c, ctx, "maintenance.schedule_added", "maintenance_schedule", sid, a["code"], new=ctx.body, hotel_id=a["hotel_id"])
    return {"id": sid, "_created": True}


def raise_due_preventive(c, hotel: dict) -> int:
    """Create work orders for schedules that are due (idempotent: one open order per schedule). Used by the worker."""
    today = business_date(hotel)
    n = 0
    for s in c.all("SELECT m.*, a.hotel_id, a.name AS asset_name, a.room_id FROM maintenance_schedules m JOIN assets a ON a.id = m.asset_id "
                   "WHERE a.hotel_id = ? AND m.active = 1 AND a.status <> 'retired' AND m.next_due <= ?", [hotel["id"], (today + dt.timedelta(days=3)).isoformat()]):
        if c.one("SELECT id FROM work_orders WHERE schedule_id = ? AND status NOT IN ('verified','cancelled')", [s["id"]]):
            continue
        number = next_number(c, hotel["id"], "work_order", "WO")
        reporter = s["assigned_to"] or c.scalar("SELECT id FROM users WHERE organisation_id = ? ORDER BY id LIMIT 1", [hotel["organisation_id"]])
        wid = c.insert("work_orders", {"hotel_id": hotel["id"], "number": number, "asset_id": s["asset_id"], "room_id": s["room_id"], "schedule_id": s["id"],
                                       "title": f"Preventive: {s['title']} — {s['asset_name']}", "description": s["checklist"], "kind": "preventive", "priority": "normal",
                                       "status": "assigned" if s["assigned_to"] else "open", "reported_by": reporter, "assigned_to": s["assigned_to"],
                                       "due_date": s["next_due"], "created_at": now_iso()})
        for uid in ([s["assigned_to"]] if s["assigned_to"] else _users_with(c, hotel["id"], "maintenance.manage")):
            queue_notification(c, hotel["id"], "in_app", str(uid), "Preventive maintenance due", f"{number}: {s['title']} on {s['asset_name']} due {s['next_due']}",
                               "work_order", wid)
        n += 1
    return n


@route("POST", "/api/hotels/{hotel_id:int}/maintenance/raise-preventive", perm="maintenance.manage", tag="maintenance",
       summary="Create work orders now for preventive schedules due within 3 days (the worker also does this daily)")
def raise_preventive(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"created": raise_due_preventive(c, get_hotel(c, hid))}


# ------------------------------------------------------------------ depreciation
@route("POST", "/api/hotels/{hotel_id:int}/assets/depreciate", perm="accounting.post_manual", tag="maintenance",
       summary="Post straight-line depreciation for a month (period YYYY-MM) for all capitalised assets (once per asset per month)")
def depreciate(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    period = ctx.field("period", kind=str)
    try:
        y, m = int(period[:4]), int(period[5:7])
        last = dt.date(y, m, calendar.monthrange(y, m)[1])
    except (ValueError, IndexError):
        raise bad_request("period must be YYYY-MM")
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        if last > business_date(hotel) + dt.timedelta(days=31):
            raise bad_request("Depreciation cannot be posted for future months")
        total, lines, done = 0, [], []
        for a in c.all("SELECT * FROM assets WHERE hotel_id = ? AND capitalised = 1 AND status <> 'retired' AND (purchase_date IS NULL OR purchase_date <= ?)", [hid, last.isoformat()]):
            if c.one("SELECT id FROM asset_depreciation WHERE asset_id = ? AND period = ?", [a["id"], period]):
                continue
            depreciable = a["purchase_cost"] - a["salvage_value"] - a["accumulated_depreciation"]
            if depreciable <= 0:
                continue
            amount = min(depreciable, (a["purchase_cost"] - a["salvage_value"]) // a["useful_life_months"])
            if amount <= 0:
                continue
            total += amount
            done.append((a, amount))
        if not total:
            return {"assets": 0, "total": 0}
        org = hotel["organisation_id"]
        je = post_journal(c, hid, min(last, business_date(hotel)), f"Depreciation {period}", "asset", f"DEP-{period}", [
            (account_id(c, org, "exp_depreciation"), total, 0, None, f"Depreciation {period}"),
            (account_id(c, org, "accum_depreciation"), 0, total, None, f"Depreciation {period}")], ctx.user_id)
        for a, amount in done:
            c.insert("asset_depreciation", {"asset_id": a["id"], "period": period, "amount": amount, "journal_entry_id": je})
            c.update("assets", a["id"], {"accumulated_depreciation": a["accumulated_depreciation"] + amount})
        audit(c, ctx, "asset.depreciation", "assets", period, period, new={"assets": len(done), "total": total, "journal": je}, hotel_id=hid)
    return {"assets": len(done), "total": total, "journal_entry_id": je}


# ------------------------------------------------------------------ work orders
def _wo(c, ctx: Ctx, wid, lock=False) -> dict:
    w = c.lock("work_orders", int(wid)) if lock else c.one("SELECT * FROM work_orders WHERE id = ?", [int(wid)])
    if not w:
        raise not_found("Work order")
    ctx.check_hotel(w["hotel_id"])
    return w


def _block_room(c, w: dict, block: bool) -> None:
    if not w["room_id"]:
        return
    room = c.one("SELECT * FROM rooms WHERE id = ?", [w["room_id"]])
    if block and room["occupancy"] == "vacant" and room["service_status"] == "in_service":
        c.update("rooms", room["id"], {"service_status": "maintenance", "service_note": f"{w['number']}: {w['title']}"[:300]})
    elif not block and room["service_status"] == "maintenance" and (room["service_note"] or "").startswith(w["number"]):
        c.update("rooms", room["id"], {"service_status": "in_service", "service_note": None, "hk_status": "dirty"})
        from .frontoffice import _hk_task
        _hk_task(c, get_hotel(c, w["hotel_id"]), room["id"], "deep_clean", f"Clean after maintenance {w['number']}")


@route("GET", "/api/hotels/{hotel_id:int}/work-orders", perm="maintenance.report", tag="maintenance",
       summary="Work orders (?status, ?mine=1, ?open=1); reporters see the faults they reported")
def list_work_orders(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT w.*, a.name AS asset_name, a.code AS asset_code, r.number AS room_number, u.full_name AS assigned_to_name, rb.full_name AS reported_by_name "
           "FROM work_orders w LEFT JOIN assets a ON a.id = w.asset_id LEFT JOIN rooms r ON r.id = w.room_id LEFT JOIN users u ON u.id = w.assigned_to "
           "JOIN users rb ON rb.id = w.reported_by WHERE w.hotel_id = ?")
    params: list = [hid]
    if ctx.q("mine") == "1" or not (ctx.can("maintenance.manage") or ctx.can("maintenance.work") or ctx.can("maintenance.view")):
        sql += " AND (w.assigned_to = ? OR w.reported_by = ?)"
        params += [ctx.user_id, ctx.user_id]
    if ctx.q("open") == "1":
        sql += " AND w.status NOT IN ('verified','cancelled')"
    if ctx.q("status"):
        sql += " AND w.status = ?"
        params.append(ctx.q("status"))
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY CASE w.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, w.id DESC LIMIT 300", params)
        today = business_date(get_hotel(c, hid)).isoformat()
        techs = c.all("SELECT DISTINCT u.id, u.full_name FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN role_permissions rp ON rp.role_id = ur.role_id "
                      "LEFT JOIN user_hotels uh ON uh.user_id = u.id WHERE rp.permission_code = 'maintenance.work' AND u.status = 'active' "
                      "AND (u.all_hotels = 1 OR uh.hotel_id = ?) ORDER BY u.full_name", [hid])
    for r in rows:
        r["overdue"] = bool(r["due_date"] and r["due_date"] < today and r["status"] not in ("completed", "verified", "cancelled"))
    counts: dict = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"items": rows, "counts": counts, "overdue": sum(1 for r in rows if r["overdue"]), "technicians": techs, "priorities": PRIORITIES}


@route("POST", "/api/hotels/{hotel_id:int}/work-orders", perm="maintenance.report", tag="maintenance",
       summary="Report a fault / raise a work order (asset_id or room_id, title, description, priority, blocks_room)")
def create_work_order(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    prio = ctx.field("priority", required=False, default="normal", kind=str)
    if prio not in PRIORITIES:
        raise bad_request("priority must be urgent, high, normal or low")
    kind = ctx.field("kind", required=False, default="corrective", kind=str)
    if kind not in ("corrective", "preventive", "inspection"):
        raise bad_request("Unknown kind")
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        asset_id, room_id = ctx.field("asset_id", required=False, kind=int), ctx.field("room_id", required=False, kind=int)
        if asset_id and not c.one("SELECT id FROM assets WHERE id = ? AND hotel_id = ?", [asset_id, hid]):
            raise bad_request("Asset not found")
        if room_id and not c.one("SELECT id FROM rooms WHERE id = ? AND hotel_id = ?", [room_id, hid]):
            raise bad_request("Room not found")
        assigned = ctx.field("assigned_to", required=False, kind=int) if ctx.can("maintenance.manage") else None
        number = next_number(c, hid, "work_order", "WO")
        due = ctx.field("due_date", required=False)
        wid = c.insert("work_orders", {"hotel_id": hid, "number": number, "asset_id": asset_id, "room_id": room_id, "title": ctx.field("title", kind=str)[:200],
                                       "description": ctx.field("description", required=False, kind=str), "kind": kind, "priority": prio,
                                       "status": "assigned" if assigned else "open", "blocks_room": 1 if ctx.field("blocks_room", required=False, default=False) else 0,
                                       "reported_by": ctx.user_id, "assigned_to": assigned,
                                       "due_date": parse_date(due, "due_date").isoformat() if due else (business_date(hotel) + dt.timedelta(days={"urgent": 0, "high": 1, "normal": 3, "low": 7}[prio])).isoformat(),
                                       "created_at": now_iso()})
        w = c.one("SELECT * FROM work_orders WHERE id = ?", [wid])
        if w["blocks_room"]:
            _block_room(c, w, True)
        if asset_id and prio in ("urgent", "high"):
            c.update("assets", asset_id, {"status": "under_repair"})
        for uid in ([assigned] if assigned else _users_with(c, hid, "maintenance.manage")):
            queue_notification(c, hid, "in_app", str(uid), f"{'URGENT ' if prio == 'urgent' else ''}Fault reported", f"{number}: {w['title']}", "work_order", wid)
        audit(c, ctx, "maintenance.reported", "work_order", wid, number, new=ctx.body, hotel_id=hid)
    return {"id": wid, "number": number, "_created": True}


@route("GET", "/api/work-orders/{wo_id:int}", perm="maintenance.report", tag="maintenance", summary="Work order with notes and parts used")
def get_work_order(ctx: Ctx):
    with get_db().tx() as c:
        w = _wo(c, ctx, ctx.path["wo_id"])
        if not (ctx.can("maintenance.view") or w["reported_by"] == ctx.user_id):
            raise forbidden("You can only view faults you reported")
        w["notes"] = c.all("SELECT n.*, u.full_name AS by_name FROM work_order_notes n JOIN users u ON u.id = n.created_by WHERE n.work_order_id = ? ORDER BY n.id", [w["id"]])
        w["parts"] = c.all("SELECT p.*, i.name AS item_name, i.unit, s.name AS store_name FROM work_order_parts p JOIN inventory_items i ON i.id = p.item_id "
                           "JOIN stores s ON s.id = p.store_id WHERE p.work_order_id = ? ORDER BY p.id", [w["id"]])
        for p in w["parts"]:
            p["quantity"] = p.pop("quantity_milli") / 1000
        w["asset"] = c.one("SELECT id, code, name, category, location FROM assets WHERE id = ?", [w["asset_id"]]) if w["asset_id"] else None
        w["room"] = c.one("SELECT id, number, service_status FROM rooms WHERE id = ?", [w["room_id"]]) if w["room_id"] else None
        w["assigned_to_name"] = c.scalar("SELECT full_name FROM users WHERE id = ?", [w["assigned_to"]]) if w["assigned_to"] else None
        w["reported_by_name"] = c.scalar("SELECT full_name FROM users WHERE id = ?", [w["reported_by"]])
    return w


@route("POST", "/api/work-orders/{wo_id:int}/assign", perm="maintenance.manage", tag="maintenance", summary="Assign a technician and/or external service provider")
def assign(ctx: Ctx):
    with get_db().tx() as c:
        w = _wo(c, ctx, ctx.path["wo_id"], lock=True)
        if w["status"] in ("verified", "cancelled", "completed"):
            raise conflict(f"This work order is {w['status']}")
        uid = ctx.field("user_id", required=False, kind=int)
        if uid and not c.one("SELECT id FROM users WHERE id = ? AND organisation_id = ? AND status = 'active'", [uid, ctx.org_id]):
            raise bad_request("Technician not found")
        data = {"assigned_to": uid, "status": "assigned" if w["status"] == "open" and uid else w["status"]}
        if "service_provider_id" in (ctx.body or {}):
            data["service_provider_id"] = ctx.field("service_provider_id", required=False, kind=int)
        if "priority" in (ctx.body or {}):
            if ctx.body["priority"] not in PRIORITIES:
                raise bad_request("Unknown priority")
            data["priority"] = ctx.body["priority"]
        c.update("work_orders", w["id"], data)
        if uid:
            queue_notification(c, w["hotel_id"], "in_app", str(uid), "Work order assigned to you", f"{w['number']}: {w['title']}", "work_order", w["id"])
        audit(c, ctx, "maintenance.assigned", "work_order", w["id"], w["number"], new=data, hotel_id=w["hotel_id"])
    return {"ok": True}


@route("POST", "/api/work-orders/{wo_id:int}/status", perm="maintenance.view", tag="maintenance",
       summary="Move a work order: in_progress / on_hold / completed (assignee or manager), verified (manager, not the person who did the work), cancelled")
def set_status(ctx: Ctx):
    status = ctx.field("status", kind=str)
    with get_db().tx() as c:
        w = _wo(c, ctx, ctx.path["wo_id"], lock=True)
        if status not in NEXT.get(w["status"], ()):
            raise conflict(f"A {w['status'].replace('_', ' ')} work order cannot move to {status.replace('_', ' ')}")
        manager = ctx.can("maintenance.manage")
        if status in ("verified", "cancelled", "assigned") and not manager:
            raise forbidden("Only maintenance managers can verify or cancel work orders")
        if status in ("in_progress", "on_hold", "completed") and not (manager or (ctx.can("maintenance.work") and w["assigned_to"] in (None, ctx.user_id))):
            raise forbidden("This work order is assigned to someone else")
        if status == "verified" and w["assigned_to"] == ctx.user_id:
            raise forbidden("The technician who did the work cannot verify it")
        data: dict = {"status": status}
        note = ctx.field("note", required=status in ("on_hold", "cancelled") or (status == "in_progress" and w["status"] == "completed"), kind=str)
        if status == "in_progress" and not w["started_at"]:
            data.update({"started_at": now_iso(), "assigned_to": w["assigned_to"] or ctx.user_id})
        if status == "completed":
            data["resolution"] = ctx.field("resolution", kind=str)
            data["completed_at"] = now_iso()
            if "labour_hours" in (ctx.body or {}):
                data["labour_hours"] = int(ctx.body["labour_hours"])
            if "vendor_cost" in (ctx.body or {}):
                data["vendor_cost"] = to_minor(ctx.body["vendor_cost"] or 0, "vendor_cost")
        if status == "verified":
            data.update({"verified_by": ctx.user_id, "verified_at": now_iso()})
            _block_room(c, w, False)
            if w["asset_id"]:
                c.execute("UPDATE assets SET status = 'operational' WHERE id = ? AND status = 'under_repair'", [w["asset_id"]])
            if w["schedule_id"]:
                s = c.one("SELECT * FROM maintenance_schedules WHERE id = ?", [w["schedule_id"]])
                done = business_date(get_hotel(c, w["hotel_id"]))
                c.update("maintenance_schedules", s["id"], {"last_done": done.isoformat(), "next_due": (done + dt.timedelta(days=s["frequency_days"])).isoformat()})
        if status == "cancelled":
            _block_room(c, w, False)
        c.update("work_orders", w["id"], data)
        if note:
            c.insert("work_order_notes", {"work_order_id": w["id"], "note": note, "created_by": ctx.user_id, "created_at": now_iso()})
        if status == "completed" and w["reported_by"] != ctx.user_id:
            queue_notification(c, w["hotel_id"], "in_app", str(w["reported_by"]), "Repair completed", f"{w['number']}: {w['title']}", "work_order", w["id"])
        audit(c, ctx, f"maintenance.{status}", "work_order", w["id"], w["number"], old={"status": w["status"]}, new={**data, "note": note}, hotel_id=w["hotel_id"])
    return {"status": status}


@route("POST", "/api/work-orders/{wo_id:int}/notes", perm="maintenance.view", tag="maintenance", summary="Add a progress note")
def add_note(ctx: Ctx):
    with get_db().tx() as c:
        w = _wo(c, ctx, ctx.path["wo_id"])
        c.insert("work_order_notes", {"work_order_id": w["id"], "note": ctx.field("note", kind=str), "created_by": ctx.user_id, "created_at": now_iso()})
    return {"ok": True}


@route("POST", "/api/work-orders/{wo_id:int}/parts", perm="maintenance.work", tag="maintenance",
       summary="Issue spare parts from a store to the work order (Dr Repairs & Maintenance / Cr Inventory)")
def issue_parts(ctx: Ctx):
    qty = to_milli(ctx.field("quantity"))
    with get_db().tx() as c:
        w = _wo(c, ctx, ctx.path["wo_id"], lock=True)
        if w["status"] in ("verified", "cancelled"):
            raise conflict(f"This work order is {w['status']}")
        hid = w["hotel_id"]
        hotel = get_hotel(c, hid)
        item = get_item(c, hid, ctx.field("item_id", kind=int))
        store = get_store(c, hid, ctx.field("store_id", kind=int))
        on = business_date(hotel)
        mid, val = apply_movement(c, hid, item, store, "issue", -qty, None, "work_order", w["number"], ctx.user_id, on, department="maintenance",
                                  reason=f"Spare part for {w['number']}")
        cost = -val
        je = post_journal(c, hid, on, f"Spare parts {w['number']}: {item['name']}", "inventory", w["number"], [
            (account_id(c, hotel["organisation_id"], "exp_maintenance"), cost, 0, "maintenance", w["title"]),
            (account_id(c, hotel["organisation_id"], "inventory"), 0, cost, "maintenance", item["name"])], ctx.user_id) if cost else None
        c.insert("work_order_parts", {"work_order_id": w["id"], "item_id": item["id"], "store_id": store["id"], "quantity_milli": qty, "value": cost,
                                      "journal_entry_id": je, "issued_by": ctx.user_id, "issued_at": now_iso()})
        c.update("work_orders", w["id"], {"parts_cost": w["parts_cost"] + cost})
        audit(c, ctx, "maintenance.parts_issued", "work_order", w["id"], w["number"], new={"item": item["code"], "qty": qty / 1000, "cost": cost}, hotel_id=hid)
    return {"cost": cost, "_created": True}


@route("GET", "/api/hotels/{hotel_id:int}/maintenance/summary", perm="maintenance.view", tag="maintenance",
       summary="Maintenance performance: open/overdue orders, completed this period, average completion time, costs, upcoming preventive work")
def summary(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        frm = ctx.q("from", today.replace(day=1).isoformat())
        done = c.all("SELECT * FROM work_orders WHERE hotel_id = ? AND completed_at IS NOT NULL AND completed_at >= ?", [hid, frm])
        open_ = c.all("SELECT priority, due_date FROM work_orders WHERE hotel_id = ? AND status NOT IN ('completed','verified','cancelled')", [hid])
        upcoming = c.all("SELECT m.title, m.next_due, a.name AS asset_name FROM maintenance_schedules m JOIN assets a ON a.id = m.asset_id WHERE a.hotel_id = ? "
                         "AND m.active = 1 AND m.next_due <= ? ORDER BY m.next_due", [hid, (today + dt.timedelta(days=30)).isoformat()])
        by_cat = c.all("SELECT a.category, COUNT(w.id) AS orders, COALESCE(SUM(w.parts_cost + w.vendor_cost),0) AS cost FROM work_orders w JOIN assets a ON a.id = w.asset_id "
                       "WHERE w.hotel_id = ? AND w.created_at >= ? GROUP BY a.category ORDER BY cost DESC", [hid, frm])
    hours = [(dt.datetime.fromisoformat(w["completed_at"].replace("Z", "+00:00")) - dt.datetime.fromisoformat(w["created_at"].replace("Z", "+00:00"))).total_seconds() / 3600 for w in done]
    return {"from": frm, "open": len(open_), "overdue": sum(1 for o in open_ if o["due_date"] and o["due_date"] < today.isoformat()),
            "urgent_open": sum(1 for o in open_ if o["priority"] == "urgent"), "completed": len(done),
            "avg_hours_to_complete": round(sum(hours) / len(hours), 1) if hours else None, "cost": sum(w["parts_cost"] + w["vendor_cost"] for w in done),
            "upcoming_preventive": upcoming, "by_category": by_cat}
