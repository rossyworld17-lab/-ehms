"""Petty cash (imprest system) and payment vouchers (release 1.2).

A fund has its own ledger account, a custodian, an imprest (float) and a per-voucher limit. Vouchers up to the limit
are posted at once (Dr expense / Cr petty cash); larger ones wait for approval by someone else. Top-ups restore the
float from cash or bank. Every petty cash voucher, expense-claim payment and supplier payment can be printed as a
payment voucher (PDF)."""
from __future__ import annotations

import io

from starlette.responses import Response

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import business_date, get_hotel, next_number, post_journal, to_minor

DEPARTMENTS = ("front_office", "housekeeping", "fnb", "kitchen", "maintenance", "security", "admin", "finance", "hr", "sales", "laundry", "events")


def fund_balance(c, fund_id: int) -> int:
    ups = c.scalar("SELECT COALESCE(SUM(amount),0) FROM petty_cash_entries WHERE fund_id = ? AND kind = 'top_up' AND status = 'posted'", [fund_id]) or 0
    out = c.scalar("SELECT COALESCE(SUM(amount),0) FROM petty_cash_entries WHERE fund_id = ? AND kind = 'voucher' AND status = 'posted'", [fund_id]) or 0
    return ups - out


def _pending(c, fund_id: int) -> int:
    return c.scalar("SELECT COALESCE(SUM(amount),0) FROM petty_cash_entries WHERE fund_id = ? AND kind = 'voucher' AND status = 'pending'", [fund_id]) or 0


def _fund(c, ctx: Ctx, fund_id) -> dict:
    f = c.one("SELECT * FROM petty_cash_funds WHERE id = ?", [int(fund_id)])
    if not f:
        raise not_found("Petty cash fund")
    ctx.check_hotel(f["hotel_id"])
    return f


def _source(c, hid: int, method_id) -> dict:
    m = c.one("SELECT * FROM payment_methods WHERE id = ? AND hotel_id = ? AND active = 1", [int(method_id), hid])
    if not m or m["kind"] not in ("cash", "bank_transfer"):
        raise bad_request("Fund petty cash from a cash or bank-transfer payment method")
    return m


def _post_top_up(c, ctx: Ctx, f: dict, amount: int, m: dict, note: str) -> int:
    hotel = get_hotel(c, f["hotel_id"])
    number = next_number(c, f["hotel_id"], "petty_cash", "PCV")
    je = post_journal(c, f["hotel_id"], business_date(hotel), f"Petty cash top-up {f['name']} ({number})", "petty_cash", number,
                      [(f["account_id"], amount, 0, "finance", note), (m["account_id"], 0, amount, "finance", m["name"])], ctx.user_id)
    return c.insert("petty_cash_entries", {"hotel_id": f["hotel_id"], "fund_id": f["id"], "number": number, "kind": "top_up", "description": note[:300],
                                           "source_account_id": m["account_id"], "amount": amount, "status": "posted", "requested_by": ctx.user_id,
                                           "decided_by": ctx.user_id, "journal_entry_id": je, "created_at": now_iso(), "decided_at": now_iso()})


def _post_voucher(c, ctx: Ctx, f: dict, v: dict) -> int:
    if v["amount"] > fund_balance(c, f["id"]):
        raise conflict("Not enough cash in the fund; top it up first")
    hotel = get_hotel(c, f["hotel_id"])
    je = post_journal(c, f["hotel_id"], business_date(hotel), f"Petty cash {v['number']}: {v['description']}", "petty_cash", v["number"],
                      [(v["expense_account_id"], v["amount"], 0, v["department"], f"{v['payee'] or ''} {v['description']}".strip()),
                       (f["account_id"], 0, v["amount"], v["department"], f"Petty cash {f['name']}")], ctx.user_id)
    return je


@route("GET", "/api/hotels/{hotel_id:int}/petty-cash", perm="finance.petty_cash", tag="finance",
       summary="Petty cash funds with balances, and recent vouchers and top-ups (?fund_id)")
def overview(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        funds = c.all("SELECT f.*, u.full_name AS custodian, a.code AS account_code FROM petty_cash_funds f JOIN users u ON u.id = f.custodian_id "
                      "JOIN accounts a ON a.id = f.account_id WHERE f.hotel_id = ? ORDER BY f.name", [hid])
        for f in funds:
            f["balance"] = fund_balance(c, f["id"])
            f["pending"] = _pending(c, f["id"])
            f["to_replenish"] = max(0, f["imprest"] - f["balance"])
        sql = ("SELECT e.*, f.name AS fund, a.name AS expense_account, u.full_name AS requested_by_name, d.full_name AS decided_by_name "
               "FROM petty_cash_entries e JOIN petty_cash_funds f ON f.id = e.fund_id LEFT JOIN accounts a ON a.id = e.expense_account_id "
               "JOIN users u ON u.id = e.requested_by LEFT JOIN users d ON d.id = e.decided_by WHERE e.hotel_id = ?")
        params: list = [hid]
        if ctx.q("fund_id"):
            sql += " AND e.fund_id = ?"
            params.append(int(ctx.q("fund_id")))
        entries = c.all(sql + " ORDER BY e.id DESC LIMIT 200", params)
        accounts = c.all("SELECT id, code, name FROM accounts WHERE organisation_id = ? AND type = 'expense' AND active = 1 AND is_postable = 1 ORDER BY code", [ctx.org_id])
        methods = c.all("SELECT id, name, kind FROM payment_methods WHERE hotel_id = ? AND active = 1 AND kind IN ('cash','bank_transfer')", [hid])
    return {"funds": funds, "entries": entries, "expense_accounts": accounts, "methods": methods, "departments": DEPARTMENTS}


@route("POST", "/api/hotels/{hotel_id:int}/petty-cash/funds", perm="finance.petty_cash.manage", tag="finance",
       summary="Open a petty cash fund: name, custodian_id, imprest, voucher_limit, source_method_id (the float is paid in from cash or bank)")
def create_fund(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    imprest = to_minor(ctx.field("imprest"), "imprest")
    limit = to_minor(ctx.field("voucher_limit"), "voucher_limit")
    if imprest <= 0 or limit <= 0 or limit > imprest:
        raise bad_request("The float must be positive and the voucher limit between 0 and the float")
    name = str(ctx.field("name", kind=str)).strip()[:100]
    with get_db().tx() as c:
        cust = c.one("SELECT u.id FROM users u LEFT JOIN user_hotels uh ON uh.user_id = u.id WHERE u.id = ? AND u.organisation_id = ? AND u.status = 'active' "
                     "AND (u.all_hotels = 1 OR uh.hotel_id = ?)", [ctx.field("custodian_id", kind=int), ctx.org_id, hid])
        if not cust:
            raise bad_request("The custodian must be an active user of this hotel")
        m = _source(c, hid, ctx.field("source_method_id"))
        used = {r["code"] for r in c.all("SELECT code FROM accounts WHERE organisation_id = ?", [ctx.org_id])}
        code = next((x for x in [*range(1001, 1010), *range(1020, 1100)] if str(x) not in used), None)
        if code is None:
            raise conflict("No free account code for a new petty cash account (1001–1099 are in use)")
        acc = c.insert("accounts", {"organisation_id": ctx.org_id, "code": str(code), "name": f"Petty Cash - {name}"[:150], "type": "asset",
                                    "is_postable": 1, "active": 1})
        fid = c.insert("petty_cash_funds", {"hotel_id": hid, "name": name, "account_id": acc, "custodian_id": cust["id"], "imprest": imprest,
                                            "voucher_limit": limit, "active": 1, "created_at": now_iso()})
        f = c.one("SELECT * FROM petty_cash_funds WHERE id = ?", [fid])
        _post_top_up(c, ctx, f, imprest, m, "Opening float")
        audit(c, ctx, "finance.petty_cash_fund", "petty_cash_fund", fid, name, new={"imprest": imprest, "limit": limit, "account": code}, hotel_id=hid)
    return {"id": fid, "account_code": str(code), "_created": True}


@route("POST", "/api/petty-cash/funds/{fund_id:int}/top-up", perm="finance.petty_cash.manage", tag="finance",
       summary="Replenish a fund: source_method_id, amount (default: back up to the float)")
def top_up(ctx: Ctx):
    with get_db().tx() as c:
        f = _fund(c, ctx, ctx.path["fund_id"])
        bal = fund_balance(c, f["id"])
        amount = to_minor(ctx.field("amount")) if ctx.field("amount", required=False) else f["imprest"] - bal
        if amount <= 0:
            raise bad_request("The fund is already at its float")
        if bal + amount > f["imprest"] * 2:
            raise bad_request("A top-up cannot take the fund above twice its float")
        m = _source(c, f["hotel_id"], ctx.field("source_method_id"))
        eid = _post_top_up(c, ctx, f, amount, m, ctx.field("note", required=False, kind=str) or "Replenishment")
        audit(c, ctx, "finance.petty_cash_top_up", "petty_cash_fund", f["id"], f["name"], new={"amount": amount}, hotel_id=f["hotel_id"])
    return {"id": eid, "amount": amount, "balance": bal + amount}


@route("POST", "/api/petty-cash/funds/{fund_id:int}/vouchers", perm="finance.petty_cash", tag="finance",
       summary="Pay out from petty cash: payee, description, expense_account_id, department, amount (over the fund's limit → needs approval)")
def create_voucher(ctx: Ctx):
    amount = to_minor(ctx.field("amount"))
    if amount <= 0:
        raise bad_request("Amount must be greater than zero")
    dept = ctx.field("department", kind=str)
    if dept not in DEPARTMENTS:
        raise bad_request(f"department must be one of {', '.join(DEPARTMENTS)}")
    with get_db().tx() as c:
        f = _fund(c, ctx, ctx.path["fund_id"])
        if not f["active"]:
            raise conflict("This fund is closed")
        if f["custodian_id"] != ctx.user_id and not ctx.can("finance.petty_cash.manage"):
            raise forbidden("Only the fund's custodian (or finance) can pay out from it")
        acc = c.one("SELECT * FROM accounts WHERE id = ? AND organisation_id = ? AND type = 'expense' AND active = 1", [ctx.field("expense_account_id", kind=int), ctx.org_id])
        if not acc:
            raise bad_request("Choose an expense account")
        if amount + _pending(c, f["id"]) > fund_balance(c, f["id"]):
            raise conflict("Not enough cash in the fund for this voucher; ask finance to top it up")
        number = next_number(c, f["hotel_id"], "petty_cash", "PCV")
        v = {"hotel_id": f["hotel_id"], "fund_id": f["id"], "number": number, "kind": "voucher", "payee": (ctx.field("payee", required=False, kind=str) or "")[:150] or None,
             "description": str(ctx.field("description", kind=str))[:300], "expense_account_id": acc["id"], "department": dept, "amount": amount,
             "status": "pending", "requested_by": ctx.user_id, "created_at": now_iso()}
        if amount <= f["voucher_limit"]:
            v.update({"status": "posted", "decided_by": ctx.user_id, "decided_at": now_iso()})
            v["journal_entry_id"] = _post_voucher(c, ctx, f, v)
        vid = c.insert("petty_cash_entries", v)
        if v["status"] == "pending":
            from .hrsuite import _notify_perm
            _notify_perm(c, f["hotel_id"], "finance.petty_cash.approve", f"Petty cash voucher {number} needs approval",
                         f"{v['description']} — {amount / 100:,.2f} (limit {f['voucher_limit'] / 100:,.2f})", "petty_cash_entry", vid)
        audit(c, ctx, "finance.petty_cash_voucher", "petty_cash_entry", vid, number, new={"amount": amount, "status": v["status"]}, hotel_id=f["hotel_id"])
    return {"id": vid, "number": number, "status": v["status"], "_created": True}


@route("POST", "/api/petty-cash/vouchers/{entry_id:int}/decide", perm="finance.petty_cash.approve", tag="finance",
       summary="Approve (posts) or reject a petty cash voucher above the limit: decision approve | reject, note")
def decide_voucher(ctx: Ctx):
    decision = ctx.field("decision", kind=str)
    if decision not in ("approve", "reject"):
        raise bad_request("decision must be approve or reject")
    note = ctx.field("note", required=decision == "reject", kind=str)
    with get_db().tx() as c:
        v = c.lock("petty_cash_entries", int(ctx.path["entry_id"]))
        if not v or v["kind"] != "voucher":
            raise not_found("Voucher")
        f = _fund(c, ctx, v["fund_id"])
        if v["status"] != "pending":
            raise conflict(f"This voucher is {v['status']}")
        if v["requested_by"] == ctx.user_id:
            raise forbidden("You cannot approve your own voucher")
        change = {"status": "posted" if decision == "approve" else "rejected", "decided_by": ctx.user_id, "decision_note": note, "decided_at": now_iso()}
        if decision == "approve":
            change["journal_entry_id"] = _post_voucher(c, ctx, f, v)
        c.update("petty_cash_entries", v["id"], change)
        audit(c, ctx, f"finance.petty_cash_{decision}", "petty_cash_entry", v["id"], v["number"], new=change, hotel_id=f["hotel_id"])
    return {"status": change["status"]}


# ------------------------------------------------------------------ payment vouchers (PDF)
def _voucher_data(c, ctx: Ctx, kind: str, vid: int) -> dict:
    if kind == "petty_cash":
        v = c.one("SELECT e.*, f.name AS fund, a.code AS acc_code, a.name AS acc_name FROM petty_cash_entries e JOIN petty_cash_funds f ON f.id = e.fund_id "
                  "LEFT JOIN accounts a ON a.id = e.expense_account_id WHERE e.id = ?", [vid])
        if not v or v["status"] != "posted":
            raise not_found("Posted petty cash entry")
        ctx.require("finance.petty_cash")
        return {"hotel_id": v["hotel_id"], "number": v["number"], "title": "PETTY CASH VOUCHER" if v["kind"] == "voucher" else "PETTY CASH TOP-UP",
                "payee": v["payee"] or ("Fund: " + v["fund"]), "description": v["description"], "amount": v["amount"],
                "account": f"{v['acc_code']} {v['acc_name']}" if v["acc_code"] else "", "method": f"Petty cash — {v['fund']}",
                "prepared_by": v["requested_by"], "approved_by": v["decided_by"], "date": str(v["decided_at"] or v["created_at"])[:10], "journal": v["journal_entry_id"]}
    if kind == "expense":
        v = c.one("SELECT e.*, a.code AS acc_code, a.name AS acc_name, m.name AS method FROM expense_claims e JOIN accounts a ON a.id = e.account_id "
                  "LEFT JOIN payment_methods m ON m.id = e.method_id WHERE e.id = ?", [vid])
        if not v or v["status"] != "paid":
            raise not_found("Paid expense claim")
        if not (ctx.can("finance.expenses.pay") or ctx.can("finance.expenses.approve") or ctx.can("accounting.view")):
            raise forbidden("Printing payment vouchers needs finance access")
        return {"hotel_id": v["hotel_id"], "number": v["number"], "title": "PAYMENT VOUCHER", "payee": v["payee"] or "", "description": v["description"],
                "amount": v["amount"], "account": f"{v['acc_code']} {v['acc_name']}", "method": f"{v['method'] or ''} {v['payment_reference'] or ''}".strip(),
                "prepared_by": v["requested_by"], "approved_by": v["approved_by"], "paid_by": v["paid_by"], "date": str(v["paid_at"])[:10], "journal": v["journal_entry_id"]}
    if kind == "supplier_payment":
        v = c.one("SELECT p.*, s.name AS supplier, i.invoice_no, i.number AS inv_number, m.name AS method FROM supplier_payments p JOIN suppliers s ON s.id = p.supplier_id "
                  "JOIN supplier_invoices i ON i.id = p.invoice_id JOIN payment_methods m ON m.id = p.method_id WHERE p.id = ?", [vid])
        if not v:
            raise not_found("Supplier payment")
        ctx.require("procurement.view")
        return {"hotel_id": v["hotel_id"], "number": v["number"], "title": "PAYMENT VOUCHER", "payee": v["supplier"],
                "description": f"Invoice {v['invoice_no']} ({v['inv_number']}) — gross {v['gross_amount'] / 100:,.2f}, WHT {v['wht_amount'] / 100:,.2f}",
                "amount": v["net_amount"], "account": "Accounts payable", "method": f"{v['method']} {v['reference'] or ''}".strip(),
                "prepared_by": v["paid_by"], "approved_by": None, "date": str(v["created_at"])[:10], "journal": v["journal_entry_id"]}
    raise bad_request("kind must be petty_cash, expense or supplier_payment")


@route("GET", "/api/vouchers/{kind}/{voucher_id:int}.pdf", tag="finance",
       summary="Payment voucher PDF for a petty cash entry, a paid expense claim or a supplier payment")
def voucher_pdf(ctx: Ctx):
    from reportlab.lib.pagesizes import A5, landscape
    from reportlab.pdfgen import canvas
    with get_db().tx() as c:
        d = _voucher_data(c, ctx, ctx.path["kind"], int(ctx.path["voucher_id"]))
        ctx.check_hotel(d["hotel_id"])
        hotel = get_hotel(c, d["hotel_id"])
        names = {u["id"]: u["full_name"] for u in c.all("SELECT id, full_name FROM users WHERE id IN (?, ?, ?)",
                                                         [d.get("prepared_by") or 0, d.get("approved_by") or 0, d.get("paid_by") or 0])}
        je = c.scalar("SELECT number FROM journal_entries WHERE id = ?", [d["journal"]]) if d.get("journal") else None
        audit(c, ctx, "finance.voucher_printed", ctx.path["kind"], int(ctx.path["voucher_id"]), d["number"], hotel_id=d["hotel_id"])
    buf = io.BytesIO()
    w, h = landscape(A5)
    cv = canvas.Canvas(buf, pagesize=(w, h))
    cv.setFont("Helvetica-Bold", 14)
    cv.drawString(36, h - 40, hotel["name"])
    cv.setFont("Helvetica-Bold", 12)
    cv.drawRightString(w - 36, h - 40, d["title"])
    cv.setFont("Helvetica", 10)
    cv.drawRightString(w - 36, h - 56, f"No. {d['number']}   Date {d['date']}")
    rows = [("Pay to", d["payee"]), ("Being", d["description"][:95]), ("Amount", f"{hotel['currency']} {d['amount'] / 100:,.2f}"),
            ("Account", d["account"]), ("Paid by", d["method"]), ("Journal", je or "")]
    y = h - 95
    for k, v in rows:
        cv.setFont("Helvetica-Bold", 10)
        cv.drawString(36, y, k)
        cv.setFont("Helvetica", 10)
        cv.drawString(120, y, str(v))
        cv.line(120, y - 3, w - 36, y - 3)
        y -= 26
    y -= 30
    for i, (label, uid) in enumerate([("Prepared by", d.get("prepared_by")), ("Approved by", d.get("approved_by")), ("Received by (signature)", None)]):
        x = 36 + i * ((w - 72) / 3)
        cv.line(x, y, x + (w - 72) / 3 - 20, y)
        cv.setFont("Helvetica", 8.5)
        cv.drawString(x, y - 12, f"{label}: {names.get(uid, '') if uid else ''}")
    cv.showPage()
    cv.save()
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="voucher-{d["number"]}.pdf"'})
