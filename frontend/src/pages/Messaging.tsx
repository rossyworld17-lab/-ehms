import React, { useEffect, useRef, useState } from "react";
import { MdNotifications } from "react-icons/md";
import { fmtDateTime, get, label, money, patch, post, put } from "../api";
import { useAuth } from "../state";
import { Button, Card, Field, Input, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, useAction, useLoad } from "../ui";

/** Bell in the top bar: the signed-in user's in-app notifications (polls every 60 s). */
export function NotificationBell() {
  const [data, setData] = useState<any>({ items: [], unread: 0 });
  const [open, setOpen] = useState(false);
  const load = () => get("/api/notifications/mine").then(setData).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 60000); return () => clearInterval(t); }, []);
  const read = async (n: any) => { if (!n.read_at) { await post(`/api/notifications/${n.id}/read`).catch(() => {}); load(); } };
  return <div className="usermenu">
    <button className="icon-btn bell" aria-label={`Notifications (${data.unread} unread)`} onClick={() => { setOpen(o => !o); if (!open) load(); }}>
      <MdNotifications />{data.unread > 0 && <b className="badge">{data.unread}</b>}</button>
    {open && <div className="menu notif-menu" role="menu" onMouseLeave={() => setOpen(false)}>
      <div className="row between pad"><b>Notifications</b>{data.unread > 0 && <button className="link small" onClick={async () => { await post("/api/notifications/read-all"); load(); }}>Mark all read</button>}</div>
      {data.items.length ? data.items.slice(0, 15).map((n: any) => <button key={n.id} className={`notif ${n.read_at ? "" : "unread"}`} onClick={() => read(n)}>
        <b>{n.subject}</b><span>{n.body}</span><small>{fmtDateTime(n.created_at)}</small></button>) : <p className="muted small pad">You're all caught up.</p>}
    </div>}
  </div>;
}

/** Administration → Messaging: templates per event/channel, delivery log, scheduled jobs. */
export default function Messaging() {
  const [tab, setTab] = useState("templates");
  return <div className="page">
    <div className="page-h"><div><h1>Messaging</h1><p className="muted">Templates, delivery history and automated reminders</p></div></div>
    <Tabs tabs={[{ id: "templates", label: "Templates" }, { id: "log", label: "Delivery log" }]} value={tab} onChange={setTab} />
    {tab === "templates" ? <Templates /> : <DeliveryLog />}
  </div>;
}

function Templates() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/notification-templates`), [hotel?.id]);
  const [edit, setEdit] = useState<any>(null);
  return <Loadable state={st}>{d => <Card pad={false}><Table rows={d.items} cols={[{ h: "Event", r: t => <><b>{t.description}</b><div className="tiny muted">{t.code}</div></> },
    { h: "Channel", r: t => label(t.channel) }, { h: "Subject / text", r: t => <span className="small">{t.subject || t.body.slice(0, 80)}</span> },
    { h: "Provider", r: t => t.provider_configured ? <Pill s="approved" text="Configured" /> : <Pill s="not_configured" text="Not configured" /> },
    { h: "Status", r: t => <Pill s={t.active ? "active" : "deactivated"} text={t.active ? "On" : "Off"} /> },
    { h: "", r: t => <button className="link small" onClick={() => setEdit(t)}>Edit</button> }]} />
    {edit && <TemplateModal t={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); st.reload(); }} />}</Card>}</Loadable>;
}

function TemplateModal({ t, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ subject: t.subject || "", body: t.body, active: !!t.active });
  const { busy, run } = useAction();
  return <Modal title={`${t.description} — ${label(t.channel)}`} width={640} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.body.trim()} onClick={async () => { if (await run(() => put(`/api/hotels/${hotel!.id}/notification-templates`, { code: t.code, channel: t.channel, ...f }), "Template saved")) onDone(); }}>Save</Button></>}>
    {["email", "in_app"].includes(t.channel) && <Field label="Subject" wide><Input value={f.subject} onChange={e => setF({ ...f, subject: e.target.value })} /></Field>}
    <Field label="Message" wide hint="Placeholders such as {guest}, {hotel}, {reference}, {arrival}, {amount}, {link} are filled in automatically"><Textarea rows={7} value={f.body} onChange={e => setF({ ...f, body: e.target.value })} /></Field>
    <label className="check"><input type="checkbox" checked={f.active} onChange={e => setF({ ...f, active: e.target.checked })} /> Send this message</label>
  </Modal>;
}

function DeliveryLog() {
  const { hotel } = useAuth();
  const [f, setF] = useState({ status: "", channel: "" });
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/notifications`, f), [hotel?.id, f.status, f.channel]);
  const { busy, run } = useAction();
  return <Card title={<div className="row gap-s"><Select value={f.status} onChange={e => setF({ ...f, status: e.target.value })}><option value="">All statuses</option>{["queued", "sent", "failed", "not_configured"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select>
    <Select value={f.channel} onChange={e => setF({ ...f, channel: e.target.value })}><option value="">All channels</option>{["email", "sms", "whatsapp"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select></div>}
    actions={<Button kind="secondary" busy={busy} onClick={async () => { const r = await run(() => post(`/api/hotels/${hotel!.id}/notifications/run-jobs`, {})); if (r) st.reload(); }}>Run reminders & deliver now</Button>} pad={false}>
    <Loadable state={st}>{d => <><div className="row gap-s pad wrap">{Object.entries(d.counts).map(([k, v]) => <span key={k} className="chip">{label(k)}: <b>{String(v)}</b></span>)}</div>
      <Table rows={d.items} empty="No messages" cols={[{ h: "When", r: n => fmtDateTime(n.created_at) }, { h: "Channel", r: n => label(n.channel) }, { h: "To", r: n => n.recipient },
        { h: "Subject / message", r: n => <span className="small">{n.subject || n.body.slice(0, 70)}</span> }, { h: "Status", r: n => <span title={n.error || ""}><Pill s={n.status} /></span> },
        { h: "Attempts", r: n => n.attempts, cls: "num" },
        { h: "", r: n => ["failed", "not_configured"].includes(n.status) && <button className="link small" onClick={async () => { if (await run(() => post(`/api/notifications/${n.id}/retry`, {}), "Message re-queued")) st.reload(); }}>Retry</button> }]} /></>}</Loadable>
  </Card>;
}

/** Sales → Promotions: promo codes for the booking engine. */
export function Promotions() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/promo-codes`), [hotel?.id]);
  const types = useLoad(() => get(`/api/hotels/${hotel!.id}/room-types`).catch(() => ({ items: [] })), [hotel?.id]);
  const [edit, setEdit] = useState<any>(null);
  const cur = hotel!.currency;
  return <div className="page"><div className="page-h"><div><h1>Promotions</h1><p className="muted">Promo codes guests can enter on the online booking engine</p></div>
    <Button onClick={() => setEdit({})}>New promo code</Button></div>
    <Loadable state={st}>{d => <Card pad={false}><Table rows={d.items} empty="No promo codes yet" cols={[{ h: "Code", r: p => <b className="mono">{p.code}</b> }, { h: "Description", r: p => p.description || "" },
      { h: "Discount", r: p => p.discount_type === "percent" ? `${p.value}% of room` : money(p.value, cur) }, { h: "Valid (arrival dates)", r: p => `${p.valid_from} → ${p.valid_to}` },
      { h: "Room", r: p => p.room_type_name || "Any" }, { h: "Min nights", r: p => p.min_nights, cls: "num" }, { h: "Used", r: p => `${p.uses}${p.max_uses ? " / " + p.max_uses : ""}`, cls: "num" },
      { h: "Status", r: p => <Pill s={p.active ? "active" : "deactivated"} /> }, { h: "", r: p => <button className="link small" onClick={() => setEdit(p)}>Edit</button> }]} /></Card>}</Loadable>
    {edit && <PromoModal p={edit} types={types.data?.items || []} onClose={() => setEdit(null)} onDone={() => { setEdit(null); st.reload(); }} />}
  </div>;
}

function PromoModal({ p, types, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ code: p.code || "", description: p.description || "", discount_type: p.discount_type || "percent", value: p.value != null ? String(p.discount_type === "amount" ? p.value / 100 : p.value) : "10",
    valid_from: p.valid_from || today, valid_to: p.valid_to || today, min_nights: p.min_nights || 1, max_uses: p.max_uses ?? "", room_type_id: p.room_type_id || "", active: p.active ?? 1 });
  const { busy, run } = useAction();
  const go = async () => {
    const body: any = { ...f, value: f.discount_type === "amount" ? Math.round(Number(f.value) * 100) : Number(f.value), max_uses: f.max_uses === "" ? null : Number(f.max_uses),
      room_type_id: f.room_type_id ? Number(f.room_type_id) : null, min_nights: Number(f.min_nights), active: !!f.active };
    if (p.id) delete body.code;
    if (await run(() => p.id ? patch(`/api/promo-codes/${p.id}`, body) : post(`/api/hotels/${hotel!.id}/promo-codes`, body), "Promo code saved")) onDone();
  };
  return <Modal title={p.id ? `Edit ${p.code}` : "New promo code"} width={640} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button busy={busy} disabled={!p.id && !f.code} onClick={go}>Save</Button></>}>
    <div className="form-grid">
      {!p.id && <Field label="Code"><Input value={f.code} onChange={e => setF({ ...f, code: e.target.value.toUpperCase() })} /></Field>}
      <Field label="Description" wide><Input value={f.description} onChange={e => setF({ ...f, description: e.target.value })} /></Field>
      <Field label="Type"><Select value={f.discount_type} onChange={e => setF({ ...f, discount_type: e.target.value })}><option value="percent">Percentage of room price</option><option value="amount">Fixed amount</option></Select></Field>
      <Field label={f.discount_type === "percent" ? "Percent" : `Amount (${hotel!.currency})`}><Input inputMode="decimal" value={f.value} onChange={e => setF({ ...f, value: e.target.value })} /></Field>
      <Field label="Arrivals from"><Input type="date" value={f.valid_from} onChange={e => setF({ ...f, valid_from: e.target.value })} /></Field>
      <Field label="Arrivals until"><Input type="date" value={f.valid_to} onChange={e => setF({ ...f, valid_to: e.target.value })} /></Field>
      <Field label="Minimum nights"><Input type="number" value={f.min_nights} onChange={e => setF({ ...f, min_nights: Number(e.target.value) })} /></Field>
      <Field label="Maximum uses" hint="Blank = unlimited"><Input type="number" value={f.max_uses} onChange={e => setF({ ...f, max_uses: e.target.value })} /></Field>
      <Field label="Room category"><Select value={f.room_type_id} onChange={e => setF({ ...f, room_type_id: e.target.value })}><option value="">Any</option>{types.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select></Field>
      {p.id && <label className="check"><input type="checkbox" checked={!!f.active} onChange={e => setF({ ...f, active: e.target.checked ? 1 : 0 })} /> Active</label>}
    </div></Modal>;
}
