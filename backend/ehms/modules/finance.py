"""Finance operations: expense claims with maker-checker, bank reconciliation, budgets and budget-vs-actual,
cash-flow statement and accounting period close. (FR-FIN-003/004/006/007, section 12)"""
from __future__ import annotations

import calendar
import datetime as dt

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import DEPARTMENT_EXPENSE_KEYS, business_date, get_hotel, next_number, parse_date, post_journal, to_minor

CASH_KEYS = ("cash", "bank", "card_clearing", "online_clearing")


# ------------------------------------------------------------------ expense claims
def _claim(c, ctx: Ctx, cid) -> dict:
    e = c.lock("expense_claims", int(cid))
    if not e:
        raise not_found("Expense claim")
    ctx.check_hotel(e["hotel_id"])
    return e


@route("GET", "/api/hotels/{hotel_id:int}/expenses", perm="finance.expenses.request", tag="finance",
       summary="Expense claims (?status); requesters see their own unless they approve or pay")
def list_expenses(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql = ("SELECT e.*, a.code AS account_code, a.name AS account_name, u.full_name AS requested_by_name, ap.full_name AS approved_by_name "
           "FROM expense_claims e JOIN accounts a ON a.id = e.account_id JOIN users u ON u.id = e.requested_by LEFT JOIN users ap ON ap.id = e.approved_by "
           "WHERE e.hotel_id = ?")
    params: list = [hid]
    if not (ctx.can("finance.expenses.approve") or ctx.can("finance.expenses.pay")):
        sql += " AND e.requested_by = ?"
        params.append(ctx.user_id)
    if ctx.q("status"):
        sql += " AND e.status = ?"
        params.append(ctx.q("status"))
    with get_db().tx() as c:
        accounts = c.all("SELECT id, code, name FROM accounts WHERE organisation_id = ? AND type = 'expense' AND active = 1 ORDER BY code", [ctx.org_id])
        return {"items": c.all(sql + " ORDER BY e.id DESC LIMIT 300", params), "accounts": accounts, "departments": list(DEPARTMENT_EXPENSE_KEYS)}


@route("POST", "/api/hotels/{hotel_id:int}/expenses", perm="finance.expenses.request", tag="finance",
       summary="Submit an expense claim (department, expense account, amount, description, receipt reference)")
def create_expense(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    amount = to_minor(ctx.field("amount"))
    if amount <= 0:
        raise bad_request("Amount must be greater than zero")
    dept = ctx.field("department", kind=str)
    if dept not in DEPARTMENT_EXPENSE_KEYS:
        raise bad_request(f"department must be one of {', '.join(DEPARTMENT_EXPENSE_KEYS)}")
    with get_db().tx() as c:
        acct = c.one("SELECT * FROM accounts WHERE id = ? AND organisation_id = ? AND type = 'expense' AND active = 1", [ctx.field("account_id", kind=int), ctx.org_id])
        if not acct:
            raise bad_request("Choose an expense account")
        number = next_number(c, hid, "expense", "EXP")
        d = ctx.field("expense_date", required=False)
        eid = c.insert("expense_claims", {"hotel_id": hid, "number": number, "department": dept, "account_id": acct["id"],
                                          "description": ctx.field("description", kind=str)[:300], "payee": ctx.field("payee", required=False, kind=str),
                                          "amount": amount, "receipt_ref": ctx.field("receipt_ref", required=False, kind=str), "status": "submitted",
                                          "requested_by": ctx.user_id,
                                          "expense_date": (parse_date(d, "expense_date") if d else business_date(get_hotel(c, hid))).isoformat(),
                                          "created_at": now_iso()})
        audit(c, ctx, "expense.submitted", "expense_claim", eid, number, new={"amount": amount, "account": acct["code"]}, hotel_id=hid)
    return {"id": eid, "number": number, "_created": True}


@route("POST", "/api/expenses/{claim_id:int}/decide", perm="finance.expenses.approve", tag="finance",
       summary="Approve or reject an expense claim (not your own)")
def decide_expense(ctx: Ctx):
    decision = ctx.field("decision", kind=str)
    if decision not in ("approve", "reject"):
        raise bad_request("decision must be approve or reject")
    with get_db().tx() as c:
        e = _claim(c, ctx, ctx.path["claim_id"])
        if e["status"] != "submitted":
            raise conflict(f"This claim is already {e['status']}")
        if e["requested_by"] == ctx.user_id:
            raise forbidden("You cannot approve your own expense claim")
        note = ctx.field("note", required=decision == "reject", kind=str)
        c.update("expense_claims", e["id"], {"status": "approved" if decision == "approve" else "rejected", "approved_by": ctx.user_id,
                                             "decision_note": note, "decided_at": now_iso()})
        audit(c, ctx, f"expense.{decision}d", "expense_claim", e["id"], e["number"], new={"note": note}, hotel_id=e["hotel_id"])
    return {"status": "approved" if decision == "approve" else "rejected"}


@route("POST", "/api/expenses/{claim_id:int}/pay", perm="finance.expenses.pay", tag="finance",
       summary="Pay an approved claim from cash or bank (posts Dr expense / Cr cash or bank)")
def pay_expense(ctx: Ctx):
    with get_db().tx() as c:
        e = _claim(c, ctx, ctx.path["claim_id"])
        if e["status"] != "approved":
            raise conflict("Only approved claims can be paid")
        m = c.one("SELECT * FROM payment_methods WHERE id = ? AND hotel_id = ? AND active = 1", [ctx.field("method_id", kind=int), e["hotel_id"]])
        if not m or m["kind"] not in ("cash", "bank_transfer"):
            raise bad_request("Pay expenses by cash or bank transfer")
        ref = ctx.field("reference", required=m["kind"] == "bank_transfer", kind=str)
        on = business_date(get_hotel(c, e["hotel_id"]))
        je = post_journal(c, e["hotel_id"], on, f"Expense {e['number']}: {e['description']}", "expense", e["number"], [
            (e["account_id"], e["amount"], 0, e["department"], e["description"]),
            (m["account_id"], 0, e["amount"], e["department"], f"{m['name']} {ref or ''}".strip())], ctx.user_id)
        c.update("expense_claims", e["id"], {"status": "paid", "paid_by": ctx.user_id, "method_id": m["id"], "payment_reference": ref,
                                             "journal_entry_id": je, "paid_at": now_iso()})
        audit(c, ctx, "expense.paid", "expense_claim", e["id"], e["number"], new={"journal": je, "method": m["code"]}, hotel_id=e["hotel_id"])
    return {"status": "paid", "journal_entry_id": je}


# ------------------------------------------------------------------ bank reconciliation
def _cash_accounts(c, org: int) -> list[dict]:
    return c.all(f"SELECT id, code, name, system_key FROM accounts WHERE organisation_id = ? AND system_key IN ({','.join('?' for _ in CASH_KEYS)}) "
                 "ORDER BY code", [org, *CASH_KEYS])


def _recon_account(c, ctx: Ctx, account_id) -> dict:
    a = c.one("SELECT * FROM accounts WHERE id = ? AND organisation_id = ?", [int(account_id), ctx.org_id])
    if not a or a["system_key"] not in CASH_KEYS:
        raise bad_request("Choose a cash, bank or clearing account")
    return a


@route("GET", "/api/hotels/{hotel_id:int}/bank-reconciliation", perm="accounting.reconcile", tag="finance",
       summary="Reconciliation workspace for an account (?account_id, ?as_at): statement lines, unreconciled book lines, balances")
def recon(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        accounts = _cash_accounts(c, ctx.org_id)
        if not ctx.q("account_id"):
            return {"accounts": accounts}
        a = _recon_account(c, ctx, ctx.q("account_id"))
        as_at = ctx.q("as_at", business_date(get_hotel(c, hid)).isoformat())
        stmt = c.all("SELECT * FROM bank_statement_lines WHERE hotel_id = ? AND account_id = ? AND txn_date <= ? ORDER BY txn_date, id", [hid, a["id"], as_at])
        book = c.all("SELECT jl.id, je.entry_date, je.number, je.description, jl.debit - jl.credit AS amount, jl.memo FROM journal_lines jl "
                     "JOIN journal_entries je ON je.id = jl.entry_id WHERE je.hotel_id = ? AND jl.account_id = ? AND je.entry_date <= ? "
                     "AND jl.id NOT IN (SELECT journal_line_id FROM bank_statement_lines WHERE journal_line_id IS NOT NULL) ORDER BY je.entry_date, jl.id",
                     [hid, a["id"], as_at])
        book_balance = c.scalar("SELECT COALESCE(SUM(jl.debit - jl.credit),0) FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id "
                                "WHERE je.hotel_id = ? AND jl.account_id = ? AND je.entry_date <= ?", [hid, a["id"], as_at])
    statement_balance = sum(s["amount"] for s in stmt if s["status"] != "ignored")
    unmatched_stmt = sum(s["amount"] for s in stmt if s["status"] == "unmatched")
    return {"accounts": accounts, "account": a, "as_at": as_at, "statement_lines": stmt, "unreconciled_book_lines": book,
            "book_balance": book_balance, "statement_balance": statement_balance,
            "summary": {"book_balance": book_balance, "outstanding_book_items": sum(b["amount"] for b in book),
                        "unmatched_statement_items": unmatched_stmt,
                        "difference": book_balance - sum(b["amount"] for b in book) - (statement_balance - unmatched_stmt)}}


@route("POST", "/api/hotels/{hotel_id:int}/bank-reconciliation/import", perm="accounting.reconcile", tag="finance",
       summary="Import bank statement lines: account_id, lines[{date, description, reference, amount}] (+ money in, − money out)")
def import_statement(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    lines = ctx.field("lines")
    if not isinstance(lines, list) or not lines:
        raise bad_request("No statement lines to import")
    if len(lines) > 2000:
        raise bad_request("Import at most 2,000 lines at a time")
    with get_db().tx() as c:
        a = _recon_account(c, ctx, ctx.field("account_id", kind=int))
        n = 0
        for i, ln in enumerate(lines, 1):
            try:
                d = parse_date(ln.get("date"), f"line {i} date")
                amt = to_minor(ln.get("amount"), f"line {i} amount")
            except Exception:
                raise bad_request(f"Line {i}: needs a YYYY-MM-DD date and an amount in kobo")
            if amt == 0:
                continue
            c.insert("bank_statement_lines", {"hotel_id": hid, "account_id": a["id"], "txn_date": d.isoformat(), "description": (ln.get("description") or "")[:300],
                                              "reference": (ln.get("reference") or "")[:100] or None, "amount": amt, "status": "unmatched",
                                              "imported_by": ctx.user_id, "created_at": now_iso()})
            n += 1
        audit(c, ctx, "bank.statement_imported", "account", a["id"], a["code"], new={"lines": n}, hotel_id=hid)
    return {"imported": n, "_created": True}


@route("POST", "/api/hotels/{hotel_id:int}/bank-reconciliation/auto-match", perm="accounting.reconcile", tag="finance",
       summary="Match statement lines to book lines with the same amount within ±5 days (one-to-one)")
def auto_match(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        a = _recon_account(c, ctx, ctx.field("account_id", kind=int))
        matched = 0
        used: set[int] = {r["journal_line_id"] for r in c.all("SELECT journal_line_id FROM bank_statement_lines WHERE journal_line_id IS NOT NULL")}
        book = c.all("SELECT jl.id, je.entry_date, jl.debit - jl.credit AS amount FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id "
                     "WHERE je.hotel_id = ? AND jl.account_id = ? ORDER BY je.entry_date, jl.id", [hid, a["id"]])
        for s in c.all("SELECT * FROM bank_statement_lines WHERE hotel_id = ? AND account_id = ? AND status = 'unmatched' ORDER BY txn_date, id", [hid, a["id"]]):
            sd = dt.date.fromisoformat(s["txn_date"])
            cands = [b for b in book if b["id"] not in used and b["amount"] == s["amount"] and abs((dt.date.fromisoformat(b["entry_date"]) - sd).days) <= 5]
            if cands:
                best = min(cands, key=lambda b: abs((dt.date.fromisoformat(b["entry_date"]) - sd).days))
                c.update("bank_statement_lines", s["id"], {"status": "matched", "journal_line_id": best["id"]})
                used.add(best["id"])
                matched += 1
        audit(c, ctx, "bank.auto_match", "account", a["id"], a["code"], new={"matched": matched}, hotel_id=hid)
    return {"matched": matched}


@route("POST", "/api/bank-statement-lines/{line_id:int}/match", perm="accounting.reconcile", tag="finance",
       summary="Manually match (journal_line_id), unmatch (null) or ignore (ignore=true) a statement line")
def manual_match(ctx: Ctx):
    with get_db().tx() as c:
        s = c.one("SELECT * FROM bank_statement_lines WHERE id = ?", [ctx.path["line_id"]])
        if not s:
            raise not_found("Statement line")
        ctx.check_hotel(s["hotel_id"])
        if ctx.field("ignore", required=False, default=False):
            c.update("bank_statement_lines", s["id"], {"status": "ignored", "journal_line_id": None})
            return {"status": "ignored"}
        jl_id = ctx.field("journal_line_id", required=False)
        if not jl_id:
            c.update("bank_statement_lines", s["id"], {"status": "unmatched", "journal_line_id": None})
            return {"status": "unmatched"}
        jl = c.one("SELECT jl.*, je.hotel_id FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id WHERE jl.id = ?", [int(jl_id)])
        if not jl or jl["hotel_id"] != s["hotel_id"] or jl["account_id"] != s["account_id"]:
            raise bad_request("That ledger line is not on this account")
        if jl["debit"] - jl["credit"] != s["amount"]:
            raise bad_request("Amounts differ; only equal amounts can be matched")
        if c.one("SELECT id FROM bank_statement_lines WHERE journal_line_id = ? AND id <> ?", [jl["id"], s["id"]]):
            raise conflict("That ledger line is already matched")
        c.update("bank_statement_lines", s["id"], {"status": "matched", "journal_line_id": jl["id"]})
        audit(c, ctx, "bank.manual_match", "bank_statement_line", s["id"], new={"journal_line_id": jl["id"]}, hotel_id=s["hotel_id"])
    return {"status": "matched"}


# ------------------------------------------------------------------ budgets
@route("GET", "/api/hotels/{hotel_id:int}/budgets", perm="accounting.view", tag="finance",
       summary="Budget vs actual for revenue and expense accounts (?year, ?month for one month else year to date)")
def budget_vs_actual(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        year = int(ctx.q("year", today.year))
        month = ctx.q("month")
        if month:
            m = int(month)
            frm, to = dt.date(year, m, 1), dt.date(year, m, calendar.monthrange(year, m)[1])
            periods = [f"{year}-{m:02d}"]
        else:
            frm, to = dt.date(year, 1, 1), min(dt.date(year, 12, 31), today if today.year == year else dt.date(year, 12, 31))
            periods = [f"{year}-{i:02d}" for i in range(1, to.month + 1)]
        accounts = c.all("SELECT id, code, name, type FROM accounts WHERE organisation_id = ? AND type IN ('revenue','expense') AND active = 1 ORDER BY code", [ctx.org_id])
        budgets = c.all(f"SELECT account_id, period, amount FROM budget_lines WHERE hotel_id = ? AND period LIKE ?", [hid, f"{year}-%"])
        actual = {r["account_id"]: r for r in c.all("SELECT jl.account_id, COALESCE(SUM(jl.debit),0) AS dr, COALESCE(SUM(jl.credit),0) AS cr FROM journal_lines jl "
                                                   "JOIN journal_entries je ON je.id = jl.entry_id WHERE je.hotel_id = ? AND je.entry_date >= ? AND je.entry_date <= ? "
                                                   "GROUP BY jl.account_id", [hid, frm.isoformat(), to.isoformat()])}
    plan: dict[int, dict[str, int]] = {}
    for b in budgets:
        plan.setdefault(b["account_id"], {})[b["period"]] = b["amount"]
    rows = []
    for a in accounts:
        act = actual.get(a["id"], {"dr": 0, "cr": 0})
        amount = (act["cr"] - act["dr"]) if a["type"] == "revenue" else (act["dr"] - act["cr"])
        bud = sum(plan.get(a["id"], {}).get(p, 0) for p in periods)
        if not amount and not bud:
            continue
        var = amount - bud
        rows.append({**a, "budget": bud, "actual": amount, "variance": var, "favourable": var >= 0 if a["type"] == "revenue" else var <= 0,
                     "months": [plan.get(a["id"], {}).get(f"{year}-{i:02d}", 0) for i in range(1, 13)]})
    return {"year": year, "month": month, "from": frm.isoformat(), "to": to.isoformat(), "items": rows,
            "all_accounts": accounts}


@route("PUT", "/api/hotels/{hotel_id:int}/budgets", perm="accounting.budgets", tag="finance",
       summary="Set a year's budget: year, lines[{account_id, months: [12 amounts in kobo]}]")
def set_budget(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    year = ctx.field("year", kind=int)
    with get_db().tx() as c:
        for ln in ctx.field("lines") or []:
            a = c.one("SELECT id FROM accounts WHERE id = ? AND organisation_id = ? AND type IN ('revenue','expense')", [int(ln.get("account_id") or 0), ctx.org_id])
            months = ln.get("months") or []
            if not a or len(months) != 12:
                raise bad_request("Each line needs a revenue or expense account and 12 monthly amounts")
            for i, amt in enumerate(months, 1):
                amt = to_minor(amt or 0, "months")
                period = f"{year}-{i:02d}"
                row = c.one("SELECT id FROM budget_lines WHERE hotel_id = ? AND account_id = ? AND period = ?", [hid, a["id"], period])
                if row:
                    c.update("budget_lines", row["id"], {"amount": amt})
                else:
                    c.insert("budget_lines", {"hotel_id": hid, "account_id": a["id"], "period": period, "amount": amt})
        audit(c, ctx, "budget.saved", "budget", year, str(year), new={"lines": len(ctx.field("lines") or [])}, hotel_id=hid)
    return {"ok": True}


# ------------------------------------------------------------------ cash-flow statement (direct method)
@route("GET", "/api/hotels/{hotel_id:int}/cash-flow", perm="reports.financial", tag="finance",
       summary="Cash-flow statement, direct method, for cash, bank and clearing accounts (?from, ?to)")
def cash_flow(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        frm = parse_date(ctx.q("from", today.replace(day=1).isoformat()), "from").isoformat()
        to = parse_date(ctx.q("to", today.isoformat()), "to").isoformat()
        cash_ids = {a["id"] for a in _cash_accounts(c, ctx.org_id)}
        ph = ",".join("?" for _ in cash_ids) or "0"
        opening = c.scalar(f"SELECT COALESCE(SUM(jl.debit - jl.credit),0) FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id "
                           f"WHERE je.hotel_id = ? AND je.entry_date < ? AND jl.account_id IN ({ph})", [hid, frm, *cash_ids])
        lines = c.all("SELECT jl.entry_id, jl.account_id, jl.debit, jl.credit, a.type, a.system_key FROM journal_lines jl "
                      "JOIN journal_entries je ON je.id = jl.entry_id JOIN accounts a ON a.id = jl.account_id "
                      "WHERE je.hotel_id = ? AND je.entry_date >= ? AND je.entry_date <= ?", [hid, frm, to])
    by_entry: dict[int, list] = {}
    for l in lines:
        by_entry.setdefault(l["entry_id"], []).append(l)
    cats = {"Receipts from guests and customers": 0, "Payments to suppliers": 0, "Payments for expenses and wages": 0, "Taxes paid": 0,
            "Other operating": 0, "Investing": 0, "Financing": 0}
    for entry in by_entry.values():
        cash = sum(l["debit"] - l["credit"] for l in entry if l["account_id"] in cash_ids)
        if not cash:
            continue
        other = [l for l in entry if l["account_id"] not in cash_ids]
        keys = {l["system_key"] for l in other}
        types = {l["type"] for l in other}
        if "equity" in types:
            cat = "Financing"
        elif keys & {"fixed_assets"}:
            cat = "Investing"
        elif keys & {"guest_ledger", "city_ledger", "advance_deposits"} or "revenue" in types:
            cat = "Receipts from guests and customers"
        elif "ap" in keys:
            cat = "Payments to suppliers"
        elif keys & {"vat_payable", "wht_payable", "paye_payable", "pension_payable"}:
            cat = "Taxes paid"
        elif "expense" in types or keys & {"salaries_payable"}:
            cat = "Payments for expenses and wages"
        else:
            cat = "Other operating"
        cats[cat] += cash
    operating = sum(v for k, v in cats.items() if k not in ("Investing", "Financing"))
    net = operating + cats["Investing"] + cats["Financing"]
    return {"from": frm, "to": to, "opening_cash": opening, "lines": [{"category": k, "amount": v} for k, v in cats.items()],
            "net_operating": operating, "net_change": net, "closing_cash": opening + net}


# ------------------------------------------------------------------ period close
@route("GET", "/api/hotels/{hotel_id:int}/accounting/periods", perm="accounting.view", tag="finance", summary="Accounting periods and their status")
def list_periods(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        rows = c.all("SELECT p.*, u.full_name AS closed_by_name FROM accounting_periods p LEFT JOIN users u ON u.id = p.closed_by WHERE p.hotel_id = ? "
                     "ORDER BY p.period DESC", [hid])
        first = c.scalar("SELECT MIN(entry_date) FROM journal_entries WHERE hotel_id = ?", [hid])
        today = business_date(get_hotel(c, hid))
    status = {r["period"]: r for r in rows}
    out = []
    y, m = (int(first[:4]), int(first[5:7])) if first else (today.year, today.month)
    while (y, m) <= (today.year, today.month):
        p = f"{y}-{m:02d}"
        out.append(status.get(p) or {"period": p, "status": "open"})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return {"items": list(reversed(out)), "current": f"{today.year}-{today.month:02d}"}


@route("POST", "/api/hotels/{hotel_id:int}/accounting/periods/{period}/close", perm="accounting.close_period", tag="finance",
       summary="Close a past accounting period (no further postings dated in it)")
def close_period(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    period = ctx.path["period"]
    try:
        dt.date.fromisoformat(period + "-01")
    except ValueError:
        raise bad_request("period must be YYYY-MM")
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        if period >= f"{today.year}-{today.month:02d}":
            raise bad_request("Only months before the current business month can be closed")
        row = c.one("SELECT * FROM accounting_periods WHERE hotel_id = ? AND period = ?", [hid, period])
        if row and row["status"] == "closed":
            raise conflict("This period is already closed")
        data = {"status": "closed", "closed_by": ctx.user_id, "closed_at": now_iso(), "note": ctx.field("note", required=False, kind=str)}
        if row:
            c.update("accounting_periods", row["id"], data)
        else:
            c.insert("accounting_periods", {"hotel_id": hid, "period": period, **data})
        audit(c, ctx, "period.closed", "accounting_period", period, period, hotel_id=hid)
    return {"period": period, "status": "closed"}


@route("POST", "/api/hotels/{hotel_id:int}/accounting/periods/{period}/reopen", perm="accounting.close_period", tag="finance",
       summary="Reopen a closed period (reason required; audited)")
def reopen_period(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        row = c.one("SELECT * FROM accounting_periods WHERE hotel_id = ? AND period = ? AND status = 'closed'", [hid, ctx.path["period"]])
        if not row:
            raise not_found("Closed period")
        c.update("accounting_periods", row["id"], {"status": "open", "note": f"Reopened: {reason}"[:300]})
        audit(c, ctx, "period.reopened", "accounting_period", row["period"], row["period"], new={"reason": reason}, hotel_id=hid)
    return {"period": row["period"], "status": "open"}
