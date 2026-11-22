import React from "react";
import { get, money, label } from "../api";
import { useAuth } from "../state";
import { BarList, Card, Kpi, LineChart, Loadable, useLoad } from "../ui";

export default function Dashboard() {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/dashboard`), [hotel?.id]);
  const cur = hotel!.currency;
  const short = (v: number) => (v >= 1e8 ? `${(v / 1e8).toFixed(1)}m` : v >= 1e5 ? `${Math.round(v / 1e5)}k` : String(Math.round(v / 100)));
  return (
    <div className="page">
      <div className="page-h"><div><h1>Dashboard</h1><p className="muted">Live position for {hotel!.name}</p></div>
        <button className="btn btn-secondary" onClick={st.reload}>Refresh</button></div>
      <Loadable state={st}>{d => (
        <>
          <div className="kpis">
            <Kpi title="Occupancy tonight" value={`${d.today.occupancy_pct}%`} sub={`${d.today.rooms_sold} of ${d.today.sellable_rooms} sellable rooms (excl. departures)`} tone="navy" />
            <Kpi title="Arrivals today" value={d.front_office.arrivals_expected} sub={`${d.front_office.arrived} already arrived`} />
            <Kpi title="Departures today" value={d.front_office.departures_expected} sub={`${d.front_office.departed} checked out`} />
            <Kpi title="In-house guests" value={d.front_office.in_house_guests} sub={`${d.room_status.occupied} occupied rooms`} />
            {can("reports.financial") && <Kpi title="Room revenue (business date)" value={money(d.today.room_revenue, cur)} sub={`ADR ${money(d.today.adr, cur)} · RevPAR ${money(d.today.revpar, cur)}`} tone="gold" />}
            {can("reports.financial") && <Kpi title="Outstanding balances" value={money(d.outstanding_balances, cur)} sub={`Payments today ${money(d.payments_today, cur)}`} />}
          </div>
          <div className="grid-2">
            <Card title="Room status">
              <div className="statusbar">
                {[["occupied", "Occupied"], ["vacant_ready", "Vacant & ready"], ["vacant_dirty", "Vacant dirty"], ["awaiting_inspection", "Awaiting inspection"], ["out_of_service", "Out of service"]].map(([k, l]) => (
                  <a key={k} href="#/rooms" className={`sb sb-${k}`}><b>{d.room_status[k]}</b><span>{l}</span></a>))}
              </div>
              <div className="row gap wrap mt">
                <span className="chip">Pending reservations: <b>{d.front_office.pending_reservations}</b></span>
                <span className="chip">Housekeeping open: <b>{d.tasks.housekeeping_open}</b></span>
                <span className="chip">Awaiting inspection: <b>{d.tasks.awaiting_inspection}</b></span>
                {can("approvals.view") && <a className="chip" href="#/approvals">Approvals pending: <b>{d.tasks.approvals_pending}</b></a>}
                {can("pos.view") && <a className="chip" href="#/pos">Open restaurant orders: <b>{d.tasks.open_pos_orders}</b></a>}
                {can("inventory.view") && <a className={`chip ${d.tasks.low_stock_items ? "chip-warn" : ""}`} href="#/inventory?tab=alerts">Low-stock items: <b>{d.tasks.low_stock_items}</b></a>}
                {can("procurement.view") && <a className="chip" href="#/procurement">POs awaiting approval: <b>{d.tasks.purchase_orders_pending}</b> · invoices: <b>{d.tasks.supplier_invoices_pending}</b></a>}
              </div>
            </Card>
            <Card title="Next 14 days — rooms on the books">
              <LineChart data={d.forecast.map((f: any) => ({ label: f.date, occ: f.occupancy_pct }))} series={[{ key: "occ", label: "Forecast occupancy %", color: "#c8a96a" }]} height={180} fmt={v => `${Math.round(v)}%`} />
            </Card>
          </div>
          <div className="grid-2">
            <Card title="Occupancy — last 30 days">
              <LineChart data={d.trend.map((t: any) => ({ label: t.date, occ: t.occupancy_pct }))} series={[{ key: "occ", label: "Occupancy %", color: "#1e3a6e" }]} fmt={v => `${Math.round(v)}%`} />
            </Card>
            {can("reports.financial") ? <Card title="Room revenue — last 30 days">
              <LineChart data={d.trend.map((t: any) => ({ label: t.date, rev: t.room_revenue, adr: t.adr }))}
                series={[{ key: "rev", label: "Room revenue", color: "#1e3a6e" }, { key: "adr", label: "ADR", color: "#c8a96a" }]} fmt={short} />
            </Card> : <Card title="Room category mix (this month)"><BarList items={d.room_type_mix.map((r: any) => ({ label: r.name, value: r.bookings }))} /></Card>}
          </div>
          <div className="grid-3">
            {can("reports.financial") && <Card title="Revenue today by department">
              <BarList items={d.revenue_today.map((r: any) => ({ label: label(r.department), value: r.amount }))} fmt={v => money(v, cur)} color="#c8a96a" />
            </Card>}
            {can("reports.financial") && <Card title="Revenue month-to-date">
              <BarList items={d.revenue_mtd.map((r: any) => ({ label: label(r.department), value: r.amount }))} fmt={v => money(v, cur)} />
            </Card>}
            <Card title="Booking channels (this month)">
              <BarList items={d.booking_sources.map((s: any) => ({ label: label(s.source), value: s.bookings }))} />
            </Card>
          </div>
        </>
      )}</Loadable>
    </div>
  );
}
