// Staff ID cards (release 1.4): print queue and register, card design, staff photo and per-employee card history.
import React, { useEffect, useState } from "react";
import { fmtDate, get, getToken, label, openFile, post, put, qs } from "../api";
import { useAuth } from "../state";
import { Button, Card, Confirm, Field, Input, Kpi, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, useAction, useLoad } from "../ui";

const STATUS_PILL: Record<string, string> = { pending: "pending", printed: "in_progress", issued: "approved", revoked: "deactivated" };
const STATUS_TEXT: Record<string, string> = { pending: "Waiting to print", printed: "Printed — to hand over", issued: "Issued", revoked: "Cancelled" };

/** An image that needs the sign-in token (staff photos are not public). */
export function useAuthImage(path: string | null, version: number = 0): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!path) { setUrl(null); return; }
    let alive = true, made: string | null = null;
    const t = getToken();
    fetch(path, { headers: t ? { Authorization: `Bearer ${t}` } : {} })
      .then(r => (r.ok ? r.blob() : null))
      .then(b => { if (alive && b) { made = URL.createObjectURL(b); setUrl(made); } else if (alive) setUrl(null); })
      .catch(() => alive && setUrl(null));
    return () => { alive = false; if (made) URL.revokeObjectURL(made); };
  }, [path, version]);
  return url;
}

function readBase64(file: File): Promise<string> {
  return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1] || ""); r.onerror = rej; r.readAsDataURL(file); });
}

export function PhotoUpload({ employeeId, onDone, text = "Upload photo" }: { employeeId: number; onDone: () => void; text?: string }) {
  const { busy, run } = useAction();
  const ref = React.useRef<HTMLInputElement>(null);
  return <>
    <input ref={ref} type="file" accept="image/jpeg,image/png,image/webp" capture="user" style={{ display: "none" }} onChange={async ev => {
      const f = ev.target.files?.[0];
      ev.target.value = "";
      if (!f) return;
      const b64 = await readBase64(f);
      if (await run(() => post(`/api/employees/${employeeId}/photo`, { filename: f.name, content_base64: b64 }), "Photo saved")) onDone();
    }} />
    <Button kind="secondary" busy={busy} onClick={() => ref.current?.click()}>{text}</Button>
  </>;
}

// ------------------------------------------------------------------ HR → ID cards tab
export function IDCards() {
  const { hotel, can } = useAuth();
  const [status, setStatus] = useState("pending");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<number[]>([]);
  const [modal, setModal] = useState<any>(null);
  const { busy, run } = useAction();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/id-cards`, { status: status === "all" ? "" : status, q }), [hotel?.id, status, q]);
  useEffect(() => setSel([]), [status, q]);
  const print = async (ids: number[] | null, layout: string) => {
    const query = qs({ ids: ids ? ids.join(",") : "", layout });
    if (await run(() => openFile(`/api/hotels/${hotel!.id}/id-cards/print?${query}`, "staff-id-cards.pdf", true), "Cards sent to print — they are now marked printed")) { setSel([]); st.reload(); }
  };
  const toggle = (id: number) => setSel(s => (s.includes(id) ? s.filter(x => x !== id) : [...s, id]));
  return <Loadable state={st}>{d => {
    const printable = d.items.filter((k: any) => k.status !== "revoked");
    const noPhoto = d.items.filter((k: any) => sel.includes(k.id) && !k.has_photo).length;
    return <>
      <div className="kpis">
        <Kpi title="Waiting to print" value={d.counts.pending} tone={d.counts.pending ? "warn" : undefined} sub="new staff and replacements" />
        <Kpi title="Printed, not handed over" value={d.counts.printed} />
        <Kpi title="Issued (in use)" value={d.counts.issued} />
        <Kpi title="Active staff without a card" value={d.active_without_card} tone={d.active_without_card ? "warn" : undefined}
          sub={d.active_without_card ? <button className="link small" disabled={busy} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/id-cards/generate-missing`), "Cards created")) st.reload(); }}>Create their cards</button> : "everyone has one"} />
      </div>
      <Card pad={false} title="Staff ID cards" actions={<div className="row gap-s wrap">
        {can("admin.id_card_design") && <a className="btn btn-secondary" href="#/admin/id-card-design">Card design</a>}
        {sel.length > 0 && <>
          <Button busy={busy} onClick={() => print(sel, "a4")}>Print {sel.length} on A4</Button>
          <Button kind="secondary" busy={busy} onClick={() => print(sel, "card")}>Card printer</Button></>}
        {sel.length === 0 && d.counts.pending > 0 && <Button busy={busy} onClick={() => print(null, "a4")}>Print all waiting ({d.counts.pending})</Button>}
      </div>}>
        <div className="row gap-s wrap pad">
          <Tabs tabs={[{ id: "pending", label: `Waiting (${d.counts.pending})` }, { id: "printed", label: `Printed (${d.counts.printed})` },
            { id: "issued", label: "Issued" }, { id: "revoked", label: "Cancelled" }, { id: "all", label: "All" }]} value={status} onChange={setStatus} />
          <Input placeholder="Search name or staff number" value={q} onChange={e => setQ(e.target.value)} style={{ maxWidth: 260 }} />
        </div>
        {noPhoto > 0 && <div className="note note-warn">{noPhoto} selected {noPhoto === 1 ? "card has" : "cards have"} no photo yet — they will print with an empty photo box. Upload the photo first if you can.</div>}
        <Table rows={d.items} empty={status === "pending" ? "No cards waiting. New employees and hires get a card here automatically." : "No cards"} cols={[
          { h: <input type="checkbox" aria-label="Select all" checked={printable.length > 0 && sel.length === printable.length}
              onChange={e => setSel(e.target.checked ? printable.map((k: any) => k.id) : [])} />,
            r: (k: any) => k.status !== "revoked" && <input type="checkbox" aria-label={`Select ${k.card_no}`} checked={sel.includes(k.id)} onChange={() => toggle(k.id)} /> },
          { h: "Employee", r: (k: any) => <><a href={`#/hr/employees/${k.employee_id}`}><b>{k.first_name} {k.last_name}</b></a>
              <div className="small muted">{k.employee_no} · {k.position} · {label(k.department)}</div></> },
          { h: "Photo", r: (k: any) => k.has_photo ? <span className="muted small">✓ on file</span>
              : k.status !== "revoked" ? <PhotoUpload employeeId={k.employee_id} onDone={st.reload} text="Add photo" /> : "—" },
          { h: "Card", r: (k: any) => <><span className="mono">{k.card_no}</span><div className="small muted">{k.reason_label}</div></> },
          { h: "Status", r: (k: any) => <><Pill s={STATUS_PILL[k.status]} text={STATUS_TEXT[k.status]} />
              {k.status === "revoked" && k.revoke_reason && <div className="small muted">{k.revoke_reason}</div>}</> },
          { h: "Expires", r: (k: any) => fmtDate(k.expiry_date) },
          { h: "", r: (k: any) => <div className="row gap-s">
              {k.status === "printed" && <Button kind="secondary" busy={busy} onClick={async () => { if (await run(() => post(`/api/id-cards/${k.id}/issue`), "Card handed over")) st.reload(); }}>Handed over</Button>}
              {k.status === "printed" && <Button kind="ghost" onClick={() => print([k.id], "a4")}>Reprint</Button>}
              {(k.status === "issued" || k.status === "printed") && <Button kind="ghost" onClick={() => setModal({ kind: "reissue", card: k, reasons: d.reasons })}>Replace</Button>}
              {k.status !== "revoked" && <Button kind="ghost" onClick={() => setModal({ kind: "revoke", card: k })}>Cancel</Button>}
            </div> },
        ]} />
      </Card>
      {modal?.kind === "reissue" && <ReissueModal employeeId={modal.card.employee_id} name={`${modal.card.first_name} ${modal.card.last_name}`} reasons={modal.reasons}
        onClose={() => setModal(null)} onDone={() => { setModal(null); setStatus("pending"); st.reload(); }} />}
      {modal?.kind === "revoke" && <Confirm title={`Cancel card ${modal.card.card_no}`} danger needReason="Reason" confirmText="Cancel card"
        text={<p>Scanning this card will show it is no longer valid. Use <b>Replace</b> instead if the person needs a new card.</p>}
        onClose={() => setModal(null)} onConfirm={async reason => { if (await run(() => post(`/api/id-cards/${modal.card.id}/revoke`, { reason }), "Card cancelled")) { setModal(null); st.reload(); } }} />}
    </>;
  }}</Loadable>;
}

function ReissueModal({ employeeId, name, reasons, onClose, onDone }: any) {
  const [f, setF] = useState({ reason: "lost", note: "" });
  const { busy, run } = useAction();
  return <Modal title={`New card for ${name}`} onClose={onClose} width={480} footer={<>
    <Button kind="secondary" onClick={onClose}>Back</Button>
    <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/employees/${employeeId}/id-cards`, f), "New card added to the print queue")) onDone(); }}>Add to print queue</Button></>}>
    <div className="stack">
      <Field label="Why is a new card needed?"><Select value={f.reason} onChange={e => setF({ ...f, reason: e.target.value })}>
        {(reasons || []).map((r: any) => <option key={r.code} value={r.code}>{r.label}</option>)}</Select></Field>
      <Field label="Note (optional)"><Textarea value={f.note} onChange={e => setF({ ...f, note: e.target.value })} /></Field>
      <p className="small muted">{f.reason === "lost" || f.reason === "damaged" ? "The current card is cancelled now, so it fails a scan straight away." : "The current card stays valid until the new one is handed over."}</p>
    </div>
  </Modal>;
}

// ------------------------------------------------------------------ employee profile panel
export function EmployeeIdCard({ e, reload }: { e: any; reload: () => void }) {
  const { hotel, can } = useAuth();
  const [v, setV] = useState(0);
  const photo = useAuthImage(e.has_photo ? `/api/employees/${e.id}/photo` : null, v);
  const cards = useLoad(() => (can("hr.id_cards") ? get(`/api/hotels/${hotel!.id}/id-cards`, { q: e.employee_no }) : Promise.resolve(null)), [e.id, v]);
  const [modal, setModal] = useState(false);
  const mayPhoto = can("hr.manage") || can("hr.id_cards");
  const mine = (cards.data?.items || []).filter((k: any) => k.employee_id === e.id);
  return <Card title="Photo & ID card" actions={<div className="row gap-s">
      {mayPhoto && e.status === "active" && <PhotoUpload employeeId={e.id} onDone={() => { setV(x => x + 1); reload(); }} text={e.has_photo ? "Change photo" : "Upload photo"} />}
      {can("hr.id_cards") && e.status === "active" && <Button kind="secondary" onClick={() => setModal(true)}>New card</Button>}
      {can("hr.id_cards") && <a className="btn btn-ghost" href="#/hr?tab=idcards">Print queue</a>}</div>}>
    <div className="row gap" style={{ alignItems: "flex-start" }}>
      <div style={{ width: 96, height: 120, borderRadius: 8, background: "var(--line, #eef0f3)", overflow: "hidden", flex: "none", display: "grid", placeItems: "center" }}>
        {photo ? <img src={photo} alt={`${e.first_name} ${e.last_name}`} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <span className="small muted">No photo</span>}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        {e.blood_group && <p className="small">Blood group: <b>{e.blood_group}</b></p>}
        {can("hr.id_cards") ? (mine.length ? <Table rows={mine} cols={[
          { h: "Card", r: (k: any) => <span className="mono">{k.card_no}</span> }, { h: "Reason", r: (k: any) => k.reason_label },
          { h: "Status", r: (k: any) => <Pill s={STATUS_PILL[k.status]} text={STATUS_TEXT[k.status]} /> }, { h: "Expires", r: (k: any) => fmtDate(k.expiry_date) }]} />
          : <p className="muted small">No ID card yet.</p>) : <p className="muted small">ID cards are managed by HR.</p>}
      </div>
    </div>
    {modal && <ReissueModal employeeId={e.id} name={`${e.first_name} ${e.last_name}`} reasons={cards.data?.reasons || []}
      onClose={() => setModal(false)} onDone={() => { setModal(false); setV(x => x + 1); }} />}
  </Card>;
}
