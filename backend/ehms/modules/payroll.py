"""Payroll: configurable statutory rules, payroll runs computed from salary structure + attendance + adjustments,
maker-checker approval posting to the ledger, payment and statutory remittance, payslips (PDF), bank schedule,
staff loans. (FR-PAYR-001..005)

Statutory defaults reflect Nigerian rules as commonly applied from 2026 (Nigeria Tax Act 2025 PAYE bands with
rent relief; Pension Reform Act 8 % employee / 10 % employer on basic + housing + transport; NHF 2.5 % of
basic; NSITF 1 % and ITF 1 % employer). EVERY rate and band is configurable per hotel and is stored with each
run — confirm them with your tax and payroll advisers before use."""
from __future__ import annotations

import calendar
import csv
import datetime as dt
import io
import json

from starlette.responses import Response

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import account_id, business_date, get_hotel, hotel_setting, post_journal, set_hotel_setting, to_minor

DEFAULT_RULES = {
    "working_days": 22, "hours_per_day": 8, "overtime_multiplier_bp": 15000,
    "pension_employee_bp": 800, "pension_employer_bp": 1000, "pension_base": ["basic", "housing", "transport"],
    "nhf_bp": 250, "nsitf_employer_bp": 100, "itf_employer_bp": 100,
    # annual bands: [width in kobo or null for the remainder, rate in basis points]
    "paye_bands": [[80_000_000, 0], [220_000_000, 1500], [900_000_000, 1800], [1_300_000_000, 2100], [2_500_000_000, 2300], [None, 2500]],
    "rent_relief_bp": 2000, "rent_relief_cap": 50_000_000,
    "minimum_wage": 7_000_000,
}


def rules_for(c, hid: int) -> dict:
    raw = hotel_setting(c, hid, "payroll.rules")
    return {**DEFAULT_RULES, **(json.loads(raw) if raw else {})}


def annual_paye(taxable: int, bands: list) -> int:
    tax, rest = 0, max(0, taxable)
    for width, rate in bands:
        portion = rest if width is None else min(rest, width)
        tax += portion * rate // 10000
        rest -= portion
        if rest <= 0:
            break
    return tax


def compute_payslip(e: dict, rules: dict, absent: int, overtime_minutes: int, bonus: int, other_deduction: int, loan: int) -> dict:
    wd = max(1, rules["working_days"])
    fixed = e["basic_salary"] + e["housing_allowance"] + e["transport_allowance"] + e["other_allowance"]
    absence = fixed * min(absent, wd) // wd
    hourly = e["basic_salary"] / (wd * rules["hours_per_day"])
    overtime = int(round(hourly * overtime_minutes / 60 * rules["overtime_multiplier_bp"] / 10000))
    gross = fixed - absence + overtime + bonus
    base_parts = {"basic": e["basic_salary"], "housing": e["housing_allowance"], "transport": e["transport_allowance"], "other": e["other_allowance"]}
    pension_base = sum(base_parts[k] for k in rules["pension_base"] if k in base_parts)
    pension_emp = pension_base * rules["pension_employee_bp"] // 10000
    pension_er = pension_base * rules["pension_employer_bp"] // 10000
    nhf = e["basic_salary"] * rules["nhf_bp"] // 10000
    rent_relief = min(e["annual_rent"] * rules["rent_relief_bp"] // 10000, rules["rent_relief_cap"])
    taxable = gross * 12 - (pension_emp + nhf) * 12 - rent_relief
    paye = (annual_paye(taxable, rules["paye_bands"]) + 6) // 12
    employer_other = gross * (rules["nsitf_employer_bp"] + rules["itf_employer_bp"]) // 10000
    loan = min(loan, max(0, gross - pension_emp - nhf - paye - other_deduction))
    net = gross - pension_emp - nhf - paye - loan - other_deduction
    return {"basic": e["basic_salary"], "housing": e["housing_allowance"], "transport": e["transport_allowance"], "other_allowance": e["other_allowance"],
            "overtime": overtime, "bonus": bonus, "absence_deduction": absence, "gross": gross, "pension_employee": pension_emp, "nhf": nhf, "paye": paye,
            "loan_deduction": loan, "other_deduction": other_deduction, "net": net, "pension_employer": pension_er, "employer_other": employer_other,
            "details": json.dumps({"annual_taxable": taxable, "rent_relief": rent_relief, "overtime_minutes": overtime_minutes,
                                   "below_minimum_wage": fixed < rules["minimum_wage"]})}


@route("GET", "/api/hotels/{hotel_id:int}/payroll/rules", perm="payroll.view", tag="payroll", summary="Statutory payroll rules in force (defaults + hotel overrides)")
def get_rules(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"rules": rules_for(c, hid), "defaults": DEFAULT_RULES}


@route("PUT", "/api/hotels/{hotel_id:int}/payroll/rules", perm="payroll.approve", tag="payroll", summary="Override statutory payroll rules (audited)")
def put_rules(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    body = ctx.body or {}
    with get_db().tx() as c:
        current = rules_for(c, hid)
        new = dict(current)
        for k, v in body.items():
            if k not in DEFAULT_RULES:
                raise bad_request(f"Unknown rule '{k}'")
            if k == "paye_bands":
                if not isinstance(v, list) or not v or any(not isinstance(b, list) or len(b) != 2 for b in v) or v[-1][0] is not None:
                    raise bad_request("paye_bands must be a list of [width, rate_bp] ending with [null, rate_bp]")
            elif k == "pension_base":
                if not set(v) <= {"basic", "housing", "transport", "other"}:
                    raise bad_request("pension_base may contain basic, housing, transport, other")
            elif not isinstance(v, int) or v < 0:
                raise bad_request(f"'{k}' must be a non-negative whole number")
            new[k] = v
        set_hotel_setting(c, hid, "payroll.rules", json.dumps({k: v for k, v in new.items() if v != DEFAULT_RULES.get(k)}))
        audit(c, ctx, "payroll.rules_changed", "payroll_rules", hid, old=current, new=new, hotel_id=hid)
    return {"rules": new}


# ------------------------------------------------------------------ runs
def _run(c, ctx: Ctx, run_id, lock=False) -> dict:
    r = c.lock("payroll_runs", int(run_id)) if lock else c.one("SELECT * FROM payroll_runs WHERE id = ?", [int(run_id)])
    if not r:
        raise not_found("Payroll run")
    ctx.check_hotel(r["hotel_id"])
    return r


def _compute_run(c, run: dict) -> None:
    hid = run["hotel_id"]
    rules = json.loads(run["rules"])
    y, m = int(run["period"][:4]), int(run["period"][5:])
    first, last = dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1])
    c.execute("DELETE FROM payslips WHERE run_id = ?", [run["id"]])
    emps = c.all("SELECT * FROM employees WHERE hotel_id = ? AND hire_date <= ? AND (status = 'active' OR (exit_date IS NOT NULL AND exit_date >= ?))",
                 [hid, last.isoformat(), first.isoformat()])
    totals = {"gross": 0, "net": 0, "paye": 0, "employer_cost": 0}
    for e in emps:
        att = c.one("SELECT COALESCE(SUM(CASE WHEN status = 'absent' THEN 1 ELSE 0 END),0) AS absent, COALESCE(SUM(overtime_minutes),0) AS ot FROM attendance "
                    "WHERE employee_id = ? AND work_date >= ? AND work_date <= ?", [e["id"], first.isoformat(), last.isoformat()])
        unpaid = c.scalar("SELECT COALESCE(SUM(l.days),0) FROM leave_requests l JOIN leave_types t ON t.id = l.leave_type_id WHERE l.employee_id = ? AND l.status = 'approved' "
                          "AND t.paid = 0 AND l.start_date >= ? AND l.start_date <= ?", [e["id"], first.isoformat(), last.isoformat()]) or 0
        adj = c.one("SELECT COALESCE(SUM(CASE WHEN kind = 'bonus' THEN amount ELSE 0 END),0) AS bonus, COALESCE(SUM(CASE WHEN kind = 'deduction' THEN amount ELSE 0 END),0) AS ded "
                    "FROM payroll_adjustments WHERE run_id = ? AND employee_id = ?", [run["id"], e["id"]])
        loan = c.scalar("SELECT COALESCE(SUM(CASE WHEN monthly_deduction < balance THEN monthly_deduction ELSE balance END),0) FROM employee_loans "
                        "WHERE employee_id = ? AND status = 'active'", [e["id"]]) or 0
        # partial month for joiners and leavers
        start = max(first, dt.date.fromisoformat(e["hire_date"]))
        end = min(last, dt.date.fromisoformat(e["exit_date"])) if e["exit_date"] else last
        not_employed = round(((start - first).days + (last - end).days) * rules["working_days"] / ((last - first).days + 1))
        p = compute_payslip(e, rules, att["absent"] + unpaid + not_employed, att["ot"], adj["bonus"], adj["ded"], loan)
        c.insert("payslips", {"run_id": run["id"], "employee_id": e["id"], "days_in_period": rules["working_days"], "days_absent": att["absent"] + unpaid + not_employed, **p})
        totals["gross"] += p["gross"]
        totals["net"] += p["net"]
        totals["paye"] += p["paye"]
        totals["employer_cost"] += p["gross"] + p["pension_employer"] + p["employer_other"]
    c.update("payroll_runs", run["id"], {"employees": len(emps), **totals})


@route("GET", "/api/hotels/{hotel_id:int}/payroll/runs", perm="payroll.view", tag="payroll", summary="Payroll runs")
def list_runs(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        return {"items": c.all("SELECT r.*, u.full_name AS created_by_name, a.full_name AS approved_by_name FROM payroll_runs r JOIN users u ON u.id = r.created_by "
                               "LEFT JOIN users a ON a.id = r.approved_by WHERE r.hotel_id = ? ORDER BY r.period DESC", [hid])}


@route("POST", "/api/hotels/{hotel_id:int}/payroll/runs", perm="payroll.run", tag="payroll", summary="Prepare a payroll run for a month (period YYYY-MM)")
def create_run(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    period = ctx.field("period", kind=str)
    try:
        dt.date.fromisoformat(period + "-01")
    except ValueError:
        raise bad_request("period must be YYYY-MM")
    with get_db().tx() as c:
        if c.one("SELECT id FROM payroll_runs WHERE hotel_id = ? AND period = ?", [hid, period]):
            raise conflict(f"A payroll run for {period} already exists")
        rid = c.insert("payroll_runs", {"hotel_id": hid, "period": period, "status": "draft", "rules": json.dumps(rules_for(c, hid)),
                                        "created_by": ctx.user_id, "created_at": now_iso()})
        _compute_run(c, c.one("SELECT * FROM payroll_runs WHERE id = ?", [rid]))
        audit(c, ctx, "payroll.run_prepared", "payroll_run", rid, period, hotel_id=hid)
        return {**c.one("SELECT * FROM payroll_runs WHERE id = ?", [rid]), "_created": True}


@route("GET", "/api/payroll/runs/{run_id:int}", perm="payroll.view", tag="payroll", summary="Payroll run with payslips, adjustments and statutory totals")
def get_run(ctx: Ctx):
    with get_db().tx() as c:
        r = _run(c, ctx, ctx.path["run_id"])
        slips = c.all("SELECT p.*, e.employee_no, e.first_name || ' ' || e.last_name AS employee, e.department, e.bank_name, e.bank_account_number FROM payslips p "
                      "JOIN employees e ON e.id = p.employee_id WHERE p.run_id = ? ORDER BY e.department, e.last_name", [r["id"]])
        adjustments = c.all("SELECT a.*, e.first_name || ' ' || e.last_name AS employee FROM payroll_adjustments a JOIN employees e ON e.id = a.employee_id "
                            "WHERE a.run_id = ? ORDER BY a.id", [r["id"]])
        remitted = {je["source_ref"].split("-")[-1] for je in c.all("SELECT source_ref FROM journal_entries WHERE source = 'payroll' AND source_ref LIKE ?",
                                                                     [f"REMIT-{r['id']}-%"])}
    keys = ("gross", "pension_employee", "nhf", "paye", "loan_deduction", "other_deduction", "net", "pension_employer", "employer_other")
    totals = {k: sum(s[k] for s in slips) for k in keys}
    if not ctx.can("payroll.pay"):
        for s in slips:
            s["bank_account_number"] = None if not s["bank_account_number"] else "•" * 6 + s["bank_account_number"][-4:]
    warnings = [f"{s['employee']}: net pay is negative" for s in slips if s["net"] < 0] + \
               [f"{s['employee']}: fixed pay below the configured minimum wage" for s in slips if json.loads(s["details"] or "{}").get("below_minimum_wage")]
    with get_db().tx() as c:
        names = {u["id"]: u["full_name"] for u in c.all("SELECT id, full_name FROM users WHERE id IN (?, ?)", [r["created_by"], r["approved_by"] or 0])}
    return {**r, "created_by_name": names.get(r["created_by"]), "approved_by_name": names.get(r["approved_by"]), "rules": json.loads(r["rules"]), "payslips": slips, "adjustments": adjustments, "totals": totals, "warnings": warnings,
            "remittances": {"paye": totals["paye"], "pension": totals["pension_employee"] + totals["pension_employer"], "nhf": totals["nhf"],
                            "statutory": totals["employer_other"] + totals["other_deduction"]}, "remitted": sorted(remitted)}


@route("POST", "/api/payroll/runs/{run_id:int}/adjustments", perm="payroll.run", tag="payroll",
       summary="Add a bonus or one-off deduction to a draft run (recalculates)")
def add_adjustment(ctx: Ctx):
    kind = ctx.field("kind", kind=str)
    if kind not in ("bonus", "deduction"):
        raise bad_request("kind must be bonus or deduction")
    amount = to_minor(ctx.field("amount"))
    if amount <= 0:
        raise bad_request("Amount must be greater than zero")
    with get_db().tx() as c:
        r = _run(c, ctx, ctx.path["run_id"], lock=True)
        if r["status"] != "draft":
            raise conflict("Only draft runs can be adjusted")
        e = c.one("SELECT id FROM employees WHERE id = ? AND hotel_id = ?", [ctx.field("employee_id", kind=int), r["hotel_id"]])
        if not e:
            raise bad_request("Employee not found")
        c.insert("payroll_adjustments", {"run_id": r["id"], "employee_id": e["id"], "kind": kind, "amount": amount, "note": ctx.field("note", kind=str)[:200],
                                         "created_by": ctx.user_id, "created_at": now_iso()})
        _compute_run(c, r)
        audit(c, ctx, f"payroll.{kind}", "payroll_run", r["id"], r["period"], new={"employee_id": e["id"], "amount": amount}, hotel_id=r["hotel_id"])
    return {"ok": True}


@route("POST", "/api/payroll/runs/{run_id:int}/recalculate", perm="payroll.run", tag="payroll", summary="Recalculate a draft run (after attendance or salary changes)")
def recalculate(ctx: Ctx):
    with get_db().tx() as c:
        r = _run(c, ctx, ctx.path["run_id"], lock=True)
        if r["status"] != "draft":
            raise conflict("Only draft runs can be recalculated")
        c.update("payroll_runs", r["id"], {"rules": json.dumps(rules_for(c, r["hotel_id"]))})
        _compute_run(c, c.one("SELECT * FROM payroll_runs WHERE id = ?", [r["id"]]))
    return {"ok": True}


@route("POST", "/api/payroll/runs/{run_id:int}/approve", perm="payroll.approve", tag="payroll",
       summary="Approve a draft run (not by its preparer): posts the payroll journal and applies loan repayments")
def approve_run(ctx: Ctx):
    with get_db().tx() as c:
        r = _run(c, ctx, ctx.path["run_id"], lock=True)
        if r["status"] != "draft":
            raise conflict(f"This run is already {r['status']}")
        if r["created_by"] == ctx.user_id:
            raise forbidden("The person who prepared the payroll cannot approve it")
        slips = c.all("SELECT * FROM payslips WHERE run_id = ?", [r["id"]])
        if not slips:
            raise conflict("This run has no payslips")
        if any(s["net"] < 0 for s in slips):
            raise conflict("Some payslips have negative net pay; adjust them first")
        hotel = get_hotel(c, r["hotel_id"])
        org = hotel["organisation_id"]
        t = {k: sum(s[k] for s in slips) for k in ("gross", "pension_employee", "nhf", "paye", "loan_deduction", "other_deduction", "net", "pension_employer", "employer_other")}
        y, m = int(r["period"][:4]), int(r["period"][5:])
        entry_date = min(dt.date(y, m, calendar.monthrange(y, m)[1]), business_date(hotel))
        je = post_journal(c, r["hotel_id"], entry_date, f"Payroll {r['period']}", "payroll", f"PAYROLL-{r['period']}", [
            (account_id(c, org, "exp_salaries"), t["gross"], 0, None, "Gross pay"),
            (account_id(c, org, "exp_payroll_statutory"), t["pension_employer"] + t["employer_other"], 0, None, "Employer pension, NSITF, ITF"),
            (account_id(c, org, "salaries_payable"), 0, t["net"], None, "Net pay due"),
            (account_id(c, org, "paye_payable"), 0, t["paye"], None, "PAYE"),
            (account_id(c, org, "pension_payable"), 0, t["pension_employee"] + t["pension_employer"], None, "Pension"),
            (account_id(c, org, "nhf_payable"), 0, t["nhf"], None, "NHF"),
            (account_id(c, org, "statutory_payable"), 0, t["employer_other"] + t["other_deduction"], None, "NSITF, ITF and other deductions"),
            (account_id(c, org, "staff_loans"), 0, t["loan_deduction"], None, "Loan repayments")], ctx.user_id)
        for s in slips:
            remaining = s["loan_deduction"]
            for loan in c.all("SELECT * FROM employee_loans WHERE employee_id = ? AND status = 'active' ORDER BY id", [s["employee_id"]]):
                if remaining <= 0:
                    break
                take = min(remaining, loan["balance"], loan["monthly_deduction"])
                bal = loan["balance"] - take
                c.update("employee_loans", loan["id"], {"balance": bal, "status": "repaid" if bal == 0 else "active"})
                remaining -= take
        c.update("payroll_runs", r["id"], {"status": "approved", "approved_by": ctx.user_id, "approved_at": now_iso(), "journal_entry_id": je})
        for s in slips:
            uid = c.scalar("SELECT user_id FROM employees WHERE id = ?", [s["employee_id"]])
            if uid:
                from ..services import queue_notification
                queue_notification(c, r["hotel_id"], "in_app", str(uid), "Payslip available", f"Your payslip for {r['period']} is ready (net {s['net'] / 100:,.2f}).",
                                   "payslip", s["id"])
        audit(c, ctx, "payroll.approved", "payroll_run", r["id"], r["period"], new={"journal": je, **t}, hotel_id=r["hotel_id"])
    return {"status": "approved", "journal_entry_id": je}


@route("POST", "/api/payroll/runs/{run_id:int}/pay", perm="payroll.pay", tag="payroll", summary="Record payment of net salaries from a bank account")
def pay_run(ctx: Ctx):
    with get_db().tx() as c:
        r = _run(c, ctx, ctx.path["run_id"], lock=True)
        if r["status"] != "approved":
            raise conflict("Only approved runs can be paid")
        m = c.one("SELECT * FROM payment_methods WHERE id = ? AND hotel_id = ? AND active = 1", [ctx.field("method_id", kind=int), r["hotel_id"]])
        if not m or m["kind"] not in ("bank_transfer", "cash"):
            raise bad_request("Pay salaries by bank transfer or cash")
        ref = ctx.field("reference", required=m["kind"] == "bank_transfer", kind=str)
        hotel = get_hotel(c, r["hotel_id"])
        je = post_journal(c, r["hotel_id"], business_date(hotel), f"Salary payment {r['period']}", "payroll", f"PAY-{r['period']}", [
            (account_id(c, hotel["organisation_id"], "salaries_payable"), r["net"], 0, None, "Net salaries"),
            (m["account_id"], 0, r["net"], None, f"{m['name']} {ref or ''}".strip())], ctx.user_id)
        c.update("payroll_runs", r["id"], {"status": "paid", "paid_by": ctx.user_id, "paid_at": now_iso(), "payment_journal_id": je})
        audit(c, ctx, "payroll.paid", "payroll_run", r["id"], r["period"], new={"journal": je, "reference": ref}, hotel_id=r["hotel_id"])
    return {"status": "paid", "journal_entry_id": je}


REMIT_KEYS = {"paye": "paye_payable", "pension": "pension_payable", "nhf": "nhf_payable", "statutory": "statutory_payable"}


@route("POST", "/api/payroll/runs/{run_id:int}/remit", perm="payroll.pay", tag="payroll",
       summary="Record remittance of PAYE, pension, NHF or other statutory amounts for an approved run")
def remit(ctx: Ctx):
    what = ctx.field("liability", kind=str)
    if what not in REMIT_KEYS:
        raise bad_request("liability must be paye, pension, nhf or statutory")
    with get_db().tx() as c:
        r = _run(c, ctx, ctx.path["run_id"], lock=True)
        if r["status"] not in ("approved", "paid"):
            raise conflict("Approve the run first")
        ref_key = f"REMIT-{r['id']}-{what}"
        if c.one("SELECT id FROM journal_entries WHERE source = 'payroll' AND source_ref = ?", [ref_key]):
            raise conflict(f"{what.upper()} for {r['period']} has already been remitted")
        s = c.one("SELECT COALESCE(SUM(paye),0) AS paye, COALESCE(SUM(pension_employee + pension_employer),0) AS pension, COALESCE(SUM(nhf),0) AS nhf, "
                  "COALESCE(SUM(employer_other + other_deduction),0) AS statutory FROM payslips WHERE run_id = ?", [r["id"]])
        amount = s[what]
        if amount <= 0:
            raise bad_request("Nothing to remit")
        m = c.one("SELECT * FROM payment_methods WHERE id = ? AND hotel_id = ? AND active = 1", [ctx.field("method_id", kind=int), r["hotel_id"]])
        if not m or m["kind"] not in ("bank_transfer", "cash"):
            raise bad_request("Remit by bank transfer or cash")
        hotel = get_hotel(c, r["hotel_id"])
        je = post_journal(c, r["hotel_id"], business_date(hotel), f"{what.upper()} remittance {r['period']}", "payroll", ref_key, [
            (account_id(c, hotel["organisation_id"], REMIT_KEYS[what]), amount, 0, None, f"{what.upper()} {r['period']}"),
            (m["account_id"], 0, amount, None, ctx.field("reference", required=False, kind=str) or m["name"])], ctx.user_id)
        audit(c, ctx, f"payroll.remit_{what}", "payroll_run", r["id"], r["period"], new={"amount": amount, "journal": je}, hotel_id=r["hotel_id"])
    return {"amount": amount, "journal_entry_id": je}


@route("GET", "/api/payroll/runs/{run_id:int}/bank-schedule.csv", perm="payroll.pay", tag="payroll", summary="Bank payment schedule (CSV) for a run")
def bank_schedule(ctx: Ctx):
    with get_db().tx() as c:
        r = _run(c, ctx, ctx.path["run_id"])
        if r["status"] == "draft":
            raise conflict("Approve the run before exporting the bank schedule")
        rows = c.all("SELECT e.employee_no, e.first_name || ' ' || e.last_name AS name, e.bank_name, e.bank_account_number, p.net FROM payslips p "
                     "JOIN employees e ON e.id = p.employee_id WHERE p.run_id = ? ORDER BY e.last_name", [r["id"]])
        audit(c, ctx, "payroll.bank_schedule_exported", "payroll_run", r["id"], r["period"], hotel_id=r["hotel_id"])
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Employee no", "Name", "Bank", "Account number", "Amount (NGN)", "Narration"])
    for x in rows:
        w.writerow([x["employee_no"], x["name"], x["bank_name"] or "", x["bank_account_number"] or "", f"{x['net'] / 100:.2f}", f"Salary {r['period']}"])
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="bank-schedule-{r["period"]}.csv"'})


def _payslip_pdf(c, slip_id: int) -> tuple[bytes, str]:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    p = c.one("SELECT p.*, r.period, r.hotel_id, r.status, e.employee_no, e.first_name, e.last_name, e.department, e.position, e.bank_name, e.bank_account_number, "
              "e.pension_pfa, e.tax_id FROM payslips p JOIN payroll_runs r ON r.id = p.run_id JOIN employees e ON e.id = p.employee_id WHERE p.id = ?", [slip_id])
    hotel = get_hotel(c, p["hotel_id"])
    f = lambda v: f"{v / 100:,.2f}"  # noqa: E731
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, title=f"Payslip {p['period']}")
    ss = getSampleStyleSheet()
    acct = p["bank_account_number"] or ""
    story = [Paragraph(f"<b>{hotel['name']}</b>", ss["Title"]), Paragraph(f"PAYSLIP — {p['period']}" + (" (DRAFT)" if p["status"] == "draft" else ""), ss["Heading2"]),
             Paragraph(f"{p['first_name']} {p['last_name']} · {p['employee_no']} · {p['position']} ({p['department']})<br/>"
                       f"Bank: {p['bank_name'] or '—'} {'•••' + acct[-4:] if acct else ''} · TIN: {p['tax_id'] or '—'} · PFA: {p['pension_pfa'] or '—'}", ss["Normal"]),
             Spacer(1, 8)]
    earn = [["Earnings", ""], ["Basic", f(p["basic"])], ["Housing", f(p["housing"])], ["Transport", f(p["transport"])], ["Other allowances", f(p["other_allowance"])],
            ["Overtime", f(p["overtime"])], ["Bonus", f(p["bonus"])], [f"Absence / unpaid days ({p['days_absent']})", "-" + f(p["absence_deduction"])], ["Gross pay", f(p["gross"])]]
    ded = [["Deductions", ""], ["PAYE", f(p["paye"])], ["Pension (employee)", f(p["pension_employee"])], ["NHF", f(p["nhf"])], ["Loan repayment", f(p["loan_deduction"])],
           ["Other deductions", f(p["other_deduction"])], ["NET PAY", f(p["net"])], ["Employer pension (not deducted)", f(p["pension_employer"])]]
    for rows in (earn, ded):
        t = Table(rows, colWidths=[110 * mm, 50 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f1f3d")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
                               ("FONTNAME", (0, -2 if rows is ded else -1), (-1, -2 if rows is ded else -1), "Helvetica-Bold")]))
        story += [t, Spacer(1, 8)]
    story.append(Paragraph("Computed from the hotel's configured statutory rules for this period.", ss["Italic"]))
    doc.build(story)
    return buf.getvalue(), f"payslip-{p['employee_no']}-{p['period']}.pdf"


@route("GET", "/api/payslips/{slip_id:int}.pdf", tag="payroll", summary="Payslip PDF (payroll staff, or the employee for their own approved payslip)")
def payslip_pdf(ctx: Ctx):
    with get_db().tx() as c:
        p = c.one("SELECT p.id, r.hotel_id, r.status, e.user_id FROM payslips p JOIN payroll_runs r ON r.id = p.run_id JOIN employees e ON e.id = p.employee_id "
                  "WHERE p.id = ?", [ctx.path["slip_id"]])
        if not p:
            raise not_found("Payslip")
        own = p["user_id"] == ctx.user_id and p["status"] in ("approved", "paid")
        if not own:
            ctx.require("payroll.view")
            ctx.check_hotel(p["hotel_id"])
        data, name = _payslip_pdf(c, p["id"])
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


# ------------------------------------------------------------------ staff loans and advances
@route("POST", "/api/employees/{employee_id:int}/loans", perm="payroll.pay", tag="payroll",
       summary="Grant a staff loan or salary advance (paid out now, recovered monthly through payroll)")
def grant_loan(ctx: Ctx):
    principal = to_minor(ctx.field("principal"))
    monthly = to_minor(ctx.field("monthly_deduction"))
    if principal <= 0 or monthly <= 0 or monthly > principal:
        raise bad_request("Enter a principal and a monthly deduction no larger than the principal")
    with get_db().tx() as c:
        e = c.one("SELECT * FROM employees WHERE id = ?", [ctx.path["employee_id"]])
        if not e:
            raise not_found("Employee")
        ctx.check_hotel(e["hotel_id"])
        if e["status"] != "active":
            raise conflict("Loans can only be granted to active employees")
        m = c.one("SELECT * FROM payment_methods WHERE id = ? AND hotel_id = ? AND active = 1", [ctx.field("method_id", kind=int), e["hotel_id"]])
        if not m or m["kind"] not in ("bank_transfer", "cash"):
            raise bad_request("Pay the loan by bank transfer or cash")
        hotel = get_hotel(c, e["hotel_id"])
        desc = ctx.field("description", kind=str)
        je = post_journal(c, e["hotel_id"], business_date(hotel), f"Staff loan {e['employee_no']}: {desc}", "payroll", e["employee_no"], [
            (account_id(c, hotel["organisation_id"], "staff_loans"), principal, 0, None, desc), (m["account_id"], 0, principal, None, m["name"])], ctx.user_id)
        lid = c.insert("employee_loans", {"employee_id": e["id"], "description": desc[:200], "principal": principal, "monthly_deduction": monthly, "balance": principal,
                                          "status": "active", "journal_entry_id": je, "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "payroll.loan_granted", "employee_loan", lid, e["employee_no"], new={"principal": principal, "monthly": monthly}, hotel_id=e["hotel_id"])
    return {"id": lid, "_created": True}
