import React, { useState } from "react";
import { fmtDateTime, get, label, money, post, toMinor, fromMinor } from "../api";
import { useAuth } from "../state";
import { Button, Card, Field, Input, Kpi, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, useAction, useLoad } from "../ui";

const FLOW = ["received", "washing", "drying", "ironing", "quality_check", "ready", "delivered"];

export default function Laundry() {
  const { hotel, can } = useAuth();
  const [tab, setTab] = useState("open");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/laundry/orders`, tab === "open" ? { open: 1 } : {}), [hotel?.id, tab]);
  const prices = useLoad(() => get(`/api/hotels/${hotel!.id}/laundry/prices`), [hotel?.id]);
  const [open, setOpen] = useState<number | null>(null);
  const [creating, setCreating] = useState<string | null>(null);
  const cur = hotel!.currency;
  return <div className="page">
    <div className="page-h"><div><h1>Laundry</h1><p className="muted">Guest laundry is charged to the room folio on delivery; internal linen is tracked by department</p></div>
      {can("laundry.manage") && <div className="row gap-s"><Button onClick={() => setCreating("guest")}>Guest laundry</Button><Button kind="secondary" onClick={() => setCreating("internal")}>Linen batch</Button></div>}</div>
    {st.data && <div className="kpis">{FLOW.slice(0, 6).map(s => <Kpi key={s} title={label(s)} value={st.data.counts[s] || 0} />)}</div>}
    <Tabs tabs={[{ id: "open", label: "In process" }, { id: "all", label: "All orders" }, { id: "summary", label: "Daily summary" }, { id: "prices", label: "Price list" }]} value={tab} onChange={setTab} />
    {["open", "all"].includes(tab) && <Card pad={false}><Loadable state={st}>{d => <Table rows={d.items} onRow={o => setOpen(o.id)} empty="No laundry orders" cols={[
      { h: "Order", r: o => <><b>{o.number}</b>{o.express ? <> <Pill s="rejected" text="Express" /></> : null}</> },
      { h: "For", r: o => o.kind === "guest" ? `Room ${o.room_number} — ${o.guest}` : `Linen: ${label(o.department)}` }, { h: "Pieces", r: o => o.pieces, cls: "num" },
      { h: "Received", r: o => fmtDateTime(o.created_at) }, { h: "Amount", r: o => o.kind === "guest" ? money(o.total, cur) : "—", cls: "num" },
      { h: "Issues", r: o => o.issues ? <span className="danger">{o.issues}</span> : "" }, { h: "Status", r: o => <Pill s={o.status === "delivered" ? "approved" : o.status === "cancelled" ? "cancelled" : "in_progress"} text={label(o.status)} /> }]} />}</Loadable></Card>}
    {tab === "summary" && <Summary />}
    {tab === "prices" && <Loadable state={prices}>{p => <PriceList data={p} onChange={prices.reload} />}</Loadable>}
    {open && <OrderModal id={open} onClose={() => { setOpen(null); st.reload(); }} />}
    {creating && prices.data && <NewOrder kind={creating} prices={prices.data} onClose={() => setCreating(null)} onDone={(id: number) => { setCreating(null); st.reload(); setOpen(id); }} />}
  </div>;
}

function NewOrder({ kind, prices, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [q, setQ] = useState("");
  const inHouse = useLoad(() => (kind === "guest" ? get(`/api/hotels/${hotel!.id}/laundry/in-house`, { q }).catch(() => ({ items: [] })) : Promise.resolve({ items: [] })), [q]);
  const [f, setF] = useState<any>({ reservation_id: null, department: "housekeeping", express: false, notes: "" });
  const [lines, setLines] = useState<any[]>([{ price_id: "", description: "", service: "wash_iron", quantity: 1, condition_note: "" }]);
  const { busy, run } = useAction();
  const active = prices.items.filter((p: any) => p.active);
  const go = async () => {
    const items = lines.filter(l => l.quantity > 0 && (l.price_id || l.description)).map(l => ({ ...l, price_id: l.price_id ? Number(l.price_id) : undefined }));
    const r = await run(() => post(`/api/hotels/${hotel!.id}/laundry/orders`, { kind, ...f, items }), "Laundry order registered");
    if (r) onDone(r.id);
  };
  return <Modal title={kind === "guest" ? "Guest laundry" : "Internal linen batch"} width={760} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={kind === "guest" && !f.reservation_id} onClick={go}>Register</Button></>}>
    {kind === "guest" ? <><Field label="In-house guest (room or name)"><Input value={q} onChange={e => setQ(e.target.value)} /></Field>
      <div className="picklist">{(inHouse.data?.items || []).slice(0, 8).map((g: any) => <button key={g.reservation_id} className={f.reservation_id === g.reservation_id ? "on" : ""} onClick={() => setF({ ...f, reservation_id: g.reservation_id })}>
        <b>Room {g.room_number}</b> {g.guest}</button>)}</div></> :
      <Field label="Department"><Select value={f.department} onChange={e => setF({ ...f, department: e.target.value })}>{prices.departments.map((d: string) => <option key={d} value={d}>{label(d)}</option>)}</Select></Field>}
    {lines.map((l, i) => <div key={i} className="form-grid tender">
      <Field label="Item"><Select value={l.price_id} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, price_id: e.target.value } : x))}>
        <option value="">Other (describe)</option>{active.map((p: any) => <option key={p.id} value={p.id}>{p.item} — {label(p.service)}{kind === "guest" ? ` · ${money(p.price, hotel!.currency)}` : ""}</option>)}</Select></Field>
      {!l.price_id && <Field label="Description"><Input value={l.description} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, description: e.target.value } : x))} /></Field>}
      <Field label="Qty"><Input type="number" min={1} value={l.quantity} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, quantity: Number(e.target.value) } : x))} /></Field>
      <Field label="Condition on receipt"><Input value={l.condition_note} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, condition_note: e.target.value } : x))} placeholder="e.g. stain on collar" /></Field>
    </div>)}
    <button className="link small" onClick={() => setLines([...lines, { price_id: "", description: "", service: "wash_iron", quantity: 1, condition_note: "" }])}>+ Add item</button>
    <div className="row gap mt">{kind === "guest" && <label className="check"><input type="checkbox" checked={f.express} onChange={e => setF({ ...f, express: e.target.checked })} /> Express (+{prices.express_surcharge_bp / 100}%)</label>}</div>
    <Field label="Notes" wide><Input value={f.notes} onChange={e => setF({ ...f, notes: e.target.value })} /></Field>
  </Modal>;
}

function OrderModal({ id, onClose }: any) {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/laundry/orders/${id}`), [id]);
  const { busy, run } = useAction();
  const [issue, setIssue] = useState<any>(null);
  const o = st.data;
  const next = o && FLOW[FLOW.indexOf(o.status) + 1];
  const act = async (fn: () => Promise<any>, msg: string) => { const r = await run(fn, msg); if (r) st.setData(r); };
  return <Modal title={o ? `${o.number} — ${label(o.status)}` : "Laundry order"} width={720} onClose={onClose} footer={o && <>
    {o.status === "received" && can("laundry.manage") && <Button kind="ghost" onClick={async () => { const reason = prompt("Reason for cancelling?"); if (reason) await act(() => post(`/api/laundry/orders/${id}/status`, { status: "cancelled", reason }), "Order cancelled"); }}>Cancel order</Button>}
    <Button kind="secondary" onClick={onClose}>Close</Button>
    {next && !["delivered", "cancelled"].includes(o.status) && can("laundry.manage") && <Button kind={next === "delivered" ? "gold" : "primary"} busy={busy}
      onClick={() => act(() => post(`/api/laundry/orders/${id}/status`, { status: next }), next === "delivered" && o.kind === "guest" ? "Delivered and charged to the room" : `Moved to ${label(next)}`)}>
      {next === "delivered" ? (o.kind === "guest" ? "Deliver & charge room" : "Deliver") : `Move to ${label(next)}`}</Button>}</>}>
    <Loadable state={st}>{o => <>
      <p className="small muted">{o.kind === "guest" ? `Room ${o.reservation?.room_number} — ${o.reservation?.guest}` : `Linen batch for ${label(o.department)}`}{o.express ? " · express" : ""}{o.notes ? ` · ${o.notes}` : ""}</p>
      <div className="steps">{FLOW.map(s => <span key={s} className={FLOW.indexOf(s) <= FLOW.indexOf(o.status) ? "done" : ""}>{label(s)}</span>)}</div>
      <Table rows={o.items} cols={[{ h: "Item", r: i => <>{i.description}<div className="tiny muted">{label(i.service)}{i.condition_note ? ` · on receipt: ${i.condition_note}` : ""}</div></> },
        { h: "Qty", r: i => i.quantity, cls: "num" }, { h: "Price", r: i => o.kind === "guest" ? money(i.unit_price * i.quantity, hotel!.currency) : "—", cls: "num" },
        { h: "Outcome", r: i => i.outcome === "ok" ? "OK" : <span className="danger" title={i.outcome_note}>{label(i.outcome)}: {i.outcome_note}</span> },
        { h: "", r: i => !["delivered", "cancelled"].includes(o.status) && can("laundry.manage") && <button className="link small" onClick={() => setIssue(i)}>Report issue</button> }]} />
      {o.kind === "guest" && <p className="right"><b>Total to charge: {money(o.total, hotel!.currency)}</b> <span className="muted small">(damaged or lost items are not charged)</span></p>}
    </>}</Loadable>
    {issue && <IssueModal item={issue} onClose={() => setIssue(null)} onDone={(r: any) => { setIssue(null); st.setData(r); }} />}
  </Modal>;
}

function IssueModal({ item, onClose, onDone }: any) {
  const [f, setF] = useState({ outcome: "damaged", note: "" });
  const { busy, run } = useAction();
  return <Modal title={`Report: ${item.description}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button kind="danger" busy={busy} disabled={f.outcome !== "ok" && !f.note.trim()} onClick={async () => { const r = await run(() => post(`/api/laundry/items/${item.id}/outcome`, f), "Recorded"); if (r) onDone(r); }}>Save</Button></>}>
    <Field label="Outcome"><Select value={f.outcome} onChange={e => setF({ ...f, outcome: e.target.value })}><option value="damaged">Damaged</option><option value="lost">Lost</option><option value="ok">OK (clear issue)</option></Select></Field>
    <Field label="What happened (required)" wide><Textarea value={f.note} onChange={e => setF({ ...f, note: e.target.value })} /></Field></Modal>;
}

function Summary() {
  const { hotel } = useAuth();
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ from: today, to: today });
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/laundry/summary`, f), [hotel?.id, f.from, f.to]);
  return <Card title={<div className="row gap-s"><Input type="date" value={f.from} onChange={e => setF({ ...f, from: e.target.value })} /><Input type="date" value={f.to} onChange={e => setF({ ...f, to: e.target.value })} /></div>}>
    <Loadable state={st}>{d => <div className="stack">
      <div className="kpis"><Kpi title="Guest orders delivered" value={d.guest.orders} /><Kpi title="Laundry revenue" value={money(d.guest.revenue, hotel!.currency)} tone="gold" />
        <Kpi title="Lost / damaged items" value={d.issues.length} /></div>
      <Table rows={d.internal} empty="No internal linen batches" cols={[{ h: "Department", r: r => label(r.department) }, { h: "Batches", r: r => r.batches, cls: "num" }, { h: "Pieces", r: r => r.pieces, cls: "num" }]} />
      <Table rows={d.issues} empty="No lost or damaged items" cols={[{ h: "Order", r: r => r.number }, { h: "Item", r: r => `${r.quantity} × ${r.description}` }, { h: "Outcome", r: r => label(r.outcome) }, { h: "Note", r: r => r.outcome_note }]} />
    </div>}</Loadable></Card>;
}

function PriceList({ data, onChange }: any) {
  const { hotel, can } = useAuth();
  const [f, setF] = useState({ item: "", service: "wash_iron", price: "" });
  const { busy, run } = useAction();
  return <Card title={`Price list · express surcharge ${data.express_surcharge_bp / 100}%`} pad={false}>
    <Table rows={data.items} cols={[{ h: "Item", r: p => p.item }, { h: "Service", r: p => label(p.service) }, { h: "Price", r: p => money(p.price, hotel!.currency), cls: "num" },
      { h: "", r: p => can("laundry.manage") && <button className="link small" onClick={async () => { const v = prompt(`New price for ${p.item} (${label(p.service)})`, fromMinor(p.price)); if (v !== null && await run(() => post(`/api/hotels/${hotel!.id}/laundry/prices`, { item: p.item, service: p.service, price: toMinor(v) }), "Price updated")) onChange(); }}>Change price</button> }]} />
    {can("laundry.manage") && <div className="form-grid pad">
      <Field label="Item"><Input value={f.item} onChange={e => setF({ ...f, item: e.target.value })} /></Field>
      <Field label="Service"><Select value={f.service} onChange={e => setF({ ...f, service: e.target.value })}>{data.services.map((s: string) => <option key={s} value={s}>{label(s)}</option>)}</Select></Field>
      <Field label={`Price (${hotel!.currency})`}><Input inputMode="decimal" value={f.price} onChange={e => setF({ ...f, price: e.target.value })} /></Field>
      <Button className="self-end" busy={busy} disabled={!f.item || isNaN(toMinor(f.price))} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/laundry/prices`, { ...f, price: toMinor(f.price) }), "Price added")) { setF({ item: "", service: "wash_iron", price: "" }); onChange(); } }}>Add</Button>
    </div>}
  </Card>;
}
