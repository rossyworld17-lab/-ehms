"""Housekeeping tasks: assignment, cleaning progress and inspection. A room becomes available
for sale only after cleaning AND inspection. (FR-HSK-001..003)"""
from __future__ import annotations

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import business_date, get_hotel

TASK_TYPES = ("checkout_clean", "stayover", "deep_clean", "inspection", "turndown")


def _task(c, ctx: Ctx, task_id) -> dict:
    t = c.one("SELECT * FROM housekeeping_tasks WHERE id = ?", [int(task_id)])
    if not t:
        raise not_found("Task")
    ctx.check_hotel(t["hotel_id"])
    return t


@route("GET", "/api/hotels/{hotel_id:int}/housekeeping/tasks", perm="housekeeping.view", tag="housekeeping",
       summary="Housekeeping tasks (filter by status, assignee, 'mine')")
def list_tasks(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT t.*, r.number AS room_number, r.floor, r.occupancy, r.hk_status, u.full_name AS assigned_to_name "
           "FROM housekeeping_tasks t JOIN rooms r ON r.id = t.room_id LEFT JOIN users u ON u.id = t.assigned_to WHERE t.hotel_id = ?")
    params: list = [hid]
    if ctx.q("mine") == "1" or not ctx.can("housekeeping.assign"):
        sql += " AND t.assigned_to = ?"
        params.append(ctx.user_id)
    if ctx.q("status"):
        st = ctx.q("status").split(",")
        sql += f" AND t.status IN ({','.join('?' for _ in st)})"
        params += st
    else:
        sql += " AND (t.status IN ('pending','in_progress','completed') OR t.business_date >= ?)"
        with get_db().tx() as c:
            params.append(business_date(get_hotel(c, hid)).isoformat())
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY t.priority, r.number", params)
        staff = c.all("SELECT DISTINCT u.id, u.full_name FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN role_permissions rp "
                      "ON rp.role_id = ur.role_id LEFT JOIN user_hotels uh ON uh.user_id = u.id WHERE rp.permission_code = 'housekeeping.update' "
                      "AND u.status = 'active' AND u.organisation_id = ? AND (u.all_hotels = 1 OR uh.hotel_id = ?) ORDER BY u.full_name", [ctx.org_id, hid])
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"items": rows, "counts": counts, "staff": staff}


@route("POST", "/api/hotels/{hotel_id:int}/housekeeping/tasks", perm="housekeeping.assign", tag="housekeeping", summary="Create a housekeeping task")
def create_task(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    ttype = ctx.field("task_type", kind=str)
    if ttype not in TASK_TYPES:
        raise bad_request(f"task_type must be one of {', '.join(TASK_TYPES)}")
    with get_db().tx() as c:
        room = c.one("SELECT * FROM rooms WHERE id = ? AND hotel_id = ?", [ctx.field("room_id", kind=int), hid])
        if not room:
            raise bad_request("Room not found")
        assigned = ctx.field("assigned_to", required=False)
        tid = c.insert("housekeeping_tasks", {"hotel_id": hid, "room_id": room["id"], "task_type": ttype, "status": "pending",
                                              "priority": int(ctx.field("priority", required=False, default=2)), "assigned_to": assigned,
                                              "notes": ctx.field("notes", required=False),
                                              "business_date": business_date(get_hotel(c, hid)).isoformat(), "created_at": now_iso()})
        if ttype in ("checkout_clean", "deep_clean") and room["occupancy"] == "vacant":
            c.update("rooms", room["id"], {"hk_status": "dirty"})
        audit(c, ctx, "hk.task_created", "housekeeping_task", tid, room["number"], new=ctx.body, hotel_id=hid)
    return {"id": tid, "_created": True}


@route("POST", "/api/housekeeping/tasks/{task_id:int}/assign", perm="housekeeping.assign", tag="housekeeping", summary="Assign a task to a staff member")
def assign(ctx: Ctx):
    with get_db().tx() as c:
        t = _task(c, ctx, ctx.path["task_id"])
        uid = ctx.field("user_id", required=False)
        if uid and not c.one("SELECT id FROM users WHERE id = ? AND organisation_id = ? AND status = 'active'", [int(uid), ctx.org_id]):
            raise bad_request("Staff member not found")
        c.update("housekeeping_tasks", t["id"], {"assigned_to": int(uid) if uid else None})
        audit(c, ctx, "hk.task_assigned", "housekeeping_task", t["id"], new={"assigned_to": uid}, hotel_id=t["hotel_id"])
    return {"ok": True}


def _own_or_manager(ctx: Ctx, t: dict) -> None:
    if t["assigned_to"] != ctx.user_id and not ctx.can("housekeeping.assign"):
        raise forbidden("This task is assigned to someone else")


@route("POST", "/api/housekeeping/tasks/{task_id:int}/start", perm="housekeeping.update", tag="housekeeping", summary="Start cleaning")
def start(ctx: Ctx):
    with get_db().tx() as c:
        t = _task(c, ctx, ctx.path["task_id"])
        _own_or_manager(ctx, t)
        if t["status"] not in ("pending", "rejected"):
            raise conflict(f"A {t['status'].replace('_', ' ')} task cannot be started")
        c.update("housekeeping_tasks", t["id"], {"status": "in_progress", "started_at": now_iso(), "assigned_to": t["assigned_to"] or ctx.user_id})
        room = c.one("SELECT * FROM rooms WHERE id = ?", [t["room_id"]])
        if room["occupancy"] == "vacant":
            c.update("rooms", room["id"], {"hk_status": "in_progress"})
        audit(c, ctx, "hk.task_started", "housekeeping_task", t["id"], room["number"], hotel_id=t["hotel_id"])
    return {"ok": True}


@route("POST", "/api/housekeeping/tasks/{task_id:int}/complete", perm="housekeeping.update", tag="housekeeping",
       summary="Mark cleaning complete (room awaits inspection); optionally report issues / damaged items")
def complete(ctx: Ctx):
    with get_db().tx() as c:
        t = _task(c, ctx, ctx.path["task_id"])
        _own_or_manager(ctx, t)
        if t["status"] != "in_progress":
            raise conflict("Start the task before completing it")
        issues = ctx.field("issues", required=False)
        c.update("housekeeping_tasks", t["id"], {"status": "completed", "completed_at": now_iso(), "issues": issues})
        room = c.one("SELECT * FROM rooms WHERE id = ?", [t["room_id"]])
        if room["occupancy"] == "vacant":
            c.update("rooms", room["id"], {"hk_status": "clean"})
        audit(c, ctx, "hk.task_completed", "housekeeping_task", t["id"], room["number"], new={"issues": issues}, hotel_id=t["hotel_id"])
    return {"ok": True}


@route("POST", "/api/housekeeping/tasks/{task_id:int}/inspect", perm="housekeeping.inspect", tag="housekeeping",
       summary="Inspect a cleaned room: pass makes it available, fail sends it back")
def inspect(ctx: Ctx):
    passed = bool(ctx.field("passed"))
    with get_db().tx() as c:
        t = _task(c, ctx, ctx.path["task_id"])
        if t["status"] != "completed":
            raise conflict("Only completed tasks can be inspected")
        note = ctx.field("note", required=not passed, kind=str)
        room = c.one("SELECT * FROM rooms WHERE id = ?", [t["room_id"]])
        if passed:
            c.update("housekeeping_tasks", t["id"], {"status": "inspected", "inspected_by": ctx.user_id, "inspected_at": now_iso()})
            if room["occupancy"] == "vacant":
                c.update("rooms", room["id"], {"hk_status": "inspected"})
        else:
            c.update("housekeeping_tasks", t["id"], {"status": "rejected", "inspected_by": ctx.user_id, "inspected_at": now_iso(),
                                                     "notes": ((t["notes"] or "") + f"\nInspection failed: {note}").strip()})
            if room["occupancy"] == "vacant":
                c.update("rooms", room["id"], {"hk_status": "dirty"})
        audit(c, ctx, "hk.inspected", "housekeeping_task", t["id"], room["number"], new={"passed": passed, "note": note}, hotel_id=t["hotel_id"])
    return {"ok": True, "room_status": "available" if passed else "dirty"}
