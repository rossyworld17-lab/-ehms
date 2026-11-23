"""Release 1.1 — full HR suite: every staff member can apply for leave; HR manager approves leave and staff
requests, keeps job history, training and appraisals, creates staff logins, and offboarding removes access."""
import datetime as dt

from ehms.db import get_db

from test_frontoffice_finance import ctx_ids

DEMO_STAFF = ["gm", "fom", "frontdesk", "finance", "accounts", "hkmanager", "housekeeper", "fnbmanager", "cashier", "waiter", "chef",
              "inventory", "stores", "procurement", "hrmanager", "hrofficer", "maintenance", "technician", "security", "sales", "marketing", "guestservice"]


def emp(email):
    with get_db().tx() as c:
        return c.one("SELECT e.* FROM employees e JOIN users u ON u.id = e.user_id WHERE u.email = ?", [email])


def next_weekday(d: dt.date, n: int) -> dt.date:
    d = d + dt.timedelta(days=n)
    while d.weekday() == 6:
        d += dt.timedelta(days=1)
    return d


def test_every_staff_member_can_apply_for_leave_and_hr_approves(client):
    h, _ = ctx_ids()
    for s in DEMO_STAFF:                                  # every staff login is linked to an employee record
        client.login(f"{s}@demo.ehms")
        assert client.get("/api/me/employee").json()["linked"] is True, s
    client.login("waiter@demo.ehms")
    me = client.get("/api/me/employee").json()
    annual = next(b for b in me["leave_balances"] if b["code"] == "ANNUAL")
    start = next_weekday(dt.date.fromisoformat(h["business_date"]), 14)
    r = client.post("/api/me/leave", {"leave_type_id": annual["leave_type_id"], "start_date": start.isoformat(), "end_date": start.isoformat(), "reason": "Family event"})
    assert r.status_code == 201, r.text
    lid = r.json()["id"]
    client.login("waiter@demo.ehms")
    assert client.post(f"/api/leave/{lid}/decide", {"decision": "approve"}).status_code == 403          # staff cannot approve
    client.login("hrmanager@demo.ehms")
    pend = client.get(f"/api/hotels/{h['id']}/leave", params={"status": "pending"}).json()["items"]
    assert any(x["id"] == lid for x in pend)
    assert client.post(f"/api/leave/{lid}/decide", {"decision": "approve"}).json()["status"] == "approved"
    cal = client.get(f"/api/hotels/{h['id']}/hr/leave-calendar", params={"from": start.isoformat(), "to": start.isoformat()}).json()
    assert any(x["id"] == lid for x in cal["items"]) and cal["off_per_day"][start.isoformat()] >= 1
    with get_db().tx() as c:
        assert c.scalar("SELECT COUNT(*) FROM attendance WHERE note = ?", [f"Leave #{lid}"]) == 1
    # the employee cancels approved leave that has not started: attendance is cleared and HR is told
    client.login("waiter@demo.ehms")
    assert client.post(f"/api/me/leave/{lid}/cancel", {"reason": "Event moved"}).json()["status"] == "cancelled"
    with get_db().tx() as c:
        assert c.scalar("SELECT COUNT(*) FROM attendance WHERE note = ?", [f"Leave #{lid}"]) == 0
    assert client.post(f"/api/me/leave/{lid}/cancel", {}).status_code == 409


def test_holidays_adjustments_and_all_staff_balances(client):
    h, _ = ctx_ids()
    client.login("hrmanager@demo.ehms")
    mon = next_weekday(dt.date.fromisoformat(h["business_date"]), 21)
    with get_db().tx() as c:   # a Monday whose week has no seeded public holiday (e.g. not Christmas week)
        hols = {r["holiday_date"] for r in c.all("SELECT holiday_date FROM public_holidays WHERE hotel_id = ?", [h["id"]])}
    while mon.weekday() != 0 or any((mon + dt.timedelta(days=i)).isoformat() in hols for i in range(6)):
        mon += dt.timedelta(days=1)
    assert client.post(f"/api/hotels/{h['id']}/holidays", {"holiday_date": mon.isoformat(), "name": "Test holiday"}).status_code == 201
    assert client.post(f"/api/hotels/{h['id']}/holidays", {"holiday_date": mon.isoformat(), "name": "Twice"}).status_code == 409
    e = emp("cashier@demo.ehms")
    client.login("cashier@demo.ehms")
    bal = client.get("/api/me/employee").json()["leave_balances"]
    annual = next(b for b in bal if b["code"] == "ANNUAL")
    r = client.post("/api/me/leave", {"leave_type_id": annual["leave_type_id"], "start_date": mon.isoformat(), "end_date": (mon + dt.timedelta(days=5)).isoformat()})
    assert r.json()["days"] == 5                                                  # Mon–Sat = 6 days, minus the holiday
    client.login("hrmanager@demo.ehms")
    assert client.post(f"/api/employees/{e['id']}/leave-adjustments", {"leave_type_id": annual["leave_type_id"], "days": 3, "reason": "Carry-over from last year"}).status_code == 201
    allb = client.get(f"/api/hotels/{h['id']}/hr/leave-balances").json()
    mine = next(x for x in allb["items"] if x["employee_id"] == e["id"])
    a = next(b for b in mine["balances"] if b["code"] == "ANNUAL")
    assert a["entitlement"] == annual["entitlement"] + 3 and a["adjustment"] == 3 and a["pending"] == 5
    client.login("frontdesk@demo.ehms")
    assert client.post(f"/api/employees/{e['id']}/leave-adjustments", {"leave_type_id": annual["leave_type_id"], "days": 3, "reason": "x"}).status_code == 403


def test_hr_dashboard_alerts(client):
    h, _ = ctx_ids()
    client.login("hrmanager@demo.ehms")
    d = client.get(f"/api/hotels/{h['id']}/hr/dashboard").json()
    assert d["headcount"] >= 20 and d["by_department"]
    assert any(x["name"].startswith("Sani") for x in d["alerts"]["probation_ending"])            # waiter's probation ends in 10 days
    assert d["alerts"]["contracts_ending"] and d["alerts"]["certifications_expiring"]
    assert d["pending"]["requests"] >= 3 and d["holidays"]
    client.login("waiter@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/hr/dashboard").status_code == 403


def test_staff_requests_lifecycle(client):
    h, _ = ctx_ids()
    hk, fd, waiter = emp("housekeeper@demo.ehms"), emp("frontdesk@demo.ehms"), emp("waiter@demo.ehms")
    client.login("housekeeper@demo.ehms")
    assert client.post("/api/me/requests", {"kind": "salary_advance", "amount": 999_999_999_99}).status_code == 409     # above the limit
    assert client.post("/api/me/requests", {"kind": "data_change", "data": {"basic_salary": 1}}).status_code == 400     # pay is HR-only
    g = client.post("/api/me/requests", {"kind": "grievance", "subject": "Unfair roster", "details": "Night shifts every week for two months"}).json()
    client.login("hrofficer@demo.ehms")                                             # no confidential-records access
    items = client.get(f"/api/hotels/{h['id']}/hr/requests").json()["items"]
    assert not any(x["id"] == g["id"] for x in items)
    client.login("hrmanager@demo.ehms")
    reqs = {(x["employee_id"], x["kind"]): x for x in client.get(f"/api/hotels/{h['id']}/hr/requests", params={"status": "submitted"}).json()["items"]}
    assert (hk["id"], "grievance") in reqs
    # detail change: applied on approval
    dc = reqs[(waiter["id"], "data_change")]
    assert client.post(f"/api/hr/requests/{dc['id']}/decide", {"decision": "approve"}).json()["status"] == "completed"
    assert emp("waiter@demo.ehms")["address"].startswith("14 Adeola")
    # letter: PDF for the employee only once approved
    lt = reqs[(fd["id"], "letter")]
    client.login("frontdesk@demo.ehms")
    assert client.get(f"/api/hr/requests/{lt['id']}/letter.pdf").status_code == 409
    client.login("hrmanager@demo.ehms")
    client.post(f"/api/hr/requests/{lt['id']}/decide", {"decision": "approve"})
    client.login("frontdesk@demo.ehms")
    pdf = client.get(f"/api/hr/requests/{lt['id']}/letter.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    client.login("waiter@demo.ehms")
    assert client.get(f"/api/hr/requests/{lt['id']}/letter.pdf").status_code == 403
    # advance: approved by HR, then paid by finance
    adv = reqs[(hk["id"], "salary_advance")]
    client.login("hrmanager@demo.ehms")
    assert client.post(f"/api/hr/requests/{adv['id']}/decide", {"decision": "reject"}).status_code == 400   # reason needed
    assert client.post(f"/api/hr/requests/{adv['id']}/decide", {"decision": "approve"}).json()["status"] == "approved"
    client.login("finance@demo.ehms")                                               # approves payroll, does not pay
    assert client.post(f"/api/hr/requests/{adv['id']}/complete").status_code == 403
    client.login("accounts@demo.ehms")                                              # the accountant pays it out
    assert client.post(f"/api/hr/requests/{adv['id']}/complete").json()["status"] == "completed"
    # the HR manager cannot decide their own request
    client.login("hrmanager@demo.ehms")
    own = client.post("/api/me/requests", {"kind": "letter", "subject": "Bank loan"}).json()
    assert client.post(f"/api/hr/requests/{own['id']}/decide", {"decision": "approve"}).status_code == 403
    # the employee sees outcomes and can withdraw an undecided request
    client.login("housekeeper@demo.ehms")
    mine = {x["kind"]: x for x in client.get("/api/me/requests").json()["items"]}
    assert mine["salary_advance"]["status"] == "completed"
    assert client.post(f"/api/me/requests/{g['id']}/cancel").json()["status"] == "cancelled"


def test_shift_swap_request(client):
    h, _ = ctx_ids()
    a, b = emp("waiter@demo.ehms"), emp("cashier@demo.ehms")
    day = next_weekday(dt.date.fromisoformat(h["business_date"]), 3).isoformat()
    client.login("hrmanager@demo.ehms")
    shifts = client.get(f"/api/hotels/{h['id']}/roster").json()["shifts"]
    client.put(f"/api/hotels/{h['id']}/roster", {"assignments": [{"employee_id": a["id"], "date": day, "shift_id": shifts[0]["id"]},
                                                                {"employee_id": b["id"], "date": day, "shift_id": shifts[-1]["id"]}]})
    client.login("waiter@demo.ehms")
    r = client.post("/api/me/requests", {"kind": "shift_swap", "date": day, "with_employee_id": b["id"], "details": "Doctor's appointment"}).json()
    client.login("hrmanager@demo.ehms")
    client.post(f"/api/hr/requests/{r['id']}/decide", {"decision": "approve"})
    with get_db().tx() as c:
        sa = c.scalar("SELECT shift_id FROM shift_assignments WHERE employee_id = ? AND work_date = ?", [a["id"], day])
        sb = c.scalar("SELECT shift_id FROM shift_assignments WHERE employee_id = ? AND work_date = ?", [b["id"], day])
    assert (sa, sb) == (shifts[-1]["id"], shifts[0]["id"])


def test_job_history_training_and_appraisals(client):
    h, _ = ctx_ids()
    w = emp("waiter@demo.ehms")
    client.login("hrmanager@demo.ehms")
    p = client.post(f"/api/employees/{w['id']}/history", {"kind": "promotion", "effective_date": h["business_date"], "position": "Senior Waiter", "basic_salary": 13_000_000,
                                                          "note": "Excellent guest feedback"})
    assert p.status_code == 201
    assert client.post(f"/api/employees/{w['id']}/history", {"kind": "salary_change", "effective_date": h["business_date"]}).status_code == 400
    assert client.post(f"/api/employees/{w['id']}/history", {"kind": "confirmation", "effective_date": h["business_date"]}).status_code == 201
    e = client.get(f"/api/employees/{w['id']}").json()
    assert e["position"] == "Senior Waiter" and e["basic_salary"] == 13_000_000 and e["probation_end_date"] == h["business_date"]
    assert [x["kind"] for x in e["history"]][:2] == ["confirmation", "promotion"] and e["line_manager"]
    assert client.post(f"/api/employees/{w['id']}/trainings", {"kind": "certification", "title": "Food handler", "completed_on": "2026-05-01", "expires_on": "2026-01-01"}).status_code == 400
    assert client.post(f"/api/employees/{w['id']}/trainings", {"kind": "certification", "title": "Food handler", "completed_on": "2026-05-01", "expires_on": "2027-05-01"}).status_code == 201
    crit = [{"name": "Service", "rating": 5}, {"name": "Upselling", "rating": 3}]
    assert client.post(f"/api/employees/{w['id']}/appraisals", {"period": "2026 H2", "criteria": [{"name": "x", "rating": 9}]}).status_code == 400
    a = client.post(f"/api/employees/{w['id']}/appraisals", {"period": "2026 H2", "criteria": crit, "goals": "Lead the breakfast team"}).json()
    assert a["overall_rating"] == 4
    hm = emp("hrmanager@demo.ehms")
    assert client.post(f"/api/employees/{hm['id']}/appraisals", {"period": "2026 H2", "criteria": crit}).status_code == 403          # not yourself
    client.login("waiter@demo.ehms")
    assert not any(x["id"] == a["id"] for x in client.get("/api/me/hr").json()["appraisals"])                                   # drafts are private
    client.login("hrmanager@demo.ehms")
    assert client.post(f"/api/appraisals/{a['id']}/share").json()["status"] == "shared"
    assert client.patch(f"/api/appraisals/{a['id']}", {"goals": "x"}).status_code == 409
    client.login("waiter@demo.ehms")
    me = client.get("/api/me/hr").json()
    assert any(x["id"] == a["id"] for x in me["appraisals"]) and me["profile"]["position"] == "Senior Waiter" and me["trainings"]
    assert client.post(f"/api/me/appraisals/{a['id']}/acknowledge", {"comment": "Thank you"}).json()["status"] == "acknowledged"
    client.login("hrofficer@demo.ehms")
    assert client.post(f"/api/employees/{w['id']}/appraisals", {"period": "x", "criteria": crit}).status_code == 403
    assert client.post(f"/api/employees/{w['id']}/history", {"kind": "promotion", "effective_date": h["business_date"], "position": "x"}).status_code == 201  # HR officer manages records


def test_hr_creates_logins_and_offboarding_removes_access(client):
    h, _ = ctx_ids()
    client.login("hrmanager@demo.ehms")
    new = client.post(f"/api/hotels/{h['id']}/employees", {"first_name": "Bisi", "last_name": "Adeyemi", "department": "housekeeping", "position": "Room Attendant",
                                                           "hire_date": h["business_date"], "email": "bisi.adeyemi@example.com", "basic_salary": 12_000_000}).json()
    roles = {r["code"]: r["id"] for r in client.get("/api/hr/assignable-roles").json()["items"]}
    assert "housekeeping_staff" in roles and "super_admin" not in roles and "it_admin" not in roles
    with get_db().tx() as c:
        admin_role = c.scalar("SELECT id FROM roles WHERE code = 'super_admin'")
    assert client.post(f"/api/employees/{new['id']}/account", {"role_id": admin_role}).status_code == 403
    acc = client.post(f"/api/employees/{new['id']}/account", {"role_id": roles["housekeeping_staff"]})
    assert acc.status_code == 201, acc.text
    temp = acc.json()["temporary_password"]
    assert client.post(f"/api/employees/{new['id']}/account", {"role_id": roles["housekeeping_staff"]}).status_code == 409
    r = client.post("/api/auth/login", {"email": "bisi.adeyemi@example.com", "password": temp}, token=None)
    assert r.status_code == 200 and r.json()["user"]["must_change_password"]
    # the new starter can use My HR straight away
    client.token = r.json()["token"]
    assert client.get("/api/me/employee").json()["linked"] is True
    # offboarding: recording the exit suspends the login and ends sessions
    client.login("hrmanager@demo.ehms")
    assert client.patch(f"/api/employees/{new['id']}", {"status": "resigned", "exit_reason": "Relocated"}).status_code == 200
    assert client.post("/api/auth/login", {"email": "bisi.adeyemi@example.com", "password": temp}, token=None).status_code in (401, 403)
    client.login("frontdesk@demo.ehms")
    assert client.post(f"/api/employees/{new['id']}/account", {"role_id": roles["housekeeping_staff"]}).status_code == 403


def test_hr_can_end_leave_early(client):
    h, _ = ctx_ids()
    e = emp("chef@demo.ehms")
    bd = dt.date.fromisoformat(h["business_date"])
    with get_db().tx() as c:
        t = c.one("SELECT * FROM leave_types WHERE hotel_id = ? AND code = 'ANNUAL'", [h["id"]])
        lid = c.insert("leave_requests", {"employee_id": e["id"], "leave_type_id": t["id"], "start_date": (bd - dt.timedelta(days=3)).isoformat(),
                                           "end_date": (bd + dt.timedelta(days=4)).isoformat(), "days": 7, "status": "approved", "requested_by": e["user_id"],
                                           "created_at": "2026-01-01T00:00:00Z"})
    client.login("chef@demo.ehms")
    assert client.post(f"/api/me/leave/{lid}/cancel", {}).status_code == 409                   # already started
    client.login("hrmanager@demo.ehms")
    r = client.post(f"/api/leave/{lid}/cancel", {"reason": "Needed back for a banquet"}).json()
    assert r["status"] == "approved" and r["end_date"] == (bd - dt.timedelta(days=1)).isoformat()
