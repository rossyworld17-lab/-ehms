import React, { useState } from "react";
import { addDays, fmtDate, fmtDateTime, get, label, money, patch, post } from "../api";
import { navigate, useAuth } from "../state";
import { BarList, Button, Card, Field, Input, Kpi, LineChart, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, useAction, useLoad } from "../ui";

const short = (v: number) => (v >= 1e8 ? `${(v / 1e8).toFixed(1)}m` : v >= 1e5 ? `${Math.round(v / 1e5)}k` : String(Math.round(v / 100)));
const Delta = ({ v, invert }: { v?: number | null; invert?: boolean }) => v == null ? <span className="muted">—</span>
  : <span className={(v >= 0) !== !!invert ? "pos" : "danger"}>{v >= 0 ? "▲" : "▼"} {Math.abs(v)}%</span>;

export default function Insights({ q }: { q: URLSearchParams }) {
  const { can } = useAuth();
  const tabs = [
    can("bi.view") && { id: "analytics", label: "Analytics" },
    can("bi.view") && { id: "forecast", label: "Forecast" },
    can("bi.view") && { id: "occupancy", label: "Occupancy history" },
    can("bi.view") && can("hr.view") && { id: "hr", label: "HR analytics" },
    can("ai.anomalies.view") && { id: "anomalies", label: "Unusual transactions" },
    can("ai.assistant") && { id: "recommendations", label: "Recommendations" },
    can("bi.schedule") && { id: "schedules", label: "Scheduled reports" },
  ].filter(Boolean) as { id: string; label: string }[];
  const [tab, setTab] = useState(q.get("tab") && tabs.some(t => t.id === q.get("tab")) ? q.get("tab")! : tabs[0]?.id);
  const change = (t: string) => { setTab(t); navigate(`/insights?tab=${t}`); };
  return <div className="page">
    <div className="page-h"><div><h1>Insights</h1><p className="muted">Business intelligence, forecasts, unusual transactions and recommendations — every figure explains where it comes from</p></div></div>
    <Tabs tabs={tabs} value={tab} onChange={change} />
    {tab === "analytics" && <Analytics />}{tab === "forecast" && <Forecast />}{tab === "occupancy" && <OccupancyHistory />}{tab === "hr" && <HrAnalytics />}
    {tab === "anomalies" && <Anomalies />}{tab === "recommendations" && <Recommendations />}{tab === "schedules" && <Schedules />}
  </div>;
}

function Analytics() {
  const { hotel, user } = useAuth();
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ hotel_ids: String(hotel!.id), from: addDays(today, -30), to: addDays(today, -1), granularity: "day", compare: "previous_period", department: "" });
  const [applied, setApplied] = useState(f);
  const st = useLoad(() => get("/api/bi/analytics", Object.fromEntries(Object.entries(applied).filter(([, v]) => v))), [JSON.stringify(applied)]);
  const hotels = user!.hotels;
  return <div className="stack">
    <Card><div className="filters">
      {hotels.length > 1 && <Field label="Property"><Select value={f.hotel_ids} onChange={e => setF({ ...f, hotel_ids: e.target.value })}>
        <option value={hotels.map(h => h.id).join(",")}>All properties (consolidated)</option>{hotels.map(h => <option key={h.id} value={h.id}>{h.name}</option>)}</Select></Field>}
      <Field label="From"><Input type="date" value={f.from} onChange={e => setF({ ...f, from: e.target.value })} /></Field>
      <Field label="To"><Input type="date" value={f.to} onChange={e => setF({ ...f, to: e.target.value })} /></Field>
      <Field label="Group by"><Select value={f.granularity} onChange={e => setF({ ...f, granularity: e.target.value })}>{["day", "week", "month", "quarter", "year"].map(g => <option key={g} value={g}>{label(g)}</option>)}</Select></Field>
      <Field label="Compare with"><Select value={f.compare} onChange={e => setF({ ...f, compare: e.target.value })}><option value="previous_period">Previous period</option><option value="previous_year">Same period last year</option><option value="none">No comparison</option></Select></Field>
      <Field label="Department (financials)"><Select value={f.department} onChange={e => setF({ ...f, department: e.target.value })}><option value="">All</option>
        {["room", "fnb", "laundry", "events", "other"].map(d => <option key={d} value={d}>{label(d)}</option>)}</Select></Field>
      <Button onClick={() => setApplied(f)}>Apply</Button>
    </div></Card>
    <Loadable state={st}>{d => { const k = d.current.kpis, ch = d.comparison?.change_pct || {}, cur = d.hotels[0].currency; return <>
      <div className="kpis">
        <Kpi title="Occupancy" value={`${k.occupancy_pct}%`} tone="navy" sub={<><Delta v={ch.occupancy_pct} /> · {k.room_nights_sold} of {k.available_room_nights} room nights</>} />
        <Kpi title="ADR" value={money(k.adr, cur)} sub={<Delta v={ch.adr} />} />
        <Kpi title="RevPAR" value={money(k.revpar, cur)} tone="gold" sub={<Delta v={ch.revpar} />} />
        <Kpi title="Room revenue" value={money(k.room_revenue, cur)} sub={<Delta v={ch.room_revenue} />} />
        <Kpi title="Bookings made" value={k.bookings_made} sub={<><Delta v={ch.bookings_made} /> · lead {k.avg_lead_time_days} d · stay {k.avg_length_of_stay} n</>} />
        <Kpi title="Cancellations" value={`${k.cancellations} (${k.cancellation_rate_pct}%)`} sub={<><Delta v={ch.cancellations} invert /> · {k.no_shows} no-show(s)</>} />
      </div>
      {d.comparison && <p className="muted small">Compared with {fmtDate(d.comparison.from)} – {fmtDate(d.comparison.to)}.</p>}
      <Card title="Occupancy %"><LineChart data={d.current.series.map((s: any, i: number) => ({ label: s.period, a: s.occupancy_pct, b: d.comparison?.series[i]?.occupancy_pct }))}
        series={[{ key: "a", label: "This period", color: "#1e3a6e" }, ...(d.comparison ? [{ key: "b", label: "Comparison", color: "#c8a96a" }] : [])]} fmt={v => `${Math.round(v)}%`} height={180} /></Card>
      {d.current.financial ? <div className="grid-2">
        <Card title="Profit summary (general ledger)">
          <dl className="dl"><dt>Revenue</dt><dd><b>{money(d.current.financial.revenue, cur)}</b> <Delta v={ch.revenue} /></dd>
            <dt>Expenses</dt><dd>{money(d.current.financial.expenses, cur)} <Delta v={ch.expenses} invert /></dd>
            <dt>Gross operating profit</dt><dd><b>{money(d.current.financial.gross_operating_profit, cur)}</b> <Delta v={ch.gross_operating_profit} /></dd>
            <dt>GOP margin</dt><dd>{d.current.financial.gop_margin_pct != null ? `${d.current.financial.gop_margin_pct}%` : "—"}</dd></dl>
          <p className="muted small mt">Source: {d.current.financial.source}. Only posted entries are counted.</p></Card>
        <Card title="Revenue by department"><BarList items={d.current.financial.revenue_by_department.map((r: any) => ({ label: label(r.department), value: r.amount }))} fmt={v => money(v, cur)} color="var(--gold)" /></Card>
        <Card title="Revenue and expenses by period"><LineChart data={d.current.series.map((s: any) => ({ label: s.period, r: s.revenue, e: s.expenses }))}
          series={[{ key: "r", label: "Revenue", color: "#1e3a6e" }, { key: "e", label: "Expenses", color: "#c0392b" }]} fmt={short} /></Card>
        <Card title="Largest expenses" pad={false}><Table rows={d.current.financial.expenses_by_account.slice(0, 8)} cols={[{ h: "Account", r: a => `${a.code} ${a.name}` }, { h: "Amount", r: a => money(a.amount, cur), cls: "num" }]} empty="No expenses posted" /></Card>
      </div> : <p className="note">{d.note}</p>}
      <div className="grid-2">
        <Card title="Bookings by source"><BarList items={d.current.by_source.map((s: any) => ({ label: label(s.source), value: s.bookings }))} /></Card>
        <Card title="By property" pad={false}><Table rows={d.current.by_hotel} rowKey={h => h.hotel_id} cols={[{ h: "Property", r: h => h.hotel }, { h: "Occupancy", r: h => `${h.occupancy_pct}%`, cls: "num" },
          { h: "ADR", r: h => money(h.adr, cur), cls: "num" }, { h: "RevPAR", r: h => money(h.revpar, cur), cls: "num" }, { h: "Room revenue", r: h => money(h.room_revenue, cur), cls: "num" }]} /></Card>
      </div>
      <Card title="Detail by period" pad={false}><Table rows={d.current.series} rowKey={s => s.period} cols={[{ h: "Period", r: s => s.period }, { h: "Sold / available", r: s => `${s.sold} / ${s.available}`, cls: "num" },
        { h: "Occupancy", r: s => `${s.occupancy_pct}%`, cls: "num" }, { h: "ADR", r: s => money(s.adr, cur), cls: "num" }, { h: "RevPAR", r: s => money(s.revpar, cur), cls: "num" },
        ...(d.current.financial ? [{ h: "Revenue (GL)", r: (s: any) => money(s.revenue, cur), cls: "num" }, { h: "Expenses (GL)", r: (s: any) => money(s.expenses, cur), cls: "num" }] : [])]} /></Card>
    </>; }}</Loadable>
  </div>;
}

function Forecast() {
  const { hotel } = useAuth();
  const [days, setDays] = useState(30);
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/insights/forecast`, { days }), [hotel?.id, days]);
  return <Loadable state={st}>{f => <div className="stack">
    <div className="row gap-s"><span className="muted">Horizon</span>{[14, 30, 60, 90].map(n => <Button key={n} kind={n === days ? "primary" : "secondary"} onClick={() => setDays(n)}>{n} days</Button>)}</div>
    <div className="kpis"><Kpi title="Room nights on the books" value={f.totals.on_books} tone="navy" /><Kpi title="Expected room nights" value={f.totals.expected_room_nights} />
      {f.totals.expected_room_revenue != null && <Kpi title="Expected room revenue" value={money(f.totals.expected_room_revenue, hotel!.currency)} tone="gold" />}<Kpi title="Method" value={f.method === "pickup" ? "Pickup model" : "Weekday average"} /></div>
    <Card title="Expected occupancy"><LineChart data={f.days.map((d: any) => ({ label: d.date, e: d.expected_occupancy_pct, b: f.rooms ? Math.round(d.on_books * 1000 / f.rooms) / 10 : 0 }))}
      series={[{ key: "e", label: "Expected %", color: "#1e3a6e" }, { key: "b", label: "On the books %", color: "#c8a96a" }]} fmt={v => `${Math.round(v)}%`} height={190} /></Card>
    <Card title="How this forecast works"><p>{f.explanation}</p><ul className="small muted">{f.limitations.map((l: string) => <li key={l}>{l}</li>)}</ul></Card>
    <Card pad={false}><Table rows={f.days} rowKey={d => d.date} cols={[{ h: "Date", r: d => new Date(d.date + "T00:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" }) },
      { h: "On books", r: d => d.on_books, cls: "num" }, { h: "Expected", r: d => d.expected_rooms, cls: "num" }, { h: "Range", r: d => `${d.low}–${d.high}`, cls: "num" },
      { h: "Occupancy", r: d => `${d.expected_occupancy_pct}%`, cls: "num" }, ...(f.days[0]?.expected_room_revenue != null ? [{ h: "Room revenue", r: (d: any) => money(d.expected_room_revenue, hotel!.currency), cls: "num" }] : [])]} /></Card>
  </div>}</Loadable>;
}

function OccupancyHistory() {
  const { hotel } = useAuth();
  const today = new Date().toISOString().slice(0, 10);
  const [r, setR] = useState({ from: addDays(today, -28), to: addDays(today, -1) });
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/bi/occupancy-history`, r), [hotel?.id, r.from, r.to]);
  const heat = (p: number) => `rgba(30,58,110,${Math.min(1, p / 100) * 0.85 + (p > 0 ? 0.08 : 0)})`;
  return <div className="stack">
    <div className="filters"><Field label="From"><Input type="date" value={r.from} onChange={e => setR({ ...r, from: e.target.value })} /></Field>
      <Field label="To"><Input type="date" value={r.to} onChange={e => setR({ ...r, to: e.target.value })} /></Field></div>
    <Loadable state={st}>{d => <>
      <Card title="Occupancy by room category" pad={false}><div className="table-wrap"><table className="table heat">
        <thead><tr><th>Category</th>{d.dates.map((x: string) => <th key={x} title={x}>{x.slice(8)}</th>)}</tr></thead>
        <tbody>{d.categories.map((c: any) => <tr key={c.id}><td>{c.name} <span className="muted small">({c.rooms})</span></td>
          {c.occupancy_pct.map((p: number, i: number) => <td key={i} title={`${d.dates[i]}: ${c.sold[i]} of ${c.rooms} (${p}%)`} style={{ background: heat(p), color: p > 50 ? "#fff" : undefined }}>{c.sold[i] || ""}</td>)}</tr>)}</tbody>
      </table></div></Card>
      <Card title="Room performance" pad={false}><Table rows={d.rooms} cols={[{ h: "Room", r: x => x.number }, { h: "Category", r: x => x.room_type }, { h: "Nights sold", r: x => x.nights_sold, cls: "num" },
        { h: "Occupancy", r: x => `${x.occupancy_pct}%`, cls: "num" }, { h: "Room revenue", r: x => money(x.room_revenue, hotel!.currency), cls: "num" }, { h: "Out-of-order jobs", r: x => x.blocking_work_orders || "", cls: "num" }]} /></Card>
    </>}</Loadable>
  </div>;
}

function HrAnalytics() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/bi/hr`), [hotel?.id]);
  return <Loadable state={st}>{d => <div className="stack">
    <p className="muted small">{fmtDate(d.from)} – {fmtDate(d.to)}</p>
    <div className="kpis"><Kpi title="Headcount" value={d.summary.headcount} tone="navy" /><Kpi title="Joiners / leavers" value={`${d.summary.joiners} / ${d.summary.leavers}`} />
      <Kpi title="Turnover" value={`${d.summary.turnover_pct}%`} /><Kpi title="Attendance rate" value={d.summary.attendance_rate_pct != null ? `${d.summary.attendance_rate_pct}%` : "—"} tone="gold" />
      <Kpi title="Overtime" value={`${d.summary.overtime_hours} h`} /></div>
    <Card title="By department" pad={false}><Table rows={d.by_department} rowKey={x => x.department} cols={[{ h: "Department", r: x => label(x.department) }, { h: "Headcount", r: x => x.headcount, cls: "num" },
      { h: "Attendance", r: x => x.attendance_rate_pct != null ? `${x.attendance_rate_pct}%` : "—", cls: "num" }, { h: "Lateness", r: x => x.lateness_rate_pct != null ? `${x.lateness_rate_pct}%` : "—", cls: "num" },
      { h: "Absences", r: x => x.absent, cls: "num" }, { h: "Leave days recorded", r: x => x.leave, cls: "num" }, { h: "Overtime", r: x => `${x.overtime_hours} h`, cls: "num" }]} /></Card>
    <div className="grid-2">
      <Card title="Approved leave"><BarList items={d.leave.map((l: any) => ({ label: l.name, value: l.days }))} fmt={v => `${v} days`} /></Card>
      <Card title="Payroll cost">{d.payroll.length ? <Table rows={d.payroll} rowKey={p => p.period} cols={[{ h: "Period", r: p => p.period }, { h: "Staff", r: p => p.employees, cls: "num" },
        { h: "Gross", r: p => money(p.gross, hotel!.currency), cls: "num" }, { h: "Employer cost", r: p => money(p.employer_cost, hotel!.currency), cls: "num" }, { h: "Status", r: p => <Pill s={p.status} /> }]} />
        : <p className="muted">{d.payroll_note || "No payroll runs in this period."}</p>}</Card>
    </div>
  </div>}</Loadable>;
}

function Anomalies() {
  const { hotel, can, user } = useAuth();
  const [status, setStatus] = useState("open");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/insights/anomalies`, status ? { status } : {}), [hotel?.id, status]);
  const [open, setOpen] = useState<any>(null);
  const { busy, run } = useAction();
  return <Loadable state={st}>{d => <div className="stack">
    <p className="note">{d.note}</p>
    <div className="row between"><div className="row gap-s">{["open", "reviewing", "confirmed", "dismissed", ""].map(s => <Button key={s} kind={s === status ? "primary" : "secondary"} onClick={() => setStatus(s)}>
      {s ? label(s) : "All"}{s && d.counts[s] ? ` (${d.counts[s]})` : ""}</Button>)}</div>
      {can("ai.review") && <Button kind="secondary" busy={busy} onClick={async () => { const r = await run(() => post(`/api/hotels/${hotel!.id}/insights/anomalies/scan`, {}), "Scan finished"); if (r) st.reload(); }}>Scan now</Button>}</div>
    <Card pad={false}><Table rows={d.items} onRow={setOpen} empty="Nothing to review" cols={[{ h: "Raised", r: a => fmtDate(a.created_at) }, { h: "Severity", r: a => <Pill s={a.severity === "high" ? "urgent" : a.severity === "medium" ? "high" : "low"} text={label(a.severity)} /> },
      { h: "What", r: a => <><b>{a.title}</b><div className="small muted">{d.rules[a.rule]}</div></> }, { h: "Person", r: a => a.user_name || "—" }, { h: "Status", r: a => <Pill s={a.status} /> }]} /></Card>
    {open && <ReviewModal flag={open} rules={d.rules} canReview={can("ai.review") && open.user_id !== user!.id} onClose={() => setOpen(null)} onDone={() => { setOpen(null); st.reload(); }} />}
  </div>}</Loadable>;
}

function ReviewModal({ flag, rules, canReview, onClose, onDone }: any) {
  const [note, setNote] = useState("");
  const { busy, run } = useAction();
  const closed = ["confirmed", "dismissed"].includes(flag.status);
  const act = async (status: string) => { if (await run(() => post(`/api/anomalies/${flag.id}/review`, { status, note: note || undefined }), "Review recorded")) onDone(); };
  const link = flag.entity_type === "folio" ? `/folio/${flag.entity_id}` : null;
  return <Modal title={flag.title} onClose={onClose} width={620} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    {canReview && !closed && <><Button kind="secondary" busy={busy} onClick={() => act("reviewing")}>Mark as being reviewed</Button>
      <Button kind="secondary" busy={busy} disabled={!note.trim()} onClick={() => act("dismissed")}>Dismiss — explained</Button>
      <Button kind="danger" busy={busy} disabled={!note.trim()} onClick={() => act("confirmed")}>Confirm issue</Button></>}</>}>
    <p><b>Rule:</b> {rules[flag.rule]}</p><p>{flag.explanation}</p>
    <dl className="dl"><dt>Person</dt><dd>{flag.user_name || "—"}</dd><dt>Amount</dt><dd>{flag.amount ? money(flag.amount) : "—"}</dd><dt>Status</dt><dd><Pill s={flag.status} /></dd>
      {flag.reviewer_name && <><dt>Reviewed by</dt><dd>{flag.reviewer_name}, {fmtDateTime(flag.reviewed_at)}</dd><dt>Note</dt><dd>{flag.review_note}</dd></>}</dl>
    {link && <p><a href={`#${link}`} onClick={onClose}>Open the record</a></p>}
    {!closed && (canReview ? <Field label="Review note (required to close)" wide><Textarea value={note} onChange={e => setNote(e.target.value)} /></Field>
      : <p className="muted small">You can view this flag; reviewing needs the ai.review permission, and a flag about your own transactions must be reviewed by someone else.</p>)}
  </Modal>;
}

function Recommendations() {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/insights/recommendations`), [hotel?.id]);
  const [sel, setSel] = useState<number[]>([]);
  const { busy, run } = useAction();
  return <Loadable state={st}>{d => <div className="stack">
    {d.rates && <Card title="Room rates">
      <p className="muted small">{d.rates.method}</p>
      <Table rows={d.rates.items} rowKey={r => r.date} empty="No rate changes suggested — demand is in the normal range" cols={[{ h: "Night", r: r => fmtDate(r.date) }, { h: "Expected occupancy", r: r => `${r.expected_occupancy_pct}%`, cls: "num" },
        { h: "Suggested change", r: r => <b className={r.suggested_change_pct > 0 ? "pos" : "danger"}>{r.suggested_change_pct > 0 ? "+" : ""}{r.suggested_change_pct}%</b>, cls: "num" }, { h: "Why", r: r => <span className="small">{r.reason}</span> }]} />
      {d.rates.rule_candidates.length > 0 && <div className="mt"><h4>Turn into a pricing rule (needs approval)</h4>{d.rates.rule_candidates.map((c: any) => <div key={c.name} className="row between card-row">
        <span>{c.name}: occupancy {c.min_occupancy_pct}–{c.max_occupancy_pct}% → {c.adjustment_bp > 0 ? "+" : ""}{c.adjustment_bp / 100}% ({c.nights_affected} night(s) now)</span>
        {can("sales.pricing") && <Button kind="secondary" busy={busy} onClick={async () => { await run(() => post(`/api/hotels/${hotel!.id}/insights/recommendations/propose-rule`, c), "Rule proposed — it now awaits approval"); }}>Propose rule</Button>}</div>)}</div>}
    </Card>}
    {d.reorder && <Card title="Stock to reorder" actions={can("procurement.requisition") && sel.length > 0 && <Button busy={busy} onClick={async () => {
      const r = await run(() => post(`/api/hotels/${hotel!.id}/insights/recommendations/requisition`, { item_ids: sel }), "Requisition raised for approval"); if (r) { setSel([]); navigate("/procurement?tab=requisitions"); } }}>Raise requisition ({sel.length})</Button>}>
      <p className="muted small">{d.reorder.method}</p>
      <Table rows={d.reorder.items} rowKey={r => r.item_id} empty="Nothing needs reordering" cols={[
        ...(can("procurement.requisition") ? [{ h: "", r: (r: any) => <input type="checkbox" aria-label={`Select ${r.name}`} checked={sel.includes(r.item_id)} onChange={e => setSel(e.target.checked ? [...sel, r.item_id] : sel.filter(x => x !== r.item_id))} /> }] : []),
        { h: "Item", r: r => <><b>{r.name}</b> <span className="muted small">{r.code}</span></> }, { h: "On hand", r: r => `${r.on_hand} ${r.unit}`, cls: "num" }, { h: "Daily use", r: r => r.daily_use || "—", cls: "num" },
        { h: "Days of cover", r: r => r.days_cover ?? "—", cls: "num" }, { h: "Suggested order", r: r => <b>{r.suggested_qty} {r.unit}</b>, cls: "num" }, { h: "Est. cost", r: r => money(r.estimated_cost, hotel!.currency), cls: "num" },
        { h: "", r: r => r.urgency === "high" ? <Pill s="urgent" text="Urgent" /> : null }, { h: "Why", r: r => <span className="small">{r.reason}</span> }]} />
    </Card>}
    {d.denied.length > 0 && <p className="muted small">Not shown for your role: {d.denied.join("; ")}.</p>}
  </div>}</Loadable>;
}

function Schedules() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/report-schedules`), [hotel?.id]);
  const [adding, setAdding] = useState(false);
  const { busy, run } = useAction();
  const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  return <Loadable state={st}>{d => <div className="stack">
    <div className="row between"><p className="muted">Reports are generated by the background worker for the period just ended, saved in Documents and announced to recipients — access is checked again each time.</p>
      <Button onClick={() => setAdding(true)}>Schedule a report</Button></div>
    <Card pad={false}><Table rows={d.items} empty="No scheduled reports" cols={[{ h: "Report", r: s => <><b>{s.name}</b><div className="small muted">{label(s.report_code)} · {s.format.toUpperCase()}</div></> },
      { h: "When", r: s => s.frequency === "daily" ? "Daily" : s.frequency === "weekly" ? `Weekly on ${days[s.weekday]}` : `Monthly on day ${s.month_day}` },
      { h: "Recipients", r: s => <span className="small">{s.recipients.map((r: any) => r.name).join(", ")}</span> },
      { h: "Last run", r: s => s.last_run_on ? <>{fmtDate(s.last_run_on)}<div className="small muted">{s.last_status}{s.last_error ? ` — ${s.last_error}` : ""}</div></> : "—" },
      { h: "", r: s => <div className="row gap-s">{s.active ? <Pill s="active" /> : <Pill s="inactive" text="Paused" />}
        {s.active ? <Button kind="ghost" busy={busy} onClick={async () => { if (await run(() => post(`/api/report-schedules/${s.id}/run`, {}), "Report generated — see Documents")) st.reload(); }}>Run now</Button> : null}
        <Button kind="ghost" busy={busy} onClick={async () => { if (await run(() => patch(`/api/report-schedules/${s.id}`, { active: !s.active }), s.active ? "Paused" : "Resumed")) st.reload(); }}>{s.active ? "Pause" : "Resume"}</Button></div> }]} /></Card>
    {adding && <NewSchedule data={d} onClose={() => setAdding(false)} onDone={() => { setAdding(false); st.reload(); }} />}
  </div>}</Loadable>;
}

function NewSchedule({ data, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState<any>({ name: "", report_code: data.reports[0]?.code || "", frequency: "weekly", weekday: 0, month_day: 1, format: "pdf", recipients: [] as number[] });
  const { busy, run } = useAction();
  const eligible = data.recipients.filter((r: any) => r.reports.includes(f.report_code));
  return <Modal title="Schedule a report" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.report_code || !f.recipients.length} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/report-schedules`, f), "Report scheduled")) onDone(); }}>Save</Button></>}>
    <div className="form-grid">
      <Field label="Report"><Select value={f.report_code} onChange={e => setF({ ...f, report_code: e.target.value, recipients: [] })}>{data.reports.map((r: any) => <option key={r.code} value={r.code}>{r.name}</option>)}</Select></Field>
      <Field label="Name (optional)"><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Frequency"><Select value={f.frequency} onChange={e => setF({ ...f, frequency: e.target.value })}><option value="daily">Daily (yesterday)</option><option value="weekly">Weekly (last 7 days)</option><option value="monthly">Monthly (last month)</option></Select></Field>
      {f.frequency === "weekly" && <Field label="Day"><Select value={f.weekday} onChange={e => setF({ ...f, weekday: Number(e.target.value) })}>{["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"].map((d, i) => <option key={d} value={i}>{d}</option>)}</Select></Field>}
      {f.frequency === "monthly" && <Field label="Day of month"><Input type="number" min={1} max={31} value={f.month_day} onChange={e => setF({ ...f, month_day: Number(e.target.value) })} /></Field>}
      <Field label="Format"><Select value={f.format} onChange={e => setF({ ...f, format: e.target.value })}><option value="pdf">PDF</option><option value="xlsx">Excel</option><option value="csv">CSV</option></Select></Field>
      <Field label="Recipients (only people allowed to see this report are listed)" wide><div className="checklist">{eligible.map((r: any) => <label key={r.id} className="check">
        <input type="checkbox" checked={f.recipients.includes(r.id)} onChange={e => setF({ ...f, recipients: e.target.checked ? [...f.recipients, r.id] : f.recipients.filter((x: number) => x !== r.id) })} /> {r.name}</label>)}</div></Field>
    </div></Modal>;
}
