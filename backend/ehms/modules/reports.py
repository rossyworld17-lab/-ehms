"""Reports and documents: guest invoice/receipt PDF, operational reports with CSV / Excel / PDF export. (Section 10, 24)"""
from __future__ import annotations

import csv
import datetime as dt
import io

from starlette.responses import Response

from ..db import get_db
from ..http import Ctx, audit, bad_request, forbidden, not_found, route
from ..services import business_date, get_hotel, parse_date


def money(v: int, cur: str = "NGN") -> str:
    sign = "-" if v < 0 else ""
    return f"{sign}{cur} {abs(v) / 100:,.2f}"


# ------------------------------------------------------------------ invoice PDF
@route("GET", "/api/folios/{folio_id:int}/invoice.pdf", perm="folio.view", tag="reports", summary="Guest invoice / receipt as PDF")
def invoice_pdf(ctx: Ctx):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from .frontoffice import folio_balance
    with get_db().tx() as c:
        f = c.one("SELECT * FROM folios WHERE id = ?", [ctx.path["folio_id"]])
        if not f:
            raise not_found("Folio")
        ctx.check_hotel(f["hotel_id"])
        hotel = get_hotel(c, f["hotel_id"])
        g = c.one("SELECT * FROM guests WHERE id = ?", [f["guest_id"]])
        r = c.one("SELECT r.*, rm.number AS room_number FROM reservations r LEFT JOIN rooms rm ON rm.id = r.room_id WHERE r.id = ?", [f["reservation_id"]]) if f["reservation_id"] else None
        lines = c.all("SELECT * FROM folio_lines WHERE folio_id = ? ORDER BY id", [f["id"]])
        tot = folio_balance(c, f["id"])
        taxes = c.all("SELECT code, name, rate_bp FROM tax_rules WHERE hotel_id = ? AND active = 1", [hotel["id"]])
    cur = hotel["currency"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Invoice {f['number']}", author=hotel["name"])
    ss = getSampleStyleSheet()
    navy = colors.HexColor("#0f1f3d")
    gold = colors.HexColor("#c8a96a")
    story = [Paragraph(f"<font color='#0f1f3d' size=18><b>{hotel['name']}</b></font>", ss["Normal"]), Spacer(1, 3),
             Paragraph(" · ".join(x for x in [hotel.get("address"), hotel.get("city"), hotel.get("phone"), hotel.get("email")] if x) or "", ss["Normal"]),
             Spacer(1, 10)]
    title = "RECEIPT" if f["status"] == "closed" and tot["balance"] == 0 else "INVOICE"
    meta = [["Document", f"{title} {f['number']}", "Guest", f"{g['first_name']} {g['last_name']}"],
            ["Date", business_date(hotel).isoformat(), "Company", g.get("company") or "—"],
            ["Reservation", r["reference"] if r else "—", "Room", (r or {}).get("room_number") or "—"],
            ["Stay", f"{r['arrival']} to {r['departure']}" if r else "—", "Status", f["status"].upper()]]
    mt = Table(meta, colWidths=[25 * mm, 60 * mm, 25 * mm, 64 * mm])
    mt.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 9),
                            ("TEXTCOLOR", (0, 0), (0, -1), colors.grey), ("TEXTCOLOR", (2, 0), (2, -1), colors.grey)]))
    story += [mt, Spacer(1, 10)]
    rows = [["Date", "Description", "Net", "Svc chg", "Tax", "Amount"]]
    for l in lines:
        sign = -1 if l["kind"] == "payment" else 1
        is_pay = l["kind"] in ("payment",)
        rows.append([l["business_date"], Paragraph(l["description"], ss["BodyText"]), "" if is_pay else money(l["net_amount"], ""),
                     money(l["service_charge"], "") if l["service_charge"] else "", money(l["tax_amount"], "") if l["tax_amount"] else "",
                     money(sign * l["total_amount"], "")])
    t = Table(rows, colWidths=[22 * mm, 74 * mm, 22 * mm, 18 * mm, 18 * mm, 24 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), navy), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                           ("ALIGN", (2, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd"))]))
    story += [t, Spacer(1, 8)]
    summary = [["Total charges", money(tot["charges"] + tot["adjustments"], cur)], ["Payments received", money(tot["payments"], cur)]]
    if tot["refunds"]:
        summary.append(["Refunds", money(tot["refunds"], cur)])
    summary.append(["Balance due", money(tot["balance"], cur)])
    st = Table(summary, colWidths=[40 * mm, 38 * mm], hAlign="RIGHT")
    st.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                            ("LINEABOVE", (0, -1), (-1, -1), 1, gold), ("FONTSIZE", (0, 0), (-1, -1), 9.5)]))
    story += [st, Spacer(1, 14)]
    if taxes:
        story.append(Paragraph("Taxes applied: " + ", ".join(f"{t['name']} {t['rate_bp'] / 100:g}%" for t in taxes), ss["Italic"]))
    if hotel.get("terms"):
        story += [Spacer(1, 6), Paragraph(hotel["terms"], ss["BodyText"])]
    story += [Spacer(1, 10), Paragraph("Thank you for staying with us.", ss["Normal"])]
    doc.build(story)
    return Response(buf.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{f["number"]}.pdf"'})


# ------------------------------------------------------------------ tabular reports
def _report_rows(c, ctx: Ctx, hid: int, name: str) -> tuple[str, list[str], list[list]]:
    hotel = get_hotel(c, hid)
    bdate = business_date(hotel)
    cur = hotel["currency"]
    if name in ("arrivals", "departures", "in_house"):
        d = parse_date(ctx.q("date", bdate.isoformat()), "date").isoformat()
        cond = {"arrivals": "r.arrival = ? AND r.status IN ('confirmed','tentative','checked_in')",
                "departures": "r.departure = ? AND r.status IN ('checked_in','checked_out')",
                "in_house": "r.status = 'checked_in' AND r.arrival <= ?"}[name]
        rows = c.all("SELECT r.reference, g.first_name || ' ' || g.last_name AS guest, rm.number AS room, rt.name AS room_type, r.arrival, r.departure, "
                     "r.adults, r.children, r.status, r.special_requests FROM reservations r JOIN guests g ON g.id = r.guest_id "
                     "JOIN room_types rt ON rt.id = r.room_type_id LEFT JOIN rooms rm ON rm.id = r.room_id WHERE r.hotel_id = ? AND "
                     + cond + " ORDER BY rm.number", [hid, d])
        title = {"arrivals": "Arrivals", "departures": "Departures", "in_house": "In-house guests"}[name] + f" — {d}"
        cols = ["Reference", "Guest", "Room", "Category", "Arrival", "Departure", "Adults", "Children", "Status", "Requests"]
        return title, cols, [[r["reference"], r["guest"], r["room"] or "", r["room_type"], r["arrival"], r["departure"], r["adults"], r["children"],
                              r["status"], r["special_requests"] or ""] for r in rows]
    if name == "daily_revenue":
        if not ctx.can("reports.financial"):
            raise forbidden("Financial reports require reports.financial")
        d = parse_date(ctx.q("date", bdate.isoformat()), "date").isoformat()
        rows = c.all("SELECT fl.department, COUNT(*) AS lines, SUM(fl.net_amount) AS net, SUM(fl.service_charge) AS svc, SUM(fl.tax_amount) AS tax, "
                     "SUM(fl.total_amount) AS total FROM folio_lines fl JOIN folios f ON f.id = fl.folio_id WHERE f.hotel_id = ? AND fl.business_date = ? "
                     "AND fl.kind IN ('charge','adjustment') GROUP BY fl.department ORDER BY fl.department", [hid, d])
        pays = c.all("SELECT pm.name, p.kind, SUM(p.amount) AS amount FROM payments p JOIN payment_methods pm ON pm.id = p.method_id "
                     "JOIN journal_entries je ON je.id = p.journal_entry_id WHERE p.hotel_id = ? AND je.entry_date = ? GROUP BY pm.name, p.kind", [hid, d])
        from .pos import pos_direct_revenue
        direct = pos_direct_revenue(c, hid, d, d)
        if direct["orders"]:
            rows.append({"department": "fnb (POS paid at outlet)", "lines": direct["orders"], "net": direct["net"], "svc": direct["service_charge"],
                         "tax": direct["tax"], "total": direct["total"]})
        out = [[r["department"], r["lines"], money(r["net"], cur), money(r["svc"], cur), money(r["tax"], cur), money(r["total"], cur)] for r in rows]
        out.append(["TOTAL", sum(r["lines"] for r in rows), money(sum(r["net"] for r in rows), cur), money(sum(r["svc"] for r in rows), cur),
                    money(sum(r["tax"] for r in rows), cur), money(sum(r["total"] for r in rows), cur)])
        for p in pays:
            out.append([f"{'Refund' if p['kind'] == 'refund' else 'Payment'} — {p['name']}", "", "", "", "", money(p["amount"] * (-1 if p["kind"] == "refund" else 1), cur)])
        return f"Daily revenue — {d}", ["Department", "Lines", "Net", "Service charge", "Tax", "Total"], out
    if name == "occupancy":
        from .dashboard import kpis_range
        d_from = parse_date(ctx.q("from", (bdate - dt.timedelta(days=30)).isoformat()), "from")
        d_to = parse_date(ctx.q("to", bdate.isoformat()), "to")
        if (d_to - d_from).days > 366:
            raise bad_request("Maximum range is one year")
        out = [[k["date"], k["sellable_rooms"], k["rooms_sold"], f"{k['occupancy_pct']}%", money(k["room_revenue"], cur), money(k["adr"], cur), money(k["revpar"], cur)]
               for k in kpis_range(c, hid, d_from, d_to)]
        return f"Occupancy {d_from} to {d_to}", ["Date", "Sellable", "Sold", "Occupancy", "Room revenue", "ADR", "RevPAR"], out
    if name == "outstanding_balances":
        if not ctx.can("reports.financial"):
            raise forbidden("Financial reports require reports.financial")
        rows = c.all("SELECT f.number, g.first_name || ' ' || g.last_name AS guest, r.reference, r.status, "
                     "SUM(CASE WHEN fl.kind IN ('charge','adjustment','refund') THEN fl.total_amount ELSE -fl.total_amount END) AS balance "
                     "FROM folios f JOIN guests g ON g.id = f.guest_id LEFT JOIN reservations r ON r.id = f.reservation_id "
                     "JOIN folio_lines fl ON fl.folio_id = f.id WHERE f.hotel_id = ? AND f.status = 'open' "
                     "GROUP BY f.number, g.first_name, g.last_name, r.reference, r.status ORDER BY balance DESC", [hid])
        return "Outstanding guest balances", ["Folio", "Guest", "Reservation", "Status", "Balance"], \
            [[r["number"], r["guest"], r["reference"] or "", r["status"] or "", money(r["balance"], cur)] for r in rows if r["balance"]]
    if name == "outlet_sales":
        d_from = parse_date(ctx.q("from", bdate.isoformat()), "from").isoformat()
        d_to = parse_date(ctx.q("to", bdate.isoformat()), "to").isoformat()
        rows = c.all("SELECT ou.name AS outlet, COUNT(o.id) AS orders, COALESCE(SUM(o.covers),0) AS covers, COALESCE(SUM(o.discount_amount),0) AS discounts, "
                     "COALESCE(SUM(o.net_amount),0) AS net, COALESCE(SUM(o.service_charge),0) AS svc, COALESCE(SUM(o.tax_amount),0) AS tax, "
                     "COALESCE(SUM(o.total_amount),0) AS total FROM pos_orders o JOIN outlets ou ON ou.id = o.outlet_id WHERE o.hotel_id = ? "
                     "AND o.status = 'settled' AND o.business_date >= ? AND o.business_date <= ? GROUP BY ou.name ORDER BY total DESC", [hid, d_from, d_to])
        items = c.all("SELECT i.name, SUM(i.quantity) AS qty, SUM(i.quantity * i.unit_price) AS gross FROM pos_order_items i JOIN pos_orders o ON o.id = i.order_id "
                      "WHERE o.hotel_id = ? AND o.status = 'settled' AND i.kitchen_status <> 'void' AND o.business_date >= ? AND o.business_date <= ? "
                      "GROUP BY i.name ORDER BY gross DESC", [hid, d_from, d_to])
        voids = c.scalar("SELECT COUNT(*) FROM pos_order_items i JOIN pos_orders o ON o.id = i.order_id WHERE o.hotel_id = ? AND i.kitchen_status = 'void' "
                         "AND o.business_date >= ? AND o.business_date <= ?", [hid, d_from, d_to])
        out = [[r["outlet"], r["orders"], r["covers"], money(r["discounts"], cur), money(r["net"], cur), money(r["svc"], cur), money(r["tax"], cur),
                money(r["total"], cur)] for r in rows]
        out.append(["TOTAL", sum(r["orders"] for r in rows), sum(r["covers"] for r in rows), money(sum(r["discounts"] for r in rows), cur),
                    money(sum(r["net"] for r in rows), cur), money(sum(r["svc"] for r in rows), cur), money(sum(r["tax"] for r in rows), cur),
                    money(sum(r["total"] for r in rows), cur)])
        out.append([f"Voided items: {voids}", "", "", "", "", "", "", ""])
        out += [[f"  {i['name']}", int(i["qty"]), "", "", money(i["gross"], cur), "", "", ""] for i in items]
        return f"Outlet sales {d_from} to {d_to}", ["Outlet / item", "Orders / qty", "Covers", "Discounts", "Net", "Service charge", "Tax", "Total"], out
    if name in ("stock_valuation", "low_stock", "stock_movements", "expiring_stock"):
        if not ctx.can("inventory.view"):
            raise forbidden("Inventory reports require inventory.view")
        if name == "stock_valuation":
            rows = c.all("SELECT s.name AS store, i.code, i.name, i.category, i.unit, l.quantity_milli, l.value FROM stock_levels l "
                         "JOIN inventory_items i ON i.id = l.item_id JOIN stores s ON s.id = l.store_id WHERE s.hotel_id = ? AND l.quantity_milli <> 0 "
                         "ORDER BY s.name, i.category, i.name", [hid])
            out = [[r["store"], r["code"], r["name"], r["category"], f"{r['quantity_milli'] / 1000:g} {r['unit']}",
                    money(r["value"] * 1000 // r["quantity_milli"] if r["quantity_milli"] > 0 else 0, cur), money(r["value"], cur)] for r in rows]
            out.append(["TOTAL", "", "", "", "", "", money(sum(r["value"] for r in rows), cur)])
            return f"Stock valuation (weighted average cost) — {bdate}", ["Store", "Code", "Item", "Category", "On hand", "Avg cost", "Value"], out
        if name == "low_stock":
            rows = c.all("SELECT i.code, i.name, i.unit, i.reorder_level_milli, i.reorder_qty_milli, i.last_cost, COALESCE(SUM(l.quantity_milli),0) AS q "
                         "FROM inventory_items i LEFT JOIN stock_levels l ON l.item_id = i.id WHERE i.hotel_id = ? AND i.active = 1 AND i.reorder_level_milli > 0 "
                         "GROUP BY i.id, i.code, i.name, i.unit, i.reorder_level_milli, i.reorder_qty_milli, i.last_cost "
                         "HAVING COALESCE(SUM(l.quantity_milli),0) <= i.reorder_level_milli ORDER BY i.name", [hid])
            return f"Items at or below reorder level — {bdate}", ["Code", "Item", "On hand", "Reorder level", "Suggested order", "Est. cost"], \
                [[r["code"], r["name"], f"{r['q'] / 1000:g} {r['unit']}", f"{r['reorder_level_milli'] / 1000:g}", f"{r['reorder_qty_milli'] / 1000:g}",
                  money(r["reorder_qty_milli"] * r["last_cost"] // 1000, cur)] for r in rows]
        if name == "expiring_stock":
            limit = (bdate + dt.timedelta(days=int(ctx.q("days", 30)))).isoformat()
            rows = c.all("SELECT b.expiry_date, b.batch_no, b.quantity_milli, i.name, i.unit, s.name AS store FROM stock_batches b JOIN inventory_items i ON i.id = b.item_id "
                         "JOIN stores s ON s.id = b.store_id WHERE s.hotel_id = ? AND b.quantity_milli > 0 AND b.expiry_date IS NOT NULL AND b.expiry_date <= ? "
                         "ORDER BY b.expiry_date", [hid, limit])
            return f"Stock expiring by {limit}", ["Expiry", "Item", "Store", "Batch", "Quantity", "Status"], \
                [[r["expiry_date"], r["name"], r["store"], r["batch_no"] or "", f"{r['quantity_milli'] / 1000:g} {r['unit']}",
                  "EXPIRED" if r["expiry_date"] < bdate.isoformat() else "expiring"] for r in rows]
        d_from = parse_date(ctx.q("from", bdate.replace(day=1).isoformat()), "from").isoformat()
        d_to = parse_date(ctx.q("to", bdate.isoformat()), "to").isoformat()
        rows = c.all("SELECT m.business_date, m.movement_type, m.source_ref, i.name, i.unit, s.name AS store, m.quantity_milli, m.value, m.department, m.reason, "
                     "u.full_name AS user_name FROM stock_movements m JOIN inventory_items i ON i.id = m.item_id JOIN stores s ON s.id = m.store_id "
                     "LEFT JOIN users u ON u.id = m.created_by WHERE m.hotel_id = ? AND m.business_date >= ? AND m.business_date <= ? ORDER BY m.id", [hid, d_from, d_to])
        return f"Stock movements {d_from} to {d_to}", ["Date", "Type", "Reference", "Item", "Store", "Quantity", "Value", "Department", "Reason", "User"], \
            [[r["business_date"], r["movement_type"], r["source_ref"] or "", r["name"], r["store"], f"{r['quantity_milli'] / 1000:g} {r['unit']}",
              money(r["value"], cur), r["department"] or "", r["reason"] or "", r["user_name"] or ""] for r in rows]
    if name == "payables":
        if not ctx.can("procurement.view"):
            raise forbidden("The payables report requires procurement.view")
        rows = c.all("SELECT s.name AS supplier, i.number, i.invoice_no, i.invoice_date, i.due_date, i.amount, i.amount_paid, i.status FROM supplier_invoices i "
                     "JOIN suppliers s ON s.id = i.supplier_id WHERE i.hotel_id = ? AND i.status IN ('approved','part_paid') ORDER BY i.due_date", [hid])
        out = []
        for r in rows:
            days = (bdate - dt.date.fromisoformat(r["due_date"])).days
            out.append([r["supplier"], r["number"], r["invoice_no"], r["invoice_date"], r["due_date"], "current" if days <= 0 else f"{days} days overdue",
                        money(r["amount"], cur), money(r["amount_paid"], cur), money(r["amount"] - r["amount_paid"], cur)])
        out.append(["TOTAL", "", "", "", "", "", "", "", money(sum(r["amount"] - r["amount_paid"] for r in rows), cur)])
        return f"Supplier payables — {bdate}", ["Supplier", "Invoice", "Supplier ref", "Date", "Due", "Ageing", "Amount", "Paid", "Outstanding"], out
    raise not_found("Report")


REPORTS = {"arrivals": "Arrivals", "departures": "Departures", "in_house": "In-house guests", "daily_revenue": "Daily revenue",
           "occupancy": "Occupancy & ADR / RevPAR", "outstanding_balances": "Outstanding guest balances",
           "outlet_sales": "Restaurant & bar sales by outlet", "stock_valuation": "Stock valuation", "low_stock": "Low stock / reorder list",
           "expiring_stock": "Expiring stock", "stock_movements": "Stock movements", "payables": "Supplier payables & ageing"}
# reports that need more than reports.view
REPORT_PERMS = {"daily_revenue": "reports.financial", "outstanding_balances": "reports.financial", "outlet_sales": "reports.financial",
                "stock_valuation": "inventory.view", "low_stock": "inventory.view", "expiring_stock": "inventory.view",
                "stock_movements": "inventory.view", "payables": "procurement.view"}


@route("GET", "/api/hotels/{hotel_id:int}/reports", perm="reports.view", tag="reports", summary="List available reports")
def list_reports(ctx: Ctx):
    ctx.check_hotel(ctx.path["hotel_id"])
    return {"items": [{"code": k, "name": v, "financial": REPORT_PERMS.get(k) == "reports.financial"}
                      for k, v in REPORTS.items() if k not in REPORT_PERMS or ctx.can(REPORT_PERMS[k])]}


@route("GET", "/api/hotels/{hotel_id:int}/reports/{name}", perm="reports.view", tag="reports",
       summary="Run a report (?format=json|csv|xlsx|pdf)")
def run_report(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    fmt = ctx.q("format", "json")
    name = ctx.path["name"]
    if name in REPORT_PERMS and not ctx.can(REPORT_PERMS[name]):
        raise forbidden(f"This report requires {REPORT_PERMS[name]}")
    with get_db().tx() as c:
        title, cols, rows = _report_rows(c, ctx, hid, name)
        hotel_name = get_hotel(c, hid)["name"]
        if fmt != "json":
            # FR-BI-006: exports of reports leave an audit record
            audit(c, ctx, "report.exported", "report", name, title, new={"format": fmt, "rows": len(rows), "query": ctx.query}, hotel_id=hid)
    fname = ctx.path["name"]
    if fmt == "json":
        return {"title": title, "columns": cols, "rows": rows}
    data, media, ext = render_report(fmt, fname, title, cols, rows, hotel_name)
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{fname}.{ext}"'})


def render_report(fmt: str, fname: str, title: str, cols: list, rows: list, hotel_name: str) -> tuple[bytes, str, str]:
    """Render a tabular report to csv / xlsx / pdf bytes (shared by downloads and scheduled reports)."""
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        w.writerows(rows)
        return buf.getvalue().encode("utf-8"), "text/csv", "csv"
    if fmt == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        wb = Workbook()
        ws = wb.active
        ws.title = fname[:30]
        ws.append([f"{hotel_name} — {title}"])
        ws["A1"].font = Font(bold=True, size=13)
        ws.append([])
        ws.append(cols)
        for cell in ws[3]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="0F1F3D")
        for r in rows:
            ws.append(r)
        for i, col in enumerate(cols, 1):
            ws.column_dimensions[ws.cell(3, i).column_letter].width = max(12, min(40, max([len(str(col))] + [len(str(r[i - 1])) for r in rows]) + 2))
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"
    if fmt == "pdf":
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=landscape(A4), title=title)
        ss = getSampleStyleSheet()
        t = Table([cols] + [[str(x) for x in r] for r in rows] or [cols], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f1f3d")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTSIZE", (0, 0), (-1, -1), 8), ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd"))]))
        doc.build([Paragraph(f"<b>{hotel_name}</b> — {title}", ss["Title"]), Spacer(1, 8), t])
        return buf.getvalue(), "application/pdf", "pdf"
    raise bad_request("format must be json, csv, xlsx or pdf")
