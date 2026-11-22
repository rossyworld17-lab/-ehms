import React, { useState } from "react";
import { addDays, fmtDate, fromMinor, get, label, money, openFile, patch, post, toMinor } from "../api";
import { navigate, useAuth } from "../state";
import { Button, Card, Field, Input, Kpi, Loadable, Modal, Pill, Select, Table, Textarea, useAction, useLoad } from "../ui";
import { DocumentsPanel } from "./Documents";

export default function Groups() {
  const { hotel, can } = useAuth();
  const [status, setStatus] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/groups`, status ? { status } : {}), [hotel?.id, status]);
  const [adding, setAdding] = useState(false);
  return <div className="page">
    <div className="page-h"><div><h1>Groups & blocks</h1><p className="muted">Room blocks held for groups, rooming lists, pickup and master billing</p></div>
      {can("reservations.groups") && <Button onClick={() => setAdding(true)}>New group block</Button>}</div>
    <div className="row gap-s mb">{["", "tentative", "definite", "released", "completed", "cancelled"].map(s => <Button key={s} kind={s === status ? "primary" : "secondary"} onClick={() => setStatus(s)}>{s ? label(s) : "All"}</Button>)}</div>
    <Loadable state={st}>{d => <Card pad={false}><Table rows={d.items} onRow={g => navigate(`/groups/${g.id}`)} empty="No group blocks" cols={[
      { h: "Group", r: g => <><b>{g.name}</b><div className="small muted">{g.code}</div></> }, { h: "Stay", r: g => `${fmtDate(g.arrival)} → ${fmtDate(g.departure)}` },
      { h: "Cut-off", r: g => fmtDate(g.cutoff_date) }, { h: "Rooms", r: g => `${g.rooms_picked} / ${g.rooms_blocked}`, cls: "num" },
      { h: "Pickup", r: g => <div className="row gap-s"><div className="meter"><span style={{ width: `${Math.min(100, g.pickup_pct)}%` }} /></div>{g.pickup_pct}%</div> },
      { h: "Billing", r: g => label(g.billing) }, { h: "Status", r: g => <Pill s={g.status === "definite" ? "confirmed" : g.status} text={label(g.status)} /> }]} /></Card>}</Loadable>
    {adding && <NewGroup onClose={() => setAdding(false)} onDone={(id: number) => { setAdding(false); navigate(`/groups/${id}`); }} />}
  </div>;
}

function NewGroup({ onClose, onDone }: any) {
  const { hotel } = useAuth();
  const accts = useLoad(() => get(`/api/hotels/${hotel!.id}/accounts/active`).catch(() => ({ items: [] })), [hotel?.id]);
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState<any>({ name: "", arrival: addDays(today, 30), departure: addDays(today, 32), cutoff_date: addDays(today, 23), status: "tentative", billing: "individual", corporate_account_id: "", notes: "" });
  const [rooms, setRooms] = useState<Record<number, { rooms: string; rate: string }>>({});
  const types = useLoad(() => get(`/api/hotels/${hotel!.id}/availability`, { arrival: f.arrival, departure: f.departure }), [hotel?.id, f.arrival, f.departure]);
  const { busy, run } = useAction();
  const lines = Object.entries(rooms).filter(([, v]) => Number(v.rooms) > 0).map(([k, v]) => ({ room_type_id: Number(k), rooms: Number(v.rooms), rate: v.rate ? toMinor(v.rate) : undefined }));
  return <Modal title="New group block" width={720} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.name.trim() || !lines.length} onClick={async () => { const r = await run(() => post(`/api/hotels/${hotel!.id}/groups`, { ...f, corporate_account_id: f.corporate_account_id ? Number(f.corporate_account_id) : undefined, rooms: lines }), "Group block created"); if (r) onDone(r.id); }}>Create block</Button></>}>
    <div className="form-grid">
      <Field label="Group name" wide><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} placeholder="e.g. Okonkwo–Bello wedding" /></Field>
      <Field label="Arrival"><Input type="date" value={f.arrival} onChange={e => setF({ ...f, arrival: e.target.value })} /></Field>
      <Field label="Departure"><Input type="date" value={f.departure} onChange={e => setF({ ...f, departure: e.target.value })} /></Field>
      <Field label="Cut-off date" hint="Rooms not picked up are released after this date"><Input type="date" value={f.cutoff_date} onChange={e => setF({ ...f, cutoff_date: e.target.value })} /></Field>
      <Field label="Status"><Select value={f.status} onChange={e => setF({ ...f, status: e.target.value })}><option value="tentative">Tentative</option><option value="definite">Definite</option></Select></Field>
      <Field label="Billing"><Select value={f.billing} onChange={e => setF({ ...f, billing: e.target.value })}><option value="individual">Each guest pays</option><option value="master_room">Rooms to master folio</option><option value="master_all">Rooms to master; extras transferred</option></Select></Field>
      <Field label="Account (optional)"><Select value={f.corporate_account_id} onChange={e => setF({ ...f, corporate_account_id: e.target.value })}><option value="">—</option>{(accts.data?.items || []).map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>
      <Field label="Notes" wide><Textarea value={f.notes} onChange={e => setF({ ...f, notes: e.target.value })} /></Field>
    </div>
    <h4 className="mt">Rooms to hold</h4>
    <Loadable state={types}>{t => <Table rows={t.room_types} cols={[{ h: "Category", r: x => x.name }, { h: "Free every night", r: x => x.available, cls: "num" }, { h: "Rack rate", r: x => money(x.base_rate, hotel!.currency), cls: "num" },
      { h: "Rooms", r: x => <Input type="number" min={0} style={{ width: 80 }} value={rooms[x.id]?.rooms || ""} onChange={e => setRooms({ ...rooms, [x.id]: { rooms: e.target.value, rate: rooms[x.id]?.rate || "" } })} /> },
      { h: "Group rate (₦)", r: x => <Input inputMode="decimal" style={{ width: 120 }} placeholder={fromMinor(x.base_rate)} value={rooms[x.id]?.rate || ""} onChange={e => setRooms({ ...rooms, [x.id]: { rooms: rooms[x.id]?.rooms || "", rate: e.target.value } })} /> }]} />}</Loadable>
  </Modal>;
}

export function GroupDetail({ id }: { id: number }) {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/groups/${id}`), [id]);
  const [modal, setModal] = useState<string | null>(null);
  const { busy, run } = useAction();
  const cur = hotel!.currency;
  return <div className="page"><Loadable state={st}>{g => { const active = ["tentative", "definite"].includes(g.status); return <>
    <div className="page-h"><div><h1>{g.name} <Pill s={g.status === "definite" ? "confirmed" : g.status} text={label(g.status)} /></h1>
      <p className="muted">{g.code} · {fmtDate(g.arrival)} → {fmtDate(g.departure)} · cut-off {fmtDate(g.cutoff_date)}{g.account ? ` · ${g.account.name}` : ""}</p></div>
      <div className="row gap-s wrap">
        {active && can("reservations.groups") && <Button onClick={() => setModal("rooming")}>Add rooming list</Button>}
        {g.status === "tentative" && can("reservations.groups") && <Button kind="gold" busy={busy} onClick={async () => { if (await run(() => patch(`/api/groups/${id}`, { status: "definite" }), "Group is definite")) st.reload(); }}>Mark definite</Button>}
        {active && can("reservations.groups") && <Button kind="secondary" busy={busy} onClick={async () => { const r = await run(() => post(`/api/groups/${id}/release`, {}), "Unpicked rooms released"); if (r) st.reload(); }}>Release unpicked rooms</Button>}
        {!g.master_folio && g.billing !== "individual" && can("reservations.groups") && <Button kind="secondary" busy={busy} onClick={async () => { if (await run(() => post(`/api/groups/${id}/master-folio`, {}), "Master folio opened")) st.reload(); }}>Open master folio</Button>}
        <Button kind="secondary" onClick={() => openFile(`/api/groups/${id}/rooming-list.csv`, `rooming-list-${g.code}.csv`)}>Rooming list (CSV)</Button>
      </div></div>
    <div className="kpis"><Kpi title="Pickup" value={`${g.pickup_pct}%`} tone="navy" sub="room nights picked up / held" /><Kpi title="Reservations" value={g.reservations.length} />
      <Kpi title="Billing" value={label(g.billing)} />{g.master_folio && <Kpi title="Master folio" value={<a href={`#/folio/${g.master_folio.id}`}>{g.master_folio.number}</a>} sub={money(g.master_folio.balance, cur)} tone="gold" />}</div>
    <Card title="Allotment" pad={false}><Table rows={g.rooms} cols={[{ h: "Category", r: r => r.room_type }, { h: "Held", r: r => r.rooms, cls: "num" }, { h: "Picked up", r: r => r.picked_up_max, cls: "num" },
      { h: "Remaining", r: r => r.remaining, cls: "num" }, { h: "Group rate", r: r => money(r.rate, cur), cls: "num" }, { h: "Room nights", r: r => `${r.room_nights_picked} / ${r.room_nights_held}`, cls: "num" }]} /></Card>
    <Card title="Rooming list" pad={false}><Table rows={g.reservations} onRow={r => navigate(`/reservations/${r.id}`)} empty="No guests yet — add a rooming list" cols={[
      { h: "Guest", r: r => `${r.last_name}, ${r.first_name}` }, { h: "Category", r: r => r.room_type }, { h: "Room", r: r => r.room_number || "—" },
      { h: "Stay", r: r => `${fmtDate(r.arrival)} → ${fmtDate(r.departure)}` }, { h: "Guests", r: r => `${r.adults}+${r.children}` }, { h: "Status", r: r => <Pill s={r.status} /> }, { h: "Reference", r: r => r.reference }]} /></Card>
    {g.notes && <Card title="Notes"><p>{g.notes}</p></Card>}
    <DocumentsPanel entityType="group" entityId={g.id} defaultCategory="contract" title="Contracts & documents" />
    {modal === "rooming" && <RoomingList group={g} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
  </>; }}</Loadable></div>;
}

function RoomingList({ group, onClose, onDone }: any) {
  const codes = group.rooms.map((r: any) => r.room_type_code).join(", ");
  const [csv, setCsv] = useState(`first_name,last_name,email,phone,room_type,arrival,departure,adults\n`);
  const [res, setRes] = useState<any>(null);
  const { busy, run } = useAction();
  return <Modal title="Add a rooming list" width={720} onClose={onClose} footer={<><Button kind="secondary" onClick={res ? onDone : onClose}>{res ? "Done" : "Cancel"}</Button>
    {!res && <Button busy={busy} onClick={async () => { const r = await run(() => post(`/api/groups/${group.id}/rooming-list`, { csv }), "Rooming list processed"); if (r) setRes(r); }}>Create reservations</Button>}</>}>
    {!res ? <div className="stack">
      <p className="small">Paste from a spreadsheet (comma-separated, first line = headings). Room types for this block: <b>{codes}</b>. Arrival/departure default to the group's dates; email, phone and adults are optional.</p>
      <input type="file" accept=".csv,text/csv" onChange={async e => { const file = e.target.files?.[0]; if (file) setCsv(await file.text()); }} />
      <Textarea rows={10} value={csv} onChange={e => setCsv(e.target.value)} style={{ fontFamily: "monospace", fontSize: ".82rem" }} />
    </div> : <div className="stack">
      <p><b>{res.created}</b> reservation(s) created, <b>{res.failed}</b> row(s) need attention.</p>
      <Table rows={res.results} rowKey={r => r.row} cols={[{ h: "Row", r: r => r.row }, { h: "Result", r: r => r.ok ? <Pill s="confirmed" text="Created" /> : <Pill s="rejected" text="Not created" /> },
        { h: "Detail", r: r => r.ok ? `${r.guest} — ${r.reference}` : r.error }]} />
    </div>}
  </Modal>;
}
