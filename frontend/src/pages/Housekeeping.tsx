import React, { useState } from "react";
import { fmtDateTime, get, label, post } from "../api";
import { useAuth } from "../state";
import { Button, Card, Field, Input, Loadable, Modal, Pill, Select, Textarea, useAction, useLoad } from "../ui";

const COLS = [["pending", "To do"], ["in_progress", "In progress"], ["completed", "Awaiting inspection"], ["inspected", "Done (today)"], ["rejected", "Failed inspection"]];

export default function Housekeeping() {
  const { hotel, can, user } = useAuth();
  const [mine, setMine] = useState(!can("housekeeping.assign"));
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/housekeeping/tasks`, { mine: mine ? 1 : "" }), [hotel?.id, mine]);
  const rooms = useLoad(() => (can("housekeeping.assign") ? get(`/api/hotels/${hotel!.id}/rooms`) : Promise.resolve({ items: [] })), [hotel?.id]);
  const { busy, run } = useAction();
  const [inspect, setInspect] = useState<any>(null);
  const [complete, setComplete] = useState<any>(null);
  const [creating, setCreating] = useState(false);
  const act = async (fn: () => Promise<any>, msg: string) => { if (await run(fn, msg)) st.reload(); };
  return (
    <div className="page">
      <div className="page-h"><div><h1>Housekeeping</h1><p className="muted">Rooms become sellable only after cleaning and inspection</p></div>
        <div className="row gap-s">
          {can("housekeeping.assign") && <label className="check"><input type="checkbox" checked={mine} onChange={e => setMine(e.target.checked)} /> My tasks only</label>}
          {can("housekeeping.assign") && <Button onClick={() => setCreating(true)}>New task</Button>}
          <Button kind="secondary" onClick={st.reload}>Refresh</Button></div></div>
      <Loadable state={st}>{d => <div className="kanban">
        {COLS.filter(([k]) => k !== "rejected" || d.counts.rejected).map(([k, l]) => (
          <div key={k} className="kcol"><div className="kcol-h">{l} <b>{d.items.filter((t: any) => t.status === k).length}</b></div>
            {d.items.filter((t: any) => t.status === k).map((t: any) => (
              <div key={t.id} className={`kcard prio-${t.priority}`}>
                <div className="row between"><b className="big">Room {t.room_number}</b><Pill s={t.status} /></div>
                <div className="muted small">{label(t.task_type)} · floor {t.floor} · {t.occupancy === "occupied" ? "Occupied" : "Vacant"}</div>
                {t.notes && <div className="small">{t.notes}</div>}
                {t.issues && <div className="small danger">Issues: {t.issues}</div>}
                {can("housekeeping.assign") ? <Select value={t.assigned_to || ""} onChange={e => act(() => post(`/api/housekeeping/tasks/${t.id}/assign`, { user_id: e.target.value ? Number(e.target.value) : null }), "Task assigned")} aria-label="Assign to">
                  <option value="">Unassigned</option>{d.staff.map((s: any) => <option key={s.id} value={s.id}>{s.full_name}</option>)}</Select>
                  : <div className="small muted">Assigned to {t.assigned_to_name || "—"}</div>}
                <div className="row gap-s mt">
                  {["pending", "rejected"].includes(t.status) && (t.assigned_to === user!.id || can("housekeeping.assign")) && can("housekeeping.update") && <Button busy={busy} onClick={() => act(() => post(`/api/housekeeping/tasks/${t.id}/start`), "Cleaning started")}>Start</Button>}
                  {t.status === "in_progress" && (t.assigned_to === user!.id || can("housekeeping.assign")) && <Button busy={busy} onClick={() => setComplete(t)}>Complete</Button>}
                  {t.status === "completed" && can("housekeeping.inspect") && <Button kind="gold" onClick={() => setInspect(t)}>Inspect</Button>}
                </div>
                {t.completed_at && <div className="tiny muted">Completed {fmtDateTime(t.completed_at)}</div>}
              </div>))}
          </div>))}
      </div>}</Loadable>
      {complete && <CompleteModal t={complete} onClose={() => setComplete(null)} onDone={() => { setComplete(null); st.reload(); }} />}
      {inspect && <InspectModal t={inspect} onClose={() => setInspect(null)} onDone={() => { setInspect(null); st.reload(); }} />}
      {creating && <NewTask rooms={rooms.data?.items || []} staff={st.data?.staff || []} onClose={() => setCreating(false)} onDone={() => { setCreating(false); st.reload(); }} />}
    </div>
  );
}

function CompleteModal({ t, onClose, onDone }: any) {
  const [issues, setIssues] = useState("");
  const { busy, run } = useAction();
  return <Modal title={`Complete room ${t.room_number}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/housekeeping/tasks/${t.id}/complete`, { issues: issues || undefined }), "Marked clean — awaiting inspection")) onDone(); }}>Mark complete</Button></>}>
    <Field label="Damaged / missing items or maintenance issues (optional)"><Textarea value={issues} onChange={e => setIssues(e.target.value)} /></Field></Modal>;
}

function InspectModal({ t, onClose, onDone }: any) {
  const [note, setNote] = useState("");
  const { busy, run } = useAction();
  const go = async (passed: boolean) => { if (await run(() => post(`/api/housekeeping/tasks/${t.id}/inspect`, { passed, note: note || undefined }), passed ? `Room ${t.room_number} is ready for sale` : "Sent back for re-cleaning")) onDone(); };
  return <Modal title={`Inspect room ${t.room_number}`} onClose={onClose} footer={<><Button kind="danger" busy={busy} disabled={!note.trim()} onClick={() => go(false)}>Fail</Button><Button kind="gold" busy={busy} onClick={() => go(true)}>Pass — room ready</Button></>}>
    {t.issues && <p className="note">Reported issues: {t.issues}</p>}
    <Field label="Inspection note" hint="Required when failing an inspection"><Textarea value={note} onChange={e => setNote(e.target.value)} /></Field></Modal>;
}

function NewTask({ rooms, staff, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ room_id: "", task_type: "deep_clean", assigned_to: "", priority: 2, notes: "" });
  const { busy, run } = useAction();
  return <Modal title="New housekeeping task" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} disabled={!f.room_id} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/housekeeping/tasks`, { ...f, room_id: Number(f.room_id), assigned_to: f.assigned_to ? Number(f.assigned_to) : undefined }), "Task created")) onDone(); }}>Create</Button></>}>
    <div className="form-grid">
      <Field label="Room"><Select value={f.room_id} onChange={e => setF({ ...f, room_id: e.target.value })}><option value="">Select…</option>{rooms.map((r: any) => <option key={r.id} value={r.id}>{r.number} · {label(r.display_status)}</option>)}</Select></Field>
      <Field label="Task"><Select value={f.task_type} onChange={e => setF({ ...f, task_type: e.target.value })}>{["checkout_clean", "stayover", "deep_clean", "turndown", "inspection"].map(t => <option key={t} value={t}>{label(t)}</option>)}</Select></Field>
      <Field label="Assign to"><Select value={f.assigned_to} onChange={e => setF({ ...f, assigned_to: e.target.value })}><option value="">Unassigned</option>{staff.map((s: any) => <option key={s.id} value={s.id}>{s.full_name}</option>)}</Select></Field>
      <Field label="Priority"><Select value={f.priority} onChange={e => setF({ ...f, priority: Number(e.target.value) })}><option value={1}>High</option><option value={2}>Normal</option><option value={3}>Low</option></Select></Field>
      <Field label="Notes" wide><Input value={f.notes} onChange={e => setF({ ...f, notes: e.target.value })} /></Field>
    </div></Modal>;
}
