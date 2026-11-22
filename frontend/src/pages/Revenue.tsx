import React, { useState } from "react";
import { fmtDate, fmtDateTime, get, label, money, patch, post, put, toMinor, fromMinor } from "../api";
import { useAuth } from "../state";
import { Button, Card, Field, Input, Kpi, LineChart, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, useAction, useLoad } from "../ui";

export default function Revenue() {
  const { can } = useAuth();
  const [tab, setTab] = useState("dashboard");
  return <div className="page">
    <div className="page-h"><div><h1>Sales & revenue</h1><p className="muted">Forecast on the books, pricing, accounts and targets</p></div></div>
    <Tabs tabs={[{ id: "dashboard", label: "Revenue dashboard" }, { id: "pricing", label: "Pricing" }, { id: "accounts", label: "Accounts" }, { id: "targets", label: "Targets" }]} value={tab} onChange={setTab} />
    {tab === "dashboard" && <Dashboard />}{tab === "pricing" && <Pricing />}{tab === "accounts" && <Accounts />}{tab === "targets" && <Targets />}
  </div>;
}

function Dashboard() {
  const { hotel } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/revenue/dashboard`), [hotel?.id]);
  const short = (v: number) => (v >= 1e8 ? `${(v / 1e8).toFixed(1)}m` : v >= 1e5 ? `${Math.round(v / 1e5)}k` : String(Math.round(v / 100)));
  return <Loadable state={st}>{d => <div className="stack">
    <div className="kpis"><Kpi title="Occupancy (last 30 days)" value={`${d.period.occupancy_pct}%`} tone="navy" sub={`${d.period.rooms_sold} room nights`} /><Kpi title="ADR" value={money(d.period.adr, cur)} />
      <Kpi title="RevPAR" value={money(d.period.revpar, cur)} tone="gold" /><Kpi title="Average length of stay" value={d.period.alos != null ? `${d.period.alos} nights` : "—"} />
      <Kpi title="Booking window" value={d.period.booking_window_days != null ? `${d.period.booking_window_days} days` : "—"} /><Kpi title="Cancellation / no-show rate" value={d.period.cancellation_rate_pct != null ? `${d.period.cancellation_rate_pct}%` : "—"} /></div>
    <Card title="Next 30 days on the books"><LineChart data={d.forward.map((f: any) => ({ label: f.date, occ: f.occupancy_pct }))} series={[{ key: "occ", label: "Occupancy on the books %", color: "#1e3a6e" }]} height={170} fmt={v => `${Math.round(v)}%`} /></Card>
    <Card pad={false}><Table rows={d.forward} cols={[{ h: "Date", r: f => new Date(f.date + "T00:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" }) },
      { h: "On books", r: f => f.rooms_on_books, cls: "num" }, { h: "Occupancy", r: f => `${f.occupancy_pct}%`, cls: "num" }, { h: "Pickup (7 days)", r: f => f.pickup_7d ? `+${f.pickup_7d}` : "", cls: "num" },
      { h: "ADR on books", r: f => f.adr_on_books ? money(f.adr_on_books, cur) : "—", cls: "num" }, { h: "Our rate (lowest)", r: f => f.our_rate ? money(f.our_rate, cur) : "—", cls: "num" },
      { h: "Competitor avg", r: f => f.competitor_avg ? money(f.competitor_avg, cur) : "—", cls: "num" }, { h: "Suggestion", r: f => f.recommendation ? <span className="small">{f.recommendation}</span> : "" }]} /></Card>
    <p className="muted small">Suggestions are simple rules (occupancy and competitor gap) for a person to consider; prices only change through approved seasons and rules.</p>
    <Card title="Room revenue — this year vs last year"><LineChart data={d.year_on_year.map((y: any) => ({ label: y.month, a: y.this_year.room_revenue, b: y.last_year.room_revenue }))}
      series={[{ key: "a", label: "This year", color: "#1e3a6e" }, { key: "b", label: "Last year", color: "#c8a96a" }]} fmt={short} /></Card>
    <Card pad={false}><Table rows={d.year_on_year} cols={[{ h: "Month", r: y => y.month }, { h: "Occupancy", r: y => `${y.this_year.occupancy_pct}% (${y.last_year.occupancy_pct}%)`, cls: "num" },
      { h: "ADR", r: y => `${money(y.this_year.adr, cur)} (${money(y.last_year.adr, cur)})`, cls: "num" }, { h: "RevPAR", r: y => `${money(y.this_year.revpar, cur)} (${money(y.last_year.revpar, cur)})`, cls: "num" },
      { h: "Room revenue", r: y => money(y.this_year.room_revenue, cur), cls: "num" }]} /></Card>
  </div>}</Loadable>;
}

function Pricing() {
  const { hotel, can, user } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/revenue/pricing`), [hotel?.id]);
  const [modal, setModal] = useState<string | null>(null);
  const { busy, run } = useAction();
  return <Loadable state={st}>{d => <div className="stack">
    <Card title="Seasons" actions={can("sales.pricing") && <Button kind="secondary" onClick={() => setModal("season")}>Add season</Button>} pad={false}>
      <Table rows={d.seasons} empty="No seasons" cols={[{ h: "Season", r: s => <b>{s.name}</b> }, { h: "Dates", r: s => `${fmtDate(s.start_date)} → ${fmtDate(s.end_date)}` }, { h: "Rooms", r: s => s.room_type || "All" },
        { h: "Adjustment", r: s => `${s.adjustment_bp > 0 ? "+" : ""}${s.adjustment_bp / 100}%` }, { h: "Status", r: s => <Pill s={s.active ? "active" : "deactivated"} text={s.active ? "Active" : "Off"} /> },
        { h: "", r: s => can("sales.pricing") && <button className="link small" onClick={async () => { if (await run(() => post(`/api/revenue/seasons/${s.id}/toggle`, {}))) st.reload(); }}>{s.active ? "Turn off" : "Turn on"}</button> }]} /></Card>
    <Card title="Dynamic pricing rules (occupancy-based)" actions={can("sales.pricing") && <Button kind="secondary" onClick={() => setModal("rule")}>Propose rule</Button>} pad={false}>
      <p className="small muted pad">A rule changes new quotes when occupancy for the night is in its band. It takes effect only after someone other than its author approves it. Guests keep the rate they were quoted.</p>
      <Table rows={d.rules} empty="No rules" cols={[{ h: "Rule", r: r => <b>{r.name}</b> }, { h: "Occupancy band", r: r => `${r.min_occupancy_pct}–${r.max_occupancy_pct}%` }, { h: "Rooms", r: r => r.room_type || "All" },
        { h: "Adjustment", r: r => `${r.adjustment_bp > 0 ? "+" : ""}${r.adjustment_bp / 100}%` }, { h: "Proposed by", r: r => r.created_by_name },
        { h: "Status", r: r => <Pill s={r.status === "active" ? "approved" : r.status === "pending_approval" ? "pending" : "cancelled"} text={label(r.status)} /> },
        { h: "", r: r => can("sales.pricing_approve") && <span className="row gap-s">
          {r.status === "pending_approval" && r.created_by !== user!.id && <><Button busy={busy} onClick={async () => { if (await run(() => post(`/api/revenue/rules/${r.id}/decide`, { decision: "approve" }), "Rule active")) st.reload(); }}>Approve</Button>
            <Button kind="ghost" onClick={async () => { if (await run(() => post(`/api/revenue/rules/${r.id}/decide`, { decision: "reject" }), "Rejected")) st.reload(); }}>Reject</Button></>}
          {r.status === "active" && <Button kind="ghost" onClick={async () => { if (await run(() => post(`/api/revenue/rules/${r.id}/decide`, { decision: "deactivate" }), "Deactivated")) st.reload(); }}>Deactivate</Button>}</span> }]} /></Card>
    <Card title="Competitor rates" actions={can("sales.pricing") && <Button kind="secondary" onClick={() => setModal("comp")}>Record rates</Button>} pad={false}>
      <Table rows={d.competitors} empty="No competitor rates recorded" cols={[{ h: "Stay date", r: x => fmtDate(x.stay_date) }, { h: "Competitor", r: x => x.competitor }, { h: "Room", r: x => x.room_category },
        { h: "Rate", r: x => money(x.rate, cur), cls: "num" }, { h: "Source", r: x => x.source || "—" }, { h: "By", r: x => x.recorded_by_name }]} /></Card>
    {modal === "season" && <SeasonModal types={d.room_types} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
    {modal === "rule" && <RuleModal types={d.room_types} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
    {modal === "comp" && <CompModal onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
  </div>}</Loadable>;
}

function SeasonModal({ types, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ name: "", start_date: "", end_date: "", pct: "20", room_type_id: "" });
  const { busy, run } = useAction();
  return <Modal title="Add season" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.name || !f.start_date || !f.end_date} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/revenue/seasons`, { name: f.name, start_date: f.start_date, end_date: f.end_date, adjustment_bp: Math.round(Number(f.pct) * 100), room_type_id: f.room_type_id ? Number(f.room_type_id) : undefined }), "Season added")) onDone(); }}>Add</Button></>}>
    <div className="form-grid"><Field label="Name"><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="From"><Input type="date" value={f.start_date} onChange={e => setF({ ...f, start_date: e.target.value })} /></Field>
      <Field label="To"><Input type="date" value={f.end_date} onChange={e => setF({ ...f, end_date: e.target.value })} /></Field>
      <Field label="Adjustment % (negative for discounts)"><Input value={f.pct} onChange={e => setF({ ...f, pct: e.target.value })} /></Field>
      <Field label="Room category"><Select value={f.room_type_id} onChange={e => setF({ ...f, room_type_id: e.target.value })}><option value="">All</option>{types.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select></Field></div></Modal>;
}

function RuleModal({ types, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ name: "", min: "80", max: "100", pct: "10", room_type_id: "" });
  const { busy, run } = useAction();
  return <Modal title="Propose a dynamic pricing rule" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.name} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/revenue/rules`, { name: f.name, min_occupancy_pct: Number(f.min), max_occupancy_pct: Number(f.max), adjustment_bp: Math.round(Number(f.pct) * 100), room_type_id: f.room_type_id ? Number(f.room_type_id) : undefined }), "Rule proposed — awaiting approval")) onDone(); }}>Propose</Button></>}>
    <div className="form-grid"><Field label="Name"><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="From occupancy %"><Input type="number" value={f.min} onChange={e => setF({ ...f, min: e.target.value })} /></Field>
      <Field label="To occupancy %"><Input type="number" value={f.max} onChange={e => setF({ ...f, max: e.target.value })} /></Field>
      <Field label="Adjustment % (−30 to +50)"><Input value={f.pct} onChange={e => setF({ ...f, pct: e.target.value })} /></Field>
      <Field label="Room category"><Select value={f.room_type_id} onChange={e => setF({ ...f, room_type_id: e.target.value })}><option value="">All</option>{types.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select></Field></div></Modal>;
}

function CompModal({ onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [rows, setRows] = useState<any[]>([{ competitor: "", stay_date: new Date().toISOString().slice(0, 10), room_category: "Standard double", rate: "", source: "" }]);
  const { busy, run } = useAction();
  return <Modal title="Record competitor rates" width={800} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/revenue/competitor-rates`, { rows: rows.filter(r => r.competitor && r.rate).map(r => ({ ...r, rate: toMinor(r.rate) })) }), "Rates recorded")) onDone(); }}>Save</Button></>}>
    {rows.map((r, i) => <div key={i} className="form-grid tender">{["competitor", "stay_date", "room_category", "rate", "source"].map(k => <Field key={k} label={label(k)}>
      <Input type={k === "stay_date" ? "date" : "text"} value={r[k]} onChange={e => setRows(rows.map((x, j) => j === i ? { ...x, [k]: e.target.value } : x))} /></Field>)}</div>)}
    <button className="link small" onClick={() => setRows([...rows, { ...rows[rows.length - 1], rate: "" }])}>+ Add row</button></Modal>;
}

function Accounts() {
  const { hotel, can } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/accounts/corporate`), [hotel?.id]);
  const [sel, setSel] = useState<number | null>(null);
  const [create, setCreate] = useState(false);
  return <Loadable state={st}>{d => <Card title="Corporate, travel-agent and government accounts" actions={can("sales.manage") && <Button onClick={() => setCreate(true)}>New account</Button>} pad={false}>
    <Table rows={d.items} onRow={a => setSel(a.id)} cols={[{ h: "Account", r: a => <><b>{a.name}</b><div className="tiny muted">{a.code} · {label(a.kind)}</div></> }, { h: "Contact", r: a => a.contact_name || "—" },
      { h: "Manager", r: a => a.account_manager_name || "—" }, { h: "YTD bookings", r: a => a.ytd_bookings, cls: "num" }, { h: "YTD revenue", r: a => money(a.ytd_revenue, cur), cls: "num" },
      { h: "Commission due", r: a => a.kind === "travel_agent" ? money(a.commission_due, cur) : "", cls: "num" },
      { h: "Status", r: a => <Pill s={a.status === "active" ? "active" : a.status === "suspended" ? "suspended" : "pending"} text={label(a.status)} /> }]} />
    {sel && <AccountModal id={sel} onClose={() => { setSel(null); st.reload(); }} />}
    {create && <NewAccount kinds={d.kinds} onClose={() => setCreate(false)} onDone={() => { setCreate(false); st.reload(); }} />}
  </Card>}</Loadable>;
}

function NewAccount({ kinds, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState<any>({ name: "", kind: "corporate", contact_name: "", email: "", phone: "", credit_limit: "", payment_terms_days: 30, commission_pct: "", status: "active" });
  const { busy, run } = useAction();
  return <Modal title="New account" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.name} onClick={async () => { const b: any = { ...f, credit_limit: toMinor(f.credit_limit || "0"), commission_bp: Math.round(Number(f.commission_pct || 0) * 100) }; delete b.commission_pct;
      if (await run(() => post(`/api/hotels/${hotel!.id}/accounts/corporate`, b), "Account created")) onDone(); }}>Create</Button></>}>
    <div className="form-grid"><Field label="Name" wide><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Type"><Select value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}>{kinds.map((k: string) => <option key={k} value={k}>{label(k)}</option>)}</Select></Field>
      <Field label="Status"><Select value={f.status} onChange={e => setF({ ...f, status: e.target.value })}>{["lead", "prospect", "active"].map(k => <option key={k} value={k}>{label(k)}</option>)}</Select></Field>
      {["contact_name", "email", "phone"].map(k => <Field key={k} label={label(k)}><Input value={f[k]} onChange={e => setF({ ...f, [k]: e.target.value })} /></Field>)}
      <Field label="Credit limit"><Input inputMode="decimal" value={f.credit_limit} onChange={e => setF({ ...f, credit_limit: e.target.value })} /></Field>
      <Field label="Payment terms (days)"><Input type="number" value={f.payment_terms_days} onChange={e => setF({ ...f, payment_terms_days: Number(e.target.value) })} /></Field>
      {f.kind === "travel_agent" && <Field label="Commission %"><Input value={f.commission_pct} onChange={e => setF({ ...f, commission_pct: e.target.value })} /></Field>}</div></Modal>;
}

function AccountModal({ id, onClose }: any) {
  const { hotel, can } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/accounts/corporate/${id}`), [id]);
  const types = useLoad(() => get(`/api/hotels/${hotel!.id}/room-types`).catch(() => ({ items: [] })), [hotel?.id]);
  const [r, setR] = useState({ room_type_id: "", rate: "", valid_from: "", valid_to: "" });
  const { busy, run } = useAction();
  return <Modal title={st.data ? st.data.name : "Account"} width={760} onClose={onClose}><Loadable state={st}>{a => <>
    <dl className="dl"><dt>Type</dt><dd>{label(a.kind)}</dd><dt>Contact</dt><dd>{a.contact_name || "—"} {a.email || ""} {a.phone || ""}</dd><dt>Terms</dt><dd>{a.payment_terms_days} days · credit limit {money(a.credit_limit, cur)}</dd>
      <dt>City ledger</dt><dd className={a.over_credit_limit ? "danger" : ""}>{money(a.city_ledger, cur)}{a.over_credit_limit ? " — over the credit limit" : ""}</dd></dl>
    {can("sales.manage") && a.status !== "active" && <Button className="mb" onClick={async () => { if (await run(() => patch(`/api/accounts/corporate/${id}`, { status: "active" }), "Account activated")) st.reload(); }}>Activate account</Button>}
    <h4>Negotiated rates</h4><Table rows={a.rates} empty="None" cols={[{ h: "Room", r: x => x.room_type }, { h: "Rate", r: x => money(x.rate, cur), cls: "num" }, { h: "Valid", r: x => `${fmtDate(x.valid_from)} → ${fmtDate(x.valid_to)}` }]} />
    {can("sales.manage") && <div className="form-grid tender"><Field label="Room"><Select value={r.room_type_id} onChange={e => setR({ ...r, room_type_id: e.target.value })}><option value="">Select…</option>{(types.data?.items || []).map((t: any) => <option key={t.id} value={t.id}>{t.name} (rack {money(t.base_rate, cur)})</option>)}</Select></Field>
      <Field label="Rate"><Input inputMode="decimal" value={r.rate} onChange={e => setR({ ...r, rate: e.target.value })} /></Field>
      <Field label="From"><Input type="date" value={r.valid_from} onChange={e => setR({ ...r, valid_from: e.target.value })} /></Field>
      <Field label="To"><Input type="date" value={r.valid_to} onChange={e => setR({ ...r, valid_to: e.target.value })} /></Field>
      <Button className="self-end" kind="secondary" busy={busy} disabled={!r.room_type_id || !r.rate || !r.valid_from || !r.valid_to} onClick={async () => { const x = await run(() => post(`/api/accounts/corporate/${id}/rates`, { ...r, hotel_id: hotel!.id, room_type_id: Number(r.room_type_id), rate: toMinor(r.rate) }), "Rate added"); if (x) { setR({ room_type_id: "", rate: "", valid_from: "", valid_to: "" }); st.reload(); } }}>Add rate</Button></div>}
    <h4>Recent bookings</h4><Table rows={a.bookings} empty="None" onRow={b => location.hash = `#/reservations/${b.id}`} cols={[{ h: "Ref", r: b => b.reference }, { h: "Guest", r: b => b.guest }, { h: "Dates", r: b => `${fmtDate(b.arrival)} → ${fmtDate(b.departure)}` }, { h: "Status", r: b => label(b.status) }]} />
  </>}</Loadable></Modal>;
}

function Targets() {
  const { hotel, can } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/sales/targets`), [hotel?.id]);
  const [f, setF] = useState({ period: new Date().toISOString().slice(0, 7), metric: "room_revenue", target: "" });
  const { busy, run } = useAction();
  return <Loadable state={st}>{d => <Card title={`Targets ${d.year}`} pad={false}>
    <Table rows={d.items} empty="No targets set" cols={[{ h: "Month", r: t => t.period }, { h: "Metric", r: t => label(t.metric) }, { h: "Target", r: t => t.metric === "rooms_sold" ? t.target : money(t.target, cur), cls: "num" },
      { h: "Actual", r: t => t.metric === "rooms_sold" ? t.actual : money(t.actual, cur), cls: "num" },
      { h: "Achieved", r: t => <div className="row gap-s"><div className="meter"><span style={{ width: `${Math.min(100, t.achieved_pct || 0)}%` }} /></div>{t.achieved_pct ?? 0}%</div> }, { h: "Owner", r: t => t.owner_name || "—" }]} />
    {can("sales.manage") && <div className="form-grid pad"><Field label="Month"><Input type="month" value={f.period} onChange={e => setF({ ...f, period: e.target.value })} /></Field>
      <Field label="Metric"><Select value={f.metric} onChange={e => setF({ ...f, metric: e.target.value })}>{d.metrics.map((m: string) => <option key={m} value={m}>{label(m)}</option>)}</Select></Field>
      <Field label={f.metric === "rooms_sold" ? "Room nights" : `Amount (${cur})`}><Input inputMode="decimal" value={f.target} onChange={e => setF({ ...f, target: e.target.value })} /></Field>
      <Button className="self-end" busy={busy} disabled={!f.target} onClick={async () => { if (await run(() => put(`/api/hotels/${hotel!.id}/sales/targets`, { ...f, target: f.metric === "rooms_sold" ? Number(f.target) : toMinor(f.target) }), "Target saved")) st.reload(); }}>Set target</Button></div>}
  </Card>}</Loadable>;
}
