"""Release 0.6: laundry, HR (employees, attendance, leave, records, self-service) and payroll."""
import datetime as dt
import uuid

from ehms.db import get_db

from test_frontoffice_finance import arrival_today, ctx_ids
from test_pos_inventory_procurement import assert_books_balance, gl_balance


def user_id(email):
    with get_db().tx() as c:
        return c.scalar("SELECT id FROM users WHERE email = ?", [email])


# ------------------------------------------------------------------ laundry
def test_guest_laundry_billed_on_delivery_and_internal_linen(client):
    client.login("frontdesk@demo.ehms")
    h, methods = ctx_ids()
    res, _ = arrival_today(client, h)
    folio_id = client.post(f"/api/reservations/{res['id']}/check-in", {}).json()["folio"]["id"]
    client.login("hkmanager@demo.ehms")
    p = client.post(f"/api/hotels/{h['id']}/laundry/prices", {"item": "Shirt", "service": "wash_iron", "price": 150000, "express_surcharge_bp": 5000})
    assert p.status_code == 201
    o = client.post(f"/api/hotels/{h['id']}/laundry/orders", {"kind": "guest", "reservation_id": res["id"], "express": True,
                                                              "items": [{"price_id": p.json()["id"], "quantity": 3, "condition_note": "Collar stain"}]})
    assert o.status_code == 201, o.text
    order = o.json()
    assert order["total"] == 3 * 150000 * 3 // 2
    # one shirt is damaged: recorded with a note and not charged
    item = order["items"][0]
    assert client.post(f"/api/laundry/items/{item['id']}/outcome", {"outcome": "damaged"}).status_code == 400
    # split the damaged piece into its own line by re-registering quantities is not needed: whole line outcome applies
    assert client.post(f"/api/laundry/orders/{order['id']}/status", {"status": "delivered"}).status_code == 409   # must pass QC
    for st in ("washing", "drying", "ironing", "quality_check"):
        assert client.post(f"/api/laundry/orders/{order['id']}/status", {"status": st}).status_code == 200
    assert client.post(f"/api/laundry/orders/{order['id']}/status", {"status": "washing"}).status_code == 400    # cannot go back
    assert client.post(f"/api/laundry/orders/{order['id']}/status", {"status": "cancelled", "reason": "x"}).status_code == 409
    d = client.post(f"/api/laundry/orders/{order['id']}/status", {"status": "delivered"})
    assert d.status_code == 200 and d.json()["folio_line_id"]
    client.login("frontdesk@demo.ehms")
    line = next(l for l in client.get(f"/api/folios/{folio_id}").json()["lines"] if l["reference"] == order["number"])
    assert line["department"] == "laundry" and line["net_amount"] == 675000
    # internal linen batch: no charge
    client.login("housekeeper@demo.ehms")
    i = client.post(f"/api/hotels/{h['id']}/laundry/orders", {"kind": "internal", "department": "housekeeping",
                                                              "items": [{"description": "Bed sheets", "service": "wash_iron", "quantity": 40}]}).json()
    assert i["total"] == 0
    damaged = client.post(f"/api/laundry/items/{i['items'][0]['id']}/outcome", {"outcome": "lost", "note": "2 sheets missing from batch"})
    assert damaged.status_code == 200
    summ = client.get(f"/api/hotels/{h['id']}/laundry/summary").json()
    assert summ["guest"]["revenue"] == 675000 and summ["internal"][0]["pieces"] == 40 and summ["issues"][0]["outcome"] == "lost"
    # guest laundry needs a checked-in guest; receptionist without manage? (receptionist has laundry) — accountant has none
    client.login("accounts@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/laundry/orders").status_code == 403
    assert_books_balance(h["id"])


# ------------------------------------------------------------------ HR
def linked_employee(client, email, **salary):
    """The demo seed links every staff account to an employee record; optionally reset its pay for exact maths."""
    with get_db().tx() as c:
        eid = c.scalar("SELECT e.id FROM employees e JOIN users u ON u.id = e.user_id WHERE u.email = ?", [email])
    if salary:
        assert client.patch(f"/api/employees/{eid}", {"other_allowance": 0, "annual_rent": 0, **salary}).status_code == 200
    return {"id": eid}


def make_employee(client, h, **kw):
    body = {"first_name": "Ada", "last_name": f"Test{uuid.uuid4().hex[:4]}", "department": "housekeeping", "position": "Room attendant",
            "hire_date": "2025-01-06", "basic_salary": 20000000, "housing_allowance": 10000000, "transport_allowance": 5000000,
            "bank_name": "Demo Bank", "bank_account_number": "0123456789", "tax_id": "TIN-1", **kw}
    r = client.post(f"/api/hotels/{h['id']}/employees", body)
    assert r.status_code == 201, r.text
    return r.json()


def test_employee_register_visibility_and_records(client):
    h, _ = ctx_ids()
    client.login("hrmanager@demo.ehms")
    e = make_employee(client, h)
    assert e["employee_no"].startswith("EMP-CGL-")
    assert client.post(f"/api/employees/{e['id']}/records", {"kind": "appraisal", "record_date": "2026-06-30", "title": "Mid-year review", "rating": 4}).status_code == 201
    full = client.get(f"/api/employees/{e['id']}").json()
    assert full["basic_salary"] == 20000000 and full["bank_account_number"] == "0123456789" and len(full["records"]) == 2
    # a department manager sees the employee but not pay, bank details or confidential records
    client.login("hkmanager@demo.ehms")
    v = client.get(f"/api/employees/{e['id']}").json()
    assert "basic_salary" not in v and v["bank_account_number"].endswith("6789") and v["bank_account_number"].startswith("•") and v["records"] is None
    assert client.post(f"/api/hotels/{h['id']}/employees", {}).status_code == 403
    client.login("frontdesk@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/employees").status_code == 403
    # exit records the reason and date
    client.login("hrmanager@demo.ehms")
    assert client.patch(f"/api/employees/{e['id']}", {"status": "resigned"}).status_code == 400   # reason required
    assert client.patch(f"/api/employees/{e['id']}", {"status": "resigned", "exit_reason": "Relocation", "exit_date": "2026-11-30"}).status_code == 200
    assert client.get(f"/api/employees/{e['id']}").json()["status"] == "resigned"


def test_leave_self_service_approval_and_attendance(client):
    h, _ = ctx_ids()
    client.login("hrmanager@demo.ehms")
    e = linked_employee(client, "housekeeper@demo.ehms")
    client.login("housekeeper@demo.ehms")
    me = client.get("/api/me/employee").json()
    assert me["linked"] and me["employee"]["id"] == e["id"]
    annual = next(b for b in me["leave_balances"] if b["code"] == "ANNUAL")
    assert annual["entitlement"] == 15
    # Mon 2027-01-04 .. Wed 2027-01-06 = 3 working days
    r = client.post("/api/me/leave", {"leave_type_id": annual["leave_type_id"], "start_date": "2027-01-04", "end_date": "2027-01-06", "reason": "Family"})
    assert r.status_code == 201 and r.json()["days"] == 3
    assert client.post("/api/me/leave", {"leave_type_id": annual["leave_type_id"], "start_date": "2027-01-05", "end_date": "2027-01-05"}).status_code == 409
    assert client.post("/api/me/leave", {"leave_type_id": annual["leave_type_id"], "start_date": "2027-02-01", "end_date": "2027-02-28"}).status_code == 409
    assert client.post(f"/api/leave/{r.json()['id']}/decide", {"decision": "approve"}).status_code == 403   # staff cannot approve
    client.login("hkmanager@demo.ehms")
    assert client.post(f"/api/leave/{r.json()['id']}/decide", {"decision": "approve"}).json()["status"] == "approved"
    sheet = client.get(f"/api/hotels/{h['id']}/attendance", params={"date": "2027-01-05"}).json()
    assert next(x for x in sheet["items"] if x["employee_id"] == e["id"])["status"] == "leave"
    client.login("housekeeper@demo.ehms")
    assert client.get("/api/notifications/mine").json()["items"][0]["subject"] == "Leave approved"
    # self clock-in / clock-out
    assert client.post("/api/me/clock", {"action": "out"}).status_code == 409
    assert client.post("/api/me/clock", {"action": "in"}).json()["clocked"] == "in"
    assert client.post("/api/me/clock", {"action": "in"}).status_code == 409
    assert client.post("/api/me/clock", {"action": "out"}).json()["clocked"] == "out"
    # a manager cannot approve their own leave
    client.login("hrmanager@demo.ehms")
    lv = client.get(f"/api/hotels/{h['id']}/leave").json()
    sick = next(t for t in lv["types"] if t["code"] == "SICK")
    own = client.post("/api/me/leave", {"leave_type_id": sick["id"], "start_date": "2027-03-01", "end_date": "2027-03-01"}).json()
    assert client.post(f"/api/leave/{own['id']}/decide", {"decision": "approve"}).status_code == 403


# ------------------------------------------------------------------ payroll
def test_payroll_compute_approve_pay_remit(client):
    h, methods = ctx_ids()
    bd = dt.date.fromisoformat(h["business_date"])
    period = bd.strftime("%Y-%m")
    client.login("hrmanager@demo.ehms")
    clean = linked_employee(client, "housekeeper2@demo.ehms", basic_salary=20000000, housing_allowance=10000000, transport_allowance=5000000,
                            hire_date="2024-01-01")
    busy = make_employee(client, h, first_name="Busy", hire_date="2024-01-01")
    # attendance for "busy": one absence and two hours overtime this month
    d1 = bd.replace(day=2).isoformat()
    d2 = bd.replace(day=3).isoformat()
    assert client.put(f"/api/hotels/{h['id']}/attendance", {"date": d1, "rows": [{"employee_id": busy["id"], "status": "absent"}]}).status_code == 200
    client.put(f"/api/hotels/{h['id']}/attendance", {"date": d2, "rows": [{"employee_id": busy["id"], "status": "present", "overtime_minutes": 120}]})
    # staff loan for "clean" (granted by accounts)
    client.login("accounts@demo.ehms")
    assert client.post(f"/api/employees/{clean['id']}/loans", {"description": "Salary advance", "principal": 3000000, "monthly_deduction": 1000000,
                                                               "method_id": methods["CASH"]}).status_code == 201
    client.login("hrmanager@demo.ehms")
    run = client.post(f"/api/hotels/{h['id']}/payroll/runs", {"period": period})
    assert run.status_code == 201, run.text
    rid = run.json()["id"]
    assert client.post(f"/api/hotels/{h['id']}/payroll/runs", {"period": period}).status_code == 409
    client.post(f"/api/payroll/runs/{rid}/adjustments", {"employee_id": busy["id"], "kind": "bonus", "amount": 1000000, "note": "Guest compliment award"})
    detail = client.get(f"/api/payroll/runs/{rid}").json()
    c = next(s for s in detail["payslips"] if s["employee_id"] == clean["id"])
    # hand-checked: fixed 350,000 → pension 28,000, NHF 5,000; annual taxable 4,200,000 − 396,000 = 3,804,000
    # PAYE = 2,200,000 × 15% + 804,000 × 18% = 474,720 per year = 39,560 per month
    assert (c["gross"], c["pension_employee"], c["nhf"], c["paye"], c["pension_employer"]) == (35000000, 2800000, 500000, 3956000, 3500000)
    assert c["loan_deduction"] == 1000000 and c["net"] == 35000000 - 2800000 - 500000 - 3956000 - 1000000
    b = next(s for s in detail["payslips"] if s["employee_id"] == busy["id"])
    assert b["absence_deduction"] == 35000000 // 22 and b["bonus"] == 1000000 and b["overtime"] > 0
    # maker-checker: HR prepared, HR cannot approve; finance approves
    assert client.post(f"/api/payroll/runs/{rid}/approve", {}).status_code == 403
    client.login("finance@demo.ehms")
    ap = client.post(f"/api/payroll/runs/{rid}/approve", {})
    assert ap.status_code == 200, ap.text
    t = detail["totals"]
    t = client.get(f"/api/payroll/runs/{rid}").json()["totals"]
    assert gl_balance("salaries_payable", h["id"]) == -t["net"]
    assert gl_balance("paye_payable", h["id"]) == -t["paye"]
    with get_db().tx() as cx:
        assert cx.scalar("SELECT balance FROM employee_loans WHERE employee_id = ?", [clean["id"]]) == 2000000
    assert client.post(f"/api/payroll/runs/{rid}/adjustments", {"employee_id": busy["id"], "kind": "bonus", "amount": 1, "note": "x"}).status_code in (403, 409)
    # accountant pays and remits PAYE once; exports the bank schedule
    client.login("accounts@demo.ehms")
    assert client.post(f"/api/payroll/runs/{rid}/pay", {"method_id": methods["TRANSFER"]}).status_code == 400   # reference required
    assert client.post(f"/api/payroll/runs/{rid}/pay", {"method_id": methods["TRANSFER"], "reference": "BULK-1"}).json()["status"] == "paid"
    assert gl_balance("salaries_payable", h["id"]) == 0
    assert client.post(f"/api/payroll/runs/{rid}/remit", {"liability": "paye", "method_id": methods["TRANSFER"], "reference": "LIRS-1"}).json()["amount"] == t["paye"]
    assert client.post(f"/api/payroll/runs/{rid}/remit", {"liability": "paye", "method_id": methods["TRANSFER"]}).status_code == 409
    assert gl_balance("paye_payable", h["id"]) == 0
    csv_ = client.get(f"/api/payroll/runs/{rid}/bank-schedule.csv")
    assert csv_.status_code == 200 and "0123456789" in csv_.text
    # the employee downloads their own payslip; another employee cannot
    client.login("housekeeper2@demo.ehms")
    mine = client.get("/api/me/employee").json()["payslips"]
    assert mine and client.get(f"/api/payslips/{mine[0]['id']}.pdf").content[:4] == b"%PDF"
    other = b["id"]
    assert client.get(f"/api/payslips/{other}.pdf").status_code == 403
    assert_books_balance(h["id"])


def test_payroll_rules_configurable_and_validated(client):
    h, _ = ctx_ids()
    client.login("finance@demo.ehms")
    assert client.put(f"/api/hotels/{h['id']}/payroll/rules", {"paye_bands": [[100, 0]]}).status_code == 400
    assert client.put(f"/api/hotels/{h['id']}/payroll/rules", {"nonsense": 1}).status_code == 400
    r = client.put(f"/api/hotels/{h['id']}/payroll/rules", {"pension_employee_bp": 750, "paye_bands": [[None, 1000]]})
    assert r.status_code == 200 and r.json()["rules"]["pension_employee_bp"] == 750
    from ehms.modules.payroll import annual_paye
    assert annual_paye(1_000_000, [[None, 1000]]) == 100_000
    client.login("hrmanager@demo.ehms")
    assert client.put(f"/api/hotels/{h['id']}/payroll/rules", {"nhf_bp": 0}).status_code == 403
