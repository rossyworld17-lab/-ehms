"""Recruitment (FR-HR-002): job openings, applicants moving through stages (applied → screening → interview →
offer → hired), interview notes and scores, CVs in the document store, and hiring that creates the employee
record through the normal HR registration. Applicant data is personal data: applicants who were not hired and
did not consent to be kept on file can be anonymised once the opening is closed."""
from __future__ import annotations

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, not_found, route
from ..services import next_number, parse_date, to_minor

STAGES = ("applied", "screening", "interview", "offer", "hired", "rejected", "withdrawn")
NEXT = {"applied": ("screening", "rejected", "withdrawn"), "screening": ("interview", "rejected", "withdrawn"),
        "interview": ("interview", "offer", "rejected", "withdrawn"), "offer": ("hired", "rejected", "withdrawn"),
        "hired": (), "rejected": (), "withdrawn": ()}


def _opening(c, ctx: Ctx, oid) -> dict:
    o = c.one("SELECT * FROM job_openings WHERE id = ?", [int(oid)])
    if not o:
        raise not_found("Job opening")
    ctx.check_hotel(o["hotel_id"])
    return o


def _applicant(c, ctx: Ctx, aid) -> tuple[dict, dict]:
    a = c.one("SELECT * FROM applicants WHERE id = ?", [int(aid)])
    if not a:
        raise not_found("Applicant")
    return a, _opening(c, ctx, a["opening_id"])


@route("GET", "/api/hotels/{hotel_id:int}/recruitment", perm="hr.view", tag="hr", summary="Job openings with applicant counts per stage")
def list_openings(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        rows = c.all("SELECT * FROM job_openings WHERE hotel_id = ? ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, id DESC", [hid])
        counts = c.all("SELECT a.opening_id, a.stage, COUNT(*) AS n FROM applicants a JOIN job_openings o ON o.id = a.opening_id WHERE o.hotel_id = ? GROUP BY a.opening_id, a.stage", [hid])
    by: dict = {}
    for r in counts:
        by.setdefault(r["opening_id"], {})[r["stage"]] = r["n"]
    return {"items": [{**o, "stages": by.get(o["id"], {}), "applicants": sum(by.get(o["id"], {}).values())} for o in rows]}


@route("POST", "/api/hotels/{hotel_id:int}/recruitment", perm="hr.recruit", tag="hr",
       summary="Open a position (title, department, employment_type, positions, salary_min, salary_max, description, closing_date)")
def create_opening(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    smin = to_minor(ctx.field("salary_min"), "salary_min") if ctx.field("salary_min", required=False) not in (None, "") else None
    smax = to_minor(ctx.field("salary_max"), "salary_max") if ctx.field("salary_max", required=False) not in (None, "") else None
    if smin is not None and smax is not None and smin > smax:
        raise bad_request("The minimum salary cannot exceed the maximum")
    closing = ctx.field("closing_date", required=False)
    with get_db().tx() as c:
        ref = next_number(c, hid, "job_opening", "JOB", 4)
        oid = c.insert("job_openings", {"hotel_id": hid, "reference": ref, "title": ctx.field("title", kind=str)[:150], "department": ctx.field("department", kind=str),
                                        "employment_type": ctx.field("employment_type", required=False, kind=str) or "full_time",
                                        "positions": int(ctx.field("positions", required=False) or 1), "salary_min": smin, "salary_max": smax,
                                        "description": ctx.field("description", required=False, kind=str),
                                        "closing_date": parse_date(closing, "closing_date").isoformat() if closing else None,
                                        "status": "open", "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "recruitment.opening_created", "job_opening", oid, ref, hotel_id=hid)
    return {"id": oid, "reference": ref, "_created": True}


@route("PATCH", "/api/recruitment/{opening_id:int}", perm="hr.recruit", tag="hr", summary="Change an opening's status (open, on_hold, filled, closed), positions or closing date")
def update_opening(ctx: Ctx):
    body = ctx.body or {}
    with get_db().tx() as c:
        o = _opening(c, ctx, ctx.path["opening_id"])
        ch = {}
        if "status" in body:
            if body["status"] not in ("draft", "open", "on_hold", "filled", "closed"):
                raise bad_request("Invalid status")
            ch["status"] = body["status"]
        for k in ("positions",):
            if k in body:
                ch[k] = max(1, int(body[k]))
        if "closing_date" in body:
            ch["closing_date"] = parse_date(body["closing_date"], "closing_date").isoformat() if body["closing_date"] else None
        if "description" in body:
            ch["description"] = body["description"]
        if not ch:
            raise bad_request("Nothing to change")
        c.update("job_openings", o["id"], ch)
        audit(c, ctx, "recruitment.opening_updated", "job_opening", o["id"], o["reference"], old={k: o[k] for k in ch}, new=ch, hotel_id=o["hotel_id"])
    return {"ok": True}


@route("GET", "/api/recruitment/{opening_id:int}", perm="hr.view", tag="hr", summary="Opening with applicants")
def get_opening(ctx: Ctx):
    with get_db().tx() as c:
        o = _opening(c, ctx, ctx.path["opening_id"])
        apps = c.all("SELECT * FROM applicants WHERE opening_id = ? ORDER BY CASE stage WHEN 'offer' THEN 0 WHEN 'interview' THEN 1 WHEN 'screening' THEN 2 "
                     "WHEN 'applied' THEN 3 WHEN 'hired' THEN 4 ELSE 5 END, id", [o["id"]])
        hired = sum(1 for a in apps if a["stage"] == "hired")
    return {**o, "applicants": apps, "hired": hired, "pipeline": {s: sum(1 for a in apps if a["stage"] == s) for s in STAGES}}


@route("POST", "/api/recruitment/{opening_id:int}/applicants", perm="hr.recruit", tag="hr",
       summary="Add an applicant (first_name, last_name, email, phone, source, expected_salary, consent_to_retain)")
def add_applicant(ctx: Ctx):
    with get_db().tx() as c:
        o = _opening(c, ctx, ctx.path["opening_id"])
        if o["status"] not in ("open", "on_hold"):
            raise conflict("This position is not accepting applicants")
        email = (ctx.field("email", required=False, kind=str) or "").lower() or None
        if email and c.one("SELECT id FROM applicants WHERE opening_id = ? AND lower(email) = ?", [o["id"], email]):
            raise conflict("This applicant has already applied for this position")
        exp = ctx.field("expected_salary", required=False)
        aid = c.insert("applicants", {"opening_id": o["id"], "first_name": ctx.field("first_name", kind=str)[:100], "last_name": ctx.field("last_name", kind=str)[:100],
                                      "email": email, "phone": ctx.field("phone", required=False, kind=str), "source": ctx.field("source", required=False, kind=str),
                                      "expected_salary": to_minor(exp, "expected_salary") if exp not in (None, "") else None,
                                      "consent_to_retain": 1 if ctx.field("consent_to_retain", required=False) else 0, "stage": "applied",
                                      "created_by": ctx.user_id, "created_at": now_iso(), "updated_at": now_iso()})
        c.insert("applicant_events", {"applicant_id": aid, "kind": "stage", "to_stage": "applied", "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "recruitment.applicant_added", "applicant", aid, o["reference"], hotel_id=o["hotel_id"])
    return {"id": aid, "_created": True}


@route("GET", "/api/applicants/{applicant_id:int}", perm="hr.view", tag="hr", summary="Applicant with stage history, interviews and notes")
def get_applicant(ctx: Ctx):
    with get_db().tx() as c:
        a, o = _applicant(c, ctx, ctx.path["applicant_id"])
        ev = c.all("SELECT e.*, u.full_name AS by_name FROM applicant_events e LEFT JOIN users u ON u.id = e.created_by WHERE e.applicant_id = ? ORDER BY e.id", [a["id"]])
    scores = [e["score"] for e in ev if e["score"]]
    return {**a, "opening": {"id": o["id"], "reference": o["reference"], "title": o["title"], "department": o["department"]}, "events": ev,
            "allowed_next": list(NEXT[a["stage"]]), "average_score": round(sum(scores) / len(scores), 1) if scores else None}


@route("POST", "/api/applicants/{applicant_id:int}/stage", perm="hr.recruit", tag="hr",
       summary="Move to the next stage ({stage, note, offered_salary, start_date}); rejection needs a note")
def move_stage(ctx: Ctx):
    to = ctx.field("stage", kind=str)
    with get_db().tx() as c:
        a, o = _applicant(c, ctx, ctx.path["applicant_id"])
        if to not in NEXT[a["stage"]] or to == "hired":
            raise conflict(f"From {a['stage']} the applicant can move to: {', '.join(s for s in NEXT[a['stage']] if s != 'hired') or 'nothing'}"
                           + (" (use Hire to complete the hiring)" if to == "hired" else ""))
        note = ctx.field("note", required=to == "rejected", kind=str)
        ch = {"stage": to, "updated_at": now_iso()}
        if to == "offer":
            ch["offered_salary"] = to_minor(ctx.field("offered_salary"), "offered_salary")
            ch["start_date"] = parse_date(ctx.field("start_date", kind=str), "start_date").isoformat()
        c.update("applicants", a["id"], ch)
        c.insert("applicant_events", {"applicant_id": a["id"], "kind": "stage", "from_stage": a["stage"], "to_stage": to, "note": note,
                                      "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "recruitment.stage", "applicant", a["id"], o["reference"], old={"stage": a["stage"]}, new={"stage": to}, hotel_id=o["hotel_id"])
    return {"stage": to}


@route("POST", "/api/applicants/{applicant_id:int}/notes", perm="hr.recruit", tag="hr",
       summary="Add a note or an interview record ({kind: note|interview, note, interview_at, score 1-5})")
def add_note(ctx: Ctx):
    kind = ctx.field("kind", required=False, kind=str) or "note"
    if kind not in ("note", "interview"):
        raise bad_request("kind must be note or interview")
    score = ctx.field("score", required=False)
    if score not in (None, "") and not 1 <= int(score) <= 5:
        raise bad_request("score must be 1 to 5")
    with get_db().tx() as c:
        a, o = _applicant(c, ctx, ctx.path["applicant_id"])
        if a["stage"] in ("hired", "rejected", "withdrawn") and kind == "interview":
            raise conflict("This applicant's process is finished")
        c.insert("applicant_events", {"applicant_id": a["id"], "kind": kind, "note": ctx.field("note", kind=str), "interview_at": ctx.field("interview_at", required=False),
                                      "score": int(score) if score not in (None, "") else None, "created_by": ctx.user_id, "created_at": now_iso()})
        if score not in (None, ""):
            avg = c.scalar("SELECT AVG(score) FROM applicant_events WHERE applicant_id = ? AND score IS NOT NULL", [a["id"]])
            c.update("applicants", a["id"], {"rating": max(1, min(5, round(float(avg)))), "updated_at": now_iso()})
    return {"ok": True, "_created": True}


@route("POST", "/api/applicants/{applicant_id:int}/hire", perm="hr.recruit", tag="hr",
       summary="Hire an applicant with an accepted offer: creates the employee record (position, hire_date, basic_salary and other HR fields); needs hr.manage")
def hire(ctx: Ctx):
    ctx.require("hr.manage")
    with get_db().tx() as c:
        a, o = _applicant(c, ctx, ctx.path["applicant_id"])
        if a["stage"] != "offer":
            raise conflict("Only an applicant with an offer can be hired")
        hired = c.scalar("SELECT COUNT(*) FROM applicants WHERE opening_id = ? AND stage = 'hired'", [o["id"]])
        if hired >= o["positions"]:
            raise conflict("All positions for this opening are already filled")
    from .hr import create_employee
    body = {"first_name": a["first_name"], "last_name": a["last_name"], "email": a["email"], "phone": a["phone"], "department": o["department"],
            "position": o["title"], "employment_type": o["employment_type"], "hire_date": str(a["start_date"] or "")[:10] or None,
            "basic_salary": a["offered_salary"] or 0, **(ctx.body or {})}
    sub = Ctx(request=ctx.request, user=ctx.user, permissions=ctx.permissions, hotel_ids=ctx.hotel_ids, path={"hotel_id": o["hotel_id"]}, body=body)
    emp = create_employee(sub)
    with get_db().tx() as c:
        c.update("applicants", a["id"], {"stage": "hired", "employee_id": emp["id"], "updated_at": now_iso()})
        c.insert("applicant_events", {"applicant_id": a["id"], "kind": "stage", "from_stage": "offer", "to_stage": "hired", "note": f"Employee {emp['employee_no']}",
                                      "created_by": ctx.user_id, "created_at": now_iso()})
        filled = c.scalar("SELECT COUNT(*) FROM applicants WHERE opening_id = ? AND stage = 'hired'", [o["id"]])
        if filled >= o["positions"]:
            c.update("job_openings", o["id"], {"status": "filled"})
        # CVs and certificates move with the person
        c.execute("UPDATE documents SET entity_type = 'employee', entity_id = ?, hotel_id = ? WHERE entity_type = 'applicant' AND entity_id = ?",
                  [emp["id"], o["hotel_id"], a["id"]])
        audit(c, ctx, "recruitment.hired", "applicant", a["id"], o["reference"], new={"employee": emp["employee_no"]}, hotel_id=o["hotel_id"])
    return {"employee_id": emp["id"], "employee_no": emp["employee_no"], "opening_filled": filled >= o["positions"]}


@route("POST", "/api/recruitment/{opening_id:int}/anonymise", perm="hr.recruit", tag="hr",
       summary="Anonymise unsuccessful applicants who did not consent to be kept on file (opening must be filled or closed)")
def anonymise(ctx: Ctx):
    with get_db().tx() as c:
        o = _opening(c, ctx, ctx.path["opening_id"])
        if o["status"] not in ("filled", "closed"):
            raise conflict("Close the opening first")
        rows = c.all("SELECT id FROM applicants WHERE opening_id = ? AND stage IN ('rejected','withdrawn') AND consent_to_retain = 0 AND email IS NOT NULL", [o["id"]])
        for r in rows:
            c.update("applicants", r["id"], {"first_name": "Former", "last_name": f"applicant #{r['id']}", "email": None, "phone": None, "updated_at": now_iso()})
            c.execute("UPDATE applicant_events SET note = '[removed]' WHERE applicant_id = ? AND note IS NOT NULL", [r["id"]])
        audit(c, ctx, "recruitment.anonymised", "job_opening", o["id"], o["reference"], new={"applicants": len(rows)}, hotel_id=o["hotel_id"])
    return {"anonymised": len(rows)}
