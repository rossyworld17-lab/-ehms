import React, { useState } from "react";
import { fmtDate, fmtDateTime, fromMinor, get, label, money, openFile, patch, post, put, toMinor } from "../api";
import { navigate, useAuth } from "../state";
import { Button, Card, Field, Input, Loadable, Modal, Pill, Select, Table, Textarea, errText, useAction, useLoad, useToast } from "../ui";

/** Cancel or mark no-show, showing the fee the policy applies and allowing an authorised waiver. */
export function CancelModal({ res, kind, onClose, onDone }: { res: any; kind: "cancel" | "no_show"; onClose: () => void; onDone: () => void }) {
  const { can, hotel } = useAuth();
  const fee = useLoad(() => get(`/api/reservations/${res.id}/cancellation-fee`, { kind }), [res.id, kind]);
  const [reason, setReason] = useState("");
  const [waive, setWaive] = useState(false);
  const [waiveReason, setWaiveReason] = useState("");
  const { busy, run } = useAction();
  const go = async () => {
    const body: any = kind === "cancel" ? { reason } : {};
    if (waive) body.waive_fee_reason = waiveReason;
    const r = await run(() => post(`/api/reservations/${res.id}/${kind === "cancel" ? "cancel" : "no-show"}`, body), kind === "cancel" ? "Reservation cancelled" : "Marked as no-show");
    if (r) onDone();
  };
  return <Modal title={kind === "cancel" ? "Cancel reservation" : "Mark as no-show"} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Back</Button>
    <Button kind="danger" busy={busy} disabled={(kind === "cancel" && !reason.trim()) || (waive && waiveReason.trim().length < 5)} onClick={go}>{kind === "cancel" ? "Cancel reservation" : "Mark no-show"}</Button></>}>
    <div className="stack">
      <p>{kind === "cancel" ? "Cancel" : "Mark"} {res.reference} for {res.guest.first_name} {res.guest.last_name}{kind === "no_show" ? " as a no-show (allowed on or after the arrival date)" : ""}?</p>
      <Loadable state={fee}>{f => f.fee > 0 ? <div className="note">
        <b>{kind === "cancel" ? "Cancellation" : "No-show"} fee: {money(f.fee, hotel!.currency)}</b> — {f.explanation} It will be posted to the folio{f.policy ? ` (policy: ${f.policy.name})` : ""}.
        {can("reservations.waive_fee") && <label className="check mt"><input type="checkbox" checked={waive} onChange={e => setWaive(e.target.checked)} /> Waive the fee</label>}
      </div> : <p className="muted">{f.explanation}</p>}</Loadable>
      {waive && <Field label="Reason for waiving (recorded in the audit trail)"><Textarea value={waiveReason} onChange={e => setWaiveReason(e.target.value)} /></Field>}
      {kind === "cancel" && <Field label="Reason for cancellation"><Textarea value={reason} onChange={e => setReason(e.target.value)} /></Field>}
    </div></Modal>;
}

/** Other folios of the stay, extra-folio creation, transfers and credit/debit notes — shown on the folio page. */
export function FolioExtras({ folio, onChange }: { folio: any; onChange: () => void }) {
  const { can, hotel } = useAuth();
  const [modal, setModal] = useState<string | null>(null);
  const cur = hotel!.currency;
  const stayId = folio.reservation?.id;
  return <>
    <div className="row gap-s wrap">
      {folio.status === "open" && can("folio.transfer") && stayId && folio.reservation.status !== "checked_out" && <Button kind="secondary" onClick={() => setModal("window")}>New folio (split bill)</Button>}
      {folio.status === "open" && can("folio.transfer") && (folio.other_folios || []).some((o: any) => o.status === "open") && <Button kind="secondary" onClick={() => setModal("transfer")}>Transfer charges</Button>}
      {can("finance.notes.request") && <Button kind="secondary" onClick={() => setModal("note")}>Credit / debit note</Button>}
    </div>
    {(folio.other_folios || []).length > 0 && <Card title="Other folios for this stay" pad={false}><Table rows={folio.other_folios} onRow={o => navigate(`/folio/${o.id}`)} cols={[
      { h: "Folio", r: o => o.number }, { h: "Name", r: o => o.window_name || "Guest folio" }, { h: "Status", r: o => <Pill s={o.status} /> }, { h: "Balance", r: o => money(o.balance, cur), cls: "num" }]} /></Card>}
    {(folio.notes || []).length > 0 && <Card title="Credit and debit notes" pad={false}><Table rows={folio.notes} cols={[
      { h: "Number", r: n => n.number }, { h: "Kind", r: n => label(n.kind) }, { h: "Total", r: n => money(n.total_amount, cur), cls: "num" }, { h: "Status", r: n => <Pill s={n.status} /> },
      { h: "", r: n => <Button kind="ghost" onClick={() => openFile(`/api/notes/${n.id}/pdf`, `${n.number}.pdf`, true)}>PDF</Button> }]} /></Card>}
    {modal === "window" && <WindowModal resId={stayId} onClose={() => setModal(null)} onDone={(id: number) => { setModal(null); navigate(`/folio/${id}`); }} />}
    {modal === "transfer" && <TransferModal folio={folio} onClose={() => setModal(null)} onDone={() => { setModal(null); onChange(); }} />}
    {modal === "note" && <NoteModal folio={folio} onClose={() => setModal(null)} onDone={() => { setModal(null); onChange(); }} />}
  </>;
}

function WindowModal({ resId, onClose, onDone }: any) {
  const [name, setName] = useState("Company account");
  const { hotel } = useAuth();
  const list = useLoad(() => get(`/api/hotels/${hotel!.id}/accounts/active`).catch(() => ({ items: [] })), [hotel?.id]);
  const [acct, setAcct] = useState("");
  const { busy, run } = useAction();
  return <Modal title="Open an additional folio" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!name.trim()} onClick={async () => { const r = await run(() => post(`/api/reservations/${resId}/folios`, { window_name: name, corporate_account_id: acct ? Number(acct) : undefined }), "Folio opened"); if (r) onDone(r.id); }}>Open folio</Button></>}>
    <div className="form-grid"><Field label="Name" hint="e.g. Company account, Incidentals"><Input value={name} onChange={e => setName(e.target.value)} /></Field>
      <Field label="Bill to account (optional)"><Select value={acct} onChange={e => setAcct(e.target.value)}><option value="">—</option>{(list.data?.items || []).map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field></div>
    <p className="muted small">Move charges here with “Transfer charges”. All folios of the stay must be settled before check-out.</p></Modal>;
}

function TransferModal({ folio, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const targets = (folio.other_folios || []).filter((o: any) => o.status === "open");
  const charges = folio.lines.filter((l: any) => l.kind === "charge" && !l.reversed);
  const [sel, setSel] = useState<number[]>([]);
  const [target, setTarget] = useState(String(targets[0]?.id || ""));
  const [reason, setReason] = useState("");
  const [amount, setAmount] = useState("");
  const { busy, run } = useAction();
  return <Modal title="Transfer charges" width={680} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!sel.length || !target || !reason.trim() || (!!amount && sel.length !== 1)} onClick={async () => {
      const r = await run(() => post(`/api/folios/${folio.id}/transfer`, { line_ids: sel, target_folio_id: Number(target), reason, amount: amount ? toMinor(amount) : undefined }), "Charges transferred");
      if (r) onDone(); }}>Transfer</Button></>}>
    <div className="stack">
      <Field label="To folio"><Select value={target} onChange={e => setTarget(e.target.value)}>{targets.map((t: any) => <option key={t.id} value={t.id}>{t.number} — {t.window_name || "Guest folio"}</option>)}</Select></Field>
      <Table rows={charges} cols={[{ h: "", r: l => <input type="checkbox" aria-label={`Select ${l.description}`} checked={sel.includes(l.id)} onChange={e => setSel(e.target.checked ? [...sel, l.id] : sel.filter(x => x !== l.id))} /> },
        { h: "Date", r: l => fmtDate(l.business_date) }, { h: "Charge", r: l => l.description }, { h: "Amount", r: l => money(l.total_amount, hotel!.currency), cls: "num" }]} empty="No charges to transfer" />
      <div className="form-grid"><Field label="Part amount (₦, optional)" hint="Only when moving part of one charge"><Input inputMode="decimal" value={amount} onChange={e => setAmount(e.target.value)} /></Field>
        <Field label="Reason" wide><Textarea value={reason} onChange={e => setReason(e.target.value)} /></Field></div>
    </div></Modal>;
}

function NoteModal({ folio, onClose, onDone }: any) {
  const [f, setF] = useState({ kind: "credit", department: "room", description: "", net_amount: "", reason: "" });
  const { busy, run } = useAction();
  return <Modal title="Raise a credit or debit note" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.description.trim() || !(toMinor(f.net_amount) > 0) || f.reason.trim().length < 5} onClick={async () => {
      const r = await run(() => post(`/api/folios/${folio.id}/notes`, { ...f, net_amount: toMinor(f.net_amount) }), "Note raised — awaiting approval"); if (r) onDone(); }}>Submit for approval</Button></>}>
    <div className="form-grid">
      <Field label="Type"><Select value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}><option value="credit">Credit note (reduce what the guest owes)</option><option value="debit">Debit note (additional charge)</option></Select></Field>
      <Field label="Department"><Select value={f.department} onChange={e => setF({ ...f, department: e.target.value })}>{["room", "fnb", "minibar", "laundry", "events", "transport", "spa", "other"].map(d => <option key={d} value={d}>{label(d)}</option>)}</Select></Field>
      <Field label="Amount before tax (₦)" hint="Service charge and tax are calculated as for the original charge"><Input inputMode="decimal" value={f.net_amount} onChange={e => setF({ ...f, net_amount: e.target.value })} /></Field>
      <Field label="Description (printed on the note)" wide><Input value={f.description} onChange={e => setF({ ...f, description: e.target.value })} /></Field>
      <Field label="Reason (internal)" wide><Textarea value={f.reason} onChange={e => setF({ ...f, reason: e.target.value })} /></Field>
    </div>
    <p className="muted small">A finance approver (not you) must approve it. Approval posts it to this folio and the ledger; a closed folio is reopened so any refund or payment follows the normal rules.</p></Modal>;
}

/** Finance: notes awaiting approval. */
export function NotesQueue() {
  const { hotel, can, user } = useAuth();
  const [status, setStatus] = useState("pending_approval");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/notes`, status ? { status } : {}), [hotel?.id, status]);
  const [open, setOpen] = useState<any>(null);
  const [note, setNote] = useState("");
  const { busy, run } = useAction();
  const cur = hotel!.currency;
  return <Loadable state={st}>{d => <div className="stack">
    <div className="row gap-s">{[["pending_approval", "Awaiting approval"], ["approved", "Approved"], ["rejected", "Rejected"], ["", "All"]].map(([k, l]) => <Button key={k} kind={k === status ? "primary" : "secondary"} onClick={() => setStatus(k)}>{l}</Button>)}</div>
    <Card pad={false}><Table rows={d.items} onRow={setOpen} empty="Nothing here" cols={[{ h: "Number", r: n => n.number }, { h: "Kind", r: n => label(n.kind) }, { h: "Folio", r: n => n.folio_number },
      { h: "Guest", r: n => n.guest }, { h: "Description", r: n => <span className="small">{n.description}</span> }, { h: "Total", r: n => money(n.total_amount, cur), cls: "num" },
      { h: "Raised by", r: n => n.requested_by_name }, { h: "Status", r: n => <Pill s={n.status} /> }]} /></Card>
    {open && <Modal title={`${label(open.kind)} note ${open.number}`} onClose={() => setOpen(null)} footer={<><Button kind="secondary" onClick={() => setOpen(null)}>Close</Button>
      <Button kind="ghost" onClick={() => openFile(`/api/notes/${open.id}/pdf`, `${open.number}.pdf`, true)}>PDF</Button>
      {open.status === "pending_approval" && can("finance.notes.approve") && open.requested_by !== user!.id && <>
        <Button kind="danger" busy={busy} disabled={!note.trim()} onClick={async () => { if (await run(() => post(`/api/notes/${open.id}/decide`, { decision: "reject", note }), "Note rejected")) { setOpen(null); st.reload(); } }}>Reject</Button>
        <Button busy={busy} onClick={async () => { const r = await run(() => post(`/api/notes/${open.id}/decide`, { decision: "approve", note: note || undefined }), "Note approved and posted"); if (r) { setOpen(null); st.reload(); } }}>Approve</Button></>}</>}>
      <dl className="dl"><dt>Folio</dt><dd><a href={`#/folio/${open.folio_id}`}>{open.folio_number}</a> — {open.guest}</dd><dt>Description</dt><dd>{open.description}</dd><dt>Reason</dt><dd>{open.reason}</dd>
        <dt>Net</dt><dd>{money(open.net_amount, cur)}</dd><dt>Service charge</dt><dd>{money(open.service_charge, cur)}</dd><dt>Tax</dt><dd>{money(open.tax_amount, cur)}</dd><dt>Total</dt><dd><b>{money(open.total_amount, cur)}</b></dd>
        <dt>Raised</dt><dd>{open.requested_by_name}, {fmtDateTime(open.created_at)}</dd>{open.decided_by_name && <><dt>Decided</dt><dd>{open.decided_by_name}, {fmtDateTime(open.decided_at)} {open.decision_note ? `— ${open.decision_note}` : ""}</dd></>}</dl>
      {open.status === "pending_approval" && can("finance.notes.approve") && (open.requested_by === user!.id ? <p className="muted small mt">You raised this note, so someone else must decide it.</p>
        : <Field label="Note (required to reject)" wide><Textarea value={note} onChange={e => setNote(e.target.value)} /></Field>)}
    </Modal>}
  </div>}</Loadable>;
}

/** Finance: exchange rates. */
export function ExchangeRates() {
  const { can } = useAuth();
  const st = useLoad(() => get("/api/exchange-rates"), []);
  const [f, setF] = useState({ currency: "USD", rate: "", rate_date: new Date().toISOString().slice(0, 10), source: "" });
  const { busy, run } = useAction();
  const toast = useToast();
  return <Loadable state={st}>{d => <div className="stack">
    <div className="grid-2">
      <Card title="Current rates" pad={false}><Table rows={d.latest} rowKey={r => r.currency} empty="No rates recorded — foreign-currency payments are disabled until a rate exists" cols={[
        { h: "Currency", r: r => <b>{r.currency}</b> }, { h: "Rate (₦ per unit)", r: r => (r.rate_micro / 1e6).toLocaleString(undefined, { maximumFractionDigits: 6 }), cls: "num" },
        { h: "Date", r: r => fmtDate(r.rate_date) }, { h: "Source", r: r => <span className="small">{r.source || "—"}</span> }]} /></Card>
      {can("finance.exchange_rates") && <Card title="Record a rate">
        <div className="form-grid"><Field label="Currency"><Input value={f.currency} maxLength={3} onChange={e => setF({ ...f, currency: e.target.value.toUpperCase() })} /></Field>
          <Field label="₦ per 1 unit"><Input inputMode="decimal" value={f.rate} placeholder="1550.25" onChange={e => setF({ ...f, rate: e.target.value })} /></Field>
          <Field label="Date"><Input type="date" value={f.rate_date} onChange={e => setF({ ...f, rate_date: e.target.value })} /></Field>
          <Field label="Source"><Input value={f.source} placeholder="e.g. bank buying rate" onChange={e => setF({ ...f, source: e.target.value })} /></Field></div>
        <Button className="mt" busy={busy} disabled={f.currency.length !== 3 || !f.rate} onClick={async () => {
          const r = await run(() => post("/api/exchange-rates", f), "Rate recorded"); if (r) { if (r.warning) toast("info", r.warning); setF({ ...f, rate: "" }); st.reload(); } }}>Save rate</Button>
        <p className="muted small mt">Payments in foreign currency are converted at the latest rate on or before the business date. Rates are not edited once recorded.</p></Card>}
    </div>
    <Card title="History" pad={false}><Table rows={d.history} cols={[{ h: "Date", r: r => fmtDate(r.rate_date) }, { h: "Currency", r: r => r.currency },
      { h: "Rate", r: r => (r.rate_micro / 1e6).toLocaleString(undefined, { maximumFractionDigits: 6 }), cls: "num" }, { h: "Entered by", r: r => r.entered_by || "—" }, { h: "Source", r: r => r.source || "" }]} /></Card>
  </div>}</Loadable>;
}

/** Settings: cancellation policies. */
export function CancellationPolicies() {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/cancellation-policies`), [hotel?.id]);
  const [adding, setAdding] = useState(false);
  const { busy, run } = useAction();
  const fee = (t: string, v: number) => t === "none" ? "No fee" : t === "first_night" ? "First night" : t === "percent" ? `${v / 100}% of stay` : money(v, hotel!.currency);
  return <Loadable state={st}>{d => <Card title="Cancellation policies" actions={can("admin.settings.manage") && <Button onClick={() => setAdding(true)}>New policy</Button>} pad={false}>
    <Table rows={d.items} cols={[{ h: "Policy", r: p => <><b>{p.name}</b>{p.is_default ? <> <Pill s="active" text="Default" /></> : null}</> }, { h: "Free until", r: p => p.free_until_hours ? `${p.free_until_hours} h before arrival` : "Never" },
      { h: "Late cancellation", r: p => fee(p.fee_type, p.fee_value) }, { h: "No-show", r: p => fee(p.no_show_fee_type, p.no_show_fee_value) },
      { h: "", r: p => can("admin.settings.manage") && !p.is_default ? <Button kind="ghost" busy={busy} onClick={async () => { if (await run(() => patch(`/api/cancellation-policies/${p.id}`, { is_default: true }), "Default policy changed")) st.reload(); }}>Make default</Button> : null }]} />
    <p className="muted small pad">The default applies to new bookings unless another policy is chosen. A booking keeps the policy it was made under.</p>
    {adding && <NewPolicy onClose={() => setAdding(false)} onDone={() => { setAdding(false); st.reload(); }} />}
  </Card>}</Loadable>;
}

function NewPolicy({ onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState<any>({ name: "", free_until_hours: 24, fee_type: "first_night", fee_value: "", no_show_fee_type: "first_night", no_show_fee_value: "", is_default: false });
  const { busy, run } = useAction();
  const val = (t: string, v: string) => t === "percent" ? Math.round(Number(v) * 100) : t === "fixed" ? toMinor(v) : 0;
  return <Modal title="New cancellation policy" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.name.trim()} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/cancellation-policies`, { ...f, free_until_hours: Number(f.free_until_hours),
      fee_value: val(f.fee_type, f.fee_value), no_show_fee_value: val(f.no_show_fee_type, f.no_show_fee_value) }), "Policy created")) onDone(); }}>Save</Button></>}>
    <div className="form-grid">
      <Field label="Name" wide><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Free cancellation until (hours before arrival)"><Input type="number" min={0} value={f.free_until_hours} onChange={e => setF({ ...f, free_until_hours: e.target.value })} /></Field>
      {(["fee", "no_show_fee"] as const).map(k => <React.Fragment key={k}>
        <Field label={k === "fee" ? "Late cancellation fee" : "No-show fee"}><Select value={f[`${k}_type`]} onChange={e => setF({ ...f, [`${k}_type`]: e.target.value })}>
          <option value="none">No fee</option><option value="first_night">First night</option><option value="percent">Percentage of stay</option><option value="fixed">Fixed amount</option></Select></Field>
        {["percent", "fixed"].includes(f[`${k}_type`]) && <Field label={f[`${k}_type`] === "percent" ? "Percentage" : "Amount (₦)"}><Input inputMode="decimal" value={f[`${k}_value`]} onChange={e => setF({ ...f, [`${k}_value`]: e.target.value })} /></Field>}
      </React.Fragment>)}
      <label className="check"><input type="checkbox" checked={f.is_default} onChange={e => setF({ ...f, is_default: e.target.checked })} /> Use as default for new bookings</label>
    </div></Modal>;
}

/** Inventory: costing method. */
export function CostingSetting() {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/inventory/costing`), [hotel?.id]);
  const [reason, setReason] = useState("");
  const { busy, run } = useAction();
  return <Loadable state={st}>{d => <Card title="Stock costing method">
    <p>Current method: <b>{d.method === "fifo" ? "FIFO (first in, first out)" : "Weighted average cost"}</b>. {d.method === "fifo" ? "Issues are costed from the oldest receipts first, and batches are used in receipt order." : "Issues are costed at the average cost of stock on hand; batches are used first-expiry-first-out."}</p>
    {can("inventory.manage") && can("accounting.view") && <div className="row gap-s wrap mt"><Input value={reason} placeholder="Reason for the change (audited)" onChange={e => setReason(e.target.value)} style={{ minWidth: 260 }} />
      <Button kind="secondary" busy={busy} disabled={reason.trim().length < 5} onClick={async () => { if (await run(() => put(`/api/hotels/${hotel!.id}/inventory/costing`, { method: d.method === "fifo" ? "wac" : "fifo", reason }), "Costing method changed")) { setReason(""); st.reload(); } }}>
        Switch to {d.method === "fifo" ? "weighted average" : "FIFO"}</Button></div>}
    <p className="muted small mt">Changing the method affects issues from now on; agree it with your auditors and change it at a period end.</p></Card>}</Loadable>;
}
