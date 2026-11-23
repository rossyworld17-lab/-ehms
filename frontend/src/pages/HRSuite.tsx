import React, { useState } from "react";
import { del, fmtDate, fmtDateTime, get, label, money, openFile, post, toMinor } from "../api";
import { navigate, useAuth } from "../state";
import { Button, Card, Empty, Field, Input, Kpi, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, errText, useAction, useLoad, useToast } from "../ui";
import { DocumentsPanel } from "./Documents";

const REQ_LABEL: Record<string, string> = { salary_advance: "Salary advance", loan: "Staff loan", letter: "Employment letter", data_change: "Change of details",
  shift_swap: "Shift swap", grievance: "Grievance (confidential)", other: "Other request" };
const reqPill = (s: string) => <Pill s={s === "completed" ? "approved" : s === "submitted" ? "pending" : s} text={label(s)} />;

// ======================================================================== HR dashboard
export function HRDashboard({ go }: { go: (tab: string) => void }) {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/hr/dashboard`), [hotel?.id]);
  return <Loadable state={st}>{d => <div className="stack">
    <div className="kpis">
      <Kpi title="Active staff" value={d.headcount} tone="navy" sub={`${d.joiners_this_month.length} joined · ${d.leavers_this_month.length} left this month`} />
      <Kpi title="On leave today" value={d.on_leave_today.length} />
      <Kpi title="Leave awaiting approval" value={d.pending.leave} tone={d.pending.leave ? "gold" : undefined} sub={<button className="link small" onClick={() => go("leave")}>Review</button>} />
      <Kpi title="Staff requests waiting" value={d.pending.requests} tone={d.pending.requests ? "gold" : undefined} sub={<button className="link small" onClick={() => go("requests")}>Review</button>} />
      <Kpi title="Appraisals not yet acknowledged" value={d.pending.appraisals_unacknowledged} />
    </div>
    <div className="grid-2">
      <Card title="Needs attention">
        {!d.alerts.probation_ending.length && !d.alerts.contracts_ending.length && !d.alerts.certifications_expiring.length && !d.logins_without_employee.length ? <p className="muted">Nothing needs attention.</p> : <ul className="alert-list">
          {d.alerts.probation_ending.map((x: any) => <li key={`p${x.id}`}><a href={`#/hr/employees/${x.id}`}>{x.name}</a> — probation ends {fmtDate(x.date)}: confirm or extend</li>)}
          {d.alerts.contracts_ending.map((x: any) => <li key={`c${x.id}`}><a href={`#/hr/employees/${x.id}`}>{x.name}</a> — contract ends {fmtDate(x.date)}: renew or plan the exit</li>)}
          {d.alerts.certifications_expiring.map((x: any, i: number) => <li key={`t${i}`}><a href={`#/hr/employees/${x.id}`}>{x.name}</a> — {x.title} {x.expired ? <b className="danger">expired</b> : "expires"} {fmtDate(x.date)}</li>)}
          {d.logins_without_employee.map((u: any) => <li key={`u${u.id}`}>{u.full_name} ({u.email}) has a login but no employee record, so cannot use My HR — create the employee and choose this login</li>)}
        </ul>}
      </Card>
      <Card title="Staff by department"><Table rows={d.by_department} rowKey={x => x.department} cols={[{ h: "Department", r: x => label(x.department) }, { h: "Staff", r: x => x.count, cls: "num" }]} /></Card>
      <Card title="On leave today" pad={false}><Table rows={d.on_leave_today} empty="Nobody is on leave today" cols={[{ h: "Name", r: x => x.name }, { h: "Department", r: x => label(x.department) }, { h: "Leave", r: x => x.type }, { h: "Back after", r: x => fmtDate(x.until) }]} /></Card>
      <Card title="Celebrations">
        {d.birthdays.length || d.anniversaries.length ? <ul className="alert-list">
          {d.birthdays.map((b: any) => <li key={`b${b.id}`}>🎂 {b.name} — birthday {fmtDate(b.date)}</li>)}
          {d.anniversaries.map((a: any) => <li key={`a${a.id}`}>{a.name} — {a.years} year(s) with us ({fmtDate(a.date)})</li>)}</ul> : <p className="muted">No birthdays in the next two weeks.</p>}
        {d.holidays.length > 0 && <><h4 className="mt">Coming public holidays</h4><ul className="alert-list">{d.holidays.map((h: any) => <li key={h.id}>{fmtDate(h.holiday_date)} — {h.name}</li>)}</ul></>}
      </Card>
      {d.staff_without_login.length > 0 && <Card title="Staff without a system login" pad={false}><Table rows={d.staff_without_login} onRow={x => navigate(`/hr/employees/${x.id}`)} cols={[{ h: "Name", r: x => x.name }, { h: "Department", r: x => label(x.department) }, { h: "Email", r: x => x.email || <span className="muted">none</span> }]} />
        <p className="muted small pad">Open an employee and use <b>Give system access</b> so they can apply for leave and use My HR.</p></Card>}
    </div>
  </div>}</Loadable>;
}

// ======================================================================== staff requests (HR side)
export function StaffRequests() {
  const { hotel, can, user } = useAuth();
  const [status, setStatus] = useState("submitted");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/hr/requests`, status ? { status } : {}), [hotel?.id, status]);
  const [open, setOpen] = useState<any>(null);
  const [note, setNote] = useState("");
  const { busy, run } = useAction();
  const cur = hotel!.currency;
  const decide = async (decision: string) => { if (await run(() => post(`/api/hr/requests/${open.id}/decide`, { decision, note: note || undefined }), decision === "approve" ? "Approved" : "Rejected")) { setOpen(null); setNote(""); st.reload(); } };
  return <Loadable state={st}>{d => <div className="stack">
    <div className="row gap-s wrap">{[["submitted", "Waiting"], ["approved", "Approved — to pay"], ["completed", "Done"], ["rejected", "Rejected"], ["", "All"]].map(([k, l]) => <Button key={k} kind={k === status ? "primary" : "secondary"} onClick={() => setStatus(k)}>{l}</Button>)}</div>
    <Card pad={false}><Table rows={d.items} onRow={setOpen} empty="No requests" cols={[{ h: "Ref", r: r => r.number }, { h: "Employee", r: r => <><b>{r.employee}</b><div className="tiny muted">{label(r.department)}</div></> },
      { h: "Request", r: r => <><b>{REQ_LABEL[r.kind]}</b><div className="small muted">{r.subject}</div></> }, { h: "Amount", r: r => r.amount ? money(r.amount, cur) : "", cls: "num" },
      { h: "Sent", r: r => fmtDate(r.created_at) }, { h: "Status", r: r => reqPill(r.status) }]} /></Card>
    {open && <Modal title={`${REQ_LABEL[open.kind]} — ${open.employee}`} onClose={() => { setOpen(null); setNote(""); }} width={600} footer={<><Button kind="secondary" onClick={() => setOpen(null)}>Close</Button>
      {open.kind === "letter" && open.status === "completed" && <Button kind="ghost" onClick={() => openFile(`/api/hr/requests/${open.id}/letter.pdf`, `${open.number}.pdf`, true)}>Letter PDF</Button>}
      {open.status === "approved" && can("payroll.pay") && <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/hr/requests/${open.id}/complete`), "Marked as paid")) { setOpen(null); st.reload(); } }}>Mark as paid</Button>}
      {open.status === "submitted" && can("hr.requests.approve") && open.user_id !== user!.id && <>
        <Button kind="danger" busy={busy} disabled={!note.trim()} onClick={() => decide("reject")}>Reject</Button>
        <Button busy={busy} onClick={() => decide("approve")}>{open.kind === "grievance" || open.kind === "other" ? "Resolve" : "Approve"}</Button></>}</>}>
      <dl className="dl"><dt>Reference</dt><dd>{open.number}</dd><dt>Subject</dt><dd>{open.subject}</dd>{open.details && <><dt>Details</dt><dd>{open.details}</dd></>}
        {open.amount && <><dt>Amount</dt><dd>{money(open.amount, cur)} over {open.months} month(s)</dd></>}
        {open.data && open.kind === "data_change" && <><dt>New details</dt><dd>{Object.entries(open.data).map(([k, v]) => <div key={k}>{label(k)}: <b>{String(v)}</b></div>)}</dd></>}
        {open.data && open.kind === "shift_swap" && <><dt>Swap</dt><dd>{fmtDate(open.data.date)} with {open.data.with_name}</dd></>}
        <dt>Status</dt><dd>{reqPill(open.status)}</dd>{open.decided_by_name && <><dt>Decided</dt><dd>{open.decided_by_name}, {fmtDateTime(open.decided_at)}{open.decision_note ? ` — ${open.decision_note}` : ""}</dd></>}</dl>
      {open.status === "submitted" && can("hr.requests.approve") && (open.user_id === user!.id ? <p className="muted small mt">This is your own request; another HR approver must decide it.</p>
        : <><Field label={open.kind === "grievance" ? "Resolution / note (required to reject)" : "Note (required to reject)"} wide><Textarea value={note} onChange={e => setNote(e.target.value)} /></Field>
          <p className="muted small">{open.kind === "data_change" ? "Approving updates the employee's record." : open.kind === "shift_swap" ? "Approving swaps the two shifts on the roster." :
            open.kind === "letter" ? "Approving issues the employment letter; the employee downloads it from My HR." : ["salary_advance", "loan"].includes(open.kind) ? "Approving sends it to payroll, who pay it out as a staff loan and mark it paid." : ""}</p></>)}
    </Modal>}
  </div>}</Loadable>;
}

// ======================================================================== performance
export function Performance() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/hr/appraisals`), [hotel?.id]);
  const [open, setOpen] = useState<any>(null);
  return <Loadable state={st}>{d => <div className="stack">
    <div className="kpis"><Kpi title="Appraisals" value={d.items.length} tone="navy" /><Kpi title="Drafts" value={d.items.filter((a: any) => a.status === "draft").length} />
      <Kpi title="Waiting for employee" value={d.items.filter((a: any) => a.status === "shared").length} /><Kpi title="Acknowledged" value={d.items.filter((a: any) => a.status === "acknowledged").length} /></div>
    <p className="muted small">Start an appraisal from the employee's profile (Human resources → Employees → open the person → New appraisal).</p>
    <Card pad={false}><Table rows={d.items} onRow={setOpen} empty="No appraisals yet" cols={[{ h: "Employee", r: a => <><b>{a.employee}</b><div className="tiny muted">{a.position}</div></> },
      { h: "Period", r: a => a.period }, { h: "Rating", r: a => <span className="stars-ro">{"★".repeat(a.overall_rating || 0)}<span className="muted">{"★".repeat(5 - (a.overall_rating || 0))}</span></span> },
      { h: "Reviewer", r: a => a.reviewer }, { h: "Status", r: a => <Pill s={a.status === "acknowledged" ? "approved" : a.status === "shared" ? "pending" : "draft"} text={label(a.status)} /> }]} /></Card>
    {open && <AppraisalModal a={open} onClose={() => { setOpen(null); st.reload(); }} />}
  </div>}</Loadable>;
}

function AppraisalModal({ a, onClose }: any) {
  const { can } = useAuth();
  const { busy, run } = useAction();
  return <Modal title={`Appraisal — ${a.employee || ""} ${a.period}`} width={640} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    {a.status === "draft" && can("hr.performance") && <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/appraisals/${a.id}/share`), "Shared with the employee")) onClose(); }}>Share with employee</Button>}</>}>
    <Table rows={a.criteria} rowKey={c => c.name} cols={[{ h: "Criterion", r: c => c.name }, { h: "Rating", r: c => "★".repeat(c.rating) }, { h: "Comment", r: c => <span className="small">{c.comment}</span> }]} />
    <dl className="dl mt"><dt>Overall</dt><dd>{a.overall_rating} / 5</dd>{a.strengths && <><dt>Strengths</dt><dd>{a.strengths}</dd></>}{a.improvements && <><dt>To improve</dt><dd>{a.improvements}</dd></>}
      {a.goals && <><dt>Goals</dt><dd>{a.goals}</dd></>}{a.employee_comment && <><dt>Employee's comment</dt><dd>{a.employee_comment}</dd></>}</dl></Modal>;
}

// ======================================================================== training register
export function TrainingRegister() {
  const { hotel } = useAuth();
  const [exp, setExp] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/hr/trainings`, exp ? { expiring: exp } : {}), [hotel?.id, exp]);
  const today = new Date().toISOString().slice(0, 10);
  return <div className="stack"><div className="row gap-s">{[["", "All"], ["60", "Expiring in 60 days"]].map(([k, l]) => <Button key={k} kind={k === exp ? "primary" : "secondary"} onClick={() => setExp(k)}>{l}</Button>)}</div>
    <Loadable state={st}>{d => <Card pad={false}><Table rows={d.items} onRow={t => navigate(`/hr/employees/${t.employee_id}`)} empty="No training recorded" cols={[{ h: "Employee", r: t => <><b>{t.employee}</b><div className="tiny muted">{label(t.department)}</div></> },
      { h: "Training / certificate", r: t => <><b>{t.title}</b><div className="small muted">{label(t.kind)}{t.provider ? ` · ${t.provider}` : ""}</div></> },
      { h: "Completed", r: t => fmtDate(t.completed_on) }, { h: "Expires", r: t => t.expires_on ? <span className={t.expires_on < today ? "danger" : ""}>{fmtDate(t.expires_on)}</span> : "—" }]} /></Card>}</Loadable></div>;
}

// ======================================================================== leave views
export function LeaveCalendar() {
  const { hotel } = useAuth();
  const now = new Date();
  const [from, setFrom] = useState(new Date(now.getFullYear(), now.getMonth(), 1).toISOString().slice(0, 10));
  const st = useLoad(() => { const f = new Date(from + "T00:00:00Z"); const t = new Date(f); t.setUTCDate(t.getUTCDate() + 34); return get(`/api/hotels/${hotel!.id}/hr/leave-calendar`, { from, to: t.toISOString().slice(0, 10) }); }, [hotel?.id, from]);
  const move = (n: number) => { const d = new Date(from + "T00:00:00Z"); d.setUTCMonth(d.getUTCMonth() + n); setFrom(d.toISOString().slice(0, 10)); };
  return <Loadable state={st}>{d => { const people = Array.from(new Map(d.items.map((x: any) => [x.employee_id, x])).values()) as any[]; const hol = new Set(d.holidays.map((h: any) => String(h.holiday_date).slice(0, 10)));
    return <Card title={<div className="row gap-s"><Button kind="ghost" onClick={() => move(-1)}>‹</Button><b>{fmtDate(d.from)} – {fmtDate(d.to)}</b><Button kind="ghost" onClick={() => move(1)}>›</Button></div>} pad={false}>
      {!people.length ? <Empty text="Nobody is on leave in this period" /> : <div className="table-wrap"><table className="table heat"><thead><tr><th>Employee</th>{d.days.map((x: string) => <th key={x} className={hol.has(x) ? "hol" : ""} title={x}>{x.slice(8)}</th>)}</tr></thead>
        <tbody>{people.map((p: any) => <tr key={p.employee_id}><td>{p.employee}<div className="tiny muted">{label(p.department)}</div></td>{d.days.map((x: string) => { const l = d.items.find((i: any) => i.employee_id === p.employee_id && i.start_date <= x && x <= i.end_date);
          return <td key={x} className={l ? (l.status === "approved" ? "lv-on" : "lv-pend") : hol.has(x) ? "hol" : ""} title={l ? `${l.leave_type} (${l.status})` : hol.has(x) ? "Public holiday" : ""}>{l ? l.code.slice(0, 1) : ""}</td>; })}</tr>)}
          <tr><td className="muted small">Staff off</td>{d.days.map((x: string) => <td key={x} className="small">{d.off_per_day[x] || ""}</td>)}</tr></tbody></table></div>}
      <p className="muted small pad">Dark = approved, light = waiting for approval, shaded column = public holiday. Letters show the leave type (A annual, S sick…).</p></Card>; }}</Loadable>;
}

export function LeaveBalances() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/hr/leave-balances`), [hotel?.id]);
  return <Loadable state={st}>{d => <Card title={`Leave balances ${d.year}`} pad={false}><div className="table-wrap"><table className="table"><thead><tr><th>Employee</th>{d.types.map((t: any) => <th key={t.id} className="num">{t.name}</th>)}</tr></thead>
    <tbody>{d.items.map((r: any) => <tr key={r.employee_id} className="clickable" onClick={() => navigate(`/hr/employees/${r.employee_id}`)}><td><b>{r.employee}</b><div className="tiny muted">{label(r.department)}</div></td>
      {d.types.map((t: any) => { const b = r.balances.find((x: any) => x.leave_type_id === t.id); return <td key={t.id} className="num" title={b ? `entitlement ${b.entitlement}, used ${b.used}, pending ${b.pending}` : ""}>{b ? <><b>{b.remaining}</b><span className="muted small"> / {b.entitlement}</span></> : "—"}</td>; })}</tr>)}</tbody></table></div>
    <p className="muted small pad">Remaining / entitlement for the year. Hover a cell for used and pending days.</p></Card>}</Loadable>;
}

export function Holidays() {
  const { hotel, can } = useAuth();
  const [year, setYear] = useState(new Date().getFullYear());
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/holidays`, { year }), [hotel?.id, year]);
  const [f, setF] = useState({ holiday_date: "", name: "" });
  const { busy, run } = useAction();
  return <Card title={<div className="row gap-s"><Button kind="ghost" onClick={() => setYear(year - 1)}>‹</Button><b>Public holidays {year}</b><Button kind="ghost" onClick={() => setYear(year + 1)}>›</Button></div>}>
    <Loadable state={st}>{d => <Table rows={d.items} empty="No public holidays recorded" cols={[{ h: "Date", r: h => fmtDate(h.holiday_date) }, { h: "Holiday", r: h => h.name },
      { h: "", r: h => can("hr.manage") ? <button className="link small" onClick={async () => { if (await run(() => del(`/api/holidays/${h.id}`), "Removed")) st.reload(); }}>Remove</button> : null }]} />}</Loadable>
    {can("hr.manage") && <div className="row gap-s wrap mt"><Input type="date" value={f.holiday_date} onChange={e => setF({ ...f, holiday_date: e.target.value })} aria-label="Holiday date" />
      <Input placeholder="Name, e.g. Eid-el-Fitr" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} aria-label="Holiday name" />
      <Button busy={busy} disabled={!f.holiday_date || !f.name} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/holidays`, f), "Holiday added")) { setF({ holiday_date: "", name: "" }); st.reload(); } }}>Add holiday</Button></div>}
    <p className="muted small mt">Public holidays are not counted as leave days. Add movable holidays (Eid, Easter) when the government announces them.</p></Card>;
}

// ======================================================================== employee profile additions
export function EmployeeExtras({ e, reload }: { e: any; reload: () => void }) {
  const { can, hotel } = useAuth();
  const [modal, setModal] = useState<string | null>(null);
  const [appr, setAppr] = useState<any>(null);
  const cur = hotel!.currency;
  return <>
    <div className="row gap-s wrap">
      {can("hr.manage") && e.status === "active" && <Button kind="secondary" onClick={() => setModal("history")}>Promote / transfer / pay change</Button>}
      {can("hr.manage") && <Button kind="secondary" onClick={() => setModal("training")}>Add training</Button>}
      {can("hr.performance") && e.status === "active" && <Button kind="secondary" onClick={() => setModal("appraisal")}>New appraisal</Button>}
      {can("hr.manage") && <Button kind="secondary" onClick={() => setModal("adjust")}>Adjust leave</Button>}
      {can("hr.accounts") && !e.user_id && e.status === "active" && <Button kind="gold" onClick={() => setModal("account")}>Give system access</Button>}
    </div>
    <div className="grid-2">
      <Card title="Reporting line"><dl className="dl"><dt>Line manager</dt><dd>{e.line_manager ? <a href={`#/hr/employees/${e.line_manager.id}`}>{e.line_manager.first_name} {e.line_manager.last_name}</a> : "—"}</dd>
        <dt>Direct reports</dt><dd>{e.direct_reports.length ? e.direct_reports.map((r: any) => <div key={r.id}><a href={`#/hr/employees/${r.id}`}>{r.first_name} {r.last_name}</a> <span className="muted small">{r.position}</span></div>) : "—"}</dd>
        <dt>Probation ends</dt><dd>{fmtDate(e.probation_end_date) || "—"}</dd><dt>Contract ends</dt><dd>{fmtDate(e.contract_end_date) || "—"}</dd>
        <dt>System login</dt><dd>{e.login ? <>{e.login.email} <Pill s={e.login.status === "active" ? "active" : "deactivated"} text={label(e.login.status)} /><div className="small muted">{e.login.roles.join(", ")}</div></> : <span className="muted">No login — cannot use My HR</span>}</dd></dl></Card>
      <Card title="Job history" pad={false}><Table rows={e.history} empty="No promotions, transfers or pay changes recorded" cols={[{ h: "Effective", r: h => fmtDate(h.effective_date) }, { h: "Change", r: h => label(h.kind) },
        { h: "From → to", r: h => <span className="small">{h.from_value || "—"} → {h.to_value || "—"}</span> }, { h: "By", r: h => <span className="small">{h.by_name}</span> }]} /></Card>
    </div>
    <Card title="Training & certifications" pad={false}><Table rows={e.trainings} empty="No training recorded" cols={[{ h: "Title", r: t => <><b>{t.title}</b><div className="small muted">{label(t.kind)}{t.provider ? ` · ${t.provider}` : ""}</div></> },
      { h: "Completed", r: t => fmtDate(t.completed_on) || "—" }, { h: "Expires", r: t => fmtDate(t.expires_on) || "—" }]} /></Card>
    {e.appraisals && <Card title="Appraisals" pad={false}><Table rows={e.appraisals} onRow={setAppr} empty="No appraisals" cols={[{ h: "Period", r: a => a.period }, { h: "Rating", r: a => `${a.overall_rating} / 5` }, { h: "Reviewer", r: a => a.reviewer },
      { h: "Status", r: a => <Pill s={a.status === "acknowledged" ? "approved" : a.status === "shared" ? "pending" : "draft"} text={label(a.status)} /> }]} /></Card>}
    <Card title="Requests" pad={false}><Table rows={e.requests} empty="No requests" cols={[{ h: "Ref", r: r => r.number }, { h: "Request", r: r => <><b>{REQ_LABEL[r.kind]}</b><div className="small muted">{r.subject}</div></> },
      { h: "Amount", r: r => r.amount ? money(r.amount, cur) : "", cls: "num" }, { h: "Date", r: r => fmtDate(r.created_at) }, { h: "Status", r: r => reqPill(r.status) }]} /></Card>
    {modal === "history" && <HistoryModal e={e} onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
    {modal === "training" && <TrainingModal e={e} onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
    {modal === "appraisal" && <NewAppraisal e={e} onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
    {modal === "adjust" && <AdjustLeave e={e} onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
    {modal === "account" && <AccountModal e={e} onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
    {appr && <AppraisalModal a={{ ...appr, employee: `${e.first_name} ${e.last_name}` }} onClose={() => { setAppr(null); reload(); }} />}
  </>;
}

const DEPTS = ["front_office", "housekeeping", "fnb", "kitchen", "laundry", "maintenance", "security", "finance", "hr", "sales", "admin", "it", "spa", "other"];

function HistoryModal({ e, onClose, onDone }: any) {
  const [f, setF] = useState<any>({ kind: "promotion", effective_date: new Date().toISOString().slice(0, 10), position: "", department: e.department, basic_salary: "", note: "" });
  const { busy, run } = useAction();
  const needPos = ["promotion", "title_change", "demotion"].includes(f.kind);
  return <Modal title={`Change for ${e.first_name} ${e.last_name}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={(needPos && !f.position) || (f.kind === "salary_change" && !f.basic_salary)} onClick={async () => {
      const b: any = { kind: f.kind, effective_date: f.effective_date, note: f.note || undefined };
      if (needPos || (f.kind === "transfer" && f.position)) b.position = f.position;
      if (f.kind === "transfer") b.department = f.department;
      if (f.basic_salary) b.basic_salary = toMinor(f.basic_salary);
      if (await run(() => post(`/api/employees/${e.id}/history`, b), "Recorded")) onDone(); }}>Save</Button></>}>
    <div className="form-grid">
      <Field label="Change"><Select value={f.kind} onChange={x => setF({ ...f, kind: x.target.value })}>{["promotion", "transfer", "salary_change", "confirmation", "title_change", "demotion"].map(k => <option key={k} value={k}>{label(k)}</option>)}</Select></Field>
      <Field label="Effective date"><Input type="date" value={f.effective_date} onChange={x => setF({ ...f, effective_date: x.target.value })} /></Field>
      {f.kind === "transfer" && <Field label="New department"><Select value={f.department} onChange={x => setF({ ...f, department: x.target.value })}>{DEPTS.map(d => <option key={d} value={d}>{label(d)}</option>)}</Select></Field>}
      {(needPos || f.kind === "transfer") && <Field label={`New position${f.kind === "transfer" ? " (optional)" : ""}`}><Input value={f.position} placeholder={e.position} onChange={x => setF({ ...f, position: x.target.value })} /></Field>}
      {f.kind !== "confirmation" && <Field label={`New basic monthly pay${f.kind === "salary_change" ? "" : " (optional)"}`}><Input inputMode="decimal" value={f.basic_salary} onChange={x => setF({ ...f, basic_salary: x.target.value })} /></Field>}
      <Field label="Note" wide><Textarea value={f.note} onChange={x => setF({ ...f, note: x.target.value })} /></Field></div>
    <p className="muted small">The change is applied to the record, kept in the job history and the employee is notified.{f.kind === "confirmation" ? " Confirmation ends the probation period." : ""}</p></Modal>;
}

function TrainingModal({ e, onClose, onDone }: any) {
  const [f, setF] = useState({ kind: "training", title: "", provider: "", completed_on: "", expires_on: "", notes: "" });
  const { busy, run } = useAction();
  return <Modal title="Add training or certificate" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.title} onClick={async () => { const b: any = { ...f }; for (const k of ["completed_on", "expires_on", "provider", "notes"]) if (!b[k]) delete b[k]; if (await run(() => post(`/api/employees/${e.id}/trainings`, b), "Saved")) onDone(); }}>Save</Button></>}>
    <div className="form-grid"><Field label="Type"><Select value={f.kind} onChange={x => setF({ ...f, kind: x.target.value })}>{["training", "certification", "licence", "induction"].map(k => <option key={k} value={k}>{label(k)}</option>)}</Select></Field>
      <Field label="Title" wide><Input value={f.title} onChange={x => setF({ ...f, title: x.target.value })} /></Field>
      <Field label="Provider"><Input value={f.provider} onChange={x => setF({ ...f, provider: x.target.value })} /></Field>
      <Field label="Completed"><Input type="date" value={f.completed_on} onChange={x => setF({ ...f, completed_on: x.target.value })} /></Field>
      <Field label="Expires (certificates)"><Input type="date" value={f.expires_on} onChange={x => setF({ ...f, expires_on: x.target.value })} /></Field></div>
    <p className="muted small">HR is reminded 30 days before a certificate expires. Upload the certificate under Documents.</p></Modal>;
}

function NewAppraisal({ e, onClose, onDone }: any) {
  const [period, setPeriod] = useState(`${new Date().getFullYear()} ${new Date().getMonth() < 6 ? "H1" : "H2"}`);
  const [crit, setCrit] = useState([{ name: "Quality of work", rating: 3, comment: "" }, { name: "Guest service", rating: 3, comment: "" }, { name: "Teamwork", rating: 3, comment: "" },
    { name: "Punctuality & attendance", rating: 3, comment: "" }, { name: "Initiative", rating: 3, comment: "" }]);
  const [t, setT] = useState({ strengths: "", improvements: "", goals: "" });
  const { busy, run } = useAction();
  const avg = Math.round(crit.reduce((s, c) => s + c.rating, 0) / crit.length);
  return <Modal title={`Appraisal — ${e.first_name} ${e.last_name}`} width={720} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/employees/${e.id}/appraisals`, { period, criteria: crit, ...t }), "Draft saved — share it when ready")) onDone(); }}>Save draft</Button></>}>
    <div className="form-grid"><Field label="Period"><Input value={period} onChange={x => setPeriod(x.target.value)} /></Field><Field label="Overall (average)"><div className="big"><b>{avg} / 5</b></div></Field></div>
    <Table rows={crit} rowKey={c => c.name} cols={[{ h: "Criterion", r: c => c.name }, { h: "Rating", r: (c: any) => <div className="stars">{[1, 2, 3, 4, 5].map(n => <button key={n} type="button" className={c.rating >= n ? "on" : ""} aria-label={`${c.name} ${n}`} onClick={() => setCrit(crit.map(x => x.name === c.name ? { ...x, rating: n } : x))}>★</button>)}</div> },
      { h: "Comment", r: (c: any) => <Input value={c.comment} onChange={x => setCrit(crit.map(y => y.name === c.name ? { ...y, comment: x.target.value } : y))} /> }]} />
    <div className="form-grid mt"><Field label="Strengths" wide><Textarea value={t.strengths} onChange={x => setT({ ...t, strengths: x.target.value })} /></Field>
      <Field label="To improve" wide><Textarea value={t.improvements} onChange={x => setT({ ...t, improvements: x.target.value })} /></Field>
      <Field label="Goals for next period" wide><Textarea value={t.goals} onChange={x => setT({ ...t, goals: x.target.value })} /></Field></div></Modal>;
}

function AdjustLeave({ e, onClose, onDone }: any) {
  const [f, setF] = useState({ leave_type_id: String(e.leave_balances[0]?.leave_type_id || ""), days: "", reason: "" });
  const { busy, run } = useAction();
  return <Modal title="Adjust leave entitlement" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.days || Number(f.days) === 0 || !f.reason.trim()} onClick={async () => { if (await run(() => post(`/api/employees/${e.id}/leave-adjustments`, { leave_type_id: Number(f.leave_type_id), days: Number(f.days), reason: f.reason }), "Adjusted")) onDone(); }}>Save</Button></>}>
    <div className="form-grid"><Field label="Leave type"><Select value={f.leave_type_id} onChange={x => setF({ ...f, leave_type_id: x.target.value })}>{e.leave_balances.map((b: any) => <option key={b.leave_type_id} value={b.leave_type_id}>{b.name} ({b.remaining} left)</option>)}</Select></Field>
      <Field label="Days (+ add, − remove)"><Input type="number" value={f.days} onChange={x => setF({ ...f, days: x.target.value })} /></Field>
      <Field label="Reason (e.g. carry-over, long service)" wide><Input value={f.reason} onChange={x => setF({ ...f, reason: x.target.value })} /></Field></div></Modal>;
}

function AccountModal({ e, onClose, onDone }: any) {
  const roles = useLoad(() => get("/api/hr/assignable-roles"), []);
  const [f, setF] = useState({ email: e.email || "", role_id: "" });
  const [done, setDone] = useState<any>(null);
  const { busy, run } = useAction();
  return <Modal title={`System access for ${e.first_name} ${e.last_name}`} onClose={done ? onDone : onClose} footer={done ? <Button onClick={onDone}>Done</Button> : <><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.email || !f.role_id} onClick={async () => { const r = await run(() => post(`/api/employees/${e.id}/account`, { email: f.email, role_id: Number(f.role_id) }), "Login created"); if (r) setDone(r); }}>Create login</Button></>}>
    {done ? <div className="stack"><p>Login created for <b>{done.email}</b> with the role <b>{done.role}</b>.</p><p>Temporary password: <code className="big">{done.temporary_password}</code></p>
      <p className="muted small">Give it to the employee privately. They must change it at first sign-in. It is not shown again.</p></div> :
      <div className="form-grid"><Field label="Email (sign-in name)" wide><Input value={f.email} onChange={x => setF({ ...f, email: x.target.value })} /></Field>
        <Field label="Role" wide><Loadable state={roles}>{d => <Select value={f.role_id} onChange={x => setF({ ...f, role_id: x.target.value })}><option value="">Choose…</option>{d.items.map((r: any) => <option key={r.id} value={r.id}>{r.name}</option>)}</Select>}</Loadable></Field>
        <p className="muted small">Administrator roles are not listed; ask a system administrator for those.</p></div>}</Modal>;
}

// ======================================================================== My HR (every employee)
export function MyHRFull() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/me/employee`), []);
  const full = useLoad(() => get(`/api/me/hr`), []);
  const reqs = useLoad(() => get(`/api/me/requests`).catch(() => ({ items: [] })), []);
  const [tab, setTab] = useState("overview");
  const [modal, setModal] = useState<string | null>(null);
  const { busy, run } = useAction();
  const toast = useToast();
  const cur = hotel?.currency || "NGN";
  const reload = () => { st.reload(); full.reload(); reqs.reload(); };
  return <div className="page"><Loadable state={st}>{d => !d.linked ? <Empty text="Your login is not linked to an employee record yet, so you cannot use My HR. Ask HR to link it." /> : <>
    <div className="page-h"><div><h1>My HR</h1><p className="muted">{d.employee.first_name} {d.employee.last_name} · {d.employee.employee_no} · {d.employee.position} · {label(d.employee.department)}</p></div>
      <div className="row gap-s wrap">
        {!d.today?.clock_in ? <Button kind="gold" busy={busy} onClick={async () => { if (await run(() => post("/api/me/clock", { action: "in" }), "Clocked in")) reload(); }}>Clock in</Button>
          : !d.today?.clock_out ? <Button kind="secondary" busy={busy} onClick={async () => { if (await run(() => post("/api/me/clock", { action: "out" }), "Clocked out")) reload(); }}>Clock out (in since {d.today.clock_in})</Button>
          : <span className="chip">Today {d.today.clock_in}–{d.today.clock_out}</span>}
        <Button onClick={() => setModal("leave")}>Apply for leave</Button>
        <Button kind="secondary" onClick={() => setModal("request")}>New request</Button></div></div>
    <Tabs tabs={[{ id: "overview", label: "Overview" }, { id: "leave", label: "My leave" }, { id: "requests", label: "My requests" }, { id: "profile", label: "My profile" },
      { id: "performance", label: "Appraisals & training" }, { id: "pay", label: "Payslips & attendance" }]} value={tab} onChange={setTab} />
    {tab === "overview" && <div className="stack">
      {d.shift_today ? <p className="note">Today's shift: {d.shift_today.name} {d.shift_today.start_time}–{d.shift_today.end_time}</p> : <p className="muted">No shift rostered today.</p>}
      <div className="grid-2">
        <Card title="Leave left this year" pad={false}><Table rows={d.leave_balances} cols={[{ h: "Type", r: b => b.name }, { h: "Left", r: b => <b>{b.remaining - b.pending}</b>, cls: "num" }, { h: "Taken", r: b => b.used, cls: "num" }, { h: "Waiting", r: b => b.pending, cls: "num" }]} /></Card>
        <Loadable state={full}>{f => <Card title="My roster (two weeks)" pad={false}><Table rows={f.roster} rowKey={r => r.work_date} empty="No shifts rostered" cols={[{ h: "Day", r: r => new Date(r.work_date + "T00:00:00").toLocaleDateString("en-GB", { weekday: "short", day: "2-digit", month: "short" }) },
          { h: "Shift", r: r => `${r.name} ${r.start_time}–${r.end_time}` }]} />{f.holidays.length > 0 && <p className="small muted pad">Next holiday: {fmtDate(f.holidays[0].holiday_date)} — {f.holidays[0].name}</p>}</Card>}</Loadable>
      </div></div>}
    {tab === "leave" && <Card title="My leave requests" pad={false}><Table rows={d.leave_requests} empty="None yet" cols={[{ h: "Type", r: l => l.leave_type }, { h: "Dates", r: l => `${fmtDate(l.start_date)} → ${fmtDate(l.end_date)}` }, { h: "Days", r: l => l.days, cls: "num" },
      { h: "Status", r: l => <span title={l.decision_note || l.cancel_reason || ""}><Pill s={l.status} /></span> }, { h: "Note", r: l => <span className="small">{l.decision_note || l.cancel_reason || ""}</span> },
      { h: "", r: l => (l.status === "pending" || (l.status === "approved" && l.start_date > new Date().toISOString().slice(0, 10))) ? <Button kind="ghost" busy={busy} onClick={async () => { if (confirm("Cancel this leave?") && await run(() => post(`/api/me/leave/${l.id}/cancel`, { reason: "Cancelled by employee" }), "Leave cancelled")) reload(); }}>Cancel</Button> : null }]} /></Card>}
    {tab === "requests" && <Loadable state={reqs}>{r => <Card title="My requests" actions={<Button onClick={() => setModal("request")}>New request</Button>} pad={false}><Table rows={r.items} empty="No requests yet" cols={[{ h: "Ref", r: x => x.number },
      { h: "Request", r: x => <><b>{REQ_LABEL[x.kind]}</b><div className="small muted">{x.subject}</div></> }, { h: "Amount", r: x => x.amount ? money(x.amount, cur) : "", cls: "num" }, { h: "Status", r: x => reqPill(x.status) },
      { h: "HR note", r: x => <span className="small">{x.decision_note || ""}</span> },
      { h: "", r: x => x.kind === "letter" && x.status === "completed" ? <Button kind="ghost" onClick={() => openFile(`/api/hr/requests/${x.id}/letter.pdf`, `${x.number}.pdf`, true).catch(e => toast("error", errText(e)))}>Download letter</Button>
        : x.status === "submitted" ? <Button kind="ghost" busy={busy} onClick={async () => { if (await run(() => post(`/api/me/requests/${x.id}/cancel`), "Withdrawn")) reqs.reload(); }}>Withdraw</Button> : null }]} /></Card>}</Loadable>}
    {tab === "profile" && <Loadable state={full}>{f => <div className="grid-2">
      <Card title="My details" actions={<Button kind="secondary" onClick={() => setModal("change")}>Request a change</Button>}><dl className="dl">
        {[["Phone", "phone"], ["Email", "email"], ["Address", "address"], ["Next of kin", "next_of_kin"], ["Emergency contact", "emergency_contact"], ["Bank", "bank_name"], ["Account", "bank_account_number"], ["Qualifications", "qualifications"]].map(([l, k]) =>
          <React.Fragment key={k}><dt>{l}</dt><dd>{f.profile[k] || "—"}</dd></React.Fragment>)}</dl></Card>
      <Card title="My job"><dl className="dl"><dt>Position</dt><dd>{f.profile.position}</dd><dt>Department</dt><dd>{label(f.profile.department)}</dd><dt>Type</dt><dd>{label(f.profile.employment_type)}</dd>
        <dt>Joined</dt><dd>{fmtDate(f.profile.hire_date)}</dd><dt>Probation ends</dt><dd>{fmtDate(f.profile.probation_end_date) || "—"}</dd><dt>Line manager</dt><dd>{f.line_manager ? `${f.line_manager.first_name} ${f.line_manager.last_name} (${f.line_manager.position})` : "—"}</dd></dl>
        {f.history.length > 0 && <><h4 className="mt">History</h4><ul className="alert-list">{f.history.map((h: any, i: number) => <li key={i}>{fmtDate(h.effective_date)} — {label(h.kind)}: {h.to_value}</li>)}</ul></>}</Card>
    </div>}</Loadable>}
    {tab === "performance" && <Loadable state={full}>{f => <div className="stack">
      <Card title="My appraisals" pad={false}><Table rows={f.appraisals} empty="No appraisals shared with you yet" cols={[{ h: "Period", r: a => a.period }, { h: "Overall", r: a => `${a.overall_rating} / 5` }, { h: "Reviewer", r: a => a.reviewer },
        { h: "Status", r: a => <Pill s={a.status === "acknowledged" ? "approved" : "pending"} text={label(a.status)} /> }, { h: "", r: a => <Button kind="ghost" onClick={() => setModal(`appr:${a.id}`)}>Open</Button> }]} /></Card>
      <Card title="My training & certificates" pad={false}><Table rows={f.trainings} empty="No training recorded" cols={[{ h: "Title", r: t => t.title }, { h: "Type", r: t => label(t.kind) }, { h: "Completed", r: t => fmtDate(t.completed_on) || "—" }, { h: "Expires", r: t => fmtDate(t.expires_on) || "—" }]} /></Card>
      {modal?.startsWith("appr:") && <MyAppraisal a={f.appraisals.find((x: any) => `appr:${x.id}` === modal)} onClose={() => setModal(null)} onDone={() => { setModal(null); full.reload(); }} />}
    </div>}</Loadable>}
    {tab === "pay" && <div className="stack">
      <Card title="My payslips" pad={false}><Table rows={d.payslips} empty="No payslips yet" cols={[{ h: "Period", r: p => p.period }, { h: "Gross", r: p => money(p.gross, cur), cls: "num" }, { h: "Net", r: p => money(p.net, cur), cls: "num" },
        { h: "", r: p => <button className="link small" onClick={() => openFile(`/api/payslips/${p.id}.pdf`, `payslip-${p.period}.pdf`, true)}>Download</button> }]} /></Card>
      <Card title="My attendance this month" pad={false}><Table rows={d.attendance} empty="No attendance recorded this month" cols={[{ h: "Date", r: a => fmtDate(a.work_date) }, { h: "Status", r: a => label(a.status) }, { h: "In", r: a => a.clock_in || "—" }, { h: "Out", r: a => a.clock_out || "—" }]} /></Card>
      <DocumentsPanel entityType="employee" entityId={d.employee.id} title="My documents" />
    </div>}
    {modal === "leave" && <MyLeave balances={d.leave_balances} onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); setTab("leave"); }} />}
    {modal === "request" && full.data && <NewRequest me={full.data} onClose={() => setModal(null)} onDone={() => { setModal(null); reqs.reload(); setTab("requests"); }} />}
    {modal === "change" && full.data && <NewRequest me={full.data} kind="data_change" onClose={() => setModal(null)} onDone={() => { setModal(null); reqs.reload(); setTab("requests"); }} />}
  </>}</Loadable></div>;
}

function MyLeave({ balances, onClose, onDone }: any) {
  const [f, setF] = useState({ leave_type_id: String(balances[0]?.leave_type_id || ""), start_date: "", end_date: "", reason: "" });
  const { busy, run } = useAction();
  const b = balances.find((x: any) => String(x.leave_type_id) === f.leave_type_id);
  return <Modal title="Apply for leave" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.start_date || !f.end_date} onClick={async () => { if (await run(() => post("/api/me/leave", { ...f, leave_type_id: Number(f.leave_type_id) }), "Leave requested — HR will review it")) onDone(); }}>Submit</Button></>}>
    <div className="form-grid"><Field label="Type"><Select value={f.leave_type_id} onChange={e => setF({ ...f, leave_type_id: e.target.value })}>{balances.map((x: any) => <option key={x.leave_type_id} value={x.leave_type_id}>{x.name} ({x.remaining - x.pending} left)</option>)}</Select></Field>
      <Field label="From"><Input type="date" value={f.start_date} onChange={e => setF({ ...f, start_date: e.target.value, end_date: f.end_date || e.target.value })} /></Field>
      <Field label="To"><Input type="date" value={f.end_date} onChange={e => setF({ ...f, end_date: e.target.value })} /></Field>
      <Field label="Reason" wide><Input value={f.reason} onChange={e => setF({ ...f, reason: e.target.value })} /></Field></div>
    <p className="muted small">{b ? `${b.remaining - b.pending} day(s) of ${b.name} left. ` : ""}Days are counted Monday to Saturday; public holidays are not counted. HR approves or rejects, and you are notified.</p></Modal>;
}

function NewRequest({ me, kind: fixed, onClose, onDone }: any) {
  const [kind, setKind] = useState(fixed || "letter");
  const [f, setF] = useState<any>({ subject: "", details: "", amount: "", months: "", date: "", with_employee_id: "" });
  const [chg, setChg] = useState<Record<string, string>>({});
  const { busy, run } = useAction();
  const go = async () => {
    const b: any = { kind, subject: f.subject || undefined, details: f.details || undefined };
    if (["salary_advance", "loan"].includes(kind)) { b.amount = toMinor(f.amount); if (f.months) b.months = Number(f.months); }
    if (kind === "shift_swap") { b.date = f.date; b.with_employee_id = Number(f.with_employee_id); }
    if (kind === "data_change") b.data = Object.fromEntries(Object.entries(chg).filter(([, v]) => v.trim()));
    if (await run(() => post("/api/me/requests", b), "Request sent to HR")) onDone();
  };
  const ok = kind === "data_change" ? Object.values(chg).some(v => v.trim()) : ["salary_advance", "loan"].includes(kind) ? toMinor(f.amount) > 0 : kind === "shift_swap" ? f.date && f.with_employee_id : ["grievance", "other"].includes(kind) ? f.details.trim() : true;
  return <Modal title="New HR request" width={620} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button busy={busy} disabled={!ok} onClick={go}>Send to HR</Button></>}>
    <div className="form-grid">
      {!fixed && <Field label="What do you need?" wide><Select value={kind} onChange={e => setKind(e.target.value)}>{Object.entries(REQ_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</Select></Field>}
      {kind !== "data_change" && <Field label={kind === "letter" ? "What is the letter for? (e.g. visa, bank loan)" : "Subject"} wide><Input value={f.subject} onChange={e => setF({ ...f, subject: e.target.value })} /></Field>}
      {["salary_advance", "loan"].includes(kind) && <><Field label="Amount (₦)"><Input inputMode="decimal" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label="Repay over (months)"><Input type="number" min={1} max={24} value={f.months} placeholder={kind === "loan" ? "6" : "1"} onChange={e => setF({ ...f, months: e.target.value })} /></Field></>}
      {kind === "shift_swap" && <><Field label="Date"><Input type="date" value={f.date} onChange={e => setF({ ...f, date: e.target.value })} /></Field>
        <Field label="Swap with"><Select value={f.with_employee_id} onChange={e => setF({ ...f, with_employee_id: e.target.value })}><option value="">Choose…</option>{me.colleagues.map((c: any) => <option key={c.id} value={c.id}>{c.first_name} {c.last_name} ({label(c.department)})</option>)}</Select></Field></>}
      {kind === "data_change" && me.self_editable.map((k: string) => <Field key={k} label={`New ${label(k).toLowerCase()}`}><Input value={chg[k] || ""} placeholder={k === "bank_account_number" ? "" : me.profile[k] || ""} onChange={e => setChg({ ...chg, [k]: e.target.value })} /></Field>)}
      {kind !== "data_change" && <Field label={kind === "grievance" ? "What happened? (only HR managers see this)" : "Details"} wide><Textarea value={f.details} onChange={e => setF({ ...f, details: e.target.value })} /></Field>}
    </div>
    <p className="muted small">{kind === "data_change" ? "Fill in only what changed. HR checks and updates your record." : kind === "grievance" ? "Grievances are confidential and handled by HR management." :
      ["salary_advance", "loan"].includes(kind) ? "Limits: one month's basic pay for an advance, six months' for a loan. Repayments are deducted from your salary." : "HR reviews your request and you are notified of the decision."}</p></Modal>;
}

function MyAppraisal({ a, onClose, onDone }: any) {
  const [comment, setComment] = useState("");
  const { busy, run } = useAction();
  if (!a) return null;
  return <Modal title={`My appraisal — ${a.period}`} width={640} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    {a.status === "shared" && <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/me/appraisals/${a.id}/acknowledge`, { comment: comment || undefined }), "Acknowledged")) onDone(); }}>Acknowledge</Button>}</>}>
    <Table rows={a.criteria} rowKey={c => c.name} cols={[{ h: "Criterion", r: c => c.name }, { h: "Rating", r: c => "★".repeat(c.rating) }, { h: "Comment", r: c => <span className="small">{c.comment}</span> }]} />
    <dl className="dl mt"><dt>Overall</dt><dd>{a.overall_rating} / 5</dd><dt>Reviewer</dt><dd>{a.reviewer}</dd>{a.strengths && <><dt>Strengths</dt><dd>{a.strengths}</dd></>}
      {a.improvements && <><dt>To improve</dt><dd>{a.improvements}</dd></>}{a.goals && <><dt>Goals</dt><dd>{a.goals}</dd></>}{a.employee_comment && <><dt>My comment</dt><dd>{a.employee_comment}</dd></>}</dl>
    {a.status === "shared" && <Field label="Your comment (optional)" wide><Textarea value={comment} onChange={e => setComment(e.target.value)} /></Field>}</Modal>;
}
