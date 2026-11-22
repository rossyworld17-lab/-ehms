"""Release 0.9: document store (permissions, validation, integrity, versions, retention, legal hold, access history),
BI analytics with filters and period comparison, occupancy history, HR analytics, scheduled reports delivered through
the document store, explainable forecast, unusual-transaction flags with human review, recommendations that only
enter normal approval workflows, and the permission-aware assistant (rule-based and Claude engines)."""
import base64
import datetime as dt
import json
import os
import types

from ehms.db import get_db

from test_frontoffice_finance import arrival_today, ctx_ids

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def guest_id():
    with get_db().tx() as c:
        return c.scalar("SELECT MIN(id) FROM guests")


def test_documents_permissions_validation_integrity_and_history(client):
    h, _ = ctx_ids()
    gid = guest_id()
    client.login("frontdesk@demo.ehms")
    up = lambda **kw: client.post("/api/documents", {"entity_type": "guest", "entity_id": gid, "category": "identity", "filename": "passport.pdf",  # noqa: E731
                                                     "content_base64": b64(PDF), **kw})
    assert up(filename="tool.exe").status_code == 400                                   # file type whitelist
    assert up(content_base64=b64(PNG)).status_code == 400                               # content does not match .pdf
    assert up(content_base64="not base64!!").status_code == 400
    os.environ["EHMS_MAX_UPLOAD_MB"] = "0.00001"
    try:
        assert up().status_code == 413                                                  # size limit
    finally:
        os.environ.pop("EHMS_MAX_UPLOAD_MB")
    assert client.post("/api/documents", {"entity_type": "employee", "entity_id": 1, "filename": "x.pdf", "content_base64": b64(PDF)}).status_code == 403
    r = up(filename="../../etc/passport scan.pdf")
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["confidentiality"] == "confidential" and doc["visible_to_you"] is False      # ID scans: write-only for reception
    lst = client.get("/api/documents", params={"entity_type": "guest", "entity_id": gid}).json()
    assert lst["items"] == [] and lst["hidden_count"] == 1
    assert client.get(f"/api/documents/{doc['id']}/download").status_code == 403
    # the general manager (documents.confidential) can open it; the content is unchanged and the name sanitised
    client.login("gm@demo.ehms")
    d = client.get(f"/api/documents/{doc['id']}").json()
    assert d["filename"] == "passport scan.pdf" and d["retention_until"] > h["business_date"]
    dl = client.get(f"/api/documents/{doc['id']}/download")
    assert dl.status_code == 200 and dl.content == PDF and dl.headers["content-type"].startswith("application/pdf")
    # a new version supersedes the old one, which stays in the history
    v2 = client.post(f"/api/documents/{doc['id']}/replace", {"filename": "passport-renewed.pdf", "content_base64": b64(PDF + b"%v2")})
    assert v2.status_code == 201
    v2d = client.get(f"/api/documents/{v2.json()['id']}").json()
    assert v2d["version"] == 2 and v2d["previous_versions"][0]["status"] == "superseded"
    assert client.post(f"/api/documents/{doc['id']}/replace", {"filename": "x.pdf", "content_base64": b64(PDF)}).status_code == 409
    # lowering confidentiality needs documents.manage (GM has it), raising is always allowed
    assert client.patch(f"/api/documents/{v2.json()['id']}", {"confidentiality": "restricted"}).status_code == 200
    # retention: cannot delete before the retention date or while on legal hold
    did = v2.json()["id"]
    assert client.delete(f"/api/documents/{did}", json_body={"reason": "duplicate upload"}).status_code == 409
    with get_db().tx() as c:
        c.execute("UPDATE documents SET retention_until = '2000-01-01' WHERE id = ?", [did])
    assert client.post(f"/api/documents/{did}/legal-hold", {"hold": True, "reason": "Pending dispute"}).status_code == 200
    assert client.delete(f"/api/documents/{did}", json_body={"reason": "duplicate upload"}).status_code == 409
    assert client.post(f"/api/documents/{did}/legal-hold", {"hold": False, "reason": "Dispute settled"}).status_code == 200
    assert client.get(f"/api/hotels/{h['id']}/documents/retention-due").json()["items"][0]["id"] == did
    assert client.post(f"/api/documents/{did}/retention", {"retention_until": "1999-01-01", "reason": "x"}).status_code == 400  # only extend
    assert client.delete(f"/api/documents/{did}", json_body={"reason": "Retention period over"}).status_code == 200
    assert client.get(f"/api/documents/{did}").status_code == 404
    with get_db().tx() as c:
        gone = c.one("SELECT * FROM documents WHERE id = ?", [did])
        actions = [r["action"] for r in c.all("SELECT action FROM document_access_log WHERE document_id = ? ORDER BY id", [doc["id"]])]
    assert gone["status"] == "deleted" and not os.path.exists(os.path.join(os.environ["EHMS_DOCUMENT_DIR"], gone["storage_key"]))
    assert actions[:1] == ["upload"] and "denied" in actions and "download" in actions and "superseded" in actions
    # a tampered file is refused rather than served
    with get_db().tx() as c:
        key = c.scalar("SELECT storage_key FROM documents WHERE id = ?", [doc["id"]])
    with open(os.path.join(os.environ["EHMS_DOCUMENT_DIR"], key), "ab") as fh:
        fh.write(b"tampered")
    assert client.get(f"/api/documents/{doc['id']}/download").status_code == 409
    log = client.get(f"/api/hotels/{h['id']}/documents/access-log", params={"action": "integrity_failed"}).json()["items"]
    assert len(log) == 1


def test_employee_documents_need_hr_records(client):
    with get_db().tx() as c:
        emp = c.scalar("SELECT MIN(id) FROM employees")
    client.login("hrofficer@demo.ehms")
    r = client.post("/api/documents", {"entity_type": "employee", "entity_id": emp, "category": "contract", "filename": "contract.pdf", "content_base64": b64(PDF)})
    assert r.status_code == 201 and r.json()["confidentiality"] == "confidential"
    assert client.get(f"/api/documents/{r.json()['id']}").status_code == 403              # officer cannot read confidential HR files
    client.login("hrmanager@demo.ehms")
    assert client.get(f"/api/documents/{r.json()['id']}").status_code == 200
    client.login("sales@demo.ehms")                                                     # no hr.view at all
    assert client.get("/api/documents", params={"entity_type": "employee", "entity_id": emp}).status_code == 403


def test_bi_analytics_filters_comparison_and_permissions(client):
    h, _ = ctx_ids()
    client.login("gm@demo.ehms")
    r = client.get("/api/bi/analytics", params={"granularity": "week", "compare": "previous_period"})
    assert r.status_code == 200, r.text
    a = r.json()
    k = a["current"]["kpis"]
    assert {"occupancy_pct", "adr", "revpar", "cancellation_rate_pct", "avg_length_of_stay"} <= set(k)
    fin = a["current"]["financial"]
    assert fin["gross_operating_profit"] == fin["revenue"] - fin["expenses"] and fin["source"].startswith("posted journal")
    assert "occupancy_pct" in a["comparison"]["change_pct"] and a["comparison"]["to"] < a["current"]["from"]
    assert all("-" in s["period"] for s in a["current"]["series"])
    # ledger revenue for the period equals the sum of revenue accounts in the general ledger
    with get_db().tx() as c:
        led = c.scalar("SELECT COALESCE(SUM(jl.credit - jl.debit),0) FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id JOIN accounts ac ON ac.id = jl.account_id "
                       "WHERE je.hotel_id = ? AND ac.type = 'revenue' AND je.entry_date >= ? AND je.entry_date <= ?", [h["id"], a["current"]["from"], a["current"]["to"]])
    assert fin["revenue"] == led
    yoy = client.get("/api/bi/analytics", params={"compare": "previous_year", "granularity": "month", "department": "room"}).json()
    assert yoy["comparison"]["from"][:4] == str(int(yoy["current"]["from"][:4]) - 1)
    assert client.get("/api/bi/analytics", params={"granularity": "hour"}).status_code == 400
    assert client.get("/api/bi/analytics", params={"hotel_ids": "999999"}).status_code in (403, 404)
    occ = client.get(f"/api/hotels/{h['id']}/bi/occupancy-history").json()
    assert occ["categories"] and len(occ["categories"][0]["sold"]) == len(occ["dates"]) and occ["rooms"]
    hr = client.get(f"/api/hotels/{h['id']}/bi/hr").json()
    assert hr["summary"]["headcount"] > 0 and hr["by_department"]
    # sales manager: operational analytics only, no financials, no HR analytics
    client.login("sales@demo.ehms")
    s = client.get("/api/bi/analytics").json()
    assert "financial" not in s["current"] and s["note"]
    assert client.get(f"/api/hotels/{h['id']}/bi/hr").status_code == 403
    client.login("waiter@demo.ehms")
    assert client.get("/api/bi/analytics").status_code == 403


def test_scheduled_reports_are_permission_checked_and_delivered_as_documents(client):
    h, _ = ctx_ids()
    with get_db().tx() as c:
        ids = {r["email"]: r["id"] for r in c.all("SELECT id, email FROM users")}
    client.login("finance@demo.ehms")
    base = {"report_code": "daily_revenue", "frequency": "daily", "format": "xlsx"}
    bad = client.post(f"/api/hotels/{h['id']}/report-schedules", {**base, "recipients": [ids["frontdesk@demo.ehms"]]})
    assert bad.status_code == 403                                                       # receptionist may not see financial reports
    assert client.post(f"/api/hotels/{h['id']}/report-schedules", {**base, "frequency": "weekly", "recipients": [ids["gm@demo.ehms"]]}).status_code == 400
    r = client.post(f"/api/hotels/{h['id']}/report-schedules", {**base, "name": "Revenue for GM", "recipients": [ids["gm@demo.ehms"], ids["finance@demo.ehms"]]})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    run = client.post(f"/api/report-schedules/{sid}/run")
    assert run.status_code == 200 and run.json()["sent"] == 2, run.text
    doc_id = run.json()["document_id"]
    client.login("gm@demo.ehms")
    mine = client.get("/api/notifications/mine").json()["items"]
    assert any("Revenue for GM" in n["subject"] for n in mine)
    dl = client.get(f"/api/documents/{doc_id}/download")
    assert dl.status_code == 200 and dl.content[:2] == b"PK"                             # xlsx
    client.login("sales@demo.ehms")                                                     # reports.view but not reports.financial
    assert client.get(f"/api/documents/{doc_id}").status_code == 403
    # worker: due once per day; a creator who loses access suspends the schedule
    from ehms.modules.bi import run_due_schedules
    with get_db().tx() as c:
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [h["id"]])
        c.execute("UPDATE report_schedules SET active = 0 WHERE id <> ?", [sid])
        assert run_due_schedules(c, hotel) == 1
        assert run_due_schedules(c, hotel) == 0
        c.execute("UPDATE report_schedules SET last_run_on = NULL WHERE id = ?", [sid])
        c.execute("DELETE FROM job_runs WHERE job = 'report_schedule'")
        c.execute("UPDATE users SET status = 'suspended' WHERE email = 'finance@demo.ehms'")
        run_due_schedules(c, hotel)
        s = c.one("SELECT * FROM report_schedules WHERE id = ?", [sid])
    assert s["active"] == 0 and s["last_status"] == "suspended"


def test_anomaly_flags_need_human_review(client):
    h, _ = ctx_ids()
    client.login("fom@demo.ehms")
    res, _ = arrival_today(client, h)
    folio = client.post(f"/api/reservations/{res['id']}/check-in", {}).json()["folio"]["id"]
    client.post(f"/api/folios/{folio}/charges", {"department": "fnb", "description": "Dinner", "amount": 1000000})
    assert client.post(f"/api/folios/{folio}/adjustments", {"amount": 3000000, "reason": "Goodwill"}).status_code == 201
    client.login("finance@demo.ehms")
    accts = {a["system_key"]: a["id"] for a in client.get("/api/accounts").json()["items"]}
    assert client.post(f"/api/hotels/{h['id']}/journal", {"description": "Cash moved to petty cash box", "lines": [
        {"account_id": accts["exp_fuel"], "debit": 4000000}, {"account_id": accts["cash"], "credit": 4000000}]}).status_code == 201
    scan = client.post(f"/api/hotels/{h['id']}/insights/anomalies/scan")
    assert scan.status_code == 200 and scan.json()["new_flags"] >= 2
    assert client.post(f"/api/hotels/{h['id']}/insights/anomalies/scan").json()["new_flags"] == 0        # no duplicates
    flags = client.get(f"/api/hotels/{h['id']}/insights/anomalies", params={"status": "open"}).json()["items"]
    rules = {f["rule"]: f for f in flags}
    assert {"folio_allowance", "manual_cash_journal"} <= set(rules)
    assert rules["folio_allowance"]["explanation"]
    own = rules["manual_cash_journal"]
    assert client.post(f"/api/anomalies/{own['id']}/review", {"status": "dismissed", "note": "fine"}).status_code == 409   # not about yourself
    client.login("accounts@demo.ehms")                                                  # may view, may not decide
    assert client.get(f"/api/hotels/{h['id']}/insights/anomalies").status_code == 200
    assert client.post(f"/api/anomalies/{own['id']}/review", {"status": "dismissed", "note": "fine"}).status_code == 403
    client.login("gm@demo.ehms")
    assert client.post(f"/api/anomalies/{own['id']}/review", {"status": "dismissed"}).status_code == 400                  # note required
    assert client.post(f"/api/anomalies/{own['id']}/review", {"status": "dismissed", "note": "Approved petty-cash top-up"}).status_code == 200
    assert client.post(f"/api/anomalies/{own['id']}/review", {"status": "confirmed", "note": "x"}).status_code == 409
    client.login("frontdesk@demo.ehms")
    assert client.get(f"/api/hotels/{h['id']}/insights/anomalies").status_code == 403


def test_forecast_and_recommendations_only_feed_approval_workflows(client):
    h, _ = ctx_ids()
    client.login("gm@demo.ehms")
    f = client.get(f"/api/hotels/{h['id']}/insights/forecast", params={"days": 14}).json()
    assert len(f["days"]) == 14 and f["method"] in ("pickup", "weekday_average") and f["explanation"] and f["limitations"]
    assert all(d["low"] <= d["expected_rooms"] + 0.0001 and d["on_books"] <= d["expected_rooms"] + 0.0001 for d in f["days"])
    client.login("sales@demo.ehms")
    fs = client.get(f"/api/hotels/{h['id']}/insights/forecast").json()
    assert "expected_room_revenue" not in fs["days"][0]                                 # revenue needs reports.financial
    rec = client.get(f"/api/hotels/{h['id']}/insights/recommendations").json()
    assert "rates" in rec and "reorder" not in rec and rec["denied"]
    p = client.post(f"/api/hotels/{h['id']}/insights/recommendations/propose-rule", {"name": "Uplift", "min_occupancy_pct": 80, "max_occupancy_pct": 100, "adjustment_bp": 1000})
    assert p.status_code == 201 and p.json()["status"] == "pending_approval"
    assert client.post(f"/api/revenue/rules/{p.json()["id"]}/decide", {"decision": "approve"}).status_code in (403, 409)
    # reorder: inventory items with usage below cover produce a requisition that still needs approval
    client.login("procurement@demo.ehms")
    with get_db().tx() as c:
        item = c.one("SELECT i.* FROM inventory_items i WHERE i.hotel_id = ? AND i.active = 1 ORDER BY i.id", [h["id"]])
        c.execute("UPDATE inventory_items SET reorder_level_milli = 999999999 WHERE id = ?", [item["id"]])
    rr = client.get(f"/api/hotels/{h['id']}/insights/recommendations").json()["reorder"]["items"]
    assert any(r["item_id"] == item["id"] for r in rr)
    req = client.post(f"/api/hotels/{h['id']}/insights/recommendations/requisition", {"item_ids": [item["id"]]})
    assert req.status_code == 201, req.text
    with get_db().tx() as c:
        assert c.scalar("SELECT status FROM purchase_requisitions WHERE id = ?", [req.json()["id"]]) == "submitted"


def test_assistant_rule_based_respects_permissions_and_refuses_actions(client):
    h, _ = ctx_ids()
    client.login("frontdesk@demo.ehms")
    assert client.post("/api/assistant/ask", {"question": "How full are we?", "hotel_id": h["id"]}).status_code == 403
    client.login("gm@demo.ehms")
    a = client.post("/api/assistant/ask", {"question": "How full are we tonight and what was revenue yesterday?", "hotel_id": h["id"]}).json()
    assert a["engine"] == "rules" and {"occupancy_today", "revenue_summary"} <= set(a["tools_used"])
    assert "occupied" in a["answer"] and "general ledger" in a["answer"]
    fc = client.post("/api/assistant/ask", {"question": "What is the forecast for the next 14 days?", "hotel_id": h["id"]}).json()
    assert fc["tools_used"] == ["occupancy_forecast"] and "Method" in fc["answer"]
    act = client.post("/api/assistant/ask", {"question": "Please approve the pending refund", "hotel_id": h["id"]}).json()
    assert "can't make changes" in act["answer"]
    fb = client.post("/api/assistant/ask", {"question": "What do guests say? any recurring issues?", "hotel_id": h["id"]}).json()
    assert "feedback_summary" in fb["tools_used"] and "NPS" in fb["answer"]
    # front office manager: has the assistant but not financial reports
    client.login("fom@demo.ehms")
    st = client.get("/api/assistant/status").json()
    assert "revenue_summary" not in [t["name"] for t in st["topics"]]
    r = client.post("/api/assistant/ask", {"question": "What was revenue this month?", "hotel_id": h["id"]}).json()
    assert r["denied"] and "reports.financial" in r["answer"] and "revenue_summary" not in r["tools_used"]
    with get_db().tx() as c:
        logged = c.all("SELECT * FROM ai_interactions ORDER BY id")
    assert len(logged) == 5 and logged[-1]["denied"]


def test_assistant_claude_engine_only_offers_permitted_tools(client, monkeypatch):
    from ehms.modules import assistant
    h, _ = ctx_ids()
    calls = []

    def blk(**kw):
        return types.SimpleNamespace(**kw)

    class FakeMessages:
        def create(self, **kw):
            calls.append(kw)
            if len(calls) == 1:   # the model tries a tool the user may not use, then one they may
                return blk(stop_reason="tool_use", content=[blk(type="tool_use", id="t1", name="revenue_summary", input={"period": "today"}),
                                                            blk(type="tool_use", id="t2", name="occupancy_today", input={})])
            return blk(stop_reason="end_turn", content=[blk(type="text", text="Occupancy is shown; revenue is not available to your role.")])

    fake = types.SimpleNamespace(beta=types.SimpleNamespace(messages=FakeMessages()))
    monkeypatch.setattr(assistant, "claude_enabled", lambda: True)
    monkeypatch.setattr(assistant, "_claude_client", lambda: fake)
    client.login("fom@demo.ehms")
    r = client.post("/api/assistant/ask", {"question": "How are we doing today?", "hotel_id": h["id"]}).json()
    assert r["engine"] == "claude" and "revenue is not available" in r["answer"]
    offered = [t["name"] for t in calls[0]["tools"]]
    assert "revenue_summary" not in offered and "occupancy_today" in offered
    assert calls[0]["model"] == "claude-opus-5-5" and "reports.financial" not in json.dumps(calls[0]["tools"])
    results = calls[1]["messages"][-1]["content"]
    assert results[0]["is_error"] is True and "permission denied" in results[0]["content"]
    assert "occupancy_pct" in results[1]["content"]
    # provider failure falls back to the built-in engine
    monkeypatch.setattr(assistant, "_claude_client", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    r2 = client.post("/api/assistant/ask", {"question": "How full are we tonight?", "hotel_id": h["id"]}).json()
    assert r2["engine"] == "rules" and "unavailable" in r2["answer"]
