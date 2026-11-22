import React, { useState } from "react";
import { fmtDate, fmtDateTime, get, label, money, patch, post, toMinor } from "../api";
import { navigate, useAuth } from "../state";
import { Button, Card, Field, Input, Loadable, Modal, Pill, Select, Table, Textarea, useAction, useLoad } from "../ui";
import { DocumentsPanel } from "./Documents";

const STAGES = ["applied", "screening", "interview", "offer", "hired"];
const ACTION: Record<string, string> = { screening: "Move to screening", interview: "Invite to interview", offer: "Make offer", rejected: "Reject", withdrawn: "Applicant withdrew" };

export default function Recruitment() {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/recruitment`), [hotel?.id]);
  const [open, setOpen] = useState<number | null>(null);
  const [adding, setAdding] = useState(false);
  return <div className="stack">
    {open ? <Opening id={open} onBack={() => { setOpen(null); st.reload(); }} /> : <>
      <div className="row between"><p className="muted">Open positions and where each applicant is in the process.</p>{can("hr.recruit") && <Button onClick={() => setAdding(true)}>New opening</Button>}</div>
      <Loadable state={st}>{d => <Card pad={false}><Table rows={d.items} onRow={o => setOpen(o.id)} empty="No job openings" cols={[
        { h: "Position", r: o => <><b>{o.title}</b><div className="small muted">{o.reference} · {label(o.department)}</div></> }, { h: "Positions", r: o => o.positions, cls: "num" },
        { h: "Applicants", r: o => o.applicants, cls: "num" }, { h: "Pipeline", r: o => <span className="small">{STAGES.map(s => `${label(s)} ${o.stages[s] || 0}`).join(" · ")}</span> },
        { h: "Closes", r: o => fmtDate(o.closing_date) }, { h: "Status", r: o => <Pill s={o.status === "open" ? "active" : o.status} text={label(o.status)} /> }]} /></Card>}</Loadable>
    </>}
    {adding && <NewOpening onClose={() => setAdding(false)} onDone={() => { setAdding(false); st.reload(); }} />}
  </div>;
}

function NewOpening({ onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState<any>({ title: "", department: "front_office", employment_type: "full_time", positions: 1, salary_min: "", salary_max: "", closing_date: "", description: "" });
  const { busy, run } = useAction();
  return <Modal title="New job opening" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.title.trim()} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/recruitment`, { ...f, positions: Number(f.positions), salary_min: f.salary_min ? toMinor(f.salary_min) : undefined, salary_max: f.salary_max ? toMinor(f.salary_max) : undefined, closing_date: f.closing_date || undefined }), "Opening created")) onDone(); }}>Save</Button></>}>
    <div className="form-grid">
      <Field label="Job title" wide><Input value={f.title} onChange={e => setF({ ...f, title: e.target.value })} /></Field>
      <Field label="Department"><Select value={f.department} onChange={e => setF({ ...f, department: e.target.value })}>{["front_office", "housekeeping", "fnb", "kitchen", "finance", "maintenance", "security", "sales", "hr", "management", "other"].map(d => <option key={d} value={d}>{label(d)}</option>)}</Select></Field>
      <Field label="Type"><Select value={f.employment_type} onChange={e => setF({ ...f, employment_type: e.target.value })}>{["full_time", "part_time", "contract", "casual", "intern"].map(d => <option key={d} value={d}>{label(d)}</option>)}</Select></Field>
      <Field label="Positions"><Input type="number" min={1} value={f.positions} onChange={e => setF({ ...f, positions: e.target.value })} /></Field>
      <Field label="Salary from (₦/month)"><Input inputMode="decimal" value={f.salary_min} onChange={e => setF({ ...f, salary_min: e.target.value })} /></Field>
      <Field label="Salary to (₦/month)"><Input inputMode="decimal" value={f.salary_max} onChange={e => setF({ ...f, salary_max: e.target.value })} /></Field>
      <Field label="Closing date"><Input type="date" value={f.closing_date} onChange={e => setF({ ...f, closing_date: e.target.value })} /></Field>
      <Field label="Description" wide><Textarea value={f.description} onChange={e => setF({ ...f, description: e.target.value })} /></Field>
    </div></Modal>;
}

function Opening({ id, onBack }: { id: number; onBack: () => void }) {
  const { can, hotel } = useAuth();
  const st = useLoad(() => get(`/api/recruitment/${id}`), [id]);
  const [adding, setAdding] = useState(false);
  const [app, setApp] = useState<number | null>(null);
  const { busy, run } = useAction();
  return <Loadable state={st}>{o => <div className="stack">
    <div className="row between"><div><button className="link" onClick={onBack}>← All openings</button><h2>{o.title} <Pill s={o.status === "open" ? "active" : o.status} text={label(o.status)} /></h2>
      <p className="muted">{o.reference} · {label(o.department)} · {o.hired} of {o.positions} hired{o.salary_min ? ` · ${money(o.salary_min, hotel!.currency)}–${money(o.salary_max || o.salary_min, hotel!.currency)}` : ""}</p></div>
      <div className="row gap-s">{can("hr.recruit") && o.status === "open" && <Button onClick={() => setAdding(true)}>Add applicant</Button>}
        {can("hr.recruit") && ["open", "on_hold"].includes(o.status) && <Button kind="secondary" busy={busy} onClick={async () => { if (await run(() => patch(`/api/recruitment/${id}`, { status: "closed" }), "Opening closed")) st.reload(); }}>Close opening</Button>}
        {can("hr.recruit") && ["filled", "closed"].includes(o.status) && <Button kind="secondary" busy={busy} onClick={async () => { const r = await run(() => post(`/api/recruitment/${id}/anonymise`, {}), "Unsuccessful applicants anonymised"); if (r) st.reload(); }}>Anonymise unsuccessful applicants</Button>}</div></div>
    <div className="pipeline">{STAGES.map(s => <div key={s} className="pipe-col"><div className="pipe-h">{label(s)} <span className="muted">{o.pipeline[s]}</span></div>
      {o.applicants.filter((a: any) => a.stage === s).map((a: any) => <button key={a.id} className="pipe-card" onClick={() => setApp(a.id)}><b>{a.first_name} {a.last_name}</b>
        <span className="small muted">{a.source || ""}{a.rating ? ` · ${"★".repeat(a.rating)}` : ""}</span></button>)}</div>)}</div>
    {o.applicants.some((a: any) => ["rejected", "withdrawn"].includes(a.stage)) && <p className="muted small">Not progressed: {o.applicants.filter((a: any) => ["rejected", "withdrawn"].includes(a.stage)).map((a: any) => `${a.first_name} ${a.last_name} (${a.stage})`).join(", ")}</p>}
    {adding && <AddApplicant openingId={id} onClose={() => setAdding(false)} onDone={() => { setAdding(false); st.reload(); }} />}
    {app && <Applicant id={app} onClose={() => { setApp(null); st.reload(); }} />}
  </div>}</Loadable>;
}

function AddApplicant({ openingId, onClose, onDone }: any) {
  const [f, setF] = useState<any>({ first_name: "", last_name: "", email: "", phone: "", source: "", expected_salary: "", consent_to_retain: false });
  const { busy, run } = useAction();
  return <Modal title="Add applicant" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.first_name.trim() || !f.last_name.trim()} onClick={async () => { if (await run(() => post(`/api/recruitment/${openingId}/applicants`, { ...f, expected_salary: f.expected_salary ? toMinor(f.expected_salary) : undefined }), "Applicant added")) onDone(); }}>Save</Button></>}>
    <div className="form-grid">{[["first_name", "First name"], ["last_name", "Last name"], ["email", "Email"], ["phone", "Phone"], ["source", "Source (e.g. referral, job board)"], ["expected_salary", "Expected salary (₦/month)"]].map(([k, l]) =>
      <Field key={k} label={l}><Input value={f[k]} onChange={e => setF({ ...f, [k]: e.target.value })} /></Field>)}
      <label className="check"><input type="checkbox" checked={f.consent_to_retain} onChange={e => setF({ ...f, consent_to_retain: e.target.checked })} /> Applicant agreed to be kept on file for future vacancies</label></div>
    <p className="muted small">Upload the CV from the applicant's record after saving.</p></Modal>;
}

function Applicant({ id, onClose }: { id: number; onClose: () => void }) {
  const { can, hotel } = useAuth();
  const st = useLoad(() => get(`/api/applicants/${id}`), [id]);
  const [f, setF] = useState<any>({ note: "", score: "", offered_salary: "", start_date: "" });
  const { busy, run } = useAction();
  const move = async (stage: string) => { const body: any = { stage, note: f.note || undefined };
    if (stage === "offer") Object.assign(body, { offered_salary: toMinor(f.offered_salary), start_date: f.start_date });
    if (await run(() => post(`/api/applicants/${id}/stage`, body), `Moved to ${label(stage)}`)) { setF({ ...f, note: "" }); st.reload(); } };
  return <Modal title="Applicant" width={720} onClose={onClose}><Loadable state={st}>{a => <div className="stack">
    <div className="row between"><div><h3>{a.first_name} {a.last_name}</h3><p className="muted small">{a.opening.title} · {a.email || "no email"} · {a.phone || "no phone"} · {a.source || ""}</p></div><Pill s={a.stage === "hired" ? "approved" : a.stage === "rejected" ? "rejected" : "pending"} text={label(a.stage)} /></div>
    <dl className="dl"><dt>Expected salary</dt><dd>{a.expected_salary ? money(a.expected_salary, hotel!.currency) : "—"}</dd><dt>Offer</dt><dd>{a.offered_salary ? `${money(a.offered_salary, hotel!.currency)} from ${fmtDate(a.start_date)}` : "—"}</dd>
      <dt>Interview score</dt><dd>{a.average_score ?? "—"}</dd>{a.employee_id && <><dt>Employee</dt><dd><a href={`#/hr/employees/${a.employee_id}`} onClick={onClose}>Open employee record</a></dd></>}</dl>
    {can("hr.recruit") && a.allowed_next.length > 0 && <Card title="Next step">
      <div className="form-grid"><Field label="Note (required to reject)" wide><Textarea value={f.note} onChange={e => setF({ ...f, note: e.target.value })} /></Field>
        {a.allowed_next.includes("offer") && <><Field label="Offered salary (₦/month)"><Input inputMode="decimal" value={f.offered_salary} onChange={e => setF({ ...f, offered_salary: e.target.value })} /></Field>
          <Field label="Start date"><Input type="date" value={f.start_date} onChange={e => setF({ ...f, start_date: e.target.value })} /></Field></>}</div>
      <div className="row gap-s wrap mt">{a.allowed_next.filter((s: string) => s !== "hired").map((s: string) => <Button key={s} kind={["rejected", "withdrawn"].includes(s) ? "danger" : "secondary"} busy={busy}
        disabled={(s === "rejected" && !f.note.trim()) || (s === "offer" && (!f.offered_salary || !f.start_date))} onClick={() => move(s)}>{s === "interview" && a.stage === "interview" ? "Another interview" : ACTION[s] || label(s)}</Button>)}
        {a.stage === "offer" && can("hr.manage") && <Button kind="gold" busy={busy} onClick={async () => { const r = await run(() => post(`/api/applicants/${id}/hire`, {}), "Hired — employee record created"); if (r) st.reload(); }}>Hire (offer accepted)</Button>}</div>
      {a.allowed_next.includes("interview") || a.stage === "interview" ? <div className="row gap-s mt"><Select value={f.score} onChange={e => setF({ ...f, score: e.target.value })} aria-label="Interview score"><option value="">Score…</option>{[1, 2, 3, 4, 5].map(n => <option key={n} value={n}>{n}</option>)}</Select>
        <Button kind="ghost" busy={busy} disabled={!f.note.trim()} onClick={async () => { if (await run(() => post(`/api/applicants/${id}/notes`, { kind: f.score ? "interview" : "note", note: f.note, score: f.score ? Number(f.score) : undefined }), "Saved")) { setF({ ...f, note: "", score: "" }); st.reload(); } }}>Save note / interview score</Button></div> : null}
    </Card>}
    {a.stage !== "hired" && <DocumentsPanel entityType="applicant" entityId={a.id} defaultCategory="hr_record" title="CV & certificates" />}
    <Card title="History" pad={false}><Table rows={a.events} cols={[{ h: "When", r: e => fmtDateTime(e.created_at) }, { h: "Who", r: e => e.by_name || "—" },
      { h: "What", r: e => e.kind === "stage" ? `${e.from_stage ? label(e.from_stage) + " → " : ""}${label(e.to_stage)}` : e.kind === "interview" ? `Interview${e.score ? ` (score ${e.score})` : ""}` : "Note" },
      { h: "Note", r: e => <span className="small">{e.note || ""}</span> }]} /></Card>
  </div>}</Loadable></Modal>;
}
