import React, { useState } from "react";
import { GuestLoyalty } from "./CRM";
import { DocumentsPanel } from "./Documents";
import { ApiError, fmtDate, get, label, money, patch, post } from "../api";
import { navigate, useAuth } from "../state";
import { Button, Card, Field, Input, Loadable, Modal, Pill, Table, Textarea, errText, useAction, useLoad, useToast } from "../ui";

export default function Guests() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [term, setTerm] = useState("");
  const [vip, setVip] = useState(false);
  const [creating, setCreating] = useState(false);
  const st = useLoad(() => get("/api/guests", { search: term, vip: vip ? 1 : "" }), [term, vip]);
  return (
    <div className="page">
      <div className="page-h"><div><h1>Guests</h1><p className="muted">Central guest profiles and stay history</p></div>
        {can("guests.manage") && <Button onClick={() => setCreating(true)}>New guest</Button>}</div>
      <form className="row gap-s mb" onSubmit={e => { e.preventDefault(); setTerm(q); }}>
        <Input placeholder="Search name, email, phone or company" value={q} onChange={e => setQ(e.target.value)} style={{ flex: 1 }} />
        <label className="check"><input type="checkbox" checked={vip} onChange={e => setVip(e.target.checked)} /> VIP only</label>
        <Button type="submit">Search</Button></form>
      <Card pad={false}><Loadable state={st}>{d => <Table rows={d.items} onRow={g => navigate(`/guests/${g.id}`)} cols={[
        { h: "Name", r: g => <><b>{g.first_name} {g.last_name}</b> {g.vip && <Pill s="vip_hold" text="VIP" />}</> },
        { h: "Email", r: g => g.email || "—" }, { h: "Phone", r: g => g.phone || "—" }, { h: "Company", r: g => g.company || "—" },
        { h: "Stays", r: g => g.stays }, { h: "Nationality", r: g => g.nationality || "—" }]} />}</Loadable></Card>
      {creating && <GuestForm onClose={() => setCreating(false)} onSaved={g => navigate(`/guests/${g.id}`)} />}
    </div>
  );
}

function GuestForm({ guest, onClose, onSaved }: { guest?: any; onClose: () => void; onSaved: (g: any) => void }) {
  const { can } = useAuth();
  const idOk = can("guests.identity.view");
  const [f, setF] = useState<any>(guest ? { ...guest } : { first_name: "", last_name: "", email: "", phone: "", nationality: "Nigerian", company: "", address: "", preferences: "", notes: "", vip: false, marketing_consent: false, id_type: "", id_number: "" });
  const [dups, setDups] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const fields = ["first_name", "last_name", "email", "phone", "nationality", "company", "preferences", "notes", "vip", "marketing_consent", ...(idOk ? ["address", "id_type", "id_number", "date_of_birth"] : [])];
  async function save(force = false) {
    setBusy(true);
    const body: any = {};
    fields.forEach(k => { if (f[k] !== undefined && !(typeof f[k] === "string" && f[k].startsWith("••••"))) body[k] = f[k]; });
    try {
      const g = guest ? await patch(`/api/guests/${guest.id}`, body) : await post("/api/guests", { ...body, force });
      toast("success", "Guest saved"); onSaved(g);
    } catch (e) {
      if (e instanceof ApiError && e.details?.duplicates) setDups(e.details.duplicates); else toast("error", errText(e));
    } finally { setBusy(false); }
  }
  const inp = (k: string, l: string, type = "text") => <Field label={l}><Input type={type} value={f[k] || ""} onChange={e => setF({ ...f, [k]: e.target.value })} /></Field>;
  return <Modal title={guest ? "Edit guest" : "New guest"} onClose={onClose} width={680} footer={<><Button kind="secondary" onClick={onClose}>Close</Button><Button busy={busy} onClick={() => save(false)}>Save</Button></>}>
    <div className="form-grid">
      {inp("first_name", "First name")}{inp("last_name", "Last name")}{inp("email", "Email", "email")}{inp("phone", "Phone")}{inp("nationality", "Nationality")}{inp("company", "Company")}
      {idOk && <>{inp("address", "Address")}{inp("date_of_birth", "Date of birth", "date")}{inp("id_type", "ID type")}{inp("id_number", "ID number")}</>}
      <Field label="Preferences" wide><Textarea value={f.preferences || ""} onChange={e => setF({ ...f, preferences: e.target.value })} /></Field>
      <Field label="Internal notes" wide><Textarea value={f.notes || ""} onChange={e => setF({ ...f, notes: e.target.value })} /></Field>
      <label className="check"><input type="checkbox" checked={!!f.vip} onChange={e => setF({ ...f, vip: e.target.checked })} /> VIP guest</label>
      <label className="check"><input type="checkbox" checked={!!f.marketing_consent} onChange={e => setF({ ...f, marketing_consent: e.target.checked })} /> Consents to marketing messages</label>
    </div>
    {dups && <div className="note mt">Possible duplicates: {dups.map(d => <a key={d.id} href={`#/guests/${d.id}`} onClick={onClose}> {d.first_name} {d.last_name} ({d.email || d.phone})</a>)}
      <div className="mt"><Button kind="secondary" onClick={() => save(true)}>Create anyway</Button></div></div>}
  </Modal>;
}

export function GuestDetail({ id }: { id: number }) {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/guests/${id}`), [id]);
  const [edit, setEdit] = useState(false);
  return <div className="page"><Loadable state={st}>{g => <>
    <div className="page-h"><div><h1>{g.first_name} {g.last_name} {g.vip && <Pill s="vip_hold" text="VIP" />} {g.repeat_guest && <Pill s="confirmed" text="Repeat guest" />}</h1>
      <p className="muted">{g.completed_stays} completed stay(s) · lifetime spend {money(g.total_spend, hotel!.currency)}</p></div>
      <div className="row gap-s">{can("reservations.create") && <Button onClick={() => navigate("/reservations/new")}>New reservation</Button>}
        {can("guests.manage") && <Button kind="secondary" onClick={() => setEdit(true)}>Edit</Button>}</div></div>
    <div className="grid-2">
      <Card title="Profile"><dl className="dl">
        <dt>Email</dt><dd>{g.email || "—"}</dd><dt>Phone</dt><dd>{g.phone || "—"}</dd><dt>Nationality</dt><dd>{g.nationality || "—"}</dd>
        <dt>Company</dt><dd>{g.company || "—"}</dd><dt>Address</dt><dd>{g.address || "—"}</dd><dt>ID</dt><dd>{g.id_type ? `${g.id_type} ${g.id_number || ""}` : "—"}</dd>
        <dt>Marketing</dt><dd>{g.marketing_consent ? "Consented" : "No consent"}</dd><dt>Since</dt><dd>{fmtDate(g.created_at)}</dd>
      </dl></Card>
      <GuestLoyalty guestId={g.id} />
      <Card title="Preferences & notes"><p>{g.preferences || <span className="muted">No preferences recorded</span>}</p>{g.notes && <p className="note">{g.notes}</p>}</Card>
    </div>
    <DocumentsPanel entityType="guest" entityId={g.id} defaultCategory="identity" />
    <Card title="Stay history" pad={false}><Table rows={g.stays} onRow={s => navigate(`/reservations/${s.id}`)} cols={[
      { h: "Reference", r: s => s.reference }, { h: "Hotel", r: s => s.hotel_name }, { h: "Dates", r: s => `${fmtDate(s.arrival)} → ${fmtDate(s.departure)}` },
      { h: "Room", r: s => s.room_number ? `${s.room_number} (${s.room_type_name})` : s.room_type_name }, { h: "Status", r: s => <Pill s={s.status} /> }]} empty="No stays yet" /></Card>
    {edit && <GuestForm guest={g} onClose={() => setEdit(false)} onSaved={() => { setEdit(false); st.reload(); }} />}
  </>}</Loadable></div>;
}
