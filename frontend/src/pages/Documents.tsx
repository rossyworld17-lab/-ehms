import React, { useRef, useState } from "react";
import { del, fmtDate, fmtDateTime, get, label, openFile, patch, post } from "../api";
import { navigate, useAuth } from "../state";
import { Button, Card, Field, Input, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, errText, useAction, useLoad, useToast } from "../ui";

const size = (b: number) => (b > 1048576 ? `${(b / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`);
const CATS = ["identity", "contract", "invoice", "receipt", "statement", "licence", "policy", "certificate", "hr_record", "medical", "quotation", "photo", "report", "correspondence", "other"];

function readFile(file: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(",", 2)[1] || "");
    r.onerror = () => rej(new Error("Could not read the file"));
    r.readAsDataURL(file);
  });
}

/** Documents attached to one record (guest, employee, supplier, event, …). */
export function DocumentsPanel({ entityType, entityId, title = "Documents", defaultCategory = "other" }: { entityType: string; entityId: number; title?: string; defaultCategory?: string }) {
  const { can } = useAuth();
  const st = useLoad(() => get("/api/documents", { entity_type: entityType, entity_id: entityId }), [entityType, entityId]);
  const [up, setUp] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  if (!can("documents.view") && !can("documents.upload")) return null;
  return <Card title={title} actions={can("documents.upload") && <Button kind="secondary" onClick={() => setUp(true)}>Upload</Button>} pad={false}>
    <Loadable state={st}>{d => <>
      <Table rows={d.items} onRow={x => setOpen(x.id)} empty="No documents" cols={[{ h: "Document", r: x => <><b>{x.title}</b><div className="small muted">{x.filename} · {size(x.size_bytes)}</div></> },
        { h: "Category", r: x => label(x.category) }, { h: "Access", r: x => x.confidentiality === "internal" ? "" : <Pill s="urgent" text={label(x.confidentiality)} /> },
        { h: "Version", r: x => `v${x.version}`, cls: "num" }, { h: "Uploaded", r: x => <span className="small">{fmtDate(x.created_at)}{x.uploaded_by_name ? ` · ${x.uploaded_by_name}` : ""}</span> }]} />
      {d.hidden_count > 0 && <p className="muted small pad">{d.hidden_count} confidential document(s) are not shown to your role.</p>}
    </>}</Loadable>
    {up && <UploadModal entityType={entityType} entityId={entityId} defaultCategory={defaultCategory} onClose={() => setUp(false)} onDone={() => { setUp(false); st.reload(); }} />}
    {open && <DocumentModal id={open} onClose={() => { setOpen(null); st.reload(); }} />}
  </Card>;
}

function UploadModal({ entityType, entityId, defaultCategory, replaceId, onClose, onDone }: any) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [f, setF] = useState({ title: "", category: defaultCategory || "other", confidentiality: "", notes: "" });
  const { busy, run } = useAction();
  const go = async () => {
    if (!file) return;
    const content_base64 = await readFile(file);
    const body: any = replaceId ? { filename: file.name, content_base64, notes: f.notes || undefined }
      : { entity_type: entityType, entity_id: entityId, filename: file.name, content_base64, title: f.title || file.name, category: f.category, notes: f.notes || undefined, ...(f.confidentiality ? { confidentiality: f.confidentiality } : {}) };
    const r = await run(() => post(replaceId ? `/api/documents/${replaceId}/replace` : "/api/documents", body), replaceId ? "New version uploaded" : "Document uploaded");
    if (r) onDone(r);
  };
  return <Modal title={replaceId ? "Upload a new version" : "Upload a document"} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button busy={busy} disabled={!file} onClick={go}>Upload</Button></>}>
    <div className="form-grid">
      <Field label="File" hint="PDF, image, Word, Excel, CSV or text — up to 10 MB" wide><input ref={fileRef} type="file" accept=".pdf,.png,.jpg,.jpeg,.docx,.xlsx,.csv,.txt" onChange={e => setFile(e.target.files?.[0] || null)} /></Field>
      {!replaceId && <>
        <Field label="Title"><Input value={f.title} placeholder={file?.name} onChange={e => setF({ ...f, title: e.target.value })} /></Field>
        <Field label="Category"><Select value={f.category} onChange={e => setF({ ...f, category: e.target.value })}>{CATS.map(c => <option key={c} value={c}>{label(c)}</option>)}</Select></Field>
        <Field label="Access" hint="Identity, medical, HR and employee documents are confidential by default"><Select value={f.confidentiality} onChange={e => setF({ ...f, confidentiality: e.target.value })}>
          <option value="">Default for this category</option><option value="internal">Internal</option><option value="confidential">Confidential</option><option value="restricted">Restricted</option></Select></Field>
      </>}
      <Field label="Notes" wide><Textarea value={f.notes} onChange={e => setF({ ...f, notes: e.target.value })} /></Field>
    </div></Modal>;
}

export function DocumentModal({ id, onClose }: { id: number; onClose: () => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const st = useLoad(() => get(`/api/documents/${id}`), [id]);
  const [mode, setMode] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [until, setUntil] = useState("");
  const { busy, run } = useAction();
  return <Modal title="Document" onClose={onClose} width={720}><Loadable state={st}>{d => <div className="stack">
    <div className="row between"><div><h3>{d.title}</h3><p className="muted small">{d.filename} · {size(d.size_bytes)} · v{d.version} · {label(d.category)}</p></div>
      <div className="row gap-s">{d.confidentiality !== "internal" && <Pill s="urgent" text={label(d.confidentiality)} />}{d.legal_hold ? <Pill s="high" text="Legal hold" /> : null}<Pill s={d.status} /></div></div>
    <div className="row gap-s">
      <Button onClick={() => openFile(`/api/documents/${d.id}/download`, d.filename, true).catch(e => toast("error", errText(e)))}>Open / download</Button>
      {can("documents.upload") && d.status === "active" && <Button kind="secondary" onClick={() => setMode("replace")}>New version</Button>}
      {can("documents.manage") && <><Button kind="secondary" onClick={() => setMode("hold")}>{d.legal_hold ? "Lift legal hold" : "Legal hold"}</Button>
        <Button kind="secondary" onClick={() => setMode("retention")}>Extend retention</Button><Button kind="danger" onClick={() => setMode("delete")}>Delete</Button></>}
    </div>
    <dl className="dl"><dt>Uploaded</dt><dd>{fmtDateTime(d.created_at)}{d.uploaded_by_name ? ` by ${d.uploaded_by_name}` : ""}</dd><dt>Keep until</dt><dd>{fmtDate(d.retention_until)}</dd>
      {d.notes && <><dt>Notes</dt><dd>{d.notes}</dd></>}{d.replaced_by.length > 0 && <><dt>Replaced by</dt><dd>document {d.replaced_by.join(", ")}</dd></>}</dl>
    {d.previous_versions.length > 0 && <Card title="Earlier versions" pad={false}><Table rows={d.previous_versions} cols={[{ h: "Version", r: v => `v${v.version}` }, { h: "File", r: v => v.filename },
      { h: "Uploaded", r: v => fmtDateTime(v.created_at) }, { h: "", r: v => <Button kind="ghost" onClick={() => openFile(`/api/documents/${v.id}/download`, v.filename).catch(e => toast("error", errText(e)))}>Download</Button> }]} /></Card>}
    <Card title="Access history" pad={false}><Table rows={d.access_log} rowKey={r => r.at + r.action} cols={[{ h: "When", r: r => fmtDateTime(r.at) }, { h: "Who", r: r => r.user },
      { h: "Action", r: r => <Pill s={r.action === "denied" || r.action === "integrity_failed" ? "rejected" : "active"} text={label(r.action)} /> }, { h: "Detail", r: r => <span className="small">{r.detail || ""}</span> }]} /></Card>
    {mode === "replace" && <UploadModal replaceId={d.id} onClose={() => setMode(null)} onDone={(r: any) => { setMode(null); onClose(); if (r?.id) navigate(`/documents/${r.id}`); }} />}
    {mode && mode !== "replace" && <Modal title={mode === "hold" ? (d.legal_hold ? "Lift legal hold" : "Place on legal hold") : mode === "retention" ? "Extend retention" : "Delete document"} onClose={() => setMode(null)}
      footer={<><Button kind="secondary" onClick={() => setMode(null)}>Cancel</Button><Button kind={mode === "delete" ? "danger" : "primary"} busy={busy} disabled={reason.trim().length < 5 || (mode === "retention" && !until)} onClick={async () => {
        const ok = await run(() => mode === "hold" ? post(`/api/documents/${d.id}/legal-hold`, { hold: !d.legal_hold, reason }) : mode === "retention" ? post(`/api/documents/${d.id}/retention`, { retention_until: until, reason })
          : del(`/api/documents/${d.id}`, { reason }), "Saved");
        if (ok) { setMode(null); setReason(""); if (mode === "delete") onClose(); else st.reload(); } }}>Confirm</Button></>}>
      {mode === "delete" && <p>The file is erased; the record of the document and its access history are kept. Documents cannot be deleted before {fmtDate(d.retention_until)} or while on legal hold.</p>}
      {mode === "retention" && <Field label="Keep until"><Input type="date" value={until} onChange={e => setUntil(e.target.value)} /></Field>}
      <Field label="Reason" wide><Textarea value={reason} onChange={e => setReason(e.target.value)} /></Field></Modal>}
  </div>}</Loadable></Modal>;
}

/** Hotel-wide document register: search, retention queue, activity log. */
export default function Documents({ q, openId }: { q: URLSearchParams; openId?: number }) {
  const { hotel, can } = useAuth();
  const [tab, setTab] = useState("library");
  const [s, setS] = useState({ q: "", category: "" });
  const [applied, setApplied] = useState(s);
  const [open, setOpen] = useState<number | null>(openId || null);
  const st = useLoad(() => get("/api/documents", { hotel_id: hotel!.id, ...Object.fromEntries(Object.entries(applied).filter(([, v]) => v)) }), [hotel?.id, JSON.stringify(applied)]);
  const tabs = [{ id: "library", label: "Library" }, ...(can("documents.manage") ? [{ id: "retention", label: "Retention due" }, { id: "activity", label: "Activity" }] : [])];
  return <div className="page">
    <div className="page-h"><div><h1>Documents</h1><p className="muted">Files linked to guests, staff, suppliers, purchases, events and transactions — access-checked and logged</p></div>
      {can("documents.upload") && <HotelUpload onDone={() => st.reload()} />}</div>
    <Tabs tabs={tabs} value={tab} onChange={setTab} />
    {tab === "library" && <div className="stack">
      <div className="filters"><Field label="Search"><Input value={s.q} placeholder="Title or file name" onChange={e => setS({ ...s, q: e.target.value })} onKeyDown={e => e.key === "Enter" && setApplied(s)} /></Field>
        <Field label="Category"><Select value={s.category} onChange={e => setS({ ...s, category: e.target.value })}><option value="">All</option>{CATS.map(c => <option key={c} value={c}>{label(c)}</option>)}</Select></Field>
        <Button onClick={() => setApplied(s)}>Search</Button></div>
      <Loadable state={st}>{d => <Card pad={false}><Table rows={d.items} onRow={x => setOpen(x.id)} empty="No documents found" cols={[{ h: "Document", r: x => <><b>{x.title}</b><div className="small muted">{x.filename} · {size(x.size_bytes)}</div></> },
        { h: "Linked to", r: x => label(x.entity_type) }, { h: "Category", r: x => label(x.category) }, { h: "Access", r: x => x.confidentiality === "internal" ? "" : <Pill s="urgent" text={label(x.confidentiality)} /> },
        { h: "Uploaded", r: x => <span className="small">{fmtDate(x.created_at)}{x.uploaded_by_name ? ` · ${x.uploaded_by_name}` : ""}</span> }, { h: "Keep until", r: x => fmtDate(x.retention_until) }]} />
        {d.hidden_count > 0 && <p className="muted small pad">{d.hidden_count} document(s) are not shown to your role.</p>}</Card>}</Loadable>
    </div>}
    {tab === "retention" && <Retention onOpen={setOpen} />}
    {tab === "activity" && <Activity onOpen={setOpen} />}
    {open && <DocumentModal id={open} onClose={() => { setOpen(null); if (openId) navigate("/documents"); st.reload(); }} />}
  </div>;
}

function HotelUpload({ onDone }: { onDone: () => void }) {
  const { hotel } = useAuth();
  const [o, setO] = useState(false);
  return <><Button onClick={() => setO(true)}>Upload hotel document</Button>{o && <UploadModal entityType="hotel" entityId={hotel!.id} defaultCategory="policy" onClose={() => setO(false)} onDone={() => { setO(false); onDone(); }} />}</>;
}

function Retention({ onOpen }: { onOpen: (id: number) => void }) {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/documents/retention-due`), [hotel?.id]);
  return <Loadable state={st}>{d => <Card pad={false}><p className="muted small pad">Documents past their retention date and not on legal hold. Review each before deleting.</p>
    <Table rows={d.items} onRow={x => onOpen(x.id)} empty="Nothing is due for disposal" cols={[{ h: "Document", r: x => x.title }, { h: "Category", r: x => label(x.category) }, { h: "Keep until", r: x => fmtDate(x.retention_until) }]} /></Card>}</Loadable>;
}

function Activity({ onOpen }: { onOpen: (id: number) => void }) {
  const { hotel } = useAuth();
  const [action, setAction] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/documents/access-log`, action ? { action } : {}), [hotel?.id, action]);
  return <div className="stack"><div className="filters"><Field label="Action"><Select value={action} onChange={e => setAction(e.target.value)}><option value="">All</option>
    {["upload", "view", "download", "update", "superseded", "denied", "legal_hold", "hold_lifted", "retention", "delete", "integrity_failed"].map(a => <option key={a} value={a}>{label(a)}</option>)}</Select></Field></div>
    <Loadable state={st}>{d => <Card pad={false}><Table rows={d.items} rowKey={r => r.at + r.document_id + r.action} onRow={r => onOpen(r.document_id)} cols={[{ h: "When", r: r => fmtDateTime(r.at) }, { h: "Who", r: r => r.user },
      { h: "Action", r: r => <Pill s={r.action === "denied" || r.action === "integrity_failed" ? "rejected" : "active"} text={label(r.action)} /> }, { h: "Document", r: r => r.title }, { h: "Detail", r: r => <span className="small">{r.detail || ""}</span> }]} /></Card>}</Loadable></div>;
}
