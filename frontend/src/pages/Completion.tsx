// Release 1.2 screens: backups, help & support, front-office guest services (wake-up calls, early check-in / late
// check-out, registration card, referral), table bookings, purchase returns, referrals, staff welfare, petty cash and
// payment vouchers, stay fees and room photos/videos.
import React, { useState } from "react";
import { del, fmtDate, fmtDateTime, get, label, money, openFile, post, put, toMinor } from "../api";
import { useAuth } from "../state";
import { useT } from "../i18n";
import { Button, Card, Empty, Field, Input, Kpi, Loadable, Modal, Pill, Select, Table, Textarea, errText, useAction, useLoad, useToast } from "../ui";

const bytes = (n?: number | null) => (n == null ? "—" : n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

// ================================================================== Backups
export function Backups() {
  const toast = useToast();
  const st = useLoad(() => get("/api/admin/backups"), []);
  const { busy, run } = useAction();
  const [verifying, setVerifying] = useState<number | null>(null);
  const [sch, setSch] = useState<any>(null);
  return (
    <div className="page">
      <div className="page-h"><div><h1>Backups</h1><p className="muted">Whole-database backups with documents and photos, verified by a test restore.</p></div>
        <Button busy={busy} onClick={async () => { const r = await run(() => post("/api/admin/backups", {}), "Backup created"); if (r) st.reload(); }}>Back up now</Button></div>
      <Loadable state={st}>{d => <>
        <div className="kpis">
          <Kpi title="Last successful backup" value={d.last_ok ? fmtDateTime(d.last_ok) : "Never"} tone={d.last_ok ? undefined : "warn"} />
          <Kpi title="Automatic backups" value={d.schedule.enabled ? `Daily from ${String(d.schedule.hour_utc).padStart(2, "0")}:00 UTC` : "Off"} sub={`Kept ${d.schedule.retention_days} days`} />
          <Kpi title="Database" value={d.dialect === "sqlite" ? "SQLite" : "PostgreSQL"} sub={d.directory} />
        </div>
        <Card title="Backup history" actions={<Button kind="secondary" onClick={() => setSch({ ...d.schedule })}>Schedule & retention</Button>} pad={false}>
          <Table rows={d.items} empty="No backups yet — click Back up now." cols={[
            { h: "Taken", r: b => <>{fmtDateTime(b.created_at)}<div className="muted small">{b.created_by_name || "Automatic"}</div></> },
            { h: "Type", r: b => label(b.kind) },
            { h: "Status", r: b => <>{<Pill s={b.status === "ok" ? "approved" : "rejected"} text={b.status === "ok" ? "OK" : "Failed"} />}{b.error && <div className="danger small">{b.error}</div>}</> },
            { h: "Size", r: b => bytes(b.size_bytes) },
            { h: "Contents", r: b => b.status === "ok" ? `${b.tables_count} tables · ${b.rows_count?.toLocaleString()} rows` : "—" },
            { h: "Verified", r: b => b.verified === 1 ? <Pill s="approved" text="Restore tested" /> : b.verified === -1 ? <Pill s="rejected" text="Failed" /> : <span className="muted">Not yet</span> },
            { h: "", r: b => b.status === "ok" && b.file_present ? <div className="row gap-s">
              <Button kind="secondary" busy={verifying === b.id} onClick={async () => { setVerifying(b.id); try { const r = await post(`/api/admin/backups/${b.id}/verify`, {}); toast(r.ok ? "success" : "error", r.ok ? `Verified: ${r.result.tables} tables, ${r.result.rows} rows restored in a test database` : r.error); st.reload(); } catch (e) { toast("error", errText(e)); } finally { setVerifying(null); } }}>Verify</Button>
              <Button kind="secondary" onClick={() => openFile(`/api/admin/backups/${b.id}/download`, b.filename).catch(e => toast("error", errText(e)))}>Download</Button></div>
              : b.status === "ok" ? <span className="muted small">File removed</span> : null },
          ]} />
        </Card>
        <Card title="Restoring a backup">
          <ol className="steps">
            <li>Download the backup (or copy it from <code>{d.directory}</code>) and keep a copy off this computer.</li>
            <li>Stop EHMS. Point <code>DATABASE_URL</code> at a <b>new, empty</b> database (for SQLite, a new file name).</li>
            <li>In the <code>backend</code> folder run <code>python -m ehms.backup restore &lt;backup file&gt;</code>. It checks every checksum, recreates the tables and restores documents and photos.</li>
            <li>Start EHMS again and sign in. Restoring into a database that already holds data is refused, so live data cannot be overwritten by mistake.</li>
          </ol>
          <p className="small muted">Automatic backups are verified by a test restore every night; administrators get a notification if a backup or its verification fails.</p>
        </Card>
      </>}</Loadable>
      {sch && <Modal title="Schedule & retention" onClose={() => setSch(null)} footer={<>
        <Button kind="secondary" onClick={() => setSch(null)}>Cancel</Button>
        <Button busy={busy} onClick={async () => { if (await run(() => put("/api/admin/backups/schedule", sch), "Schedule saved")) { setSch(null); st.reload(); } }}>Save</Button></>}>
        <label className="check"><input type="checkbox" checked={sch.enabled} onChange={e => setSch({ ...sch, enabled: e.target.checked })} /> Take an automatic backup every day</label>
        <div className="form-grid">
          <Field label="From (hour, UTC)" hint="Lagos time is UTC+1"><Input type="number" min={0} max={23} value={sch.hour_utc} onChange={e => setSch({ ...sch, hour_utc: Number(e.target.value) })} /></Field>
          <Field label="Keep automatic backups for (days)" hint="Manual backups are kept until you delete the file"><Input type="number" min={1} max={365} value={sch.retention_days} onChange={e => setSch({ ...sch, retention_days: Number(e.target.value) })} /></Field>
        </div>
      </Modal>}
    </div>
  );
}

// ================================================================== Help & support
const HELP: { title: string; perm?: string; lines: string[] }[] = [
  { title: "Getting around", lines: ["The left menu shows only the areas your role allows; the breadcrumb at the top shows where you are.", "Switch hotel with the selector at the top; the business date beside it moves forward at night audit.", "Search any guest, reference, room or phone number from the search box at the top.", "Change the interface language from your name (top right) → Language."] },
  { title: "Front desk", perm: "reservations.view", lines: ["Front desk & reservations → open a booking to check in, take a deposit, move rooms or check out.", "On the booking: Registration card (print and sign), Early check-in / Late check-out (fees from Hotel settings), Wake-up call, Referral code.", "Front desk → Wake-up calls lists today's calls; record each as done or missed. You get a reminder 10 minutes before.", "Room board: drag an unassigned arrival onto a free room to assign it."] },
  { title: "Restaurant & bar", perm: "pos.view", lines: ["Point of sale → choose the outlet and table, add items, send to the kitchen, settle or charge to the room.", "Point of sale → Table bookings: book tables by date and time; clashes on the same table are refused."] },
  { title: "Stores & purchasing", perm: "procurement.view", lines: ["Procurement → Goods received: open a GRN and use Return to supplier for damaged or wrong goods.", "Returns before invoicing reopen the order line; after invoicing they become a credit on the supplier invoice."] },
  { title: "Finance", perm: "accounting.view", lines: ["Finance operations → Petty cash: open a fund, pay out vouchers (over the limit needs approval), top it up.", "Print a payment voucher from any paid expense, petty cash entry or supplier payment."] },
  { title: "People", lines: ["My HR: apply for leave, make requests, see payslips, appraisals and training.", "HR managers: Human resources → Welfare records support given to staff (confidential)."] },
  { title: "Administration", perm: "admin.backups", lines: ["Administration → Backups: back up now, verify with a test restore, download, and set the daily schedule and retention."] },
];

export function Help() {
  const { can } = useAuth();
  const { t } = useT();
  return (
    <div className="page">
      <div className="page-h"><div><h1>{t("Help & support")}</h1><p className="muted">Quick answers for the screens you can use. The full user guide (Word) is in the docs folder of the EHMS download.</p></div></div>
      <div className="grid-2">
        {HELP.filter(h => !h.perm || can(h.perm)).map(h => <Card key={h.title} title={h.title}><ul className="help-list">{h.lines.map((l, i) => <li key={i}>{l}</li>)}</ul></Card>)}
        <Card title="Support">
          <ul className="help-list">
            <li>Can't see a menu or button? Your role does not include it — ask your administrator (Roles & permissions).</li>
            <li>Locked out after 5 wrong passwords? Wait 15 minutes or ask an administrator to reset your password.</li>
            <li>“Too many attempts”: EHMS allows 10 sign-ins a minute per computer; wait a minute.</li>
            <li>A red banner “This screen is out of date” means an old copy of EHMS is running: close it, start the new one and press Ctrl+F5.</li>
            <li>For anything else contact your EHMS administrator or IT support with the time, the screen and what you clicked.</li>
          </ul>
        </Card>
      </div>
    </div>
  );
}

// ================================================================== Front desk: guest services on a reservation
export function StayServices({ r, onChange }: { r: any; onChange: () => void }) {
  const { can } = useAuth();
  const toast = useToast();
  const { busy, run } = useAction();
  const [modal, setModal] = useState<string | null>(null);
  const [f, setF] = useState<any>({});
  const s = r.status;
  const done = async (p: Promise<any>, msg: string) => { if (await run(() => p, msg)) { setModal(null); onChange(); } };
  const open = s !== "cancelled" && s !== "no_show" && s !== "checked_out";
  return (
    <Card title="Guest services">
      <div className="row gap-s wrap">
        {can("frontdesk.checkin") && <Button kind="secondary" onClick={() => openFile(`/api/reservations/${r.id}/registration-card.pdf`, `registration-${r.reference}.pdf`, true).catch(e => toast("error", errText(e)))}>Registration card</Button>}
        {["tentative", "confirmed"].includes(s) && can("reservations.modify") && !r.early_check_in && <Button kind="secondary" onClick={() => { setF({ kind: "early_check_in" }); setModal("early"); }}>Early check-in</Button>}
        {s === "checked_in" && can("reservations.modify") && !r.late_check_out_until && <Button kind="secondary" onClick={() => { setF({ kind: "late_check_out", until: "15:00" }); setModal("early"); }}>Late check-out</Button>}
        {["confirmed", "checked_in"].includes(s) && can("frontdesk.checkin") && <Button kind="secondary" onClick={() => { setF({ call_date: "", call_time: "06:30", note: "" }); setModal("wake"); }}>Wake-up call</Button>}
        {open && can("reservations.modify") && <Button kind="secondary" onClick={() => { setF({ code: "" }); setModal("ref"); }}>Referral code</Button>}
      </div>
      <dl className="dl mt">
        {!!r.early_check_in && <><dt>Early check-in</dt><dd>Granted</dd></>}
        {r.late_check_out_until && <><dt>Late check-out</dt><dd>Until {r.late_check_out_until}</dd></>}
      </dl>
      {modal === "early" && <Modal title={f.kind === "early_check_in" ? "Grant early check-in" : "Grant late check-out"} onClose={() => setModal(null)} footer={<>
        <Button kind="secondary" onClick={() => setModal(null)}>Cancel</Button>
        <Button busy={busy} onClick={() => done(post(`/api/reservations/${r.id}/early-late`, { ...f, waive_reason: f.waive ? f.waive_reason : undefined }), "Granted")}>Grant</Button></>}>
        {f.kind === "late_check_out" && <Field label="Check-out until"><Input type="time" value={f.until} onChange={e => setF({ ...f, until: e.target.value })} /></Field>}
        <p className="small muted">The fee set in Hotel settings → Stay fees is posted to the folio.</p>
        {can("reservations.waive_fee") && <><label className="check"><input type="checkbox" checked={!!f.waive} onChange={e => setF({ ...f, waive: e.target.checked })} /> Waive the fee</label>
          {f.waive && <Field label="Reason for waiving"><Input value={f.waive_reason || ""} onChange={e => setF({ ...f, waive_reason: e.target.value })} /></Field>}</>}
      </Modal>}
      {modal === "wake" && <Modal title="Book a wake-up call" onClose={() => setModal(null)} footer={<>
        <Button kind="secondary" onClick={() => setModal(null)}>Cancel</Button>
        <Button busy={busy} onClick={() => done(post(`/api/reservations/${r.id}/wake-up-calls`, { ...f, call_date: f.call_date || undefined }), "Wake-up call booked")}>Book</Button></>}>
        <div className="form-grid">
          <Field label="Date" hint="Empty = today"><Input type="date" min={r.arrival} max={r.departure} value={f.call_date} onChange={e => setF({ ...f, call_date: e.target.value })} /></Field>
          <Field label="Time"><Input type="time" value={f.call_time} onChange={e => setF({ ...f, call_time: e.target.value })} /></Field>
          <Field label="Note" wide><Input value={f.note} onChange={e => setF({ ...f, note: e.target.value })} placeholder="e.g. second call after 10 minutes" /></Field>
        </div>
      </Modal>}
      {modal === "ref" && <Modal title="Referred by another guest" onClose={() => setModal(null)} footer={<>
        <Button kind="secondary" onClick={() => setModal(null)}>Cancel</Button>
        <Button busy={busy} onClick={() => done(post(`/api/reservations/${r.id}/referral`, f), "Referral recorded")}>Record</Button></>}>
        <Field label="Referral code" hint="The referrer earns loyalty points when this first stay is checked out."><Input value={f.code} onChange={e => setF({ code: e.target.value.toUpperCase() })} placeholder="REF-XXXXXX" /></Field>
      </Modal>}
    </Card>
  );
}

export function WakeUpCalls() {
  const { hotel } = useAuth();
  const [day, setDay] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/wake-up-calls`, day ? { date: day } : undefined), [hotel?.id, day]);
  const { run } = useAction();
  const mark = async (id: number, status: string) => { if (await run(() => post(`/api/wake-up-calls/${id}/status`, { status }), `Marked ${status}`)) st.reload(); };
  return (
    <Card title="Wake-up calls" actions={<Input type="date" value={day || st.data?.date || ""} onChange={e => setDay(e.target.value)} aria-label="Date" />} pad={false}>
      <Loadable state={st}>{d => <Table rows={d.items} empty="No wake-up calls for this day" cols={[
        { h: "Time", r: w => <b className={w.overdue ? "danger" : ""}>{w.call_time}</b> },
        { h: "Room", r: w => w.room_number || "—" },
        { h: "Guest", r: w => <>{w.first_name} {w.last_name}<div className="muted small">{w.reference}</div></> },
        { h: "Note", r: w => w.note || "" },
        { h: "Status", r: w => <>{<Pill s={w.status === "done" ? "approved" : w.status === "pending" ? (w.overdue ? "rejected" : "pending") : "cancelled"} text={w.overdue ? "Overdue" : label(w.status)} />}{w.done_by_name && <div className="muted small">{w.done_by_name}</div>}</> },
        { h: "", r: w => w.status === "pending" ? <div className="row gap-s"><Button kind="secondary" onClick={() => mark(w.id, "done")}>Done</Button><Button kind="ghost" onClick={() => mark(w.id, "missed")}>No answer</Button><Button kind="ghost" onClick={() => mark(w.id, "cancelled")}>Cancel</Button></div> : null },
      ]} />}</Loadable>
    </Card>
  );
}

// ================================================================== POS: table bookings
export function TableBookings({ outlets }: { outlets: any[] }) {
  const { hotel, can } = useAuth();
  const [day, setDay] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/table-reservations`, day ? { date: day } : undefined), [hotel?.id, day]);
  const { busy, run } = useAction();
  const [f, setF] = useState<any>(null);
  const [seat, setSeat] = useState<any>(null);
  const setStatus = async (id: number, status: string, extra: any = {}) => { if (await run(() => post(`/api/table-reservations/${id}/status`, { status, ...extra }), "Updated")) { setSeat(null); st.reload(); } };
  const tablesOf = (oid: number) => (outlets.find(o => o.id === oid)?.tables || []) as any[];
  return (
    <Card title="Table bookings" actions={<div className="row gap-s"><Input type="date" value={day || st.data?.date || ""} onChange={e => setDay(e.target.value)} aria-label="Date" />
      {can("pos.order") && <Button onClick={() => setF({ outlet_id: outlets[0]?.id, table_id: "", guest_name: "", phone: "", party_size: 2, reserved_date: day || st.data?.date, reserved_time: "19:00", duration_min: 90, notes: "" })}>New booking</Button>}</div>} pad={false}>
      <Loadable state={st}>{d => <Table rows={d.items} empty="No table bookings for this day" cols={[
        { h: "Time", r: b => <b>{b.reserved_time}</b> },
        { h: "Guest", r: b => <>{b.guest_name}<div className="muted small">{b.phone} {b.reference ? `· in-house ${b.reference}` : ""}</div></> },
        { h: "Party", r: b => b.party_size },
        { h: "Where", r: b => <>{b.outlet}<div className="muted small">{b.table_name ? `Table ${b.table_name}` : "Table not assigned"}</div></> },
        { h: "Status", r: b => <Pill s={b.status === "booked" ? "confirmed" : b.status === "seated" ? "checked_in" : b.status} text={label(b.status)} /> },
        { h: "", r: b => can("pos.order") && b.status === "booked" ? <div className="row gap-s">
          <Button kind="secondary" onClick={() => b.table_id ? setStatus(b.id, "seated") : setSeat({ ...b, table_id: "" })}>Seat</Button>
          <Button kind="ghost" onClick={() => setStatus(b.id, "no_show")}>No-show</Button><Button kind="ghost" onClick={() => setStatus(b.id, "cancelled")}>Cancel</Button></div>
          : can("pos.order") && b.status === "seated" ? <Button kind="secondary" onClick={() => setStatus(b.id, "completed")}>Completed</Button> : null },
      ]} />}</Loadable>
      {f && <Modal title="New table booking" onClose={() => setF(null)} footer={<>
        <Button kind="secondary" onClick={() => setF(null)}>Cancel</Button>
        <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/table-reservations`, { ...f, table_id: f.table_id || null }), "Table booked")) { setF(null); st.reload(); } }}>Book</Button></>}>
        <div className="form-grid">
          <Field label="Outlet"><Select value={f.outlet_id} onChange={e => setF({ ...f, outlet_id: Number(e.target.value), table_id: "" })}>{outlets.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}</Select></Field>
          <Field label="Table" hint="Optional — assign later"><Select value={f.table_id} onChange={e => setF({ ...f, table_id: e.target.value ? Number(e.target.value) : "" })}><option value="">Not assigned</option>{tablesOf(f.outlet_id).map((t: any) => <option key={t.id} value={t.id}>{t.code} ({t.seats} seats)</option>)}</Select></Field>
          <Field label="Guest name"><Input value={f.guest_name} onChange={e => setF({ ...f, guest_name: e.target.value })} /></Field>
          <Field label="Phone"><Input value={f.phone} onChange={e => setF({ ...f, phone: e.target.value })} /></Field>
          <Field label="Party size"><Input type="number" min={1} value={f.party_size} onChange={e => setF({ ...f, party_size: Number(e.target.value) })} /></Field>
          <Field label="Date"><Input type="date" value={f.reserved_date} onChange={e => setF({ ...f, reserved_date: e.target.value })} /></Field>
          <Field label="Time"><Input type="time" value={f.reserved_time} onChange={e => setF({ ...f, reserved_time: e.target.value })} /></Field>
          <Field label="Duration (minutes)"><Input type="number" min={15} step={15} value={f.duration_min} onChange={e => setF({ ...f, duration_min: Number(e.target.value) })} /></Field>
          <Field label="Notes" wide><Input value={f.notes} onChange={e => setF({ ...f, notes: e.target.value })} placeholder="Birthday, high chair, allergies…" /></Field>
        </div>
      </Modal>}
      {seat && <Modal title={`Seat ${seat.guest_name}`} onClose={() => setSeat(null)} footer={<><Button kind="secondary" onClick={() => setSeat(null)}>Cancel</Button>
        <Button busy={busy} disabled={!seat.table_id} onClick={() => setStatus(seat.id, "seated", { table_id: seat.table_id })}>Seat</Button></>}>
        <Field label="Table"><Select value={seat.table_id} onChange={e => setSeat({ ...seat, table_id: Number(e.target.value) })}><option value="">Choose…</option>
          {tablesOf(seat.outlet_id).filter((t: any) => t.seats >= seat.party_size).map((t: any) => <option key={t.id} value={t.id}>{t.code} ({t.seats} seats)</option>)}</Select></Field>
      </Modal>}
    </Card>
  );
}

// ================================================================== Procurement: goods received & returns
export function GoodsReceived() {
  const { hotel, can } = useAuth();
  const [term, setTerm] = useState("");
  const [q, setQ] = useState("");
  const grns = useLoad(() => get(`/api/hotels/${hotel!.id}/procurement/grns`, q ? { q } : undefined), [hotel?.id, q]);
  const ret = useLoad(() => get(`/api/hotels/${hotel!.id}/procurement/returns`), [hotel?.id]);
  const [grnId, setGrnId] = useState<number | null>(null);
  return <>
    <Card title="Goods received notes" actions={<form className="row gap-s" onSubmit={e => { e.preventDefault(); setQ(term.trim()); }}>
      <Input placeholder="GRN or PO number" value={term} onChange={e => setTerm(e.target.value)} aria-label="Find a goods received note" /><Button type="submit" kind="secondary">Find</Button></form>} pad={false}>
      <Loadable state={grns}>{d => <Table rows={d.items} onRow={g => setGrnId(g.id)} empty="Goods received notes appear here after deliveries are received against purchase orders." cols={[
        { h: "GRN", r: g => <b>{g.number}</b> }, { h: "Order", r: g => g.po_number }, { h: "Supplier", r: g => g.supplier }, { h: "Received", r: g => fmtDate(g.business_date) },
        { h: "Value", r: g => money(g.value, hotel!.currency) }, { h: "Returned", r: g => g.returned_value ? money(g.returned_value, hotel!.currency) : "—" }]} />}</Loadable>
    </Card>
    <Card title="Returns to suppliers" pad={false}><Loadable state={ret}>{d => <Table rows={d.items} empty="No returns" cols={[
      { h: "Return", r: x => <b>{x.number}</b> }, { h: "GRN / order", r: x => <>{x.grn_number}<div className="muted small">{x.po_number}</div></> }, { h: "Supplier", r: x => x.supplier },
      { h: "Value", r: x => money(x.value, hotel!.currency) }, { h: "Settled as", r: x => x.settlement === "grni" ? "Before invoice (order reopened)" : "Credit on supplier invoice" },
      { h: "Reason", r: x => x.reason }, { h: "Date", r: x => fmtDate(x.created_at) }]} />}</Loadable></Card>
    {grnId && <GrnModal id={grnId} canReturn={can("procurement.return")} onClose={() => { setGrnId(null); ret.reload(); grns.reload(); }} />}
  </>;
}

function GrnModal({ id, canReturn, onClose }: { id: number; canReturn: boolean; onClose: () => void }) {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/procurement/grns/${id}`), [id]);
  const { busy, run } = useAction();
  const [qty, setQty] = useState<Record<number, string>>({});
  const [reason, setReason] = useState("");
  const [inv, setInv] = useState("");
  return <Modal title="Goods received note" width={760} onClose={onClose} footer={canReturn ? <>
    <Button kind="secondary" onClick={onClose}>Close</Button>
    <Button kind="danger" busy={busy} disabled={!reason.trim() || !Object.values(qty).some(v => Number(v) > 0)} onClick={async () => {
      const lines = Object.entries(qty).filter(([, v]) => Number(v) > 0).map(([k, v]) => ({ grn_line_id: Number(k), quantity: Number(v) }));
      const r = await run(() => post(`/api/procurement/grns/${id}/returns`, { lines, reason, invoice_id: inv ? Number(inv) : undefined }), "Return recorded");
      if (r) { setQty({}); setReason(""); st.reload(); }
    }}>Return to supplier</Button></> : undefined}>
    <Loadable state={st}>{g => <>
      <p><b>{g.number}</b> · {g.supplier} · order {g.po_number} · {fmtDate(g.business_date)}</p>
      <Table rows={g.lines} cols={[
        { h: "Item", r: l => l.description }, { h: "Received", r: l => l.received_milli / 1000 }, { h: "Returned", r: l => l.returned_milli / 1000 },
        { h: "Unit cost", r: l => money(l.unit_cost, hotel!.currency) },
        ...(canReturn ? [{ h: "Return now", r: (l: any) => <Input type="number" min={0} max={(l.received_milli - l.returned_milli) / 1000} step="any" style={{ width: 90 }}
          value={qty[l.id] || ""} onChange={e => setQty({ ...qty, [l.id]: e.target.value })} aria-label={`Quantity to return of ${l.description}`} /> }] : []),
      ]} />
      {canReturn && <div className="form-grid mt">
        <Field label="Reason" wide><Input value={reason} onChange={e => setReason(e.target.value)} placeholder="Damaged, expired, wrong item…" /></Field>
        <Field label="Already invoiced by the supplier?" hint="If so, the return becomes a credit on that invoice"><Select value={inv} onChange={e => setInv(e.target.value)}>
          <option value="">Not invoiced yet</option>{g.invoices.map((i: any) => <option key={i.id} value={i.id}>{i.invoice_no} ({money(i.amount - i.amount_paid, hotel!.currency)} unpaid)</option>)}</Select></Field>
      </div>}
      {g.returns.length > 0 && <p className="small muted mt">Returns on this GRN: {g.returns.map((x: any) => `${x.number} (${money(x.value, hotel!.currency)})`).join(", ")}</p>}
    </>}</Loadable>
  </Modal>;
}

// ================================================================== CRM: referrals
export function Referrals() {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/referrals`), [hotel?.id]);
  const { busy, run } = useAction();
  const [rules, setRules] = useState<any>(null);
  return <Loadable state={st}>{d => <>
    <div className="kpis"><Kpi title="Referrals" value={d.summary.total} /><Kpi title="Rewarded stays" value={d.summary.rewarded} /><Kpi title="Points awarded" value={d.summary.points.toLocaleString()} />
      <Kpi title="Reward per referral" value={d.rules.enabled ? `${d.rules.points_referrer} points` : "Programme off"} sub={can("crm.manage") ? <a href="#" onClick={e => { e.preventDefault(); setRules({ ...d.rules }); }}>Change</a> : undefined} /></div>
    <Card title="Referrals" pad={false}><Table rows={d.items} empty="No referrals yet. Give guests their code from their profile; new guests enter it when booking." cols={[
      { h: "Referrer", r: x => `${x.referrer_first} ${x.referrer_last}` }, { h: "New guest", r: x => `${x.referred_first} ${x.referred_last}` },
      { h: "Booking", r: x => x.reference }, { h: "Status", r: x => <Pill s={x.status === "rewarded" ? "approved" : x.status === "void" ? "cancelled" : "pending"} text={label(x.status)} /> },
      { h: "Points", r: x => x.points || "—" }, { h: "Date", r: x => fmtDate(x.created_at) }]} /></Card>
    <p className="small muted">The referrer must be a loyalty member; points are credited once, when the new guest's first stay is checked out. Self-referrals and repeat guests are refused.</p>
    {rules && <Modal title="Referral programme" onClose={() => setRules(null)} footer={<><Button kind="secondary" onClick={() => setRules(null)}>Cancel</Button>
      <Button busy={busy} onClick={async () => { if (await run(() => put(`/api/hotels/${hotel!.id}/referrals/rules`, rules), "Saved")) { setRules(null); st.reload(); } }}>Save</Button></>}>
      <label className="check"><input type="checkbox" checked={rules.enabled} onChange={e => setRules({ ...rules, enabled: e.target.checked })} /> Programme on</label>
      <Field label="Points for the referrer per completed first stay"><Input type="number" min={0} value={rules.points_referrer} onChange={e => setRules({ ...rules, points_referrer: Number(e.target.value) })} /></Field>
    </Modal>}
  </>}</Loadable>;
}

export function GuestReferral({ guestId }: { guestId: number }) {
  const { can } = useAuth();
  const st = useLoad(() => get(`/api/guests/${guestId}/referral`), [guestId]);
  const { busy, run } = useAction();
  return <Card title="Referral code"><Loadable state={st}>{d => <>
    {d.code ? <p>Personal code: <b className="code-chip">{d.code}</b> <span className="muted small">— share it; new guests enter it when they book.</span></p>
      : can("guests.manage") ? <Button kind="secondary" busy={busy} onClick={async () => { if (await run(() => post(`/api/guests/${guestId}/referral`, {}), "Code created")) st.reload(); }}>Create referral code</Button>
      : <p className="muted">No code yet.</p>}
    {d.referred.length > 0 && <Table rows={d.referred} cols={[{ h: "Referred guest", r: x => `${x.first_name} ${x.last_name}` }, { h: "Booking", r: x => x.reference },
      { h: "Status", r: x => label(x.status) }, { h: "Points", r: x => x.points || "—" }]} />}
  </>}</Loadable></Card>;
}

// ================================================================== HR: welfare
const WELFARE = ["medical", "bereavement", "wedding", "childbirth", "hardship", "wellbeing", "other"];

export function WelfareRegister() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/hr/welfare`), [hotel?.id]);
  return <Loadable state={st}>{d => <Card title={`Welfare register ${d.year}`} actions={<span className="muted small">Total support {money(d.total_amount, hotel!.currency)} · confidential</span>} pad={false}>
    <Table rows={d.items} empty="No welfare support recorded this year. Record it from the employee's profile." cols={[
      { h: "Date", r: w => fmtDate(w.support_date) }, { h: "Employee", r: w => <a href={`#/hr/employees/${w.employee_id}`}>{w.first_name} {w.last_name}</a> },
      { h: "Department", r: w => label(w.department) }, { h: "Kind", r: w => label(w.kind) }, { h: "Support", r: w => w.description },
      { h: "Amount", r: w => w.amount ? money(w.amount, hotel!.currency) : "—" }, { h: "Recorded by", r: w => w.recorded_by }]} />
  </Card>}</Loadable>;
}

export function EmployeeWelfare({ employee, onChange }: { employee: any; onChange: () => void }) {
  const { hotel, can } = useAuth();
  const { busy, run } = useAction();
  const [f, setF] = useState<any>(null);
  if (!can("hr.records") || !employee.welfare) return null;
  return <Card title="Welfare (confidential)" actions={<Button kind="secondary" onClick={() => setF({ kind: "medical", support_date: "", amount: "", description: "" })}>Record support</Button>}>
    {employee.welfare.length ? <Table rows={employee.welfare} cols={[{ h: "Date", r: w => fmtDate(w.support_date) }, { h: "Kind", r: w => label(w.kind) },
      { h: "Support", r: w => w.description }, { h: "Amount", r: w => w.amount ? money(w.amount, hotel!.currency) : "—" }]} /> : <Empty text="No welfare support recorded" />}
    {f && <Modal title="Record welfare support" onClose={() => setF(null)} footer={<><Button kind="secondary" onClick={() => setF(null)}>Cancel</Button>
      <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/employees/${employee.id}/welfare`, { ...f, amount: f.amount ? toMinor(f.amount) : 0, support_date: f.support_date || undefined }), "Recorded")) { setF(null); onChange(); } }}>Save</Button></>}>
      <div className="form-grid">
        <Field label="Kind"><Select value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}>{WELFARE.map(k => <option key={k} value={k}>{label(k)}</option>)}</Select></Field>
        <Field label="Date" hint="Empty = today"><Input type="date" value={f.support_date} onChange={e => setF({ ...f, support_date: e.target.value })} /></Field>
        <Field label="Amount (optional)"><Input inputMode="decimal" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label="Support given" wide><Textarea value={f.description} onChange={e => setF({ ...f, description: e.target.value })} /></Field>
      </div>
      <p className="small muted">Pay any money through an expense claim; this register records the support for HR.</p>
    </Modal>}
  </Card>;
}

// ================================================================== Finance: petty cash
export function PettyCash() {
  const { hotel, can, user } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/petty-cash`), [hotel?.id]);
  const users = useLoad(() => (can("finance.petty_cash.manage") && can("admin.users.view") ? get("/api/admin/users") : Promise.resolve({ items: [] })), []);
  const { busy, run } = useAction();
  const toast = useToast();
  const [m, setM] = useState<any>(null);
  const cur = hotel!.currency;
  const reload = () => { setM(null); st.reload(); };
  return <Loadable state={st}>{d => <>
    <div className="row between mb"><p className="muted small">Each fund has its own ledger account. Vouchers up to the fund's limit post at once; larger ones need approval by someone else.</p>
      {can("finance.petty_cash.manage") && <Button onClick={() => setM({ kind: "fund", name: "", custodian_id: user!.id, imprest: "", voucher_limit: "", source_method_id: d.methods[0]?.id })}>Open a fund</Button>}</div>
    <div className="grid-3">{d.funds.map((f: any) => <Card key={f.id} title={f.name} actions={<span className="muted small">{f.account_code}</span>}>
      <dl className="dl"><dt>Balance</dt><dd><b>{money(f.balance, cur)}</b> of {money(f.imprest, cur)}</dd><dt>Custodian</dt><dd>{f.custodian}</dd>
        <dt>Voucher limit</dt><dd>{money(f.voucher_limit, cur)}</dd>{f.pending > 0 && <><dt>Awaiting approval</dt><dd>{money(f.pending, cur)}</dd></>}</dl>
      <div className="row gap-s wrap mt">
        {(f.custodian_id === user!.id || can("finance.petty_cash.manage")) && <Button kind="secondary" onClick={() => setM({ kind: "voucher", fund: f, payee: "", description: "", expense_account_id: d.expense_accounts[0]?.id, department: "admin", amount: "" })}>Pay out</Button>}
        {can("finance.petty_cash.manage") && f.to_replenish > 0 && <Button kind="secondary" onClick={() => setM({ kind: "topup", fund: f, source_method_id: d.methods[0]?.id })}>Top up {money(f.to_replenish, cur)}</Button>}
      </div></Card>)}
      {!d.funds.length && <Empty text="No petty cash funds yet" />}</div>
    <Card title="Vouchers and top-ups" pad={false}><Table rows={d.entries} empty="Nothing yet" cols={[
      { h: "No.", r: e => <b>{e.number}</b> }, { h: "Fund", r: e => e.fund }, { h: "Type", r: e => e.kind === "voucher" ? "Voucher" : "Top-up" },
      { h: "Payee / purpose", r: e => <>{e.payee || ""}<div className="muted small">{e.description}{e.expense_account ? ` · ${e.expense_account}` : ""}</div></> },
      { h: "Amount", r: e => money(e.amount, cur) },
      { h: "Status", r: e => <>{<Pill s={e.status === "posted" ? "approved" : e.status} text={label(e.status)} />}<div className="muted small">{e.requested_by_name}</div></> },
      { h: "", r: e => e.status === "pending" && can("finance.petty_cash.approve") ? <div className="row gap-s">
        <Button kind="secondary" onClick={async () => { if (await run(() => post(`/api/petty-cash/vouchers/${e.id}/decide`, { decision: "approve" }), "Approved and posted")) st.reload(); }}>Approve</Button>
        <Button kind="ghost" onClick={async () => { const note = window.prompt("Reason for rejecting"); if (note && await run(() => post(`/api/petty-cash/vouchers/${e.id}/decide`, { decision: "reject", note }), "Rejected")) st.reload(); }}>Reject</Button></div>
        : e.status === "posted" ? <Button kind="ghost" onClick={() => openFile(`/api/vouchers/petty_cash/${e.id}.pdf`, `voucher-${e.number}.pdf`, true).catch(er => toast("error", errText(er)))}>Voucher</Button> : null },
    ]} /></Card>
    {m?.kind === "fund" && <Modal title="Open a petty cash fund" onClose={() => setM(null)} footer={<><Button kind="secondary" onClick={() => setM(null)}>Cancel</Button>
      <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/petty-cash/funds`, { ...m, imprest: toMinor(m.imprest), voucher_limit: toMinor(m.voucher_limit) }), "Fund opened")) reload(); }}>Open fund</Button></>}>
      <div className="form-grid">
        <Field label="Name"><Input value={m.name} onChange={e => setM({ ...m, name: e.target.value })} placeholder="Front office float" /></Field>
        <Field label="Custodian"><Select value={m.custodian_id} onChange={e => setM({ ...m, custodian_id: Number(e.target.value) })}>
          <option value={user!.id}>{user!.full_name} (me)</option>{(users.data?.items || []).filter((u: any) => u.id !== user!.id && u.status === "active").map((u: any) => <option key={u.id} value={u.id}>{u.full_name}</option>)}</Select></Field>
        <Field label="Float (imprest)"><Input inputMode="decimal" value={m.imprest} onChange={e => setM({ ...m, imprest: e.target.value })} /></Field>
        <Field label="Limit per voucher"><Input inputMode="decimal" value={m.voucher_limit} onChange={e => setM({ ...m, voucher_limit: e.target.value })} /></Field>
        <Field label="Paid in from" wide><Select value={m.source_method_id} onChange={e => setM({ ...m, source_method_id: Number(e.target.value) })}>{d.methods.map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select></Field>
      </div></Modal>}
    {m?.kind === "voucher" && <Modal title={`Pay out from ${m.fund.name}`} onClose={() => setM(null)} footer={<><Button kind="secondary" onClick={() => setM(null)}>Cancel</Button>
      <Button busy={busy} onClick={async () => { const r: any = await run(() => post(`/api/petty-cash/funds/${m.fund.id}/vouchers`, { ...m, fund: undefined, amount: toMinor(m.amount) })); if (r) { toast("success", r.status === "posted" ? `Voucher ${r.number} posted` : `Voucher ${r.number} sent for approval (over the limit)`); reload(); } }}>Save voucher</Button></>}>
      <div className="form-grid">
        <Field label="Pay to"><Input value={m.payee} onChange={e => setM({ ...m, payee: e.target.value })} /></Field>
        <Field label="Amount" hint={`Limit ${money(m.fund.voucher_limit, cur)} · balance ${money(m.fund.balance, cur)}`}><Input inputMode="decimal" value={m.amount} onChange={e => setM({ ...m, amount: e.target.value })} /></Field>
        <Field label="Expense account"><Select value={m.expense_account_id} onChange={e => setM({ ...m, expense_account_id: Number(e.target.value) })}>{d.expense_accounts.map((a: any) => <option key={a.id} value={a.id}>{a.code} {a.name}</option>)}</Select></Field>
        <Field label="Department"><Select value={m.department} onChange={e => setM({ ...m, department: e.target.value })}>{d.departments.map((x: string) => <option key={x} value={x}>{label(x)}</option>)}</Select></Field>
        <Field label="Being (purpose)" wide><Input value={m.description} onChange={e => setM({ ...m, description: e.target.value })} /></Field>
      </div></Modal>}
    {m?.kind === "topup" && <Modal title={`Top up ${m.fund.name}`} onClose={() => setM(null)} footer={<><Button kind="secondary" onClick={() => setM(null)}>Cancel</Button>
      <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/petty-cash/funds/${m.fund.id}/top-up`, { source_method_id: m.source_method_id }), "Fund topped up")) reload(); }}>Top up {money(m.fund.to_replenish, cur)}</Button></>}>
      <Field label="Paid in from"><Select value={m.source_method_id} onChange={e => setM({ ...m, source_method_id: Number(e.target.value) })}>{d.methods.map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select></Field>
    </Modal>}
  </>}</Loadable>;
}

export function VoucherButton({ kind, id, number }: { kind: "expense" | "supplier_payment" | "petty_cash"; id: number; number: string }) {
  const toast = useToast();
  return <Button kind="ghost" onClick={e => { e.stopPropagation(); openFile(`/api/vouchers/${kind}/${id}.pdf`, `voucher-${number}.pdf`, true).catch(er => toast("error", errText(er))); }}>Voucher</Button>;
}

// ================================================================== Settings: stay fees, room photos & videos
export function StayFees() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/stay-fees`), [hotel?.id]);
  const { busy, run } = useAction();
  const [f, setF] = useState<any>(null);
  return <Card title="Early check-in and late check-out"><Loadable state={st}>{d => {
    const v = f || { early_check_in: (d.early_check_in / 100).toString(), late_check_out: (d.late_check_out / 100).toString() };
    return <>
      <p className="small muted">Normal check-in from {d.check_in_time}, check-out by {d.check_out_time}. The fee is posted to the guest folio when the front desk grants it (0 = free).</p>
      <div className="form-grid">
        <Field label={`Early check-in fee (${hotel!.currency})`}><Input inputMode="decimal" value={v.early_check_in} onChange={e => setF({ ...v, early_check_in: e.target.value })} /></Field>
        <Field label={`Late check-out fee (${hotel!.currency})`}><Input inputMode="decimal" value={v.late_check_out} onChange={e => setF({ ...v, late_check_out: e.target.value })} /></Field>
      </div>
      <Button busy={busy} disabled={!f} onClick={async () => { if (await run(() => put(`/api/hotels/${hotel!.id}/stay-fees`, { early_check_in: toMinor(v.early_check_in || 0), late_check_out: toMinor(v.late_check_out || 0) }), "Fees saved")) { setF(null); st.reload(); } }}>Save</Button>
    </>;
  }}</Loadable></Card>;
}

export function RoomMedia({ roomType, onClose }: { roomType: any; onClose: () => void }) {
  const st = useLoad(() => get(`/api/room-types/${roomType.id}/media`), [roomType.id]);
  const { busy, run } = useAction();
  const toast = useToast();
  const [caption, setCaption] = useState("");
  const [video, setVideo] = useState("");
  async function upload(file: File) {
    if (file.size > 5 * 1024 * 1024) { toast("error", "Photos must be 5 MB or smaller"); return; }
    const b64 = await new Promise<string>((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1] || ""); r.onerror = rej; r.readAsDataURL(file); });
    if (await run(() => post(`/api/room-types/${roomType.id}/media`, { filename: file.name, content_base64: b64, caption }), "Photo added")) { setCaption(""); st.reload(); }
  }
  return <Modal title={`Photos & videos — ${roomType.name}`} width={760} onClose={onClose}>
    <Loadable state={st}>{d => <>
      <div className="media-grid">{d.items.map((m: any) => <figure key={m.id} className="media-tile">
        {m.kind === "photo" ? <img src={m.url} alt={m.caption || roomType.name} /> : <a href={m.url} target="_blank" rel="noopener noreferrer" className="media-video">▶ Video</a>}
        <figcaption>{m.caption || ""}</figcaption>
        <button className="x" aria-label="Remove" onClick={async () => { if (window.confirm("Remove this item?") && await run(() => del(`/api/media/${m.id}`), "Removed")) st.reload(); }}>×</button>
      </figure>)}{!d.items.length && <Empty text="No photos yet — the booking engine shows a placeholder." />}</div>
      <div className="form-grid mt">
        <Field label="Caption (optional)"><Input value={caption} onChange={e => setCaption(e.target.value)} placeholder="King bed with city view" /></Field>
        <Field label="Add a photo" hint="JPEG, PNG or WebP, up to 5 MB"><input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={e => { const f = e.target.files?.[0]; if (f) upload(f); e.currentTarget.value = ""; }} /></Field>
        <Field label="Video link" hint="YouTube, Vimeo or your website (https://)" wide><div className="row gap-s"><Input value={video} onChange={e => setVideo(e.target.value)} placeholder="https://www.youtube.com/watch?v=…" />
          <Button kind="secondary" busy={busy} disabled={!video.startsWith("https://")} onClick={async () => { if (await run(() => post(`/api/room-types/${roomType.id}/media`, { kind: "video", url: video, caption }), "Video added")) { setVideo(""); st.reload(); } }}>Add video</Button></div></Field>
      </div>
    </>}</Loadable>
  </Modal>;
}


// ================================================================== Insights: predictions, guest insights, daily summary
export function DailySummary() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/insights/daily-summary`), [hotel?.id]);
  return <Card title="Daily management summary"><Loadable state={st}>{d => <>
    <ul className="help-list">{d.summary.map((l: string, i: number) => <li key={i}>{l}</li>)}</ul>
    <p className="small muted mt">{d.source}</p></>}</Loadable></Card>;
}

export function CancellationRisk() {
  const { hotel } = useAuth();
  const [days, setDays] = useState(30);
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/insights/cancellation-risk`, { days }), [hotel?.id, days]);
  return <Card title="Cancellation risk — upcoming bookings" actions={<Select value={days} onChange={e => setDays(Number(e.target.value))} aria-label="Window">
    {[7, 14, 30, 60, 90].map(n => <option key={n} value={n}>Next {n} days</option>)}</Select>} pad={false}>
    <Loadable state={st}>{d => <>
      <Table rows={d.items} empty="No upcoming bookings" onRow={r => (location.hash = `#/reservations/${r.id}`)} cols={[
        { h: "Risk", r: r => <Pill s={r.level === "high" ? "rejected" : r.level === "medium" ? "pending" : "approved"} text={`${r.risk} · ${label(r.level)}`} /> },
        { h: "Booking", r: r => <><b>{r.reference}</b><div className="muted small">{r.guest}</div></> }, { h: "Arrival", r: r => fmtDate(r.arrival) },
        { h: "Source", r: r => label(r.source) }, { h: "Why", r: r => <span className="small">{r.reasons.join(" · ")}</span> }]} />
      <p className="small muted pad">{d.method}</p></>}</Loadable>
  </Card>;
}

export function MaintenanceRisk() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/insights/maintenance-risk`), [hotel?.id]);
  return <Card title="Predicted equipment failures" pad={false}><Loadable state={st}>{d => <>
    <Table rows={d.items} empty="Not enough repair history yet (needs two or more repairs of the same asset)." cols={[
      { h: "Asset", r: a => <><b>{a.asset}</b><div className="muted small">{label(a.category)}</div></> }, { h: "Repairs", r: a => a.repairs },
      { h: "Every ~", r: a => `${a.mean_days_between_failures} days` }, { h: "Last failure", r: a => fmtDate(a.last_failure) },
      { h: "Next expected", r: a => <>{fmtDate(a.predicted_next_failure)}<div className={a.days_left <= 7 ? "danger small" : "muted small"}>{a.days_left < 0 ? `${-a.days_left} days overdue` : `in ${a.days_left} days`}</div></> },
      { h: "Advice", r: a => <Pill s={a.days_left <= 7 ? "rejected" : a.days_left <= 30 ? "pending" : "approved"} text={a.advice} /> }]} />
    <p className="small muted pad">{d.method}</p></>}</Loadable></Card>;
}

export function GuestInsights() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/insights/guests`), [hotel?.id]);
  const Bars = ({ items }: { items: any[] }) => <div className="stack">{items.map((x: any) => <div key={x.label} className="bar-row">
    <span className="small">{x.label}</span><div className="bar"><i style={{ width: `${x.pct}%` }} /></div><span className="small muted">{x.count} · {x.pct}%</span></div>)}</div>;
  return <Loadable state={st}>{d => <>
    <div className="kpis"><Kpi title="Stays" value={d.stays} sub={`${fmtDate(d.from)} – ${fmtDate(d.to)}`} /><Kpi title="Guests" value={d.guests} />
      <Kpi title="Repeat guests" value={d.repeat_guests} /><Kpi title="Average stay" value={d.average_length_of_stay ? `${d.average_length_of_stay} nights` : "—"} /><Kpi title="VIP stays" value={d.vip_stays} /></div>
    <div className="grid-2">
      <Card title="Nationality"><Bars items={d.nationality} /></Card><Card title="Preferred room categories"><Bars items={d.room_categories} /></Card>
      <Card title="Booking sources"><Bars items={d.sources} /></Card><Card title="Booking types"><Bars items={d.booking_types} /></Card>
    </div></>}</Loadable>;
}

// ================================================================== Settings: hotel logo
export function HotelLogo() {
  const { hotel, refresh } = useAuth();
  const { busy, run } = useAction();
  const toast = useToast();
  const [v, setV] = useState(0);
  const src = (hotel as any)?.logo_url;
  return <Card title="Logo" actions={<span className="small muted">PNG, JPEG or WebP, up to 1 MB</span>}>
    <div className="row gap wrap">
      {src ? <img src={`${src}&r=${v}`} alt="Hotel logo" className="logo-preview" /> : <span className="muted">No logo yet — the booking engine and staff header show the hotel name.</span>}
      <input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} aria-label="Upload logo" onChange={async e => {
        const file = e.target.files?.[0]; e.currentTarget.value = "";
        if (!file) return;
        if (file.size > 1024 * 1024) { toast("error", "The logo must be 1 MB or smaller"); return; }
        const b64 = await new Promise<string>((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1] || ""); r.onerror = rej; r.readAsDataURL(file); });
        if (await run(() => post(`/api/hotels/${hotel!.id}/logo`, { filename: file.name, content_base64: b64 }), "Logo updated")) { setV(x => x + 1); refresh(); }
      }} />
    </div>
  </Card>;
}
