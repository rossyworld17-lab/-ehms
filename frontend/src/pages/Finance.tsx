import React, { useEffect, useState } from "react";
import { fmtDate, fmtDateTime, get, label, money, post, put, toMinor, fromMinor } from "../api";
import { useAuth } from "../state";
import { Button, Card, Empty, Field, Input, Kpi, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, useAction, useLoad, useToast } from "../ui";
import { RejectModal } from "./Inventory";
import { ExchangeRates, NotesQueue } from "./Billing";
import { PettyCash, VoucherButton } from "./Completion";

export default function Finance({ q }: { q: URLSearchParams }) {
  const { can } = useAuth();
  const tabs = [
    ...(can("finance.expenses.request") ? [{ id: "expenses", label: "Expense claims" }] : []),
    ...(can("accounting.reconcile") ? [{ id: "bank", label: "Bank reconciliation" }] : []),
    ...(can("accounting.view") ? [{ id: "budget", label: "Budget vs actual" }, { id: "periods", label: "Periods" }, { id: "online", label: "Online payments" }] : []),
    ...(can("reports.financial") ? [{ id: "cashflow", label: "Cash flow" }] : []),
    ...(can("finance.notes.request") || can("finance.notes.approve") ? [{ id: "notes", label: "Credit & debit notes" }] : []),
    ...(can("payments.receive") || can("finance.exchange_rates") ? [{ id: "fx", label: "Exchange rates" }] : []),
    ...(can("finance.petty_cash") ? [{ id: "petty", label: "Petty cash" }] : []),
  ];
  const [tab, setTab] = useState(q.get("tab") || tabs[0]?.id || "expenses");
  useEffect(() => { const t = q.get("tab"); if (t) setTab(t); }, [q.get("tab")]);
  return <div className="page">
    <div className="page-h"><div><h1>Finance operations</h1><p className="muted">Expenses, reconciliation, budgets, cash flow and period close</p></div></div>
    <Tabs tabs={tabs} value={tab} onChange={setTab} />
    {tab === "expenses" && <Expenses />}
    {tab === "bank" && <BankRec />}
    {tab === "budget" && <Budget />}
    {tab === "cashflow" && <CashFlow />}
    {tab === "periods" && <Periods />}
    {tab === "online" && <OnlinePayments />}
    {tab === "notes" && <NotesQueue />}
    {tab === "fx" && <ExchangeRates />}
    {tab === "petty" && <PettyCash />}
  </div>;
}

function Expenses() {
  const { hotel, can, user } = useAuth();
  const cur = hotel!.currency;
  const [status, setStatus] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/expenses`, { status }), [hotel?.id, status]);
  const methods = useLoad(() => get(`/api/hotels/${hotel!.id}/payment-methods`), [hotel?.id]);
  const [modal, setModal] = useState<any>(null);
  const { busy, run } = useAction();
  const act = async (fn: () => Promise<any>, msg: string) => { if (await run(fn, msg)) { setModal(null); st.reload(); } };
  return <Card title={<Select value={status} onChange={e => setStatus(e.target.value)} aria-label="Status"><option value="">All claims</option>{["submitted", "approved", "paid", "rejected"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select>}
    actions={<Button onClick={() => setModal({ kind: "new" })}>New expense claim</Button>} pad={false}>
    <Loadable state={st}>{d => <Table rows={d.items} empty="No expense claims" cols={[
      { h: "Claim", r: e => <><b>{e.number}</b><div className="tiny muted">{fmtDate(e.expense_date)} · {label(e.department)}</div></> },
      { h: "Description", r: e => <>{e.description}<div className="tiny muted">{e.payee || ""}{e.receipt_ref ? ` · receipt ${e.receipt_ref}` : ""}</div></> },
      { h: "Account", r: e => `${e.account_code} ${e.account_name}` }, { h: "By", r: e => e.requested_by_name },
      { h: "Amount", r: e => money(e.amount, cur), cls: "num" }, { h: "Status", r: e => <span title={e.decision_note || ""}><Pill s={e.status} /></span> },
      { h: "", r: e => <span className="row gap-s">
        {e.status === "submitted" && can("finance.expenses.approve") && e.requested_by !== user!.id && <>
          <Button busy={busy} onClick={() => act(() => post(`/api/expenses/${e.id}/decide`, { decision: "approve" }), "Claim approved")}>Approve</Button>
          <Button kind="ghost" onClick={() => setModal({ kind: "reject", e })}>Reject</Button></>}
        {e.status === "approved" && can("finance.expenses.pay") && <Button kind="gold" onClick={() => setModal({ kind: "pay", e })}>Pay</Button>}
        {e.status === "paid" && (can("finance.expenses.pay") || can("finance.expenses.approve") || can("accounting.view")) && <VoucherButton kind="expense" id={e.id} number={e.number} />}</span> }]} />}</Loadable>
    {modal?.kind === "new" && st.data && <NewExpense accounts={st.data.accounts} departments={st.data.departments} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
    {modal?.kind === "reject" && <RejectModal title={`Reject ${modal.e.number}`} onClose={() => setModal(null)} onReject={(note: string) => act(() => post(`/api/expenses/${modal.e.id}/decide`, { decision: "reject", note }), "Claim rejected")} />}
    {modal?.kind === "pay" && <PayExpense e={modal.e} methods={(methods.data?.items || []).filter((m: any) => ["cash", "bank_transfer"].includes(m.kind) && m.active)} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
  </Card>;
}

function NewExpense({ accounts, departments, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ department: departments[0], account_id: accounts[0]?.id || "", amount: "", description: "", payee: "", receipt_ref: "", expense_date: "" });
  const { busy, run } = useAction();
  return <Modal title="New expense claim" width={640} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!(toMinor(f.amount) > 0) || !f.description.trim()} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/expenses`, { ...f, account_id: Number(f.account_id), amount: toMinor(f.amount), expense_date: f.expense_date || undefined }), "Claim submitted for approval")) onDone(); }}>Submit</Button></>}>
    <div className="form-grid">
      <Field label="Department"><Select value={f.department} onChange={e => setF({ ...f, department: e.target.value })}>{departments.map((d: string) => <option key={d} value={d}>{label(d)}</option>)}</Select></Field>
      <Field label="Expense account"><Select value={f.account_id} onChange={e => setF({ ...f, account_id: e.target.value })}>{accounts.map((a: any) => <option key={a.id} value={a.id}>{a.code} {a.name}</option>)}</Select></Field>
      <Field label={`Amount (${hotel!.currency})`}><Input inputMode="decimal" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} /></Field>
      <Field label="Date"><Input type="date" value={f.expense_date} onChange={e => setF({ ...f, expense_date: e.target.value })} /></Field>
      <Field label="Description" wide><Input value={f.description} onChange={e => setF({ ...f, description: e.target.value })} /></Field>
      <Field label="Payee"><Input value={f.payee} onChange={e => setF({ ...f, payee: e.target.value })} /></Field>
      <Field label="Receipt / invoice no."><Input value={f.receipt_ref} onChange={e => setF({ ...f, receipt_ref: e.target.value })} /></Field>
    </div></Modal>;
}

function PayExpense({ e, methods, onClose, onDone }: any) {
  const [f, setF] = useState({ method_id: methods[0]?.id || "", reference: "" });
  const { busy, run } = useAction();
  return <Modal title={`Pay ${e.number}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button kind="gold" busy={busy} onClick={async () => { if (await run(() => post(`/api/expenses/${e.id}/pay`, { method_id: Number(f.method_id), reference: f.reference || undefined }), "Expense paid")) onDone(); }}>Pay</Button></>}>
    <div className="form-grid"><Field label="Pay from"><Select value={f.method_id} onChange={x => setF({ ...f, method_id: x.target.value })}>{methods.map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></Field>
      <Field label="Transfer reference"><Input value={f.reference} onChange={x => setF({ ...f, reference: x.target.value })} /></Field></div></Modal>;
}

/** Minimal CSV parser for statement files: date, description, reference, amount (or money in / money out). */
function parseCsv(text: string): any[] {
  const rows = text.split(/\r?\n/).map(r => r.split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/).map(c => c.replace(/^"|"$/g, "").trim())).filter(r => r.length > 1 && r.some(Boolean));
  if (!rows.length) return [];
  const head = rows[0].map(h => h.toLowerCase());
  const idx = (...n: string[]) => head.findIndex(h => n.some(x => h.includes(x)));
  const di = idx("date"), de = idx("desc", "narr", "detail"), re = idx("ref"), am = idx("amount"), cr = idx("credit", "money in", "deposit"), dr = idx("debit", "money out", "withdraw");
  const toIso = (s: string) => { const m = s.match(/^(\d{1,2})[/-](\d{1,2})[/-](\d{4})$/); return m ? `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}` : s.slice(0, 10); };
  return rows.slice(1).map(r => {
    const v = (i: number) => (i >= 0 ? r[i] || "" : "");
    const amt = am >= 0 ? toMinor(v(am)) : (toMinor(v(cr) || "0") || 0) - (toMinor(v(dr) || "0") || 0);
    return { date: toIso(v(di)), description: v(de), reference: v(re), amount: amt };
  }).filter(l => l.date && l.amount && !isNaN(l.amount));
}

function BankRec() {
  const { hotel } = useAuth();
  const cur = hotel!.currency;
  const [acct, setAcct] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/bank-reconciliation`, { account_id: acct }), [hotel?.id, acct]);
  const [importing, setImporting] = useState(false);
  const [pick, setPick] = useState<any>(null);
  const { busy, run } = useAction();
  useEffect(() => { if (!acct && st.data?.accounts?.length) setAcct(String(st.data.accounts.find((a: any) => a.system_key === "bank")?.id || st.data.accounts[0].id)); }, [st.data]);
  const d = st.data;
  return <div className="stack">
    <div className="row gap-s wrap"><Select value={acct} onChange={e => setAcct(e.target.value)} aria-label="Account">{(d?.accounts || []).map((a: any) => <option key={a.id} value={a.id}>{a.code} {a.name}</option>)}</Select>
      <Button onClick={() => setImporting(true)} disabled={!acct}>Import statement</Button>
      <Button kind="secondary" busy={busy} disabled={!acct} onClick={async () => { const r = await run(() => post(`/api/hotels/${hotel!.id}/bank-reconciliation/auto-match`, { account_id: Number(acct) })); if (r) { st.reload(); } }}>Auto-match</Button></div>
    {d?.account && <>
      <div className="kpis">
        <Kpi title="Balance per books" value={money(d.summary.book_balance, cur)} tone="navy" sub={`as at ${d.as_at}`} />
        <Kpi title="Outstanding book items" value={money(d.summary.outstanding_book_items, cur)} sub={`${d.unreconciled_book_lines.length} not yet on a statement`} />
        <Kpi title="Unmatched statement items" value={money(d.summary.unmatched_statement_items, cur)} sub={`${d.statement_lines.filter((s: any) => s.status === "unmatched").length} lines (e.g. bank charges)`} />
        <Kpi title="Difference" value={money(d.summary.difference, cur)} tone={d.summary.difference === 0 ? undefined : "gold"} sub={d.summary.difference === 0 ? "Reconciled" : "Investigate"} />
      </div>
      <div className="grid-2">
        <Card title="Statement lines" pad={false}><Table rows={d.statement_lines} empty="No statement imported yet" cols={[{ h: "Date", r: s => s.txn_date }, { h: "Description", r: s => <>{s.description}<div className="tiny muted">{s.reference || ""}</div></> },
          { h: "Amount", r: s => money(s.amount, cur), cls: "num" }, { h: "Status", r: s => <Pill s={s.status === "matched" ? "approved" : s.status === "ignored" ? "cancelled" : "pending"} text={label(s.status)} /> },
          { h: "", r: s => s.status === "unmatched" ? <span className="row gap-s"><button className="link small" onClick={() => setPick(s)}>Match</button>
            <button className="link small" onClick={async () => { if (await run(() => post(`/api/bank-statement-lines/${s.id}/match`, { ignore: true }), "Ignored")) st.reload(); }}>Ignore</button></span>
            : <button className="link small" onClick={async () => { if (await run(() => post(`/api/bank-statement-lines/${s.id}/match`, { journal_line_id: null }), "Unmatched")) st.reload(); }}>Undo</button> }]} /></Card>
        <Card title="Book entries not yet on a statement" pad={false}><Table rows={d.unreconciled_book_lines} empty="All book entries are reconciled" cols={[{ h: "Date", r: b => b.entry_date },
          { h: "Entry", r: b => <>{b.number}<div className="tiny muted">{b.description}</div></> }, { h: "Amount", r: b => money(b.amount, cur), cls: "num" }]} /></Card>
      </div>
      <p className="muted small">Post bank charges or interest found only on the statement as a manual journal in Accounting, then match them here.</p></>}
    {importing && <ImportModal account={acct} onClose={() => setImporting(false)} onDone={() => { setImporting(false); st.reload(); }} />}
    {pick && d && <Modal title={`Match ${money(pick.amount, cur)} on ${pick.txn_date}`} onClose={() => setPick(null)}>
      <div className="picklist">{d.unreconciled_book_lines.filter((b: any) => b.amount === pick.amount).map((b: any) => <button key={b.id} onClick={async () => { if (await run(() => post(`/api/bank-statement-lines/${pick.id}/match`, { journal_line_id: b.id }), "Matched")) { setPick(null); st.reload(); } }}>
        {b.entry_date} · {b.number} · {b.description}</button>)}
        {!d.unreconciled_book_lines.some((b: any) => b.amount === pick.amount) && <p className="muted small">No unreconciled book entry has exactly this amount.</p>}</div></Modal>}
  </div>;
}

function ImportModal({ account, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [text, setText] = useState("");
  const lines = parseCsv(text);
  const { busy, run } = useAction();
  return <Modal title="Import bank statement (CSV)" width={720} onClose={onClose} footer={<><span className="grow muted small">{lines.length} line(s) recognised</span><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!lines.length} onClick={async () => { const r = await run(() => post(`/api/hotels/${hotel!.id}/bank-reconciliation/import`, { account_id: Number(account), lines }), "Statement imported"); if (r) onDone(); }}>Import</Button></>}>
    <p className="small muted">Columns: Date, Description, Reference, Amount (money in positive, out negative) — or separate Credit/Debit columns. Dates as YYYY-MM-DD or DD/MM/YYYY.</p>
    <input type="file" accept=".csv,text/csv" onChange={async e => { const f = e.target.files?.[0]; if (f) setText(await f.text()); }} />
    <Field label="…or paste the CSV" wide><Textarea rows={8} value={text} onChange={e => setText(e.target.value)} placeholder={"Date,Description,Reference,Amount\n2026-11-20,NIP transfer from guest,REF123,30000.00"} /></Field>
  </Modal>;
}

function Budget() {
  const { hotel, can } = useAuth();
  const cur = hotel!.currency;
  const now = new Date();
  const [f, setF] = useState({ year: now.getFullYear(), month: String(now.getMonth() + 1) });
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/budgets`, { year: f.year, month: f.month }), [hotel?.id, f.year, f.month]);
  const [edit, setEdit] = useState(false);
  return <Card title={<div className="row gap-s"><Input className="sm" type="number" value={f.year} onChange={e => setF({ ...f, year: Number(e.target.value) })} />
    <Select value={f.month} onChange={e => setF({ ...f, month: e.target.value })}><option value="">Year to date</option>{Array.from({ length: 12 }, (_, i) => <option key={i} value={i + 1}>{new Date(2000, i, 1).toLocaleString("en-GB", { month: "long" })}</option>)}</Select></div>}
    actions={can("accounting.budgets") && <Button onClick={() => setEdit(true)}>Edit {f.year} budget</Button>} pad={false}>
    <Loadable state={st}>{d => <Table rows={d.items} empty="No budget or activity for this period" cols={[{ h: "Account", r: a => `${a.code} ${a.name}` }, { h: "Type", r: a => label(a.type) },
      { h: "Budget", r: a => money(a.budget, cur), cls: "num" }, { h: "Actual", r: a => money(a.actual, cur), cls: "num" },
      { h: "Variance", r: a => <span className={a.favourable ? "pos" : "danger"}>{money(a.variance, cur)}</span>, cls: "num" },
      { h: "Achieved", r: a => a.budget ? `${Math.round(a.actual * 100 / a.budget)}%` : "—", cls: "num" }]} />}</Loadable>
    {edit && st.data && <BudgetEditor year={f.year} data={st.data} onClose={() => setEdit(false)} onDone={() => { setEdit(false); st.reload(); }} />}
  </Card>;
}

function BudgetEditor({ year, data, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const existing: Record<number, number[]> = Object.fromEntries(data.items.map((r: any) => [r.id, r.months]));
  const [acct, setAcct] = useState(String(data.all_accounts[0]?.id || ""));
  const [vals, setVals] = useState<Record<number, string[]>>({});
  const cur = vals[Number(acct)] || (existing[Number(acct)] || Array(12).fill(0)).map((v: number) => fromMinor(v));
  const set = (i: number, v: string) => setVals({ ...vals, [Number(acct)]: cur.map((x: string, j: number) => (j === i ? v : x)) });
  const { busy, run } = useAction();
  return <Modal title={`Budget ${year}`} width={760} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} disabled={!Object.keys(vals).length} onClick={async () => { if (await run(() => put(`/api/hotels/${hotel!.id}/budgets`, { year, lines: Object.entries(vals).map(([a, m]) => ({ account_id: Number(a), months: m.map(x => toMinor(x || "0")) })) }), "Budget saved")) onDone(); }}>Save</Button></>}>
    <Field label="Account"><Select value={acct} onChange={e => setAcct(e.target.value)}>{data.all_accounts.map((a: any) => <option key={a.id} value={a.id}>{a.code} {a.name} ({a.type})</option>)}</Select></Field>
    <div className="form-grid">{cur.map((v: string, i: number) => <Field key={i} label={new Date(2000, i, 1).toLocaleString("en-GB", { month: "short" })}><Input inputMode="decimal" value={v} onChange={e => set(i, e.target.value)} /></Field>)}</div>
    <button className="link small" onClick={() => setVals({ ...vals, [Number(acct)]: Array(12).fill(cur[0]) })}>Copy January to all months</button>
  </Modal>;
}

function CashFlow() {
  const { hotel } = useAuth();
  const cur = hotel!.currency;
  const today = new Date().toISOString().slice(0, 10);
  const [f, setF] = useState({ from: today.slice(0, 8) + "01", to: today });
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/cash-flow`, f), [hotel?.id, f.from, f.to]);
  return <Card title={<div className="row gap-s"><Input type="date" value={f.from} onChange={e => setF({ ...f, from: e.target.value })} /><Input type="date" value={f.to} onChange={e => setF({ ...f, to: e.target.value })} /></div>}>
    <Loadable state={st}>{d => <div className="totals" style={{ maxWidth: 520, marginLeft: 0 }}>
      <div><span>Opening cash and bank</span><b>{money(d.opening_cash, cur)}</b></div>
      {d.lines.map((l: any) => <div key={l.category} className="small"><span>{l.category}</span><b className={l.amount < 0 ? "danger" : ""}>{money(l.amount, cur)}</b></div>)}
      <div><span>Net cash from operations</span><b>{money(d.net_operating, cur)}</b></div>
      <div><span>Net change in cash</span><b>{money(d.net_change, cur)}</b></div>
      <div className="grand"><span>Closing cash and bank</span><b>{money(d.closing_cash, cur)}</b></div>
      <p className="muted small">Direct method: every movement on cash, bank and card/online clearing accounts, classified by the other side of the entry.</p>
    </div>}</Loadable></Card>;
}

function Periods() {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/accounting/periods`), [hotel?.id]);
  const [reopen, setReopen] = useState<string | null>(null);
  const { busy, run } = useAction();
  return <Card title="Accounting periods" pad={false}><Loadable state={st}>{d => <Table rows={d.items} cols={[{ h: "Period", r: p => <b>{p.period}</b> },
    { h: "Status", r: p => <Pill s={p.status === "closed" ? "closed" : "open"} text={p.period === d.current ? "Current (open)" : label(p.status)} /> },
    { h: "Closed by", r: p => p.closed_by_name ? `${p.closed_by_name} · ${fmtDateTime(p.closed_at)}` : "—" }, { h: "Note", r: p => p.note || "" },
    { h: "", r: p => can("accounting.close_period") && p.period !== d.current && (p.status === "closed"
      ? <Button kind="ghost" onClick={() => setReopen(p.period)}>Reopen</Button>
      : <Button kind="secondary" busy={busy} onClick={async () => { if (confirm(`Close ${p.period}? No further entries can be dated in this month.`) && await run(() => post(`/api/hotels/${hotel!.id}/accounting/periods/${p.period}/close`, {}), "Period closed")) st.reload(); }}>Close period</Button>) }]} />}</Loadable>
    {reopen && <RejectModal title={`Reopen ${reopen}`} onClose={() => setReopen(null)} onReject={async (reason: string) => { if (await run(() => post(`/api/hotels/${hotel!.id}/accounting/periods/${reopen}/reopen`, { reason }), "Period reopened")) { setReopen(null); st.reload(); } }} />}
  </Card>;
}

function OnlinePayments() {
  const { hotel, can } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/gateway-transactions`), [hotel?.id]);
  const { run } = useAction();
  return <Loadable state={st}>{d => <div className="stack">
    {!d.providers.length && <p className="note">No payment provider is configured. Set PAYSTACK_SECRET_KEY or FLUTTERWAVE_SECRET_KEY on the server (see the deployment guide) to enable payment links and online booking payments.</p>}
    <Card title="Online payment transactions" pad={false}><Table rows={d.items} empty="No online payments yet" cols={[{ h: "Reference", r: t => <span className="mono small">{t.reference}</span> },
      { h: "Provider", r: t => label(t.provider) }, { h: "For", r: t => t.reservation_reference || t.folio_number || "—" }, { h: "Amount", r: t => money(t.amount, cur), cls: "num" },
      { h: "Status", r: t => <Pill s={t.status === "success" ? "approved" : t.status === "initialized" ? "pending" : "rejected"} text={label(t.status)} /> }, { h: "Created", r: t => fmtDateTime(t.created_at) },
      { h: "", r: t => t.status === "initialized" && can("payments.receive") && <button className="link small" onClick={async () => { if (await run(() => post(`/api/gateway-transactions/${t.id}/verify`, {}), "Checked with provider")) st.reload(); }}>Re-check</button> }]} /></Card>
    <Card title="Integration log" pad={false}><Table rows={d.log} empty="No integration activity" cols={[{ h: "When", r: l => fmtDateTime(l.created_at) }, { h: "Integration", r: l => l.integration },
      { h: "Direction", r: l => l.direction }, { h: "Endpoint", r: l => <span className="mono tiny">{l.endpoint}</span> }, { h: "HTTP", r: l => l.status_code ?? "—" },
      { h: "Attempt", r: l => l.attempt }, { h: "Result", r: l => l.ok ? <Pill s="approved" text="OK" /> : <span className="danger small">{l.error || "failed"}</span> }]} /></Card>
  </div>}</Loadable>;
}
