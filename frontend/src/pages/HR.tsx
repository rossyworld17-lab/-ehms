import React, { useEffect, useState } from "react";
import { fmtDate, fmtDateTime, get, label, money, openFile, patch, post, put, toMinor, fromMinor, uid } from "../api";
import { useAuth } from "../state";
import { Button, Card, Empty, Field, Input, Kpi, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, useAction, useLoad, useToast } from "../ui";
import { RejectModal } from "./Inventory";

// ======================================================================== HR
export default function HR({ q }: { q: URLSearchParams }) {
  const [tab, setTab] = useState(q.get("tab") || "employees");
  useEffect(() => { const t = q.get("tab"); if (t) setTab(t); }, [q.get("tab")]);
  return <div className="page">
    <div className="page-h"><div><h1>Human resources</h1><p className="muted">Employees, duty rosters, attendance and leave</p></div></div>
    <Tabs tabs={[{ id: "employees", label: "Employees" }, { id: "roster", label: "Roster" }, { id: "attendance", label: "Attendance" }, { id: "leave", label: "Leave" }]} value={tab} onChange={setTab} />
    {tab === "employees" && <Employees />}
    {tab === "roster" && <Roster />}
    {tab === "attendance" && <Attendance />}
    {tab === "leave" && <Leave />}
  </div>;
}

function Employees() {
  const { hotel, can } = useAuth();
  const [f, setF] = useState({ status: "active", department: "", q: "" });
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/employees`, f), [hotel?.id, f.status, f.department, f.q]);
  const [edit, setEdit] = useState<any>(null);
  return <Loadable state={st}>{d => <>
    <div className="row gap-s wrap mb">{d.headcount.map((h: any) => <span key={h.department} className="chip">{label(h.department)}: <b>{h.n}</b></span>)}</div>
    <Card title={<div className="row gap-s wrap"><Input placeholder="Search name or number…" value={f.q} onChange={e => setF({ ...f, q: e.target.value })} />
      <Select value={f.department} onChange={e => setF({ ...f, department: e.target.value })}><option value="">All departments</option>{d.departments.map((x: string) => <option key={x} value={x}>{label(x)}</option>)}</Select>
      <Select value={f.status} onChange={e => setF({ ...f, status: e.target.value })}>{["active", "suspended", "resigned", "terminated", "retired", "all"].map(x => <option key={x} value={x}>{label(x)}</option>)}</Select></div>}
      actions={can("hr.manage") && <Button onClick={() => setEdit({})}>New employee</Button>} pad={false}>
      <Table rows={d.items} onRow={e => location.hash = `#/hr/employees/${e.id}`} empty="No employees" cols={[{ h: "No.", r: e => e.employee_no },
        { h: "Name", r: e => <b>{e.first_name} {e.last_name}</b> }, { h: "Department", r: e => label(e.department) }, { h: "Position", r: e => e.position },
        { h: "Type", r: e => label(e.employment_type) }, { h: "Hired", r: e => fmtDate(e.hire_date) },
        ...(can("payroll.view") || can("hr.manage") ? [{ h: "Monthly gross", r: (e: any) => money(e.basic_salary + e.housing_allowance + e.transport_allowance + e.other_allowance, hotel!.currency), cls: "num" }] : []),
        { h: "Login", r: e => e.user_email || <span className="muted">—</span> }, { h: "Status", r: e => <Pill s={e.status === "active" ? "active" : "deactivated"} text={label(e.status)} /> }]} />
    </Card>
    {edit && <EmployeeModal e={edit} meta={d} onClose={() => setEdit(null)} onDone={() => { setEdit(null); st.reload(); }} />}
  </>}</Loadable>;
}

function EmployeeModal({ e, meta, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const users = useLoad(() => get(`/api/admin/users`).catch(() => ({ items: [] })), []);
  const money0 = (v: any) => (v == null ? "" : fromMinor(v));
  const [f, setF] = useState<any>({ first_name: e.first_name || "", last_name: e.last_name || "", gender: e.gender || "", date_of_birth: e.date_of_birth || "", phone: e.phone || "",
    email: e.email || "", address: e.address || "", department: e.department || meta.departments[0], position: e.position || "", employment_type: e.employment_type || "full_time",
    hire_date: e.hire_date || new Date().toISOString().slice(0, 10), basic_salary: money0(e.basic_salary), housing_allowance: money0(e.housing_allowance),
    transport_allowance: money0(e.transport_allowance), other_allowance: money0(e.other_allowance), annual_rent: money0(e.annual_rent), bank_name: e.bank_name || "",
    bank_account_number: e.bank_account_number || "", tax_id: e.tax_id || "", pension_pfa: e.pension_pfa || "", pension_pin: e.pension_pin || "", nhf_number: e.nhf_number || "",
    next_of_kin: e.next_of_kin || "", emergency_contact: e.emergency_contact || "", qualifications: e.qualifications || "", user_id: e.user_id || "" });
  const { busy, run } = useAction();
  const go = async () => {
    const body: any = { ...f, user_id: f.user_id ? Number(f.user_id) : null };
    for (const k of ["basic_salary", "housing_allowance", "transport_allowance", "other_allowance", "annual_rent"]) body[k] = toMinor(f[k] || "0");
    for (const k of ["date_of_birth"]) if (!body[k]) delete body[k];
    if (e.id) for (const k of ["bank_account_number", "tax_id", "pension_pin", "nhf_number"]) if (String(body[k]).startsWith("•")) delete body[k];
    if (await run(() => e.id ? patch(`/api/employees/${e.id}`, body) : post(`/api/hotels/${hotel!.id}/employees`, body), "Employee saved")) onDone();
  };
  const fld = (k: string, l: string, type = "text", wide = false) => <Field label={l} wide={wide}><Input type={type} value={f[k]} onChange={x => setF({ ...f, [k]: x.target.value })} /></Field>;
  return <Modal title={e.id ? `Edit ${e.first_name} ${e.last_name}` : "New employee"} width={820} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.first_name || !f.last_name || !f.position} onClick={go}>Save</Button></>}>
    <h4>Personal</h4><div className="form-grid">{fld("first_name", "First name")}{fld("last_name", "Last name")}
      <Field label="Gender"><Select value={f.gender} onChange={x => setF({ ...f, gender: x.target.value })}><option value="">—</option><option>Female</option><option>Male</option></Select></Field>
      {fld("date_of_birth", "Date of birth", "date")}{fld("phone", "Phone")}{fld("email", "Email")}{fld("address", "Address", "text", true)}{fld("next_of_kin", "Next of kin")}{fld("emergency_contact", "Emergency contact")}</div>
    <h4>Employment</h4><div className="form-grid">
      <Field label="Department"><Select value={f.department} onChange={x => setF({ ...f, department: x.target.value })}>{meta.departments.map((d: string) => <option key={d} value={d}>{label(d)}</option>)}</Select></Field>
      {fld("position", "Position")}
      <Field label="Type"><Select value={f.employment_type} onChange={x => setF({ ...f, employment_type: x.target.value })}>{meta.employment_types.map((t: string) => <option key={t} value={t}>{label(t)}</option>)}</Select></Field>
      {fld("hire_date", "Hire date", "date")}
      <Field label="System login (optional)"><Select value={f.user_id} onChange={x => setF({ ...f, user_id: x.target.value })}><option value="">None</option>{(users.data?.items || []).map((u: any) => <option key={u.id} value={u.id}>{u.full_name} · {u.email}</option>)}</Select></Field>
      {fld("qualifications", "Qualifications", "text", true)}</div>
    <h4>Monthly pay ({hotel!.currency})</h4><div className="form-grid">{fld("basic_salary", "Basic")}{fld("housing_allowance", "Housing")}{fld("transport_allowance", "Transport")}{fld("other_allowance", "Other allowances")}
      {fld("annual_rent", "Annual rent paid (for rent relief)")}</div>
    <h4>Bank & statutory</h4><div className="form-grid">{fld("bank_name", "Bank")}{fld("bank_account_number", "Account number")}{fld("tax_id", "Tax ID (TIN)")}{fld("pension_pfa", "Pension fund administrator")}
      {fld("pension_pin", "Pension PIN")}{fld("nhf_number", "NHF number")}</div>
  </Modal>;
}

export function EmployeeDetail({ id }: { id: number }) {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/employees/${id}`), [id]);
  const meta = useLoad(() => get(`/api/hotels/${hotel!.id}/employees`, { status: "all", q: "~none~" }), [hotel?.id]);
  const [modal, setModal] = useState<string | null>(null);
  const cur = hotel!.currency;
  return <div className="page"><Loadable state={st}>{e => <>
    <div className="page-h"><div><h1>{e.first_name} {e.last_name} <Pill s={e.status === "active" ? "active" : "deactivated"} text={label(e.status)} /></h1>
      <p className="muted">{e.employee_no} · {e.position} · {label(e.department)} · {label(e.employment_type)} · since {fmtDate(e.hire_date)}{e.exit_date ? ` · left ${fmtDate(e.exit_date)} (${e.exit_reason})` : ""}</p></div>
      <div className="row gap-s wrap">
        {can("hr.manage") && meta.data && <Button kind="secondary" onClick={() => setModal("edit")}>Edit</Button>}
        {can("hr.manage") && e.status === "active" && <Button kind="ghost" onClick={() => setModal("exit")}>Record exit</Button>}
        {can("hr.records") && <Button kind="secondary" onClick={() => setModal("record")}>Add record</Button>}
        {can("payroll.pay") && e.status === "active" && <Button kind="secondary" onClick={() => setModal("loan")}>Staff loan</Button>}
        <a className="btn btn-secondary" href="#/hr">Back</a></div></div>
    <div className="grid-2">
      <Card title="Details"><dl className="dl">
        <dt>Phone</dt><dd>{e.phone || "—"}</dd><dt>Email</dt><dd>{e.email || "—"}</dd><dt>Next of kin</dt><dd>{e.next_of_kin || "—"}</dd><dt>Emergency</dt><dd>{e.emergency_contact || "—"}</dd>
        <dt>Bank</dt><dd>{e.bank_name || "—"} {e.bank_account_number || ""}</dd><dt>TIN</dt><dd>{e.tax_id || "—"}</dd><dt>Pension</dt><dd>{e.pension_pfa || "—"} {e.pension_pin || ""}</dd>
        {"basic_salary" in e && <><dt>Basic</dt><dd>{money(e.basic_salary, cur)}</dd><dt>Allowances</dt><dd>{money(e.housing_allowance + e.transport_allowance + e.other_allowance, cur)}</dd></>}
      </dl></Card>
      <Card title="Leave balances (this year)" pad={false}><Table rows={e.leave_balances} cols={[{ h: "Type", r: b => b.name }, { h: "Entitlement", r: b => b.entitlement, cls: "num" },
        { h: "Used", r: b => b.used, cls: "num" }, { h: "Pending", r: b => b.pending, cls: "num" }, { h: "Remaining", r: b => <b>{b.remaining}</b>, cls: "num" }]} /></Card>
    </div>
    {e.records && <Card title="HR records (confidential)" pad={false}><Table rows={e.records} empty="No records" cols={[{ h: "Date", r: r => fmtDate(r.record_date) }, { h: "Kind", r: r => label(r.kind) },
      { h: "Title", r: r => <><b>{r.title}</b>{r.details && <div className="small muted">{r.details}</div>}</> }, { h: "Rating", r: r => r.rating ? "★".repeat(r.rating) : "" }, { h: "By", r: r => r.created_by_name }]} /></Card>}
    {e.payslips && <Card title="Payslips" pad={false}><Table rows={e.payslips} empty="No payslips" cols={[{ h: "Period", r: p => p.period }, { h: "Status", r: p => <Pill s={p.status === "paid" ? "approved" : "pending"} text={label(p.status)} /> },
      { h: "Gross", r: p => money(p.gross, cur), cls: "num" }, { h: "Net", r: p => money(p.net, cur), cls: "num" },
      { h: "", r: p => <button className="link small" onClick={() => openFile(`/api/payslips/${p.id}.pdf`, `payslip-${p.period}.pdf`, true)}>PDF</button> }]} /></Card>}
    {e.loans && e.loans.length > 0 && <Card title="Loans & advances" pad={false}><Table rows={e.loans} cols={[{ h: "Description", r: l => l.description }, { h: "Principal", r: l => money(l.principal, cur), cls: "num" },
      { h: "Monthly", r: l => money(l.monthly_deduction, cur), cls: "num" }, { h: "Balance", r: l => money(l.balance, cur), cls: "num" }, { h: "Status", r: l => <Pill s={l.status === "repaid" ? "approved" : "pending"} text={label(l.status)} /> }]} /></Card>}
    {modal === "edit" && meta.data && <EmployeeModal e={e} meta={meta.data} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
    {modal === "exit" && <ExitModal e={e} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
    {modal === "record" && <RecordModal e={e} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
    {modal === "loan" && <LoanModal e={e} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
  </>}</Loadable></div>;
}

function ExitModal({ e, onClose, onDone }: any) {
  const [f, setF] = useState({ status: "resigned", exit_date: new Date().toISOString().slice(0, 10), exit_reason: "" });
  const { busy, run } = useAction();
  return <Modal title={`Record exit — ${e.first_name} ${e.last_name}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button kind="danger" busy={busy} disabled={!f.exit_reason.trim()} onClick={async () => { if (await run(() => patch(`/api/employees/${e.id}`, f), "Exit recorded")) onDone(); }}>Save</Button></>}>
    <div className="form-grid"><Field label="Type"><Select value={f.status} onChange={x => setF({ ...f, status: x.target.value })}>{["resigned", "terminated", "retired", "suspended"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select></Field>
      <Field label="Last day"><Input type="date" value={f.exit_date} onChange={x => setF({ ...f, exit_date: x.target.value })} /></Field>
      <Field label="Reason (required)" wide><Textarea value={f.exit_reason} onChange={x => setF({ ...f, exit_reason: x.target.value })} /></Field></div>
    <p className="muted small">Their final payroll is pro-rated to the last day automatically.</p></Modal>;
}

function RecordModal({ e, onClose, onDone }: any) {
  const [f, setF] = useState({ kind: "training", record_date: new Date().toISOString().slice(0, 10), title: "", details: "", rating: "" });
  const { busy, run } = useAction();
  return <Modal title="Add HR record" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.title} onClick={async () => { if (await run(() => post(`/api/employees/${e.id}/records`, { ...f, rating: f.rating ? Number(f.rating) : undefined }), "Record added")) onDone(); }}>Save</Button></>}>
    <div className="form-grid"><Field label="Kind"><Select value={f.kind} onChange={x => setF({ ...f, kind: x.target.value })}>{["training", "appraisal", "disciplinary", "commendation", "transfer", "promotion", "document"].map(k => <option key={k} value={k}>{label(k)}</option>)}</Select></Field>
      <Field label="Date"><Input type="date" value={f.record_date} onChange={x => setF({ ...f, record_date: x.target.value })} /></Field>
      <Field label="Title" wide><Input value={f.title} onChange={x => setF({ ...f, title: x.target.value })} /></Field>
      {f.kind === "appraisal" && <Field label="Rating (1–5)"><Input type="number" min={1} max={5} value={f.rating} onChange={x => setF({ ...f, rating: x.target.value })} /></Field>}
      <Field label="Details" wide><Textarea value={f.details} onChange={x => setF({ ...f, details: x.target.value })} /></Field></div></Modal>;
}

function LoanModal({ e, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const methods = useLoad(() => get(`/api/hotels/${hotel!.id}/payment-methods`), [hotel?.id]);
  const [f, setF] = useState({ description: "Salary advance", principal: "", monthly_deduction: "", method_id: "" });
  const { busy, run } = useAction();
  return <Modal title={`Staff loan — ${e.first_name} ${e.last_name}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.method_id || !(toMinor(f.principal) > 0)} onClick={async () => { if (await run(() => post(`/api/employees/${e.id}/loans`, { ...f, principal: toMinor(f.principal), monthly_deduction: toMinor(f.monthly_deduction), method_id: Number(f.method_id) }), "Loan granted")) onDone(); }}>Grant</Button></>}>
    <div className="form-grid"><Field label="Description" wide><Input value={f.description} onChange={x => setF({ ...f, description: x.target.value })} /></Field>
      <Field label="Amount"><Input inputMode="decimal" value={f.principal} onChange={x => setF({ ...f, principal: x.target.value })} /></Field>
      <Field label="Monthly recovery"><Input inputMode="decimal" value={f.monthly_deduction} onChange={x => setF({ ...f, monthly_deduction: x.target.value })} /></Field>
      <Field label="Paid from"><Select value={f.method_id} onChange={x => setF({ ...f, method_id: x.target.value })}><option value="">Select…</option>{(methods.data?.items || []).filter((m: any) => ["cash", "bank_transfer"].includes(m.kind)).map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></Field></div></Modal>;
}

function Roster() {
  const { hotel, can } = useAuth();
  const [start, setStart] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/roster`, { start }), [hotel?.id, start]);
  const [changes, setChanges] = useState<Record<string, any>>({});
  const [newShift, setNewShift] = useState(false);
  const { busy, run } = useAction();
  const shift = (r: any, i: number) => changes[`${r.id}|${st.data.days[i]}`] ?? r.shifts[i] ?? "";
  const move = (n: number) => { const d = new Date(st.data.start + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); setStart(d.toISOString().slice(0, 10)); setChanges({}); };
  return <Loadable state={st}>{d => <Card title={<div className="row gap-s"><Button kind="ghost" onClick={() => move(-7)}>‹</Button><b>Week of {fmtDate(d.start)}</b><Button kind="ghost" onClick={() => move(7)}>›</Button></div>}
    actions={can("hr.attendance") && <div className="row gap-s"><Button kind="secondary" onClick={() => setNewShift(true)}>New shift</Button>
      <Button busy={busy} disabled={!Object.keys(changes).length} onClick={async () => { if (await run(() => put(`/api/hotels/${hotel!.id}/roster`, { assignments: Object.entries(changes).map(([k, v]) => ({ employee_id: Number(k.split("|")[0]), date: k.split("|")[1], shift_id: v ? Number(v) : null })) }), "Roster saved")) { setChanges({}); st.reload(); } }}>Save roster</Button></div>} pad={false}>
    <div className="table-wrap"><table className="table"><thead><tr><th>Employee</th>{d.days.map((x: string) => <th key={x}>{new Date(x + "T00:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "2-digit" })}</th>)}</tr></thead>
      <tbody>{d.rows.map((r: any) => <tr key={r.id}><td><b>{r.first_name} {r.last_name}</b><div className="tiny muted">{label(r.department)}</div></td>
        {d.days.map((x: string, i: number) => <td key={x}>{can("hr.attendance") ? <Select className="sm" value={shift(r, i)} onChange={e => setChanges({ ...changes, [`${r.id}|${x}`]: e.target.value })}>
          <option value="">Off</option>{d.shifts.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select> : (d.shifts.find((s: any) => s.id === r.shifts[i])?.name || "Off")}</td>)}</tr>)}</tbody></table></div>
    {newShift && <ShiftModal onClose={() => setNewShift(false)} onDone={() => { setNewShift(false); st.reload(); }} />}
  </Card>}</Loadable>;
}

function ShiftModal({ onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ name: "", start_time: "07:00", end_time: "15:00" });
  const { busy, run } = useAction();
  return <Modal title="New shift" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button busy={busy} disabled={!f.name} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/shift-templates`, f), "Shift created")) onDone(); }}>Create</Button></>}>
    <div className="form-grid"><Field label="Name"><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Starts"><Input type="time" value={f.start_time} onChange={e => setF({ ...f, start_time: e.target.value })} /></Field>
      <Field label="Ends"><Input type="time" value={f.end_time} onChange={e => setF({ ...f, end_time: e.target.value })} /></Field></div></Modal>;
}

function Attendance() {
  const { hotel, can } = useAuth();
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/attendance`, { date }), [hotel?.id, date]);
  const [rows, setRows] = useState<Record<number, any>>({});
  const { busy, run } = useAction();
  useEffect(() => setRows({}), [date]);
  const val = (r: any, k: string) => rows[r.employee_id]?.[k] ?? r[k] ?? (k === "status" ? "" : k === "overtime_minutes" ? 0 : "");
  const set = (r: any, k: string, v: any) => setRows({ ...rows, [r.employee_id]: { ...{ status: r.status || "present", clock_in: r.clock_in, clock_out: r.clock_out, overtime_minutes: r.overtime_minutes || 0, note: r.note }, ...rows[r.employee_id], [k]: v } });
  return <Loadable state={st}>{d => <Card title={<div className="row gap-s"><Input type="date" value={date} onChange={e => setDate(e.target.value)} />
    {Object.entries(d.summary).map(([k, v]) => <span key={k} className="chip">{label(k)}: <b>{String(v)}</b></span>)}</div>}
    actions={can("hr.attendance") && <div className="row gap-s"><Button kind="ghost" onClick={() => { const all: any = {}; d.items.filter((r: any) => !r.status && r.shift).forEach((r: any) => { all[r.employee_id] = { status: "present", clock_in: r.start_time, clock_out: r.end_time, overtime_minutes: 0 }; }); setRows({ ...all, ...rows }); }}>Mark rostered staff present</Button>
      <Button busy={busy} disabled={!Object.keys(rows).length} onClick={async () => { if (await run(() => put(`/api/hotels/${hotel!.id}/attendance`, { date, rows: Object.entries(rows).map(([id, r]) => ({ employee_id: Number(id), ...r })) }), "Attendance saved")) { setRows({}); st.reload(); } }}>Save</Button></div>} pad={false}>
    <Table rows={d.items} cols={[{ h: "Employee", r: r => <><b>{r.first_name} {r.last_name}</b><div className="tiny muted">{label(r.department)}</div></> },
      { h: "Rostered", r: r => r.shift ? `${r.shift} ${r.start_time}–${r.end_time}` : <span className="muted">Off</span> },
      { h: "Status", r: r => can("hr.attendance") ? <Select className="sm" value={val(r, "status")} onChange={e => set(r, "status", e.target.value)}><option value="">—</option>{["present", "late", "absent", "leave", "off"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select> : label(r.status || "—") },
      { h: "In", r: r => can("hr.attendance") ? <Input className="sm" type="time" value={val(r, "clock_in") || ""} onChange={e => set(r, "clock_in", e.target.value)} /> : r.clock_in || "—" },
      { h: "Out", r: r => can("hr.attendance") ? <Input className="sm" type="time" value={val(r, "clock_out") || ""} onChange={e => set(r, "clock_out", e.target.value)} /> : r.clock_out || "—" },
      { h: "Overtime (min)", r: r => can("hr.attendance") ? <Input className="sm" type="number" min={0} value={val(r, "overtime_minutes")} onChange={e => set(r, "overtime_minutes", Number(e.target.value))} /> : r.overtime_minutes },
      { h: "Note", r: r => r.note || "" }]} /></Card>}</Loadable>;
}

function Leave() {
  const { hotel, can, user } = useAuth();
  const [status, setStatus] = useState("pending");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/leave`, { status }), [hotel?.id, status]);
  const [reject, setReject] = useState<any>(null);
  const [types, setTypes] = useState(false);
  const { busy, run } = useAction();
  return <Loadable state={st}>{d => <Card title={<Select value={status} onChange={e => setStatus(e.target.value)}><option value="">All requests</option>{["pending", "approved", "rejected"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select>}
    actions={can("hr.manage") && <Button kind="secondary" onClick={() => setTypes(true)}>Leave types</Button>} pad={false}>
    <Table rows={d.items} empty="No leave requests" cols={[{ h: "Employee", r: l => <><b>{l.employee}</b><div className="tiny muted">{label(l.department)}</div></> }, { h: "Type", r: l => l.leave_type },
      { h: "Dates", r: l => `${fmtDate(l.start_date)} → ${fmtDate(l.end_date)}` }, { h: "Days", r: l => l.days, cls: "num" }, { h: "Reason", r: l => l.reason || "" },
      { h: "Status", r: l => <span title={l.decision_note || ""}><Pill s={l.status} /></span> },
      { h: "", r: l => l.status === "pending" && can("hr.leave.approve") && l.user_id !== user!.id && <span className="row gap-s">
        <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/leave/${l.id}/decide`, { decision: "approve" }), "Leave approved")) st.reload(); }}>Approve</Button>
        <Button kind="ghost" onClick={() => setReject(l)}>Reject</Button></span> }]} />
    {reject && <RejectModal title={`Reject leave for ${reject.employee}`} onClose={() => setReject(null)} onReject={async (note: string) => { if (await run(() => post(`/api/leave/${reject.id}/decide`, { decision: "reject", note }), "Leave rejected")) { setReject(null); st.reload(); } }} />}
    {types && <Modal title="Leave types" width={640} onClose={() => setTypes(false)}><Table rows={d.types} cols={[{ h: "Code", r: t => t.code }, { h: "Name", r: t => t.name }, { h: "Days / year", r: t => t.days_per_year, cls: "num" }, { h: "Paid", r: t => t.paid ? "Yes" : "No" },
      { h: "", r: t => <button className="link small" onClick={async () => { const v = prompt(`Days per year for ${t.name}`, String(t.days_per_year)); if (v !== null && await run(() => post(`/api/hotels/${hotel!.id}/leave-types`, { code: t.code, name: t.name, days_per_year: Number(v), paid: !!t.paid }), "Saved")) st.reload(); }}>Change</button> }]} /></Modal>}
  </Card>}</Loadable>;
}

// ======================================================================== Payroll
export function Payroll() {
  const { hotel, can } = useAuth();
  const [tab, setTab] = useState("runs");
  const runs = useLoad(() => get(`/api/hotels/${hotel!.id}/payroll/runs`), [hotel?.id]);
  const [open, setOpen] = useState<number | null>(null);
  const [period, setPeriod] = useState(new Date().toISOString().slice(0, 7));
  const { busy, run } = useAction();
  const cur = hotel!.currency;
  if (open) return <div className="page"><RunDetail id={open} onClose={() => { setOpen(null); runs.reload(); }} /></div>;
  return <div className="page">
    <div className="page-h"><div><h1>Payroll</h1><p className="muted">Prepared by HR, approved by finance, paid and remitted by accounts</p></div>
      {can("payroll.run") && <div className="row gap-s"><Input type="month" value={period} onChange={e => setPeriod(e.target.value)} />
        <Button busy={busy} onClick={async () => { const r = await run(() => post(`/api/hotels/${hotel!.id}/payroll/runs`, { period }), "Payroll prepared"); if (r) setOpen(r.id); }}>Prepare payroll</Button></div>}</div>
    <Tabs tabs={[{ id: "runs", label: "Payroll runs" }, { id: "rules", label: "Statutory rules" }]} value={tab} onChange={setTab} />
    {tab === "runs" ? <Card pad={false}><Loadable state={runs}>{d => <Table rows={d.items} onRow={r => setOpen(r.id)} empty="No payroll runs yet" cols={[{ h: "Period", r: r => <b>{r.period}</b> },
      { h: "Employees", r: r => r.employees, cls: "num" }, { h: "Gross", r: r => money(r.gross, cur), cls: "num" }, { h: "PAYE", r: r => money(r.paye, cur), cls: "num" },
      { h: "Net", r: r => money(r.net, cur), cls: "num" }, { h: "Employer cost", r: r => money(r.employer_cost, cur), cls: "num" },
      { h: "Status", r: r => <Pill s={r.status === "paid" ? "approved" : r.status === "approved" ? "confirmed" : "draft"} text={label(r.status)} /> },
      { h: "Prepared / approved", r: r => `${r.created_by_name}${r.approved_by_name ? " / " + r.approved_by_name : ""}` }]} />}</Loadable></Card> : <Rules />}
  </div>;
}

function RunDetail({ id, onClose }: any) {
  const { hotel, can, user } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/payroll/runs/${id}`), [id]);
  const methods = useLoad(() => get(`/api/hotels/${hotel!.id}/payment-methods`), [hotel?.id]);
  const [modal, setModal] = useState<any>(null);
  const { busy, run } = useAction();
  const bankish = (methods.data?.items || []).filter((m: any) => ["bank_transfer", "cash"].includes(m.kind));
  return <Loadable state={st}>{r => <>
    <div className="page-h"><div><h1>Payroll {r.period} <Pill s={r.status === "paid" ? "approved" : r.status === "approved" ? "confirmed" : "draft"} text={label(r.status)} /></h1>
      <p className="muted">{r.employees} employees · prepared by {r.created_by_name}{r.approved_by_name ? ` · approved by ${r.approved_by_name}` : ""}</p></div>
      <div className="row gap-s wrap">
        {r.status === "draft" && can("payroll.run") && <><Button kind="secondary" onClick={() => setModal({ kind: "adj" })}>Bonus / deduction</Button>
          <Button kind="ghost" busy={busy} onClick={async () => { if (await run(() => post(`/api/payroll/runs/${id}/recalculate`, {}), "Recalculated")) st.reload(); }}>Recalculate</Button></>}
        {r.status === "draft" && can("payroll.approve") && r.created_by !== user!.id && <Button kind="gold" busy={busy} onClick={async () => { if (confirm("Approve this payroll? The salary journal is posted and loan repayments are applied.") && await run(() => post(`/api/payroll/runs/${id}/approve`, {}), "Payroll approved")) st.reload(); }}>Approve</Button>}
        {r.status === "approved" && can("payroll.pay") && <Button kind="gold" onClick={() => setModal({ kind: "pay" })}>Record salary payment</Button>}
        {r.status !== "draft" && can("payroll.pay") && <Button kind="secondary" onClick={() => openFile(`/api/payroll/runs/${id}/bank-schedule.csv`, `bank-schedule-${r.period}.csv`)}>Bank schedule (CSV)</Button>}
        <Button kind="secondary" onClick={onClose}>Back</Button></div></div>
    {r.warnings.length > 0 && <div className="note">{r.warnings.map((w: string) => <div key={w}>⚠ {w}</div>)}</div>}
    <div className="kpis"><Kpi title="Gross pay" value={money(r.totals.gross, cur)} tone="navy" /><Kpi title="Net pay" value={money(r.totals.net, cur)} /><Kpi title="PAYE" value={money(r.totals.paye, cur)} />
      <Kpi title="Pension (employee + employer)" value={money(r.totals.pension_employee + r.totals.pension_employer, cur)} /></div>
    {r.status !== "draft" && can("payroll.pay") && <Card title="Statutory remittances"><div className="row gap-s wrap">{Object.entries(r.remittances).map(([k, v]: any) => <span key={k} className="chip">
      {k.toUpperCase()}: <b>{money(v, cur)}</b> {r.remitted.includes(k) ? <Pill s="approved" text="Remitted" /> : v > 0 && <button className="link small" onClick={() => setModal({ kind: "remit", liability: k, amount: v })}>Remit</button>}</span>)}</div></Card>}
    <Card pad={false}><Table rows={r.payslips} cols={[{ h: "Employee", r: s => <><b>{s.employee}</b><div className="tiny muted">{s.employee_no} · {label(s.department)}</div></> },
      { h: "Gross", r: s => money(s.gross, cur), cls: "num" }, { h: "Absent", r: s => s.days_absent || "", cls: "num" }, { h: "Overtime", r: s => s.overtime ? money(s.overtime, cur) : "", cls: "num" },
      { h: "PAYE", r: s => money(s.paye, cur), cls: "num" }, { h: "Pension", r: s => money(s.pension_employee, cur), cls: "num" }, { h: "NHF", r: s => money(s.nhf, cur), cls: "num" },
      { h: "Loan / other", r: s => money(s.loan_deduction + s.other_deduction, cur), cls: "num" }, { h: "Net", r: s => <b className={s.net < 0 ? "danger" : ""}>{money(s.net, cur)}</b>, cls: "num" },
      { h: "", r: s => <button className="link small" onClick={() => openFile(`/api/payslips/${s.id}.pdf`, `payslip-${s.employee_no}-${r.period}.pdf`, true)}>Payslip</button> }]} /></Card>
    {r.adjustments.length > 0 && <Card title="Adjustments" pad={false}><Table rows={r.adjustments} cols={[{ h: "Employee", r: a => a.employee }, { h: "Kind", r: a => label(a.kind) }, { h: "Amount", r: a => money(a.amount, cur), cls: "num" }, { h: "Note", r: a => a.note }]} /></Card>}
    {modal?.kind === "adj" && <AdjustmentModal run={r} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
    {modal && ["pay", "remit"].includes(modal.kind) && <PayModal title={modal.kind === "pay" ? `Pay net salaries ${money(r.totals.net, cur)}` : `Remit ${modal.liability.toUpperCase()} ${money(modal.amount, cur)}`} methods={bankish}
      onClose={() => setModal(null)} onPay={async (f: any) => { if (await run(() => post(`/api/payroll/runs/${id}/${modal.kind}`, { ...f, liability: modal.liability }), "Recorded")) { setModal(null); st.reload(); } }} />}
  </>}</Loadable>;
}

function AdjustmentModal({ run: r, onClose, onDone }: any) {
  const [f, setF] = useState({ employee_id: r.payslips[0]?.employee_id || "", kind: "bonus", amount: "", note: "" });
  const { busy, run } = useAction();
  return <Modal title="Bonus or deduction" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!(toMinor(f.amount) > 0) || !f.note} onClick={async () => { if (await run(() => post(`/api/payroll/runs/${r.id}/adjustments`, { ...f, employee_id: Number(f.employee_id), amount: toMinor(f.amount) }), "Adjustment added")) onDone(); }}>Add</Button></>}>
    <div className="form-grid"><Field label="Employee"><Select value={f.employee_id} onChange={e => setF({ ...f, employee_id: e.target.value })}>{r.payslips.map((s: any) => <option key={s.employee_id} value={s.employee_id}>{s.employee}</option>)}</Select></Field>
      <Field label="Kind"><Select value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}><option value="bonus">Bonus (taxable)</option><option value="deduction">Deduction</option></Select></Field>
      <Field label="Amount"><Input inputMode="decimal" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} /></Field>
      <Field label="Note (required)" wide><Input value={f.note} onChange={e => setF({ ...f, note: e.target.value })} /></Field></div></Modal>;
}

function PayModal({ title, methods, onClose, onPay }: any) {
  const [f, setF] = useState({ method_id: methods[0]?.id || "", reference: "" });
  return <Modal title={title} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button kind="gold" onClick={() => onPay({ method_id: Number(f.method_id), reference: f.reference || undefined })}>Record</Button></>}>
    <div className="form-grid"><Field label="From"><Select value={f.method_id} onChange={e => setF({ ...f, method_id: e.target.value })}>{methods.map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></Field>
      <Field label="Reference"><Input value={f.reference} onChange={e => setF({ ...f, reference: e.target.value })} /></Field></div></Modal>;
}

function Rules() {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/payroll/rules`), [hotel?.id]);
  const [text, setText] = useState("");
  const { busy, run } = useAction();
  useEffect(() => { if (st.data) setText(JSON.stringify(st.data.rules, null, 2)); }, [st.data]);
  const bp = (v: number) => `${v / 100}%`;
  return <Loadable state={st}>{d => <div className="grid-2">
    <Card title="Rules in force"><dl className="dl">
      <dt>Working days / month</dt><dd>{d.rules.working_days}</dd><dt>Pension</dt><dd>{bp(d.rules.pension_employee_bp)} employee, {bp(d.rules.pension_employer_bp)} employer on {d.rules.pension_base.join(" + ")}</dd>
      <dt>NHF</dt><dd>{bp(d.rules.nhf_bp)} of basic</dd><dt>NSITF / ITF</dt><dd>{bp(d.rules.nsitf_employer_bp)} / {bp(d.rules.itf_employer_bp)} of gross (employer)</dd>
      <dt>Rent relief</dt><dd>{bp(d.rules.rent_relief_bp)} of rent, max {money(d.rules.rent_relief_cap, hotel!.currency)}</dd><dt>Overtime</dt><dd>× {d.rules.overtime_multiplier_bp / 10000}</dd>
      <dt>PAYE bands (annual)</dt><dd>{d.rules.paye_bands.map((b: any, i: number) => <div key={i}>{b[0] === null ? "Above" : `Next ${money(b[0], hotel!.currency)}`}: {bp(b[1])}</div>)}</dd></dl>
      <p className="muted small">Defaults follow Nigerian rules as commonly applied from 2026. Confirm every rate with your tax and payroll advisers; each payroll run stores the rules it used.</p></Card>
    {can("payroll.approve") && <Card title="Change rules (JSON)"><Textarea rows={18} value={text} onChange={e => setText(e.target.value)} className="mono small" />
      <Button busy={busy} className="mt" onClick={async () => { let body; try { body = JSON.parse(text); } catch { alert("Invalid JSON"); return; } if (await run(() => put(`/api/hotels/${hotel!.id}/payroll/rules`, body), "Payroll rules saved")) st.reload(); }}>Save rules</Button></Card>}
  </div>}</Loadable>;
}

// ======================================================================== My HR (self-service)
export function MyHR() {
  const st = useLoad(() => get(`/api/me/employee`), []);
  const [leave, setLeave] = useState(false);
  const { busy, run } = useAction();
  const { hotel } = useAuth();
  const cur = hotel?.currency || "NGN";
  return <div className="page"><Loadable state={st}>{d => !d.linked ? <Empty text="Your account is not linked to an employee record. Ask HR to link it." /> : <>
    <div className="page-h"><div><h1>My HR</h1><p className="muted">{d.employee.first_name} {d.employee.last_name} · {d.employee.employee_no} · {d.employee.position}</p></div>
      <div className="row gap-s">
        {!d.today?.clock_in ? <Button kind="gold" busy={busy} onClick={async () => { if (await run(() => post("/api/me/clock", { action: "in" }), "Clocked in")) st.reload(); }}>Clock in</Button>
          : !d.today?.clock_out ? <Button kind="secondary" busy={busy} onClick={async () => { if (await run(() => post("/api/me/clock", { action: "out" }), "Clocked out")) st.reload(); }}>Clock out (in since {d.today.clock_in})</Button>
          : <span className="chip">Today {d.today.clock_in}–{d.today.clock_out}</span>}
        <Button onClick={() => setLeave(true)}>Request leave</Button></div></div>
    {d.shift_today && <p className="note">Today's shift: {d.shift_today.name} {d.shift_today.start_time}–{d.shift_today.end_time}</p>}
    <div className="grid-2">
      <Card title="Leave balances" pad={false}><Table rows={d.leave_balances} cols={[{ h: "Type", r: b => b.name }, { h: "Remaining", r: b => <b>{b.remaining}</b>, cls: "num" }, { h: "Used", r: b => b.used, cls: "num" }, { h: "Pending", r: b => b.pending, cls: "num" }]} /></Card>
      <Card title="My leave requests" pad={false}><Table rows={d.leave_requests} empty="None yet" cols={[{ h: "Type", r: l => l.leave_type }, { h: "Dates", r: l => `${fmtDate(l.start_date)} → ${fmtDate(l.end_date)}` }, { h: "Days", r: l => l.days, cls: "num" }, { h: "Status", r: l => <span title={l.decision_note || ""}><Pill s={l.status} /></span> }]} /></Card>
    </div>
    <Card title="My payslips" pad={false}><Table rows={d.payslips} empty="No payslips yet" cols={[{ h: "Period", r: p => p.period }, { h: "Gross", r: p => money(p.gross, cur), cls: "num" }, { h: "Net", r: p => money(p.net, cur), cls: "num" },
      { h: "", r: p => <button className="link small" onClick={() => openFile(`/api/payslips/${p.id}.pdf`, `payslip-${p.period}.pdf`, true)}>Download</button> }]} /></Card>
    <Card title="My attendance this month" pad={false}><Table rows={d.attendance} empty="No attendance recorded this month" cols={[{ h: "Date", r: a => fmtDate(a.work_date) }, { h: "Status", r: a => label(a.status) }, { h: "In", r: a => a.clock_in || "—" }, { h: "Out", r: a => a.clock_out || "—" }]} /></Card>
    {leave && <MyLeaveModal balances={d.leave_balances} onClose={() => setLeave(false)} onDone={() => { setLeave(false); st.reload(); }} />}
  </>}</Loadable></div>;
}

function MyLeaveModal({ balances, onClose, onDone }: any) {
  const [f, setF] = useState({ leave_type_id: balances[0]?.leave_type_id || "", start_date: "", end_date: "", reason: "" });
  const { busy, run } = useAction();
  return <Modal title="Request leave" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.start_date || !f.end_date} onClick={async () => { if (await run(() => post("/api/me/leave", { ...f, leave_type_id: Number(f.leave_type_id) }), "Leave requested")) onDone(); }}>Submit</Button></>}>
    <div className="form-grid"><Field label="Type"><Select value={f.leave_type_id} onChange={e => setF({ ...f, leave_type_id: e.target.value })}>{balances.map((b: any) => <option key={b.leave_type_id} value={b.leave_type_id}>{b.name} ({b.remaining - b.pending} left)</option>)}</Select></Field>
      <Field label="From"><Input type="date" value={f.start_date} onChange={e => setF({ ...f, start_date: e.target.value, end_date: f.end_date || e.target.value })} /></Field>
      <Field label="To"><Input type="date" value={f.end_date} onChange={e => setF({ ...f, end_date: e.target.value })} /></Field>
      <Field label="Reason" wide><Input value={f.reason} onChange={e => setF({ ...f, reason: e.target.value })} /></Field></div>
    <p className="muted small">Days are counted Monday to Saturday.</p></Modal>;
}
