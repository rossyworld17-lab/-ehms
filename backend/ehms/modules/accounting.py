"""General ledger: chart of accounts, journals, manual entries, reversals, trial balance,
profit & loss and balance sheet. (FR-FIN-001/002/007/008/009)"""
from __future__ import annotations

import datetime as dt

from ..db import get_db
from ..http import Ctx, audit, bad_request, conflict, not_found, route
from ..services import business_date, get_hotel, parse_date, post_journal, reverse_journal, to_minor


@route("GET", "/api/accounts", perm="accounting.view", tag="accounting", summary="Chart of accounts")
def list_accounts(ctx: Ctx):
    with get_db().tx() as c:
        return {"items": c.all("SELECT * FROM accounts WHERE organisation_id = ? ORDER BY code", [ctx.org_id])}


@route("POST", "/api/accounts", perm="accounting.manage_accounts", tag="accounting", summary="Add a ledger account")
def create_account(ctx: Ctx):
    typ = ctx.field("type", kind=str)
    if typ not in ("asset", "liability", "equity", "revenue", "expense"):
        raise bad_request("type must be asset, liability, equity, revenue or expense")
    code = ctx.field("code", kind=str)
    with get_db().tx() as c:
        if c.one("SELECT id FROM accounts WHERE organisation_id = ? AND code = ?", [ctx.org_id, code]):
            raise conflict("An account with this code already exists")
        aid = c.insert("accounts", {"organisation_id": ctx.org_id, "code": code, "name": ctx.field("name", kind=str), "type": typ,
                                    "parent_id": ctx.field("parent_id", required=False)})
        audit(c, ctx, "account.created", "account", aid, code, new=ctx.body)
    return {"id": aid, "_created": True}


@route("GET", "/api/hotels/{hotel_id:int}/journal", perm="accounting.view", tag="accounting", summary="Journal entries with lines")
def journal(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql, params = "SELECT je.*, u.full_name AS created_by_name FROM journal_entries je LEFT JOIN users u ON u.id = je.created_by WHERE je.hotel_id = ?", [hid]
    if ctx.q("from"):
        sql += " AND je.entry_date >= ?"
        params.append(ctx.q("from"))
    if ctx.q("to"):
        sql += " AND je.entry_date <= ?"
        params.append(ctx.q("to"))
    if ctx.q("source"):
        sql += " AND je.source = ?"
        params.append(ctx.q("source"))
    with get_db().tx() as c:
        entries = c.all(sql + " ORDER BY je.id DESC LIMIT 300", params)
        ids = [e["id"] for e in entries]
        lines = c.all(f"SELECT jl.*, a.code AS account_code, a.name AS account_name FROM journal_lines jl JOIN accounts a ON a.id = jl.account_id "
                      f"WHERE jl.entry_id IN ({','.join('?' for _ in ids)}) ORDER BY jl.id", ids) if ids else []
        reversed_ids = {e["reversal_of"] for e in c.all("SELECT reversal_of FROM journal_entries WHERE hotel_id = ? AND reversal_of IS NOT NULL", [hid])}
    by_entry: dict[int, list] = {}
    for l in lines:
        by_entry.setdefault(l["entry_id"], []).append(l)
    for e in entries:
        e["lines"] = by_entry.get(e["id"], [])
        e["total"] = sum(l["debit"] for l in e["lines"])
        e["reversed"] = e["id"] in reversed_ids
    return {"items": entries}


@route("POST", "/api/hotels/{hotel_id:int}/journal", perm="accounting.post_manual", tag="accounting",
       summary="Post a manual balanced journal entry (e.g. expenses, opening balances)")
def manual_journal(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    lines_in = ctx.field("lines")
    if not isinstance(lines_in, list) or len(lines_in) < 2:
        raise bad_request("At least two lines are required")
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        valid = {a["id"] for a in c.all("SELECT id FROM accounts WHERE organisation_id = ? AND active = 1 AND is_postable = 1", [ctx.org_id])}
        lines = []
        for i, l in enumerate(lines_in):
            acc = int(l.get("account_id") or 0)
            if acc not in valid:
                raise bad_request(f"Line {i + 1}: invalid account")
            dr, cr = to_minor(l.get("debit") or 0, "debit"), to_minor(l.get("credit") or 0, "credit")
            if dr < 0 or cr < 0 or (dr and cr) or not (dr or cr):
                raise bad_request(f"Line {i + 1}: enter either a debit or a credit")
            lines.append((acc, dr, cr, l.get("department"), l.get("memo")))
        entry_date = parse_date(ctx.field("entry_date", required=False) or business_date(hotel).isoformat(), "entry_date")
        jid = post_journal(c, hid, entry_date, ctx.field("description", kind=str), "manual", ctx.field("reference", required=False), lines, ctx.user_id)
        audit(c, ctx, "journal.manual_posted", "journal_entry", jid, new=ctx.body, hotel_id=hid)
    return {"id": jid, "_created": True}


@route("POST", "/api/journal/{entry_id:int}/reverse", perm="accounting.post_manual", tag="accounting", summary="Reverse a posted journal entry")
def reverse(ctx: Ctx):
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        je = c.one("SELECT * FROM journal_entries WHERE id = ?", [ctx.path["entry_id"]])
        if not je:
            raise not_found("Journal entry")
        ctx.check_hotel(je["hotel_id"])
        if je["source"] != "manual":
            raise conflict("Only manual entries can be reversed here; operational entries are reversed from their source (e.g. folio adjustment)")
        rid = reverse_journal(c, je["id"], business_date(get_hotel(c, je["hotel_id"])), reason, ctx.user_id)
        audit(c, ctx, "journal.reversed", "journal_entry", je["id"], je["number"], new={"reversal_id": rid, "reason": reason}, hotel_id=je["hotel_id"])
    return {"id": rid, "_created": True}


def _balances(c, hotel_ids: list[int], date_from: str | None, date_to: str) -> list[dict]:
    ph = ",".join("?" for _ in hotel_ids)
    params: list = list(hotel_ids) + [date_to]
    cond = "je.entry_date <= ?"
    if date_from:
        cond += " AND je.entry_date >= ?"
        params.append(date_from)
    return c.all(f"SELECT a.id, a.code, a.name, a.type, COALESCE(SUM(jl.debit),0) AS debit, COALESCE(SUM(jl.credit),0) AS credit "
                 f"FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id JOIN accounts a ON a.id = jl.account_id "
                 f"WHERE je.hotel_id IN ({ph}) AND {cond} GROUP BY a.id, a.code, a.name, a.type ORDER BY a.code", params)


def _scope(ctx: Ctx, c) -> list[int]:
    hid = ctx.q("hotel_id")
    if hid in (None, "", "all"):
        ids = [h["id"] for h in c.all("SELECT id FROM hotels WHERE organisation_id = ?", [ctx.org_id])]
        return [i for i in ids if ctx.hotel_ids is None or i in ctx.hotel_ids]
    return [ctx.check_hotel(hid)]


@route("GET", "/api/reports/trial-balance", perm="accounting.view", tag="accounting", summary="Trial balance as at a date (hotel or consolidated)")
def trial_balance(ctx: Ctx):
    as_at = parse_date(ctx.q("as_at", dt.date.today().isoformat()), "as_at").isoformat()
    with get_db().tx() as c:
        rows = _balances(c, _scope(ctx, c), None, as_at)
    for r in rows:
        net = r["debit"] - r["credit"]
        r["balance_debit"], r["balance_credit"] = (net, 0) if net >= 0 else (0, -net)
    td, tc = sum(r["balance_debit"] for r in rows), sum(r["balance_credit"] for r in rows)
    return {"as_at": as_at, "items": rows, "total_debit": td, "total_credit": tc, "balanced": td == tc}


@route("GET", "/api/reports/profit-and-loss", perm="reports.financial", tag="accounting", summary="Profit and loss for a period")
def profit_and_loss(ctx: Ctx):
    d_from = parse_date(ctx.q("from"), "from").isoformat()
    d_to = parse_date(ctx.q("to"), "to").isoformat()
    with get_db().tx() as c:
        rows = _balances(c, _scope(ctx, c), d_from, d_to)
    revenue = [{**r, "amount": r["credit"] - r["debit"]} for r in rows if r["type"] == "revenue"]
    expenses = [{**r, "amount": r["debit"] - r["credit"]} for r in rows if r["type"] == "expense"]
    tr, te = sum(r["amount"] for r in revenue), sum(r["amount"] for r in expenses)
    return {"from": d_from, "to": d_to, "revenue": revenue, "expenses": expenses, "total_revenue": tr, "total_expenses": te, "net_profit": tr - te}


@route("GET", "/api/reports/balance-sheet", perm="reports.financial", tag="accounting", summary="Balance sheet as at a date")
def balance_sheet(ctx: Ctx):
    as_at = parse_date(ctx.q("as_at", dt.date.today().isoformat()), "as_at").isoformat()
    with get_db().tx() as c:
        rows = _balances(c, _scope(ctx, c), None, as_at)
    assets = [{**r, "amount": r["debit"] - r["credit"]} for r in rows if r["type"] == "asset"]
    liabilities = [{**r, "amount": r["credit"] - r["debit"]} for r in rows if r["type"] == "liability"]
    equity = [{**r, "amount": r["credit"] - r["debit"]} for r in rows if r["type"] == "equity"]
    earnings = sum(r["credit"] - r["debit"] for r in rows if r["type"] == "revenue") - sum(r["debit"] - r["credit"] for r in rows if r["type"] == "expense")
    ta, tl, teq = sum(a["amount"] for a in assets), sum(l["amount"] for l in liabilities), sum(e["amount"] for e in equity) + earnings
    return {"as_at": as_at, "assets": assets, "liabilities": liabilities, "equity": equity, "current_earnings": earnings,
            "total_assets": ta, "total_liabilities": tl, "total_equity": teq, "balanced": ta == tl + teq}
