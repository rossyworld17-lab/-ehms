import React, { useEffect, useState } from "react";
import { api, fmtDate, fmtDateTime, get, label, money, openFile, patch, post, put, toMinor, fromMinor } from "../api";
import { useAuth } from "../state";
import { Button, Card, Empty, Field, Input, Kpi, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, useAction, useLoad } from "../ui";
import { RejectModal } from "./Inventory";

const PRIO_PILL: Record<string, string> = { urgent: "rejected", high: "maintenance", normal: "confirmed", low: "cancelled" };
const WO_PILL: Record<string, string> = { open: "pending", assigned: "confirmed", in_progress: "in_progress", on_hold: "tentative", completed: "completed", verified: "approved", cancelled: "cancelled" };

// ======================================================================== Maintenance
export function Maintenance({ q }: { q: URLSearchParams }) {
  const { can } = useAuth();
  const [tab, setTab] = useState(q.get("tab") || "orders");
  useEffect(() => { const t = q.get("tab"); if (t) setTab(t); }, [q.get("tab")]);
  return <div className="page">
    <div className="page-h"><div><h1>Maintenance</h1><p className="muted">Faults, work orders, preventive maintenance and the asset register</p></div></div>
    <Tabs tabs={[{ id: "orders", label: "Work orders" }, ...(can("maintenance.view") ? [{ id: "assets", label: "Assets" }, { id: "summary", label: "Performance" }] : [])]} value={tab} onChange={setTab} />
    {tab === "orders" && <WorkOrders />}
    {tab === "assets" && <Assets />}
    {tab === "summary" && <MaintSummary />}
  </div>;
}

function WorkOrders() {
  const { hotel, can } = useAuth();
  const [open, setOpen] = useState(true);
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/work-orders`, { open: open ? 1 : "" }), [hotel?.id, open]);
  const [sel, setSel] = useState<number | null>(null);
  const [report, setReport] = useState(false);
  const { busy, run } = useAction();
  return <Loadable state={st}>{d => <>
    <div className="kpis"><Kpi title="Open" value={d.items.filter((w: any) => !["completed", "verified", "cancelled"].includes(w.status)).length} tone="navy" />
      <Kpi title="Urgent" value={d.items.filter((w: any) => w.priority === "urgent" && !["completed", "verified", "cancelled"].includes(w.status)).length} tone={d.items.some((w: any) => w.priority === "urgent") ? "gold" : undefined} />
      <Kpi title="Overdue" value={d.overdue} /><Kpi title="Awaiting verification" value={d.counts.completed || 0} /></div>
    <Card title={<label className="check"><input type="checkbox" checked={open} onChange={e => setOpen(e.target.checked)} /> Open only</label>}
      actions={<div className="row gap-s"><Button onClick={() => setReport(true)}>Report a fault</Button>
        {can("maintenance.manage") && <Button kind="secondary" busy={busy} onClick={async () => { const r = await run(() => post(`/api/hotels/${hotel!.id}/maintenance/raise-preventive`, {})); if (r) st.reload(); }}>Raise due preventive work</Button>}</div>} pad={false}>
      <Table rows={d.items} onRow={w => setSel(w.id)} empty="No work orders" cols={[{ h: "Order", r: w => <><b>{w.number}</b><div className="tiny muted">{label(w.kind)}</div></> },
        { h: "Fault / task", r: w => <>{w.title}<div className="tiny muted">{w.asset_name || (w.room_number ? `Room ${w.room_number}` : "")}</div></> },
        { h: "Priority", r: w => <Pill s={PRIO_PILL[w.priority]} text={label(w.priority)} /> }, { h: "Assigned", r: w => w.assigned_to_name || <span className="muted">—</span> },
        { h: "Due", r: w => <span className={w.overdue ? "danger" : ""}>{fmtDate(w.due_date)}{w.overdue ? " (overdue)" : ""}</span> },
        { h: "Reported", r: w => <>{fmtDateTime(w.created_at)}<div className="tiny muted">{w.reported_by_name}</div></> }, { h: "Status", r: w => <Pill s={WO_PILL[w.status]} text={label(w.status)} /> }]} />
    </Card>
    {sel && <WorkOrderModal id={sel} techs={d.technicians} onClose={() => { setSel(null); st.reload(); }} />}
    {report && <ReportFault onClose={() => setReport(false)} onDone={() => { setReport(false); st.reload(); }} />}
  </>}</Loadable>;
}

export function ReportFault({ onClose, onDone, roomId }: any) {
  const { hotel, can } = useAuth();
  const rooms = useLoad(() => get(`/api/hotels/${hotel!.id}/rooms`).catch(() => ({ items: [] })), [hotel?.id]);
  const assets = useLoad(() => (can("maintenance.view") ? get(`/api/hotels/${hotel!.id}/assets`) : Promise.resolve({ items: [] })), [hotel?.id]);
  const [f, setF] = useState<any>({ title: "", description: "", priority: "normal", room_id: roomId || "", asset_id: "", blocks_room: false });
  const { busy, run } = useAction();
  return <Modal title="Report a fault" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.title.trim()} onClick={async () => { const r = await run(() => post(`/api/hotels/${hotel!.id}/work-orders`, { ...f, room_id: f.room_id ? Number(f.room_id) : undefined, asset_id: f.asset_id ? Number(f.asset_id) : undefined }), "Fault reported to maintenance"); if (r) onDone(r); }}>Report</Button></>}>
    <div className="form-grid">
      <Field label="What is wrong?" wide><Input value={f.title} onChange={e => setF({ ...f, title: e.target.value })} placeholder="e.g. AC not cooling, leaking tap" /></Field>
      <Field label="Room"><Select value={f.room_id} onChange={e => setF({ ...f, room_id: e.target.value })}><option value="">— (not a room)</option>{(rooms.data?.items || []).map((r: any) => <option key={r.id} value={r.id}>{r.number}</option>)}</Select></Field>
      {can("maintenance.view") && <Field label="Equipment"><Select value={f.asset_id} onChange={e => setF({ ...f, asset_id: e.target.value })}><option value="">—</option>{(assets.data?.items || []).map((a: any) => <option key={a.id} value={a.id}>{a.code} {a.name}</option>)}</Select></Field>}
      <Field label="Priority"><Select value={f.priority} onChange={e => setF({ ...f, priority: e.target.value })}>{["urgent", "high", "normal", "low"].map(p => <option key={p} value={p}>{label(p)}</option>)}</Select></Field>
      <Field label="Details" wide><Textarea value={f.description} onChange={e => setF({ ...f, description: e.target.value })} /></Field>
      {f.room_id && <label className="check"><input type="checkbox" checked={f.blocks_room} onChange={e => setF({ ...f, blocks_room: e.target.checked })} /> Take the room out of sale until repaired (vacant rooms only)</label>}
    </div></Modal>;
}

function WorkOrderModal({ id, techs, onClose }: any) {
  const { hotel, can, user } = useAuth();
  const st = useLoad(() => get(`/api/work-orders/${id}`), [id]);
  const stores = useLoad(() => (can("maintenance.work") ? get(`/api/hotels/${hotel!.id}/stores`).catch(() => ({ items: [] })) : Promise.resolve({ items: [] })), [hotel?.id]);
  const items = useLoad(() => (can("maintenance.work") ? get(`/api/hotels/${hotel!.id}/inventory/items`).catch(() => ({ items: [] })) : Promise.resolve({ items: [] })), [hotel?.id]);
  const [note, setNote] = useState("");
  const [modal, setModal] = useState<string | null>(null);
  const [part, setPart] = useState({ item_id: "", store_id: "", quantity: "1" });
  const [done, setDone] = useState({ resolution: "", labour_hours: "", vendor_cost: "" });
  const { busy, run } = useAction();
  const w = st.data;
  const move = async (status: string, extra: any = {}) => { if (await run(() => post(`/api/work-orders/${id}/status`, { status, ...extra }), `Marked ${label(status)}`)) { setModal(null); st.reload(); } };
  const mine = w && (w.assigned_to === user!.id || !w.assigned_to);
  const worker = can("maintenance.manage") || (can("maintenance.work") && mine);
  return <Modal title={w ? `${w.number} — ${w.title}` : "Work order"} width={760} onClose={onClose}>
    <Loadable state={st}>{w => <>
      <div className="row gap-s wrap mb"><Pill s={WO_PILL[w.status]} text={label(w.status)} /><Pill s={PRIO_PILL[w.priority]} text={label(w.priority)} />
        <span className="small muted">{w.asset ? `${w.asset.code} ${w.asset.name} · ${w.asset.location || ""}` : ""}{w.room ? ` Room ${w.room.number} (${label(w.room.service_status)})` : ""} · reported by {w.reported_by_name} {fmtDateTime(w.created_at)} · due {fmtDate(w.due_date)}</span></div>
      {w.description && <p className="pre small">{w.description}</p>}
      {can("maintenance.manage") && !["completed", "verified", "cancelled"].includes(w.status) && <div className="form-grid">
        <Field label="Assigned technician"><Select value={w.assigned_to || ""} onChange={async e => { if (await run(() => post(`/api/work-orders/${id}/assign`, { user_id: e.target.value ? Number(e.target.value) : null }), "Assigned")) st.reload(); }}>
          <option value="">Unassigned</option>{techs.map((t: any) => <option key={t.id} value={t.id}>{t.full_name}</option>)}</Select></Field></div>}
      <div className="row gap-s wrap mt">
        {["open", "assigned", "on_hold"].includes(w.status) && worker && <Button busy={busy} onClick={() => move("in_progress")}>Start work</Button>}
        {w.status === "in_progress" && worker && <><Button kind="gold" onClick={() => setModal("complete")}>Complete</Button><Button kind="ghost" onClick={() => setModal("hold")}>On hold</Button></>}
        {w.status === "in_progress" && can("maintenance.work") && <Button kind="secondary" onClick={() => setModal("part")}>Issue spare part</Button>}
        {w.status === "completed" && can("maintenance.manage") && w.assigned_to !== user!.id && <><Button kind="gold" busy={busy} onClick={() => move("verified")}>Verify & close</Button><Button kind="ghost" onClick={() => setModal("reopen")}>Reopen</Button></>}
        {["open", "assigned", "on_hold"].includes(w.status) && can("maintenance.manage") && <Button kind="danger" onClick={() => setModal("cancel")}>Cancel</Button>}
      </div>
      {w.resolution && <p className="note">Resolution: {w.resolution}</p>}
      {w.parts.length > 0 && <><h4>Spare parts</h4><Table rows={w.parts} cols={[{ h: "Item", r: p => p.item_name }, { h: "Qty", r: p => `${p.quantity} ${p.unit}` }, { h: "Store", r: p => p.store_name }, { h: "Cost", r: p => money(p.value, hotel!.currency), cls: "num" }]} /></>}
      <p className="small muted">Parts {money(w.parts_cost, hotel!.currency)} · vendor {money(w.vendor_cost, hotel!.currency)} · labour {w.labour_hours} h</p>
      <h4>Notes</h4>{w.notes.map((n: any) => <p key={n.id} className="small"><b>{n.by_name}</b> · {fmtDateTime(n.created_at)}<br />{n.note}</p>)}
      <div className="row gap-s"><Input value={note} onChange={e => setNote(e.target.value)} placeholder="Add a progress note" />
        <Button kind="secondary" disabled={!note.trim()} onClick={async () => { if (await run(() => post(`/api/work-orders/${id}/notes`, { note }), "Note added")) { setNote(""); st.reload(); } }}>Add</Button></div>
      {modal === "complete" && <Modal title="Complete work order" onClose={() => setModal(null)} footer={<><Button kind="secondary" onClick={() => setModal(null)}>Cancel</Button>
        <Button kind="gold" disabled={!done.resolution.trim()} onClick={() => move("completed", { resolution: done.resolution, labour_hours: Number(done.labour_hours || 0), vendor_cost: toMinor(done.vendor_cost || "0") })}>Complete</Button></>}>
        <Field label="What was done (required)" wide><Textarea value={done.resolution} onChange={e => setDone({ ...done, resolution: e.target.value })} /></Field>
        <div className="form-grid"><Field label="Labour hours"><Input type="number" value={done.labour_hours} onChange={e => setDone({ ...done, labour_hours: e.target.value })} /></Field>
          <Field label="External vendor cost"><Input inputMode="decimal" value={done.vendor_cost} onChange={e => setDone({ ...done, vendor_cost: e.target.value })} /></Field></div></Modal>}
      {modal === "part" && <Modal title="Issue a spare part" onClose={() => setModal(null)} footer={<><Button kind="secondary" onClick={() => setModal(null)}>Cancel</Button>
        <Button disabled={!part.item_id || !part.store_id} onClick={async () => { if (await run(() => post(`/api/work-orders/${id}/parts`, { ...part, item_id: Number(part.item_id), store_id: Number(part.store_id) }), "Part issued")) { setModal(null); st.reload(); } }}>Issue</Button></>}>
        <div className="form-grid"><Field label="Store"><Select value={part.store_id} onChange={e => setPart({ ...part, store_id: e.target.value })}><option value="">Select…</option>{(stores.data?.items || []).map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
          <Field label="Item"><Select value={part.item_id} onChange={e => setPart({ ...part, item_id: e.target.value })}><option value="">Select…</option>{(items.data?.items || []).map((i: any) => <option key={i.id} value={i.id}>{i.name} ({i.on_hand} {i.unit})</option>)}</Select></Field>
          <Field label="Quantity"><Input inputMode="decimal" value={part.quantity} onChange={e => setPart({ ...part, quantity: e.target.value })} /></Field></div></Modal>}
      {["hold", "cancel", "reopen"].includes(modal || "") && <RejectModal title={modal === "hold" ? "Put on hold" : modal === "cancel" ? "Cancel work order" : "Reopen — not fixed"} onClose={() => setModal(null)}
        onReject={(n: string) => move(modal === "hold" ? "on_hold" : modal === "cancel" ? "cancelled" : "in_progress", { note: n })} />}
    </>}</Loadable></Modal>;
}

function Assets() {
  const { hotel, can } = useAuth();
  const [f, setF] = useState({ category: "", q: "" });
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/assets`, f), [hotel?.id, f.category, f.q]);
  const [sel, setSel] = useState<number | null>(null);
  const [create, setCreate] = useState(false);
  const cur = hotel!.currency;
  return <Loadable state={st}>{d => <Card title={<div className="row gap-s"><Input placeholder="Search…" value={f.q} onChange={e => setF({ ...f, q: e.target.value })} />
    <Select value={f.category} onChange={e => setF({ ...f, category: e.target.value })}><option value="">All categories</option>{d.categories.map((c: string) => <option key={c} value={c}>{label(c)}</option>)}</Select></div>}
    actions={can("maintenance.manage") && <Button onClick={() => setCreate(true)}>Register asset</Button>} pad={false}>
    <Table rows={d.items} onRow={a => setSel(a.id)} empty="No assets" cols={[{ h: "Code", r: a => a.code }, { h: "Asset", r: a => <><b>{a.name}</b><div className="tiny muted">{label(a.category)} · {a.location || ""}</div></> },
      { h: "Next service", r: a => fmtDate(a.next_service) }, { h: "Open orders", r: a => a.open_work_orders || "", cls: "num" },
      { h: "Warranty", r: a => a.warranty_until ? (a.warranty_active ? `to ${fmtDate(a.warranty_until)}` : "expired") : "—" },
      { h: "Book value", r: a => a.book_value != null ? money(a.book_value, cur) : <span className="muted">not capitalised</span>, cls: "num" },
      { h: "Status", r: a => <Pill s={a.status === "operational" ? "approved" : a.status === "retired" ? "cancelled" : "maintenance"} text={label(a.status)} /> }]} />
    {sel && <AssetModal id={sel} onClose={() => { setSel(null); st.reload(); }} />}
    {create && <AssetCreate categories={d.categories} onClose={() => setCreate(false)} onDone={() => { setCreate(false); st.reload(); }} />}
  </Card>}</Loadable>;
}

function AssetCreate({ categories, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const methods = useLoad(() => get(`/api/hotels/${hotel!.id}/payment-methods`), [hotel?.id]);
  const [f, setF] = useState<any>({ name: "", category: categories[0], location: "", serial_no: "", manufacturer: "", purchase_date: "", purchase_cost: "", useful_life_months: 60, warranty_until: "", funding: "" });
  const { busy, run } = useAction();
  return <Modal title="Register asset" width={700} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.name} onClick={async () => { const b: any = { ...f, purchase_cost: toMinor(f.purchase_cost || "0"), useful_life_months: Number(f.useful_life_months), funding: f.funding || undefined };
      for (const k of ["purchase_date", "warranty_until"]) if (!b[k]) delete b[k]; if (await run(() => post(`/api/hotels/${hotel!.id}/assets`, b), "Asset registered")) onDone(); }}>Save</Button></>}>
    <div className="form-grid">
      <Field label="Name" wide><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Category"><Select value={f.category} onChange={e => setF({ ...f, category: e.target.value })}>{categories.map((c: string) => <option key={c} value={c}>{label(c)}</option>)}</Select></Field>
      <Field label="Location"><Input value={f.location} onChange={e => setF({ ...f, location: e.target.value })} /></Field>
      <Field label="Serial no."><Input value={f.serial_no} onChange={e => setF({ ...f, serial_no: e.target.value })} /></Field>
      <Field label="Manufacturer"><Input value={f.manufacturer} onChange={e => setF({ ...f, manufacturer: e.target.value })} /></Field>
      <Field label="Purchase date"><Input type="date" value={f.purchase_date} onChange={e => setF({ ...f, purchase_date: e.target.value })} /></Field>
      <Field label="Cost"><Input inputMode="decimal" value={f.purchase_cost} onChange={e => setF({ ...f, purchase_cost: e.target.value })} /></Field>
      <Field label="Useful life (months)"><Input type="number" value={f.useful_life_months} onChange={e => setF({ ...f, useful_life_months: e.target.value })} /></Field>
      <Field label="Warranty until"><Input type="date" value={f.warranty_until} onChange={e => setF({ ...f, warranty_until: e.target.value })} /></Field>
      <Field label="Capitalise in the books" hint="Posts Dr Property, Plant & Equipment"><Select value={f.funding} onChange={e => setF({ ...f, funding: e.target.value })}><option value="">No (register only)</option>
        <option value="opening">Existing asset (opening balance)</option>{(methods.data?.items || []).filter((m: any) => ["cash", "bank_transfer"].includes(m.kind)).map((m: any) => <option key={m.id} value={m.id}>Bought now — paid by {m.name}</option>)}</Select></Field>
    </div></Modal>;
}

function AssetModal({ id, onClose }: any) {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/assets/${id}`), [id]);
  const [sched, setSched] = useState(false);
  const [s, setS] = useState({ title: "", frequency_days: 30, next_due: new Date().toISOString().slice(0, 10), checklist: "" });
  const { busy, run } = useAction();
  const cur = hotel!.currency;
  return <Modal title={st.data ? `${st.data.code} — ${st.data.name}` : "Asset"} width={760} onClose={onClose}><Loadable state={st}>{a => <>
    <dl className="dl"><dt>Category</dt><dd>{label(a.category)}</dd><dt>Location</dt><dd>{a.location || "—"}</dd><dt>Serial / make</dt><dd>{a.serial_no || "—"} {a.manufacturer || ""}</dd>
      <dt>Purchased</dt><dd>{fmtDate(a.purchase_date)} · {money(a.purchase_cost, cur)}</dd>{a.capitalised ? <><dt>Book value</dt><dd>{money(a.purchase_cost - a.accumulated_depreciation, cur)} (depreciated {money(a.accumulated_depreciation, cur)})</dd></> : null}
      <dt>Maintenance cost</dt><dd>{money(a.maintenance_cost, cur)} · downtime {a.downtime_hours} h</dd></dl>
    <h4>Preventive schedules</h4><Table rows={a.schedules} empty="No schedules" cols={[{ h: "Task", r: x => x.title }, { h: "Every", r: x => `${x.frequency_days} days` }, { h: "Last done", r: x => fmtDate(x.last_done) }, { h: "Next due", r: x => fmtDate(x.next_due) }, { h: "Assigned", r: x => x.assigned_to_name || "—" }]} />
    {can("maintenance.manage") && (sched ? <div className="form-grid"><Field label="Task"><Input value={s.title} onChange={e => setS({ ...s, title: e.target.value })} /></Field>
      <Field label="Every (days)"><Input type="number" value={s.frequency_days} onChange={e => setS({ ...s, frequency_days: Number(e.target.value) })} /></Field>
      <Field label="First due"><Input type="date" value={s.next_due} onChange={e => setS({ ...s, next_due: e.target.value })} /></Field>
      <Button className="self-end" busy={busy} disabled={!s.title} onClick={async () => { if (await run(() => post(`/api/assets/${id}/schedules`, s), "Schedule added")) { setSched(false); st.reload(); } }}>Add</Button></div>
      : <button className="link small" onClick={() => setSched(true)}>+ Add preventive schedule</button>)}
    <h4>Maintenance history</h4><Table rows={a.work_orders} empty="None" cols={[{ h: "Order", r: w => w.number }, { h: "Task", r: w => w.title }, { h: "Status", r: w => label(w.status) }, { h: "Cost", r: w => money(w.parts_cost + w.vendor_cost, cur), cls: "num" }]} />
    {a.depreciation.length > 0 && <><h4>Depreciation</h4><Table rows={a.depreciation} cols={[{ h: "Period", r: x => x.period }, { h: "Amount", r: x => money(x.amount, cur), cls: "num" }]} /></>}
  </>}</Loadable></Modal>;
}

function MaintSummary() {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/maintenance/summary`), [hotel?.id]);
  const { busy, run } = useAction();
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  return <Loadable state={st}>{d => <div className="stack">
    <div className="kpis"><Kpi title="Open orders" value={d.open} tone="navy" /><Kpi title="Overdue" value={d.overdue} /><Kpi title={`Completed since ${fmtDate(d.from)}`} value={d.completed} />
      <Kpi title="Avg. hours to complete" value={d.avg_hours_to_complete ?? "—"} /><Kpi title="Maintenance cost" value={money(d.cost, hotel!.currency)} tone="gold" /></div>
    <div className="grid-2"><Card title="Preventive work due in 30 days" pad={false}><Table rows={d.upcoming_preventive} empty="Nothing due" cols={[{ h: "Due", r: x => fmtDate(x.next_due) }, { h: "Asset", r: x => x.asset_name }, { h: "Task", r: x => x.title }]} /></Card>
      <Card title="Cost by equipment category" pad={false}><Table rows={d.by_category} empty="No costs yet" cols={[{ h: "Category", r: x => label(x.category) }, { h: "Orders", r: x => x.orders, cls: "num" }, { h: "Cost", r: x => money(x.cost, hotel!.currency), cls: "num" }]} /></Card></div>
    {can("accounting.post_manual") && <Card title="Depreciation"><div className="row gap-s"><Input type="month" value={period} onChange={e => setPeriod(e.target.value)} />
      <Button busy={busy} onClick={() => run(() => post(`/api/hotels/${hotel!.id}/assets/depreciate`, { period }), "Depreciation posted (or already done for this month)")}>Post depreciation</Button></div>
      <p className="muted small">Straight-line over each capitalised asset's useful life; posted once per asset per month.</p></Card>}
  </div>}</Loadable>;
}

// ======================================================================== Security
export function Security({ q }: { q: URLSearchParams }) {
  const { can } = useAuth();
  const tabs = [...(can("security.view") ? [{ id: "incidents", label: "Incidents" }, { id: "visitors", label: "Visitors & contractors" }] : []),
    ...(can("lostfound.manage") ? [{ id: "lost", label: "Lost & found" }] : []), { id: "contacts", label: "Emergency contacts" }, ...(can("security.view") ? [{ id: "access", label: "Access log" }] : [])];
  const [tab, setTab] = useState(q.get("tab") || tabs[0].id);
  useEffect(() => { const t = q.get("tab"); if (t) setTab(t); }, [q.get("tab")]);
  const [report, setReport] = useState(false);
  return <div className="page">
    <div className="page-h"><div><h1>Security</h1><p className="muted">Incidents, visitors, lost property and emergency information</p></div>
      {can("security.report") && <Button kind="danger" onClick={() => setReport(true)}>Report an incident</Button>}</div>
    <Tabs tabs={tabs} value={tab} onChange={setTab} />
    {tab === "incidents" && <Incidents />}{tab === "visitors" && <Visitors />}{tab === "lost" && <LostFound />}{tab === "contacts" && <Contacts />}{tab === "access" && <AccessLog />}
    {report && <IncidentModal onClose={() => setReport(false)} onDone={() => setReport(false)} />}
  </div>;
}

function IncidentModal({ onClose, onDone }: any) {
  const { hotel } = useAuth();
  const now = new Date(); now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  const [f, setF] = useState({ occurred_at: now.toISOString().slice(0, 16), location: "", category: "other", severity: "medium", description: "", persons_involved: "", actions_taken: "", restricted: false });
  const { busy, run } = useAction();
  return <Modal title="Report a security incident" width={680} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button kind="danger" busy={busy} disabled={!f.location || !f.description} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/incidents`, f), "Incident recorded")) onDone(); }}>Record</Button></>}>
    <div className="form-grid">
      <Field label="When"><Input type="datetime-local" value={f.occurred_at} onChange={e => setF({ ...f, occurred_at: e.target.value })} /></Field>
      <Field label="Where"><Input value={f.location} onChange={e => setF({ ...f, location: e.target.value })} /></Field>
      <Field label="Category"><Select value={f.category} onChange={e => setF({ ...f, category: e.target.value })}>{["theft", "assault", "fire", "medical", "trespass", "damage", "fraud", "harassment", "suspicious", "safety_hazard", "noise", "other"].map(c => <option key={c} value={c}>{label(c)}</option>)}</Select></Field>
      <Field label="Severity"><Select value={f.severity} onChange={e => setF({ ...f, severity: e.target.value })}>{["low", "medium", "high", "critical"].map(c => <option key={c} value={c}>{label(c)}</option>)}</Select></Field>
      <Field label="What happened" wide><Textarea value={f.description} onChange={e => setF({ ...f, description: e.target.value })} /></Field>
      <Field label="People involved" wide><Input value={f.persons_involved} onChange={e => setF({ ...f, persons_involved: e.target.value })} /></Field>
      <Field label="Action taken" wide><Input value={f.actions_taken} onChange={e => setF({ ...f, actions_taken: e.target.value })} /></Field>
      <label className="check"><input type="checkbox" checked={f.restricted} onChange={e => setF({ ...f, restricted: e.target.checked })} /> Sensitive — restrict to senior security staff (automatic for assault and harassment)</label>
    </div></Modal>;
}

function Incidents() {
  const { hotel, can } = useAuth();
  const [status, setStatus] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/incidents`, { status }), [hotel?.id, status]);
  const [sel, setSel] = useState<number | null>(null);
  return <Loadable state={st}>{d => <Card title={<Select value={status} onChange={e => setStatus(e.target.value)}><option value="">All</option>{["open", "investigating", "resolved", "closed"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select>} pad={false}>
    <div className="row gap-s wrap pad">{Object.entries(d.by_category).map(([k, v]) => <span key={k} className="chip">{label(k)}: <b>{String(v)}</b></span>)}</div>
    <Table rows={d.items} onRow={i => setSel(i.id)} empty="No incidents" cols={[{ h: "Incident", r: i => <><b>{i.number}</b>{i.restricted ? <> <Pill s="rejected" text="Restricted" /></> : null}</> },
      { h: "When", r: i => fmtDateTime(i.occurred_at) }, { h: "Where", r: i => i.location }, { h: "Category", r: i => label(i.category) },
      { h: "Severity", r: i => <Pill s={{ low: "cancelled", medium: "pending", high: "maintenance", critical: "rejected" }[i.severity as string] || "grey"} text={label(i.severity)} /> },
      { h: "Reported by", r: i => i.reported_by_name }, { h: "Status", r: i => <Pill s={i.status === "open" ? "pending" : i.status === "investigating" ? "in_progress" : "approved"} text={label(i.status)} /> }]} />
    {sel && <IncidentDetail id={sel} onClose={() => { setSel(null); st.reload(); }} />}
  </Card>}</Loadable>;
}

function IncidentDetail({ id, onClose }: any) {
  const { can } = useAuth();
  const st = useLoad(() => get(`/api/incidents/${id}`), [id]);
  const [f, setF] = useState({ note: "", status: "", resolution: "", police_reference: "" });
  const { busy, run } = useAction();
  return <Modal title={st.data ? `${st.data.number} — ${label(st.data.category)}` : "Incident"} width={720} onClose={onClose}><Loadable state={st}>{i => <>
    <dl className="dl"><dt>When / where</dt><dd>{fmtDateTime(i.occurred_at)} · {i.location}</dd><dt>Severity</dt><dd>{label(i.severity)}</dd><dt>Reported by</dt><dd>{i.reported_by_name}</dd>
      <dt>People</dt><dd>{i.persons_involved || "—"}</dd><dt>Action taken</dt><dd>{i.actions_taken || "—"}</dd><dt>Police ref.</dt><dd>{i.police_reference || "—"}</dd><dt>Status</dt><dd>{label(i.status)}</dd></dl>
    <p className="pre">{i.description}</p>{i.resolution && <p className="note">Resolution: {i.resolution}</p>}
    <h4>Investigation notes</h4>{i.notes.map((n: any) => <p key={n.id} className="small"><b>{n.by_name}</b> · {fmtDateTime(n.created_at)}<br />{n.note}</p>)}
    {can("security.manage") && i.status !== "closed" && <div className="form-grid">
      <Field label="Note" wide><Textarea value={f.note} onChange={e => setF({ ...f, note: e.target.value })} /></Field>
      <Field label="Status"><Select value={f.status} onChange={e => setF({ ...f, status: e.target.value })}><option value="">(no change)</option>{["investigating", "resolved", "closed"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select></Field>
      <Field label="Police reference"><Input value={f.police_reference} onChange={e => setF({ ...f, police_reference: e.target.value })} /></Field>
      {["resolved", "closed"].includes(f.status) && <Field label="Resolution" wide><Textarea value={f.resolution} onChange={e => setF({ ...f, resolution: e.target.value })} /></Field>}
      <Button busy={busy} onClick={async () => { const b: any = {}; for (const [k, v] of Object.entries(f)) if (v) b[k] = v; if (await run(() => post(`/api/incidents/${id}/update`, b), "Updated")) { setF({ note: "", status: "", resolution: "", police_reference: "" }); st.reload(); } }}>Save</Button>
    </div>}</>}</Loadable></Modal>;
}

function Visitors() {
  const { hotel, can } = useAuth();
  const [onSite, setOnSite] = useState(true);
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/visitors`, onSite ? { on_site: 1 } : { date: new Date().toISOString().slice(0, 10) }), [hotel?.id, onSite]);
  const [f, setF] = useState({ kind: "visitor", name: "", phone: "", company: "", id_type: "", id_number: "", host: "", purpose: "", badge_no: "", vehicle_plate: "" });
  const [adding, setAdding] = useState(false);
  const { busy, run } = useAction();
  return <Loadable state={st}>{d => <Card title={<label className="check"><input type="checkbox" checked={onSite} onChange={e => setOnSite(e.target.checked)} /> On site now ({d.on_site})</label>}
    actions={can("security.manage") && <Button onClick={() => setAdding(true)}>Sign in visitor</Button>} pad={false}>
    <Table rows={d.items} empty="No visitors" cols={[{ h: "Name", r: v => <><b>{v.name}</b><div className="tiny muted">{label(v.kind)}{v.company ? ` · ${v.company}` : ""}</div></> }, { h: "Host / purpose", r: v => `${v.host || ""} ${v.purpose ? "— " + v.purpose : ""}` },
      { h: "ID", r: v => v.id_type ? `${v.id_type} ${v.id_number || ""}` : "—" }, { h: "Badge", r: v => v.badge_no || "—" }, { h: "In", r: v => fmtDateTime(v.time_in) }, { h: "Out", r: v => v.time_out ? fmtDateTime(v.time_out) : "" },
      { h: "", r: v => !v.time_out && can("security.manage") && <Button kind="secondary" onClick={async () => { if (await run(() => post(`/api/visitors/${v.id}/sign-out`, {}), "Signed out")) st.reload(); }}>Sign out</Button> }]} />
    {adding && <Modal title="Sign in" width={680} onClose={() => setAdding(false)} footer={<><Button kind="secondary" onClick={() => setAdding(false)}>Cancel</Button>
      <Button busy={busy} disabled={!f.name} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/visitors`, f), "Signed in")) { setAdding(false); st.reload(); } }}>Sign in</Button></>}>
      <div className="form-grid"><Field label="Type"><Select value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}><option value="visitor">Visitor</option><option value="contractor">Contractor</option><option value="delivery">Delivery</option></Select></Field>
        {(["name", "phone", "company", "id_type", "id_number", "host", "purpose", "badge_no", "vehicle_plate"] as const).map(k => <Field key={k} label={label(k)}><Input value={(f as any)[k]} onChange={e => setF({ ...f, [k]: e.target.value })} /></Field>)}</div></Modal>}
  </Card>}</Loadable>;
}

function LostFound() {
  const { hotel } = useAuth();
  const [status, setStatus] = useState("stored");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/lost-found`, { status }), [hotel?.id, status]);
  const [log, setLog] = useState(false);
  const [rel, setRel] = useState<any>(null);
  const [f, setF] = useState({ description: "", category: "other", location: "", stored_location: "" });
  const [r, setR] = useState({ outcome: "returned", claimant_name: "", claimant_contact: "", claimant_id_checked: false });
  const { busy, run } = useAction();
  return <Loadable state={st}>{d => <Card title={<Select value={status} onChange={e => setStatus(e.target.value)}>{["stored", "returned", "disposed", "donated"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select>}
    actions={<Button onClick={() => setLog(true)}>Log found item</Button>} pad={false}>
    <Table rows={d.items} empty="Nothing here" cols={[{ h: "No.", r: l => l.number }, { h: "Item", r: l => <><b>{l.description}</b>{l.valuable ? <> <Pill s="maintenance" text="Valuable" /></> : null}<div className="tiny muted">{label(l.category)}</div></> },
      { h: "Found", r: l => <>{fmtDateTime(l.found_at)}<div className="tiny muted">{l.location}{l.room_number ? ` (room ${l.room_number})` : ""} · {l.found_by_name}</div></> },
      { h: "Stored", r: l => l.stored_location }, { h: "Keep until", r: l => <span className={l.due_for_disposal ? "danger" : ""}>{fmtDate(l.dispose_after)}</span> },
      { h: "Outcome", r: l => l.status === "stored" ? <Button kind="secondary" onClick={() => setRel(l)}>Release</Button> : `${label(l.status)}${l.claimant_name ? ` to ${l.claimant_name}` : ""}` }]} />
    {log && <Modal title="Log a found item" onClose={() => setLog(false)} footer={<><Button kind="secondary" onClick={() => setLog(false)}>Cancel</Button>
      <Button busy={busy} disabled={!f.description || !f.location} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/lost-found`, f), "Item logged")) { setLog(false); st.reload(); } }}>Log</Button></>}>
      <div className="form-grid"><Field label="Description" wide><Input value={f.description} onChange={e => setF({ ...f, description: e.target.value })} /></Field>
        <Field label="Category"><Select value={f.category} onChange={e => setF({ ...f, category: e.target.value })}>{d.categories.map((c: string) => <option key={c} value={c}>{label(c)}</option>)}</Select></Field>
        <Field label="Where found"><Input value={f.location} onChange={e => setF({ ...f, location: e.target.value })} /></Field>
        <Field label="Stored at"><Input value={f.stored_location} onChange={e => setF({ ...f, stored_location: e.target.value })} placeholder="Default: lost property store / safe for valuables" /></Field></div></Modal>}
    {rel && <Modal title={`Release ${rel.number}`} onClose={() => setRel(null)} footer={<><Button kind="secondary" onClick={() => setRel(null)}>Cancel</Button>
      <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/lost-found/${rel.id}/release`, r), "Released")) { setRel(null); st.reload(); } }}>Release</Button></>}>
      <div className="form-grid"><Field label="Outcome"><Select value={r.outcome} onChange={e => setR({ ...r, outcome: e.target.value })}><option value="returned">Returned to owner</option><option value="disposed">Disposed</option><option value="donated">Donated</option></Select></Field>
        {r.outcome === "returned" && <><Field label="Claimant name"><Input value={r.claimant_name} onChange={e => setR({ ...r, claimant_name: e.target.value })} /></Field>
          <Field label="Contact"><Input value={r.claimant_contact} onChange={e => setR({ ...r, claimant_contact: e.target.value })} /></Field>
          <label className="check"><input type="checkbox" checked={r.claimant_id_checked} onChange={e => setR({ ...r, claimant_id_checked: e.target.checked })} /> Identity checked (required for valuables)</label></>}</div></Modal>}
  </Card>}</Loadable>;
}

function Contacts() {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/emergency-contacts`), [hotel?.id]);
  const [rows, setRows] = useState<any[] | null>(null);
  const { busy, run } = useAction();
  return <Loadable state={st}>{d => <Card title="Emergency contacts" actions={can("security.manage") && !rows && <Button kind="secondary" onClick={() => setRows(d.items.map((x: any) => ({ ...x })))}>Edit</Button>} pad={false}>
    {!rows ? <Table rows={d.items} empty="No contacts set" cols={[{ h: "Name", r: x => <b>{x.name}</b> }, { h: "Role", r: x => x.role }, { h: "Phone", r: x => <a href={`tel:${x.phone}`}>{x.phone}</a> }, { h: "Notes", r: x => x.notes || "" }]} /> :
      <div className="pad">{rows.map((x, i) => <div key={i} className="form-grid tender">{["name", "role", "phone", "notes"].map(k => <Field key={k} label={label(k)}><Input value={x[k] || ""} onChange={e => setRows(rows.map((y, j) => j === i ? { ...y, [k]: e.target.value } : y))} /></Field>)}
        <button className="link danger small self-end" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</button></div>)}
        <button className="link small" onClick={() => setRows([...rows, { name: "", role: "", phone: "" }])}>+ Add contact</button>
        <div className="row gap-s mt"><Button kind="secondary" onClick={() => setRows(null)}>Cancel</Button><Button busy={busy} onClick={async () => { if (await run(() => put(`/api/hotels/${hotel!.id}/emergency-contacts`, { items: rows }), "Saved")) { setRows(null); st.reload(); } }}>Save</Button></div></div>}
  </Card>}</Loadable>;
}

function AccessLog() {
  const { hotel } = useAuth();
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/access-events`, { date }), [hotel?.id, date]);
  return <Loadable state={st}>{d => <Card title={<Input type="date" value={date} onChange={e => setDate(e.target.value)} />} pad={false}>
    {!d.integration_configured && <p className="note">No door-lock / access-control system is connected yet. Set EHMS_ACCESS_API_TOKEN and point the lock system at /api/integrations/access-events (see the deployment guide).</p>}
    <Table rows={d.items} empty="No access events" cols={[{ h: "Time", r: e => fmtDateTime(e.occurred_at) }, { h: "Door", r: e => e.door }, { h: "Event", r: e => label(e.event) }, { h: "Credential", r: e => e.credential || "—" }, { h: "Person", r: e => e.person || "—" }, { h: "Source", r: e => e.source }]} /></Card>}</Loadable>;
}

// ======================================================================== Events
export function Events() {
  const { hotel, can } = useAuth();
  const [tab, setTab] = useState("upcoming");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/events`, tab === "upcoming" ? { from: new Date().toISOString().slice(0, 10) } : {}), [hotel?.id, tab]);
  const [sel, setSel] = useState<number | null>(null);
  const [create, setCreate] = useState(false);
  const cur = hotel!.currency;
  return <div className="page">
    <div className="page-h"><div><h1>Events & banqueting</h1><p className="muted">Venues, enquiries, quotations, deposits and invoicing</p></div>{can("events.manage") && <Button onClick={() => setCreate(true)}>New enquiry</Button>}</div>
    <Tabs tabs={[{ id: "upcoming", label: "Upcoming" }, { id: "all", label: "All events" }, { id: "calendar", label: "Venue calendar" }, { id: "summary", label: "Revenue & profit" }, ...(can("events.manage") ? [{ id: "venues", label: "Venues" }] : [])]} value={tab} onChange={setTab} />
    {["upcoming", "all"].includes(tab) && <Card pad={false}><Loadable state={st}>{d => <Table rows={d.items} onRow={e => setSel(e.id)} empty="No events" cols={[{ h: "Event", r: e => <><b>{e.title}</b><div className="tiny muted">{e.number} · {label(e.event_type)}</div></> },
      { h: "When", r: e => `${fmtDateTime(e.start_at)}` }, { h: "Venue", r: e => e.venue_names || "—" }, { h: "Client", r: e => <>{e.client_name}<div className="tiny muted">{e.company || ""}</div></> },
      { h: "Guests", r: e => e.expected_guests, cls: "num" }, { h: "Value", r: e => money(e.total, cur), cls: "num" },
      { h: "Status", r: e => <Pill s={{ enquiry: "enquiry", tentative: "tentative", confirmed: "confirmed", completed: "approved", cancelled: "cancelled" }[e.status as string] || "grey"} text={label(e.status)} /> }]} />}</Loadable></Card>}
    {tab === "calendar" && <VenueCalendar onOpen={setSel} />}
    {tab === "summary" && <EventSummary onOpen={setSel} />}
    {tab === "venues" && <Venues />}
    {sel && <EventModal id={sel} onClose={() => { setSel(null); st.reload(); }} />}
    {create && st.data && <NewEvent types={st.data.types} onClose={() => setCreate(false)} onDone={(id: number) => { setCreate(false); st.reload(); setSel(id); }} />}
  </div>;
}

function NewEvent({ types, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const venues = useLoad(() => get(`/api/hotels/${hotel!.id}/venues`), [hotel?.id]);
  const d0 = new Date(); d0.setDate(d0.getDate() + 14); const day = d0.toISOString().slice(0, 10);
  const [f, setF] = useState<any>({ title: "", event_type: types[0], client_name: "", client_phone: "", client_email: "", company: "", start_at: `${day}T10:00`, end_at: `${day}T17:00`, expected_guests: 50, venue_id: "", notes: "", deposit_required: "" });
  const { busy, run } = useAction();
  const go = async () => {
    const body: any = { ...f, deposit_required: toMinor(f.deposit_required || "0"), venues: f.venue_id ? [{ venue_id: Number(f.venue_id), start_at: f.start_at, end_at: f.end_at }] : [] };
    const r = await run(() => post(`/api/hotels/${hotel!.id}/events`, body), "Enquiry created");
    if (r) onDone(r.id);
  };
  return <Modal title="New event enquiry" width={720} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button busy={busy} disabled={!f.title || !f.client_name} onClick={go}>Create</Button></>}>
    <div className="form-grid">
      <Field label="Event title" wide><Input value={f.title} onChange={e => setF({ ...f, title: e.target.value })} /></Field>
      <Field label="Type"><Select value={f.event_type} onChange={e => setF({ ...f, event_type: e.target.value })}>{types.map((t: string) => <option key={t} value={t}>{label(t)}</option>)}</Select></Field>
      <Field label="Expected guests"><Input type="number" value={f.expected_guests} onChange={e => setF({ ...f, expected_guests: Number(e.target.value) })} /></Field>
      <Field label="Starts"><Input type="datetime-local" value={f.start_at} onChange={e => setF({ ...f, start_at: e.target.value })} /></Field>
      <Field label="Ends"><Input type="datetime-local" value={f.end_at} onChange={e => setF({ ...f, end_at: e.target.value })} /></Field>
      <Field label="Venue"><Select value={f.venue_id} onChange={e => setF({ ...f, venue_id: e.target.value })}><option value="">Choose later</option>{(venues.data?.items || []).filter((v: any) => v.active).map((v: any) => <option key={v.id} value={v.id}>{v.name} (up to {Math.max(v.capacity_theatre, v.capacity_banquet, v.capacity_classroom)})</option>)}</Select></Field>
      <Field label="Deposit required"><Input inputMode="decimal" value={f.deposit_required} onChange={e => setF({ ...f, deposit_required: e.target.value })} /></Field>
      <Field label="Client name"><Input value={f.client_name} onChange={e => setF({ ...f, client_name: e.target.value })} /></Field>
      <Field label="Company"><Input value={f.company} onChange={e => setF({ ...f, company: e.target.value })} /></Field>
      <Field label="Phone"><Input value={f.client_phone} onChange={e => setF({ ...f, client_phone: e.target.value })} /></Field>
      <Field label="Email"><Input value={f.client_email} onChange={e => setF({ ...f, client_email: e.target.value })} /></Field>
      <Field label="Notes" wide><Textarea value={f.notes} onChange={e => setF({ ...f, notes: e.target.value })} /></Field>
    </div></Modal>;
}

function EventModal({ id, onClose }: any) {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/events/${id}`), [id]);
  const venues = useLoad(() => get(`/api/hotels/${hotel!.id}/venues`), [hotel?.id]);
  const emps = useLoad(() => (can("events.manage") ? get(`/api/hotels/${hotel!.id}/employees`).catch(() => ({ items: [] })) : Promise.resolve({ items: [] })), [hotel?.id]);
  const [item, setItem] = useState({ kind: "catering", description: "", quantity: "1", unit_price: "" });
  const [slot, setSlot] = useState({ venue_id: "", start_at: "", end_at: "" });
  const [cost, setCost] = useState({ description: "", amount: "" });
  const [staff, setStaff] = useState({ employee_id: "", role: "" });
  const [cancel, setCancel] = useState(false);
  const { busy, run } = useAction();
  const cur = hotel!.currency;
  const set = (r: any) => r && st.setData(r);
  const e = st.data;
  const editable = e && !e.invoiced_at && !["completed", "cancelled"].includes(e.status) && can("events.manage");
  return <Modal title={e ? `${e.number} — ${e.title}` : "Event"} width={880} onClose={onClose}><Loadable state={st}>{e => <>
    <div className="row gap-s wrap mb"><Pill s={{ enquiry: "enquiry", tentative: "tentative", confirmed: "confirmed", completed: "approved", cancelled: "cancelled" }[e.status as string] || "grey"} text={label(e.status)} />
      <span className="small muted">{label(e.event_type)} · {fmtDateTime(e.start_at)} → {fmtDateTime(e.end_at)} · {e.expected_guests} guests · {e.client_name}{e.company ? ` (${e.company})` : ""} {e.client_phone || ""}</span></div>
    <div className="row gap-s wrap">
      {can("events.manage") && e.status === "enquiry" && <Button kind="secondary" busy={busy} onClick={async () => set(await run(() => post(`/api/events/${id}/status`, { status: "tentative" }), "Venue held (tentative)"))}>Hold (tentative)</Button>}
      {can("events.manage") && ["enquiry", "tentative"].includes(e.status) && <Button kind="gold" busy={busy} onClick={async () => set(await run(() => post(`/api/events/${id}/status`, { status: "confirmed" }), "Event confirmed — folio opened"))}>Confirm</Button>}
      {can("events.invoice") && e.status === "confirmed" && !e.invoiced_at && <Button kind="gold" busy={busy} onClick={async () => { if (confirm("Post all quotation lines to the event folio?")) set(await run(() => post(`/api/events/${id}/invoice`, {}), "Invoiced to the event folio")); }}>Invoice</Button>}
      {can("events.manage") && e.status === "confirmed" && e.invoiced_at && <Button busy={busy} onClick={async () => set(await run(() => post(`/api/events/${id}/status`, { status: "completed" }), "Event completed"))}>Mark completed</Button>}
      {e.folio_id && <a className="btn btn-secondary" href={`#/folio/${e.folio_id}`}>Folio {e.folio_number} (deposits & payments)</a>}
      <Button kind="secondary" onClick={() => openFile(`/api/events/${id}/quotation.pdf`, `${e.number}.pdf`, true)}>{e.invoiced_at ? "Invoice PDF" : "Quotation PDF"}</Button>
      {can("events.manage") && !["completed", "cancelled"].includes(e.status) && <Button kind="danger" onClick={() => setCancel(true)}>Cancel event</Button>}
    </div>
    <div className="kpis mt"><Kpi title="Quotation total" value={money(e.totals.total, cur)} tone="navy" sub={`net ${money(e.totals.net, cur)}`} /><Kpi title="Deposit required" value={money(e.deposit_required, cur)} />
      <Kpi title="Paid" value={money(e.totals.paid, cur)} /><Kpi title="Profit (net − direct costs)" value={money(e.totals.profit, cur)} sub={!e.totals.costs ? "no direct costs recorded yet" : e.totals.margin_pct != null ? `${e.totals.margin_pct}% margin` : ""} tone="gold" /></div>
    <h4>Venues</h4><Table rows={e.venues} empty="No venue booked" cols={[{ h: "Venue", r: v => v.venue_name }, { h: "From", r: v => fmtDateTime(v.start_at) }, { h: "To", r: v => fmtDateTime(v.end_at) },
      { h: "", r: v => editable && <button className="link small danger" onClick={async () => set(await run(() => api("DELETE", `/api/event-venues/${v.id}`), "Removed"))}>Remove</button> }]} />
    {editable && <div className="form-grid tender"><Field label="Venue"><Select value={slot.venue_id} onChange={x => setSlot({ ...slot, venue_id: x.target.value })}><option value="">Select…</option>{(venues.data?.items || []).map((v: any) => <option key={v.id} value={v.id}>{v.name}</option>)}</Select></Field>
      <Field label="From"><Input type="datetime-local" value={slot.start_at || e.start_at} onChange={x => setSlot({ ...slot, start_at: x.target.value })} /></Field>
      <Field label="To"><Input type="datetime-local" value={slot.end_at || e.end_at} onChange={x => setSlot({ ...slot, end_at: x.target.value })} /></Field>
      <Button className="self-end" kind="secondary" disabled={!slot.venue_id} onClick={async () => { const r = await run(() => post(`/api/events/${id}/venues`, { venue_id: Number(slot.venue_id), start_at: slot.start_at || e.start_at, end_at: slot.end_at || e.end_at }), "Venue added"); if (r) { set(r); setSlot({ venue_id: "", start_at: "", end_at: "" }); } }}>Add venue</Button></div>}
    <h4>Quotation</h4><Table rows={e.items} empty="No lines yet" cols={[{ h: "Item", r: i => <>{i.description}<div className="tiny muted">{label(i.kind)}</div></> }, { h: "Qty", r: i => i.quantity, cls: "num" },
      { h: "Unit price", r: i => money(i.unit_price, cur), cls: "num" }, { h: "Amount", r: i => money(i.quantity * i.unit_price, cur), cls: "num" },
      { h: "", r: i => editable && <button className="link small danger" onClick={async () => set(await run(() => api("DELETE", `/api/event-items/${i.id}`), "Removed"))}>Remove</button> }]} />
    <p className="right small">Service charge {money(e.totals.service_charge, cur)} · taxes {money(e.totals.tax, cur)} · <b>total {money(e.totals.total, cur)}</b></p>
    {editable && <div className="form-grid tender"><Field label="Kind"><Select value={item.kind} onChange={x => setItem({ ...item, kind: x.target.value })}>{["venue", "catering", "beverage", "equipment", "decoration", "accommodation", "service", "other"].map(k => <option key={k} value={k}>{label(k)}</option>)}</Select></Field>
      <Field label="Description"><Input value={item.description} onChange={x => setItem({ ...item, description: x.target.value })} /></Field>
      <Field label="Qty"><Input type="number" value={item.quantity} onChange={x => setItem({ ...item, quantity: x.target.value })} /></Field>
      <Field label="Unit price"><Input inputMode="decimal" value={item.unit_price} onChange={x => setItem({ ...item, unit_price: x.target.value })} /></Field>
      <Button className="self-end" kind="secondary" disabled={!item.description || isNaN(toMinor(item.unit_price))} onClick={async () => { const r = await run(() => post(`/api/events/${id}/items`, { ...item, quantity: Number(item.quantity), unit_price: toMinor(item.unit_price) }), "Line added"); if (r) { set(r); setItem({ ...item, description: "", unit_price: "" }); } }}>Add line</Button></div>}
    <div className="grid-2">
      <div><h4>Direct costs</h4><Table rows={e.costs} empty="None recorded" cols={[{ h: "Cost", r: x => x.description }, { h: "Amount", r: x => money(x.amount, cur), cls: "num" }]} />
        {can("events.manage") && <div className="row gap-s mt"><Input value={cost.description} onChange={x => setCost({ ...cost, description: x.target.value })} placeholder="e.g. hired chairs" />
          <Input className="sm" inputMode="decimal" value={cost.amount} onChange={x => setCost({ ...cost, amount: x.target.value })} placeholder="Amount" />
          <Button kind="secondary" disabled={!cost.description || !(toMinor(cost.amount) > 0)} onClick={async () => { const r = await run(() => post(`/api/events/${id}/costs`, { ...cost, amount: toMinor(cost.amount) }), "Cost recorded"); if (r) { set(r); setCost({ description: "", amount: "" }); } }}>Add</Button></div>}</div>
      <div><h4>Staff</h4><Table rows={e.staff} empty="No staff allocated" cols={[{ h: "Employee", r: x => x.employee }, { h: "Role", r: x => x.role }]} />
        {can("events.manage") && <div className="row gap-s mt"><Select value={staff.employee_id} onChange={x => setStaff({ ...staff, employee_id: x.target.value })}><option value="">Employee…</option>{(emps.data?.items || []).map((m: any) => <option key={m.id} value={m.id}>{m.first_name} {m.last_name}</option>)}</Select>
          <Input value={staff.role} onChange={x => setStaff({ ...staff, role: x.target.value })} placeholder="Role" />
          <Button kind="secondary" disabled={!staff.employee_id || !staff.role} onClick={async () => { const r = await run(() => post(`/api/events/${id}/staff`, { employee_id: Number(staff.employee_id), role: staff.role }), "Allocated"); if (r) { set(r); setStaff({ employee_id: "", role: "" }); } }}>Add</Button></div>}</div>
    </div>
    {cancel && <RejectModal title={`Cancel ${e.number}`} onClose={() => setCancel(false)} onReject={async (reason: string) => { const r = await run(() => post(`/api/events/${id}/status`, { status: "cancelled", reason }), "Event cancelled"); if (r) { setCancel(false); set(r); } }} />}
  </>}</Loadable></Modal>;
}

function VenueCalendar({ onOpen }: any) {
  const { hotel } = useAuth();
  const today = new Date().toISOString().slice(0, 10);
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/venues/calendar`, { from: today }), [hotel?.id]);
  return <Loadable state={st}>{d => <div className="stack">{d.venues.map((v: any) => <Card key={v.id} title={v.name} pad={false}>
    <Table rows={d.bookings.filter((b: any) => b.venue_id === v.id)} onRow={b => onOpen(b.event_id)} empty="Free for the next 30 days" cols={[{ h: "From", r: b => fmtDateTime(b.start_at) }, { h: "To", r: b => fmtDateTime(b.end_at) },
      { h: "Event", r: b => <><b>{b.title}</b><div className="tiny muted">{b.number} · {b.client_name}</div></> }, { h: "Guests", r: b => b.expected_guests, cls: "num" }, { h: "Status", r: b => <Pill s={b.status} text={label(b.status)} /> }]} /></Card>)}</div>}</Loadable>;
}

function EventSummary({ onOpen }: any) {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/events/summary`), [hotel?.id]);
  const cur = hotel!.currency;
  return <Loadable state={st}>{d => <div className="stack">
    <div className="kpis">{Object.entries(d.pipeline).map(([k, v]) => <Kpi key={k} title={label(k)} value={String(v)} />)}<Kpi title="Confirmed revenue (net)" value={money(d.revenue, cur)} tone="navy" /><Kpi title="Profit" value={money(d.profit, cur)} tone="gold" /></div>
    <Card pad={false}><Table rows={d.events} onRow={e => onOpen(e.id)} cols={[{ h: "Event", r: e => <><b>{e.title}</b><div className="tiny muted">{e.number}</div></> }, { h: "Date", r: e => fmtDate(e.start_at.slice(0, 10)) }, { h: "Status", r: e => label(e.status) },
      { h: "Net revenue", r: e => money(e.net, cur), cls: "num" }, { h: "Costs", r: e => money(e.costs, cur), cls: "num" }, { h: "Profit", r: e => money(e.profit, cur), cls: "num" }, { h: "Margin", r: e => e.margin_pct != null ? `${e.margin_pct}%` : "—", cls: "num" }]} /></Card></div>}</Loadable>;
}

function Venues() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/venues`), [hotel?.id]);
  const [edit, setEdit] = useState<any>(null);
  const { busy, run } = useAction();
  const cur = hotel!.currency;
  return <Loadable state={st}>{d => <Card title="Venues" actions={<Button onClick={() => setEdit({})}>Add venue</Button>} pad={false}>
    <Table rows={d.items} onRow={v => setEdit(v)} cols={[{ h: "Venue", r: v => <><b>{v.name}</b><div className="tiny muted">{v.code} · {v.facilities || ""}</div></> }, { h: "Theatre", r: v => v.capacity_theatre, cls: "num" }, { h: "Banquet", r: v => v.capacity_banquet, cls: "num" },
      { h: "Classroom", r: v => v.capacity_classroom, cls: "num" }, { h: "Hourly", r: v => money(v.hourly_rate, cur), cls: "num" }, { h: "Daily", r: v => money(v.daily_rate, cur), cls: "num" }, { h: "Status", r: v => <Pill s={v.active ? "active" : "deactivated"} /> }]} />
    {edit && <VenueModal v={edit} onClose={() => setEdit(null)} onSave={async (f: any) => { if (await run(() => post(`/api/hotels/${hotel!.id}/venues`, f), "Venue saved")) { setEdit(null); st.reload(); } }} busy={busy} />}
  </Card>}</Loadable>;
}

function VenueModal({ v, onClose, onSave, busy }: any) {
  const [f, setF] = useState<any>({ code: v.code || "", name: v.name || "", capacity_theatre: v.capacity_theatre || 0, capacity_banquet: v.capacity_banquet || 0, capacity_classroom: v.capacity_classroom || 0,
    area_sqm: v.area_sqm || "", hourly_rate: v.hourly_rate != null ? fromMinor(v.hourly_rate) : "", daily_rate: v.daily_rate != null ? fromMinor(v.daily_rate) : "", facilities: v.facilities || "", active: v.active ?? 1 });
  return <Modal title={v.id ? `Edit ${v.name}` : "Add venue"} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.code || !f.name} onClick={() => onSave({ ...f, hourly_rate: toMinor(f.hourly_rate || "0"), daily_rate: toMinor(f.daily_rate || "0"), area_sqm: f.area_sqm ? Number(f.area_sqm) : undefined, active: !!f.active })}>Save</Button></>}>
    <div className="form-grid">{!v.id && <Field label="Code"><Input value={f.code} onChange={e => setF({ ...f, code: e.target.value })} /></Field>}
      <Field label="Name"><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      {["capacity_theatre", "capacity_banquet", "capacity_classroom", "area_sqm"].map(k => <Field key={k} label={label(k)}><Input type="number" value={f[k]} onChange={e => setF({ ...f, [k]: Number(e.target.value) })} /></Field>)}
      <Field label="Hourly rate"><Input inputMode="decimal" value={f.hourly_rate} onChange={e => setF({ ...f, hourly_rate: e.target.value })} /></Field>
      <Field label="Daily rate"><Input inputMode="decimal" value={f.daily_rate} onChange={e => setF({ ...f, daily_rate: e.target.value })} /></Field>
      <Field label="Facilities" wide><Input value={f.facilities} onChange={e => setF({ ...f, facilities: e.target.value })} /></Field>
      {v.id && <label className="check"><input type="checkbox" checked={!!f.active} onChange={e => setF({ ...f, active: e.target.checked ? 1 : 0 })} /> Active</label>}</div></Modal>;
}
