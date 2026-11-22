import React, { useEffect, useState } from "react";
import { fmtDateTime, fromMinor, get, label, money, patch, post, toMinor } from "../api";
import { useAuth } from "../state";
import { Button, Card, Field, Input, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, useAction, useLoad } from "../ui";
import { CancellationPolicies, CostingSetting } from "./Billing";

export default function HotelSettings() {
  const [tab, setTab] = useState("profile");
  return <div className="page">
    <div className="page-h"><div><h1>Hotel settings</h1><p className="muted">Profile, policies, taxes, payment methods and messaging</p></div></div>
    <Tabs tabs={[{ id: "profile", label: "Profile & policies" }, { id: "cancellation", label: "Cancellation policies" }, { id: "taxes", label: "Taxes & charges" }, { id: "payments", label: "Payment methods" },
      { id: "stock", label: "Stock costing" }, { id: "messages", label: "Message log" }]} value={tab} onChange={setTab} />
    {tab === "cancellation" && <CancellationPolicies />}{tab === "stock" && <CostingSetting />}
    {tab === "profile" && <Profile />}{tab === "taxes" && <Taxes />}{tab === "payments" && <PaymentMethods />}{tab === "messages" && <Messages />}
  </div>;
}

const PROFILE_FIELDS: [string, string, string?][] = [["name", "Hotel name"], ["legal_name", "Legal name"], ["registration_number", "Registration (RC) number"], ["category", "Category"],
  ["star_rating", "Star rating", "number"], ["floors", "Floors", "number"], ["address", "Address"], ["city", "City"], ["state", "State"], ["country", "Country"],
  ["phone", "Phone"], ["email", "Email", "email"], ["website", "Website"], ["emergency_contact", "Emergency contact"], ["check_in_time", "Check-in time", "time"],
  ["check_out_time", "Check-out time", "time"], ["currency", "Currency (ISO)"], ["timezone", "Time zone"]];

function Profile() {
  const { hotel, refresh } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}`), [hotel?.id]);
  const [f, setF] = useState<any>(null);
  useEffect(() => { if (st.data) setF({ ...st.data, service_charge_pct: (st.data.service_charge_bp || 0) / 100 }); }, [st.data]);
  const { busy, run } = useAction();
  if (!f) return <Loadable state={st}>{() => null}</Loadable>;
  return <Card title="Hotel profile" actions={<Button busy={busy} onClick={async () => {
    const body: any = {};
    PROFILE_FIELDS.forEach(([k, , t]) => { body[k] = t === "number" ? (f[k] === "" || f[k] == null ? null : Number(f[k])) : f[k]; });
    ["cancellation_policy", "reservation_policy", "terms", "amenities"].forEach(k => (body[k] = f[k]));
    body.service_charge_bp = Math.round(Number(f.service_charge_pct || 0) * 100);
    if (await run(() => patch(`/api/hotels/${hotel!.id}`, body), "Hotel profile saved")) { st.reload(); refresh(); }
  }}>Save</Button>}>
    <div className="form-grid">
      {PROFILE_FIELDS.map(([k, l, t]) => <Field key={k} label={l}><Input type={t || "text"} value={f[k] ?? ""} onChange={e => setF({ ...f, [k]: e.target.value })} /></Field>)}
      <Field label="Service charge (%)" hint="Applied to room and F&B net revenue"><Input type="number" step="0.5" min={0} max={50} value={f.service_charge_pct} onChange={e => setF({ ...f, service_charge_pct: e.target.value })} /></Field>
      <Field label="Amenities & facilities" wide><Textarea value={f.amenities || ""} onChange={e => setF({ ...f, amenities: e.target.value })} /></Field>
      <Field label="Cancellation policy" wide><Textarea value={f.cancellation_policy || ""} onChange={e => setF({ ...f, cancellation_policy: e.target.value })} /></Field>
      <Field label="Reservation policy" wide><Textarea value={f.reservation_policy || ""} onChange={e => setF({ ...f, reservation_policy: e.target.value })} /></Field>
      <Field label="Terms & conditions (printed on invoices)" wide><Textarea value={f.terms || ""} onChange={e => setF({ ...f, terms: e.target.value })} /></Field>
    </div>
  </Card>;
}

function Taxes() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/taxes`), [hotel?.id]);
  const [f, setF] = useState({ code: "", name: "", rate: "", applies_to: "all", is_inclusive: false, effective_from: new Date().toISOString().slice(0, 10) });
  const { busy, run } = useAction();
  return <div className="stack">
    <Card title="Tax rules" pad={false}><Loadable state={st}>{d => <Table rows={d.items} cols={[
      { h: "Code", r: t => <b>{t.code}</b> }, { h: "Name", r: t => t.name }, { h: "Rate", r: t => `${t.rate_bp / 100}%` }, { h: "Applies to", r: t => label(t.applies_to) },
      { h: "Type", r: t => (t.is_inclusive ? "Inclusive" : "Added on top") }, { h: "Effective", r: t => `${t.effective_from} → ${t.effective_to || "open"}` },
      { h: "Status", r: t => <Pill s={t.active ? "active" : "deactivated"} /> },
      { h: "", r: t => <Button kind="ghost" busy={busy} onClick={async () => { if (await run(() => patch(`/api/taxes/${t.id}`, { active: !t.active }), "Tax rule updated")) st.reload(); }}>{t.active ? "Deactivate" : "Activate"}</Button> }]} empty="No taxes configured" />}</Loadable></Card>
    <Card title="Add tax rule"><p className="small muted">Rates are never hard-coded. Confirm current statutory rates (e.g. VAT) with your tax adviser and set an effective date for any change.</p>
      <div className="form-grid">
        <Field label="Code"><Input value={f.code} onChange={e => setF({ ...f, code: e.target.value })} placeholder="VAT" /></Field>
        <Field label="Name"><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} placeholder="Value Added Tax" /></Field>
        <Field label="Rate (%)"><Input type="number" step="0.01" value={f.rate} onChange={e => setF({ ...f, rate: e.target.value })} /></Field>
        <Field label="Applies to"><Select value={f.applies_to} onChange={e => setF({ ...f, applies_to: e.target.value })}>{["all", "room", "fnb", "laundry", "events", "other"].map(a => <option key={a} value={a}>{label(a)}</option>)}</Select></Field>
        <Field label="Effective from"><Input type="date" value={f.effective_from} onChange={e => setF({ ...f, effective_from: e.target.value })} /></Field>
        <label className="check"><input type="checkbox" checked={f.is_inclusive} onChange={e => setF({ ...f, is_inclusive: e.target.checked })} /> Prices already include this tax</label>
      </div>
      <Button busy={busy} disabled={!f.code || !f.name || f.rate === ""} onClick={async () => {
        if (await run(() => post(`/api/hotels/${hotel!.id}/taxes`, { ...f, rate_bp: Math.round(Number(f.rate) * 100) }), "Tax rule added")) st.reload();
      }}>Add rule</Button></Card>
  </div>;
}

function PaymentMethods() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/payment-methods`), [hotel?.id]);
  const accts = useLoad(() => get("/api/accounts"), []);
  const [f, setF] = useState({ code: "", name: "", kind: "bank_transfer", account_id: "" });
  const { busy, run } = useAction();
  return <div className="stack">
    <Card title="Payment methods" pad={false}><Loadable state={st}>{d => <Table rows={d.items} cols={[
      { h: "Code", r: m => <b>{m.code}</b> }, { h: "Name", r: m => m.name }, { h: "Kind", r: m => label(m.kind) }, { h: "Ledger account", r: m => `${m.account_code} ${m.account_name}` },
      { h: "Status", r: m => <Pill s={m.active ? "active" : "deactivated"} /> }]} />}</Loadable></Card>
    <Card title="Add payment method"><div className="form-grid">
      <Field label="Code"><Input value={f.code} onChange={e => setF({ ...f, code: e.target.value })} placeholder="ZENITH" /></Field>
      <Field label="Name"><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} placeholder="Transfer — Zenith Bank" /></Field>
      <Field label="Kind" hint="'Online' methods are confirmed only by gateway webhooks"><Select value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}>{["cash", "bank_transfer", "card_pos", "online", "city_ledger"].map(k => <option key={k} value={k}>{label(k)}</option>)}</Select></Field>
      <Field label="Ledger account"><Select value={f.account_id} onChange={e => setF({ ...f, account_id: e.target.value })}><option value="">Select…</option>
        {(accts.data?.items || []).filter((a: any) => a.type === "asset").map((a: any) => <option key={a.id} value={a.id}>{a.code} {a.name}</option>)}</Select></Field>
    </div><Button busy={busy} disabled={!f.code || !f.name || !f.account_id} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/payment-methods`, { ...f, account_id: Number(f.account_id) }), "Payment method added")) st.reload(); }}>Add method</Button></Card>
  </div>;
}

function Messages() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/notifications`), [hotel?.id]);
  return <Card title="Outgoing messages" pad={false}><p className="small muted pad">Messages marked “Not configured” were recorded but not sent because no email/SMS/WhatsApp provider is set up (see deployment guide).</p>
    <Loadable state={st}>{d => <Table rows={d.items} cols={[{ h: "When", r: n => fmtDateTime(n.created_at) }, { h: "Channel", r: n => label(n.channel) }, { h: "To", r: n => n.recipient },
      { h: "Subject", r: n => n.subject }, { h: "Status", r: n => <Pill s={n.status} /> }]} empty="No messages yet" />}</Loadable></Card>;
}

// ------------------------------------------------------------------ rooms & rates
export function RoomSetup() {
  const { hotel } = useAuth();
  const types = useLoad(() => get(`/api/hotels/${hotel!.id}/room-types`), [hotel?.id]);
  const rooms = useLoad(() => get(`/api/hotels/${hotel!.id}/rooms`), [hotel?.id]);
  const [editType, setEditType] = useState<any>(null);
  const [newRoom, setNewRoom] = useState(false);
  const cur = hotel!.currency;
  return <div className="page">
    <div className="page-h"><div><h1>Rooms & rates</h1><p className="muted">Room categories, rate plans and room inventory</p></div>
      <div className="row gap-s"><Button kind="secondary" onClick={() => setEditType({})}>New category</Button><Button onClick={() => setNewRoom(true)}>New room</Button></div></div>
    <Card title="Room categories" pad={false}><Loadable state={types}>{d => <Table rows={d.items} onRow={t => setEditType(t)} cols={[
      { h: "Code", r: t => <b>{t.code}</b> }, { h: "Name", r: t => t.name }, { h: "Rooms", r: t => t.room_count }, { h: "Max guests", r: t => t.max_occupancy },
      { h: "Standard", r: t => money(t.base_rate, cur), cls: "num" }, { h: "Weekend", r: t => (t.weekend_rate ? money(t.weekend_rate, cur) : "—"), cls: "num" },
      { h: "Corporate", r: t => (t.corporate_rate ? money(t.corporate_rate, cur) : "—"), cls: "num" }, { h: "Extra person", r: t => money(t.extra_person_charge, cur), cls: "num" },
      { h: "Status", r: t => <Pill s={t.active ? "active" : "deactivated"} /> }]} />}</Loadable></Card>
    <Card title="Rooms" pad={false}><Loadable state={rooms}>{d => <Table rows={d.items} cols={[
      { h: "Room", r: r => <b>{r.number}</b> }, { h: "Category", r: r => r.room_type_name }, { h: "Floor", r: r => r.floor }, { h: "Wing", r: r => r.wing || "—" },
      { h: "Status", r: r => <Pill s={r.display_status} /> }]} />}</Loadable></Card>
    {editType && <TypeForm t={editType} onClose={() => setEditType(null)} onDone={() => { setEditType(null); types.reload(); }} />}
    {newRoom && <RoomForm types={types.data?.items || []} onClose={() => setNewRoom(false)} onDone={() => { setNewRoom(false); rooms.reload(); types.reload(); }} />}
  </div>;
}

function TypeForm({ t, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const isNew = !t.id;
  const [f, setF] = useState<any>({ code: t.code || "", name: t.name || "", description: t.description || "", max_occupancy: t.max_occupancy || 2, beds: t.beds || 1,
    bed_config: t.bed_config || "", size_sqm: t.size_sqm || "", amenities: t.amenities || "", image_url: t.image_url || "", active: t.active ?? 1,
    base_rate: fromMinor(t.base_rate), weekend_rate: fromMinor(t.weekend_rate), corporate_rate: fromMinor(t.corporate_rate), extra_person_charge: fromMinor(t.extra_person_charge ?? 0) });
  const { busy, run } = useAction();
  const inp = (k: string, l: string, type = "text") => <Field label={l}><Input type={type} value={f[k]} onChange={e => setF({ ...f, [k]: e.target.value })} /></Field>;
  return <Modal title={isNew ? "New room category" : `Edit ${t.name}`} width={720} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} disabled={!f.name || !f.base_rate} onClick={async () => {
      const body: any = { name: f.name, description: f.description, max_occupancy: Number(f.max_occupancy), beds: Number(f.beds), bed_config: f.bed_config,
        size_sqm: f.size_sqm ? Number(f.size_sqm) : null, amenities: f.amenities, image_url: f.image_url || null, active: f.active ? 1 : 0,
        base_rate: toMinor(f.base_rate), weekend_rate: f.weekend_rate ? toMinor(f.weekend_rate) : null, corporate_rate: f.corporate_rate ? toMinor(f.corporate_rate) : null,
        extra_person_charge: toMinor(f.extra_person_charge || 0) };
      if (isNew) body.code = f.code;
      if (await run(() => (isNew ? post(`/api/hotels/${hotel!.id}/room-types`, body) : patch(`/api/room-types/${t.id}`, body)), "Room category saved")) onDone();
    }}>Save</Button></>}>
    <div className="form-grid">
      {isNew && inp("code", "Code")}{inp("name", "Name")}{inp("max_occupancy", "Max guests", "number")}{inp("beds", "Beds", "number")}{inp("bed_config", "Bed configuration")}{inp("size_sqm", "Size (m²)", "number")}
      {inp("base_rate", "Standard rate (₦)")}{inp("weekend_rate", "Weekend rate — Fri/Sat (₦)")}{inp("corporate_rate", "Corporate rate (₦)")}{inp("extra_person_charge", "Extra person / night (₦)")}
      <Field label="Image URL"><Input value={f.image_url} onChange={e => setF({ ...f, image_url: e.target.value })} /></Field>
      <Field label="Description" wide><Textarea value={f.description} onChange={e => setF({ ...f, description: e.target.value })} /></Field>
      <Field label="Amenities" wide><Input value={f.amenities} onChange={e => setF({ ...f, amenities: e.target.value })} /></Field>
      {!isNew && <label className="check"><input type="checkbox" checked={!!f.active} onChange={e => setF({ ...f, active: e.target.checked })} /> Active (sellable)</label>}
    </div></Modal>;
}

function RoomForm({ types, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ number: "", room_type_id: "", floor: "", wing: "", name: "" });
  const { busy, run } = useAction();
  return <Modal title="New room" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} disabled={!f.number || !f.room_type_id} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/rooms`, { ...f, room_type_id: Number(f.room_type_id) }), `Room ${f.number} created`)) onDone(); }}>Create</Button></>}>
    <div className="form-grid">
      <Field label="Room number"><Input value={f.number} onChange={e => setF({ ...f, number: e.target.value })} /></Field>
      <Field label="Category"><Select value={f.room_type_id} onChange={e => setF({ ...f, room_type_id: e.target.value })}><option value="">Select…</option>{types.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select></Field>
      <Field label="Floor"><Input value={f.floor} onChange={e => setF({ ...f, floor: e.target.value })} /></Field>
      <Field label="Wing / building"><Input value={f.wing} onChange={e => setF({ ...f, wing: e.target.value })} /></Field>
    </div></Modal>;
}
