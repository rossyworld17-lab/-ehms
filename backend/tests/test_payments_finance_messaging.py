"""Release 0.5: online payment gateways (Paystack, Flutterwave), payment links, booking-engine prepayment,
promo codes, expense claims, bank reconciliation, budgets, cash flow, period close, messaging and worker."""
import datetime as dt
import hashlib
import hmac
import json
import uuid

import pytest

from ehms import gateways
from ehms.db import get_db

from test_frontoffice_finance import arrival_today, ctx_ids
from test_pos_inventory_procurement import assert_books_balance, gl_balance


class FakeGateway:
    """Stands in for the provider HTTP APIs. `paid` maps reference -> amount actually paid (minor units)."""

    def __init__(self):
        self.paid: dict[str, int] = {}
        self.calls: list[str] = []
        self.down = False

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append(f"{method} {url}")
        if self.down:
            raise OSError("connection refused")
        payload = json.loads(body) if body else {}
        if url.endswith("/transaction/initialize"):
            return 200, json.dumps({"status": True, "data": {"authorization_url": f"https://checkout.paystack.test/{payload['reference']}"}}).encode()
        if "/transaction/verify/" in url:
            ref = url.rsplit("/", 1)[1]
            amt = self.paid.get(ref)
            return 200, json.dumps({"status": True, "data": {"status": "success" if amt else "abandoned", "amount": amt or 0, "currency": "NGN"}}).encode()
        if url.endswith("/v3/payments"):
            return 200, json.dumps({"status": "success", "data": {"link": f"https://checkout.flutterwave.test/{payload['tx_ref']}"}}).encode()
        if "verify_by_reference" in url:
            ref = url.split("tx_ref=")[1]
            amt = self.paid.get(ref)
            return 200, json.dumps({"status": "success", "data": {"status": "successful" if amt else "pending", "amount": (amt or 0) / 100,
                                                                  "currency": "NGN"}}).encode()
        if "termii" in url or "graph.facebook.com" in url:
            return 200, b'{"message": "Successfully Sent"}'
        return 404, b"{}"


@pytest.fixture()
def gw(monkeypatch):
    fake = FakeGateway()
    monkeypatch.setattr(gateways, "transport", fake)
    monkeypatch.setattr(gateways.time, "sleep", lambda s: None)
    monkeypatch.setenv("PAYSTACK_SECRET_KEY", "sk_test_secret")
    return fake


def paystack_sig(raw: bytes) -> str:
    return hmac.new(b"sk_test_secret", raw, hashlib.sha512).hexdigest()


def post_raw(client, path, payload: dict, headers: dict):
    raw = json.dumps(payload).encode()
    return client.request("POST", path, json_body=payload, headers={k: (v(raw) if callable(v) else v) for k, v in headers.items()}, token=None)


def checked_in_folio(client):
    client.login("frontdesk@demo.ehms")
    h, methods = ctx_ids()
    res, _ = arrival_today(client, h)
    ci = client.post(f"/api/reservations/{res['id']}/check-in", {})
    return h, methods, res, ci.json()["folio"]["id"]


# ------------------------------------------------------------------ gateways
def test_payment_link_and_paystack_webhook(client, gw):
    h, _, res, folio_id = checked_in_folio(client)
    link = client.post(f"/api/folios/{folio_id}/payment-link", {"amount": 5000000})
    assert link.status_code == 201, link.text
    ref = link.json()["reference"]
    assert link.json()["authorization_url"].endswith(ref)
    # the guest got the link by email (stored as not_configured: no SMTP in tests — never reported as sent)
    with get_db().tx() as c:
        n = c.one("SELECT * FROM notifications WHERE related_entity = 'folio' AND related_id = ? ORDER BY id DESC", [str(folio_id)])
    assert ref in n["body"] and n["status"] == "not_configured"
    body = {"event": "charge.success", "data": {"reference": ref}}
    # a forged webhook is rejected
    assert post_raw(client, "/api/public/webhooks/paystack", body, {"x-paystack-signature": "bad"}).status_code == 401
    # a validly signed webhook for an unpaid transaction does not credit anything (verify says abandoned)
    r = post_raw(client, "/api/public/webhooks/paystack", body, {"x-paystack-signature": paystack_sig})
    assert r.status_code == 200 and r.json()["status"] == "failed"
    # the guest pays: webhook + return page both arrive; the folio is credited exactly once
    gw.paid[ref] = 5000000
    r = post_raw(client, "/api/public/webhooks/paystack", body, {"x-paystack-signature": paystack_sig})
    assert r.json()["status"] == "success"
    again = client.get(f"/api/public/payments/{ref}", token=None).json()
    assert again["status"] == "success" and again["already_recorded"]
    folio = client.get(f"/api/folios/{folio_id}").json()
    online = [l for l in folio["lines"] if l["reference"] == ref]
    assert len(online) == 1 and online[0]["total_amount"] == 5000000
    assert gl_balance("online_clearing", h["id"]) == 5000000
    with get_db().tx() as c:
        assert c.scalar("SELECT COUNT(*) FROM integration_logs WHERE integration = 'paystack' AND direction = 'inbound'") >= 3
    assert_books_balance(h["id"])


def test_amount_mismatch_is_not_credited(client, gw):
    h, _, res, folio_id = checked_in_folio(client)
    ref = client.post(f"/api/folios/{folio_id}/payment-link", {"amount": 2000000, "send": False}).json()["reference"]
    gw.paid[ref] = 100  # tampered amount
    assert client.get(f"/api/public/payments/{ref}", token=None).json()["status"] == "amount_mismatch"
    assert not [l for l in client.get(f"/api/folios/{folio_id}").json()["lines"] if l["reference"] == ref]


def test_gateway_unreachable_is_reported_and_retried(client, gw):
    h, _, res, folio_id = checked_in_folio(client)
    gw.down = True
    r = client.post(f"/api/folios/{folio_id}/payment-link", {"amount": 1000})
    assert r.status_code == 502 and r.json()["error"]["code"] == "gateway_unreachable"
    assert len([x for x in gw.calls if x.endswith("/initialize")]) == 3   # retried


def test_no_gateway_configured(client, monkeypatch):
    monkeypatch.delenv("PAYSTACK_SECRET_KEY", raising=False)
    monkeypatch.delenv("FLUTTERWAVE_SECRET_KEY", raising=False)
    h, _, res, folio_id = checked_in_folio(client)
    assert client.post(f"/api/folios/{folio_id}/payment-link", {"amount": 1000}).status_code == 501


def test_booking_engine_prepay_with_promo_code_flutterwave(client, gw, monkeypatch):
    monkeypatch.delenv("PAYSTACK_SECRET_KEY")
    monkeypatch.setenv("FLUTTERWAVE_SECRET_KEY", "FLWSECK_TEST")
    monkeypatch.setenv("FLUTTERWAVE_WEBHOOK_HASH", "my-hash")
    h, _ = ctx_ids()
    client.login("gm@demo.ehms")
    bd = dt.date.fromisoformat(h["business_date"])
    a, d = (bd + dt.timedelta(days=10)).isoformat(), (bd + dt.timedelta(days=12)).isoformat()
    assert client.post(f"/api/hotels/{h['id']}/promo-codes", {"code": "bad", "discount_type": "percent", "value": 150, "valid_from": a, "valid_to": d}).status_code == 400
    p = client.post(f"/api/hotels/{h['id']}/promo-codes", {"code": "Easter 20", "discount_type": "percent", "value": 20, "valid_from": bd.isoformat(),
                                                           "valid_to": (bd + dt.timedelta(days=60)).isoformat(), "min_nights": 2, "max_uses": 1})
    assert p.status_code == 201
    av = client.get("/api/public/hotels/CGL/availability", params={"arrival": a, "departure": d, "adults": 2, "promo_code": "easter20"}, token=None).json()
    opt = av["options"][0]
    assert opt["promo_error"] is None and opt["price"]["discount"] == opt["price"]["room_total"] * 20 // 100
    bad = client.get("/api/public/hotels/CGL/availability", params={"arrival": a, "departure": d, "promo_code": "NOPE"}, token=None).json()
    assert bad["options"][0]["promo_error"]
    body = {"arrival": a, "departure": d, "room_type_id": opt["room_type_id"], "first_name": "Ada", "last_name": "Online", "email": "ada.online@example.com",
            "phone": "+2348000000001", "adults": 2, "accept_terms": True, "payment_option": "pay_online", "promo_code": "EASTER20"}
    r = client.post("/api/public/hotels/CGL/bookings", body, token=None)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["payment"] == "pay_online" and out["total"] == opt["price"]["total"] and "flutterwave" in out["authorization_url"]
    # promo has max_uses 1: a second booking with it is refused
    assert client.post("/api/public/hotels/CGL/bookings", {**body, "email": "x@example.com"}, token=None).status_code == 400
    ref = out["payment_reference"]
    gw.paid[ref] = out["total"]
    hook = post_raw(client, "/api/public/webhooks/flutterwave", {"event": "charge.completed", "data": {"tx_ref": ref}}, {"verif-hash": "my-hash"})
    assert hook.json()["status"] == "success"
    assert post_raw(client, "/api/public/webhooks/flutterwave", {"data": {"tx_ref": ref}}, {"verif-hash": "wrong"}).status_code == 401
    page = client.get(f"/api/public/payments/{ref}", token=None).json()
    assert page["booking"]["status"] == "confirmed" and page["booking"]["reference"] == out["reference"]
    with get_db().tx() as c:
        r = c.one("SELECT * FROM reservations WHERE reference = ?", [out["reference"]])
        assert r["promo_code"] == "EASTER20" and r["discount_amount"] > 0
    assert_books_balance(h["id"])


# ------------------------------------------------------------------ finance operations
def test_expense_claim_maker_checker(client):
    h, methods = ctx_ids()
    client.login("hkmanager@demo.ehms")
    with get_db().tx() as c:
        acct = c.scalar("SELECT id FROM accounts WHERE system_key = 'exp_supplies'")
    r = client.post(f"/api/hotels/{h['id']}/expenses", {"department": "housekeeping", "account_id": acct, "amount": 1250000,
                                                        "description": "Emergency curtain cleaning", "payee": "QuickClean", "receipt_ref": "RC-1"})
    assert r.status_code == 201
    eid = r.json()["id"]
    assert client.post(f"/api/expenses/{eid}/decide", {"decision": "approve"}).status_code == 403   # no approve permission
    client.login("accounts@demo.ehms")
    assert client.post(f"/api/expenses/{eid}/pay", {"method_id": methods["CASH"]}).status_code == 409   # not approved
    client.login("finance@demo.ehms")
    assert client.post(f"/api/expenses/{eid}/decide", {"decision": "approve"}).json()["status"] == "approved"
    before = gl_balance("exp_supplies", h["id"])
    client.login("accounts@demo.ehms")
    assert client.post(f"/api/expenses/{eid}/pay", {"method_id": methods["TRANSFER"]}).status_code == 400   # transfer needs a reference
    assert client.post(f"/api/expenses/{eid}/pay", {"method_id": methods["TRANSFER"], "reference": "NIP-1"}).json()["status"] == "paid"
    assert gl_balance("exp_supplies", h["id"]) - before == 1250000
    # finance self-approval is blocked
    client.login("finance@demo.ehms")
    own = client.post(f"/api/hotels/{h['id']}/expenses", {"department": "admin", "account_id": acct, "amount": 100, "description": "x"}).json()
    assert client.post(f"/api/expenses/{own['id']}/decide", {"decision": "approve"}).status_code == 403
    assert_books_balance(h["id"])


def test_bank_reconciliation_auto_match(client):
    h, methods, res, folio_id = checked_in_folio(client)
    ref = uuid.uuid4().hex[:8]
    client.post(f"/api/folios/{folio_id}/payments", {"amount": 3000000, "method_id": methods["TRANSFER"], "reference": ref, "idempotency_key": uuid.uuid4().hex})
    client.login("accounts@demo.ehms")
    ws = client.get(f"/api/hotels/{h['id']}/bank-reconciliation").json()
    bank = next(a for a in ws["accounts"] if a["system_key"] == "bank")
    imp = client.post(f"/api/hotels/{h['id']}/bank-reconciliation/import", {"account_id": bank["id"], "lines": [
        {"date": h["business_date"], "description": f"NIP transfer {ref}", "amount": 3000000},
        {"date": h["business_date"], "description": "Bank charges", "amount": -5000}]})
    assert imp.json()["imported"] == 2
    assert client.post(f"/api/hotels/{h['id']}/bank-reconciliation/auto-match", {"account_id": bank["id"]}).json()["matched"] >= 1
    ws = client.get(f"/api/hotels/{h['id']}/bank-reconciliation", params={"account_id": bank["id"]}).json()
    charges = next(s for s in ws["statement_lines"] if s["amount"] == -5000)
    assert charges["status"] == "unmatched"
    assert ws["summary"]["difference"] == 0    # book − outstanding book items == statement − unmatched statement items
    # receptionist cannot reconcile
    client.login("frontdesk@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/bank-reconciliation").status_code == 403


def test_budget_cash_flow_and_period_close(client):
    h, methods = ctx_ids()
    client.login("finance@demo.ehms")
    bd = dt.date.fromisoformat(h["business_date"])
    with get_db().tx() as c:
        rev = c.scalar("SELECT id FROM accounts WHERE system_key = 'rev_room'")
        cash = c.scalar("SELECT id FROM accounts WHERE system_key = 'cash'")
        equity = c.scalar("SELECT id FROM accounts WHERE system_key = 'equity'")
    assert client.put(f"/api/hotels/{h['id']}/budgets", {"year": bd.year, "lines": [{"account_id": rev, "months": [100000000] * 12}]}).status_code == 200
    bva = client.get(f"/api/hotels/{h['id']}/budgets", params={"year": bd.year, "month": bd.month}).json()
    row = next(r for r in bva["items"] if r["id"] == rev)
    assert row["budget"] == 100000000 and row["variance"] == row["actual"] - 100000000
    # owner injects cash (financing) — cash flow reconciles opening + net change = closing
    client.post(f"/api/hotels/{h['id']}/journal", {"description": "Owner capital", "lines": [{"account_id": cash, "debit": 7000000}, {"account_id": equity, "credit": 7000000}]})
    cf = client.get(f"/api/hotels/{h['id']}/cash-flow", params={"from": bd.replace(day=1).isoformat(), "to": bd.isoformat()}).json()
    assert next(l for l in cf["lines"] if l["category"] == "Financing")["amount"] >= 7000000
    with get_db().tx() as c:
        closing = c.scalar("SELECT COALESCE(SUM(jl.debit - jl.credit),0) FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id JOIN accounts a ON a.id = jl.account_id "
                           "WHERE je.hotel_id = ? AND je.entry_date <= ? AND a.system_key IN ('cash','bank','card_clearing','online_clearing')", [h["id"], bd.isoformat()])
    assert cf["closing_cash"] == closing
    # period close: last month closes; postings dated in it are refused; reopen needs a reason
    prev = (bd.replace(day=1) - dt.timedelta(days=1))
    period = prev.strftime("%Y-%m")
    assert client.post(f"/api/hotels/{h['id']}/accounting/periods/{bd.strftime('%Y-%m')}/close", {}).status_code == 400
    assert client.post(f"/api/hotels/{h['id']}/accounting/periods/{period}/close", {}).json()["status"] == "closed"
    late = client.post(f"/api/hotels/{h['id']}/journal", {"description": "Late accrual", "entry_date": prev.isoformat(),
                                                         "lines": [{"account_id": cash, "debit": 100}, {"account_id": equity, "credit": 100}]})
    assert late.status_code == 409 and late.json()["error"]["code"] == "period_closed"
    assert client.post(f"/api/hotels/{h['id']}/accounting/periods/{period}/reopen", {}).status_code == 400
    assert client.post(f"/api/hotels/{h['id']}/accounting/periods/{period}/reopen", {"reason": "Audit adjustment"}).json()["status"] == "open"
    assert client.post(f"/api/hotels/{h['id']}/journal", {"description": "Late accrual", "entry_date": prev.isoformat(),
                                                         "lines": [{"account_id": cash, "debit": 100}, {"account_id": equity, "credit": 100}]}).status_code == 201
    periods = client.get(f"/api/hotels/{h['id']}/accounting/periods").json()
    assert periods["current"] == bd.strftime("%Y-%m")


# ------------------------------------------------------------------ messaging & worker
def test_templates_in_app_notifications_and_worker(client, gw, monkeypatch):
    h, _ = ctx_ids()
    bd = dt.date.fromisoformat(h["business_date"])
    with get_db().tx() as c:
        r = c.one("SELECT * FROM reservations WHERE hotel_id = ? AND status = 'confirmed' AND arrival > ? ORDER BY arrival LIMIT 1", [h["id"], bd.isoformat()])
        c.execute("UPDATE reservations SET arrival = ?, departure = ? WHERE id = ?", [(bd + dt.timedelta(days=1)).isoformat(), (bd + dt.timedelta(days=3)).isoformat(), r["id"]])
    client.login("admin@demo.ehms")
    t = client.get(f"/api/hotels/{h['id']}/notification-templates").json()["items"]
    assert any(x["code"] == "checkin_reminder" and x["channel"] == "sms" for x in t)
    assert client.put(f"/api/hotels/{h['id']}/notification-templates", {"code": "checkin_reminder", "channel": "email", "subject": "Tomorrow at {hotel}",
                                                                        "body": "Hi {guest}, ref {reference} {unknown_field}"}).status_code == 200
    monkeypatch.setenv("EHMS_TERMII_API_KEY", "termii-test")
    out = client.post(f"/api/hotels/{h['id']}/notifications/run-jobs", {}).json()
    assert out["jobs"]["checkin_reminders"] >= 1 and out["delivery"]["sent"] >= 1   # SMS delivered through the (fake) provider
    with get_db().tx() as c:
        msgs = c.all("SELECT * FROM notifications WHERE related_entity = 'reservation' AND related_id = ?", [str(r["id"])])
    email = next(m for m in msgs if m["channel"] == "email")
    sms = next(m for m in msgs if m["channel"] == "sms")
    assert email["subject"] == "Tomorrow at Crestview Grand Lagos (Demo)" and "{" not in email["body"] and email["status"] == "not_configured"
    assert sms["status"] == "sent"
    # idempotent: running again sends no second reminder
    assert client.post(f"/api/hotels/{h['id']}/notifications/run-jobs", {}).json()["jobs"]["checkin_reminders"] == 0
    # email cannot be retried until SMTP is configured
    assert client.post(f"/api/notifications/{email['id']}/retry", {}).status_code == 409
    log = client.get(f"/api/hotels/{h['id']}/notifications", params={"status": "sent"}).json()
    assert any(m["id"] == sms["id"] for m in log["items"])
    # low-stock digest reaches inventory managers in-app
    client.login("inventory@demo.ehms")
    with get_db().tx() as c:
        c.execute("UPDATE inventory_items SET reorder_level_milli = 999999999 WHERE code = 'RICE'")
        c.execute("DELETE FROM job_runs WHERE job = 'low_stock_digest'")
    from ehms.worker import run_jobs
    assert run_jobs()["low_stock_digests"] >= 1
    mine = client.get("/api/notifications/mine").json()
    assert mine["unread"] >= 1 and "Rice" in mine["items"][0]["body"]
    assert client.post(f"/api/notifications/{mine['items'][0]['id']}/read", {}).status_code == 200
    assert client.post("/api/notifications/read-all", {}).status_code == 200
    assert client.get("/api/notifications/mine").json()["unread"] == 0
    # someone else's notification cannot be marked
    client.login("frontdesk@demo.ehms")
    assert client.post(f"/api/notifications/{mine['items'][0]['id']}/read", {}).status_code == 404
