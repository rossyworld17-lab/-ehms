import React, { useState } from "react";
import { addDays, fmtDate, get, label, money, post, toMinor } from "../api";
import { useAuth } from "../state";
import { Button, Card, Field, Input, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, useAction, useLoad } from "../ui";

const today = () => new Date().toISOString().slice(0, 10);

export default function Accounting() {
  const { can } = useAuth();
  const [tab, setTab] = useState("tb");
  const tabs = [{ id: "tb", label: "Trial balance" }, ...(can("reports.financial") ? [{ id: "pl", label: "Profit & loss" }, { id: "bs", label: "Balance sheet" }] : []),
    { id: "journal", label: "Journal" }, { id: "coa", label: "Chart of accounts" }];
  return <div className="page">
    <div className="page-h"><div><h1>Accounting</h1><p className="muted">Double-entry general ledger fed automatically by folios, payments and refunds</p></div></div>
    <Tabs tabs={tabs} value={tab} onChange={setTab} />
    {tab === "tb" && <TrialBalance />}{tab === "pl" && <ProfitLoss />}{tab === "bs" && <BalanceSheet />}{tab === "journal" && <Journal />}{tab === "coa" && <Accounts />}
  </div>;
}

function Scope({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { user, hotel } = useAuth();
  return <Select value={value} onChange={e => onChange(e.target.value)} aria-label="Scope">
    <option value={String(hotel!.id)}>{hotel!.name}</option>{user!.hotels.length > 1 && <option value="all">All properties (consolidated)</option>}</Select>;
}

function TrialBalance() {
  const { hotel } = useAuth();
  const [asAt, setAsAt] = useState(today());
  const [scope, setScope] = useState(String(hotel!.id));
  const st = useLoad(() => get("/api/reports/trial-balance", { as_at: asAt, hotel_id: scope }), [asAt, scope]);
  const cur = hotel!.currency;
  return <Card title="Trial balance" actions={<><Scope value={scope} onChange={setScope} /><Input type="date" value={asAt} onChange={e => setAsAt(e.target.value)} aria-label="As at" /></>} pad={false}>
    <Loadable state={st}>{d => <>
      <Table rows={d.items} cols={[{ h: "Code", r: r => r.code }, { h: "Account", r: r => r.name }, { h: "Type", r: r => label(r.type) },
        { h: "Debit", r: r => (r.balance_debit ? money(r.balance_debit, cur) : ""), cls: "num" }, { h: "Credit", r: r => (r.balance_credit ? money(r.balance_credit, cur) : ""), cls: "num" }]} empty="No postings yet" />
      <div className="totals-row"><span>Totals</span><b>{money(d.total_debit, cur)}</b><b>{money(d.total_credit, cur)}</b>{d.balanced ? <Pill s="approved" text="Balanced" /> : <Pill s="failed" text="Out of balance" />}</div>
    </>}</Loadable></Card>;
}

function ProfitLoss() {
  const { hotel } = useAuth();
  const [from, setFrom] = useState(today().slice(0, 8) + "01");
  const [to, setTo] = useState(today());
  const [scope, setScope] = useState(String(hotel!.id));
  const st = useLoad(() => get("/api/reports/profit-and-loss", { from, to, hotel_id: scope }), [from, to, scope]);
  const cur = hotel!.currency;
  return <Card title="Profit & loss" actions={<><Scope value={scope} onChange={setScope} /><Input type="date" value={from} onChange={e => setFrom(e.target.value)} /><Input type="date" value={to} onChange={e => setTo(e.target.value)} /></>}>
    <Loadable state={st}>{d => <div className="fs">
      <h4>Revenue</h4>{d.revenue.map((r: any) => <div key={r.code} className="fs-row"><span>{r.code} {r.name}</span><b>{money(r.amount, cur)}</b></div>)}
      <div className="fs-row sub"><span>Total revenue</span><b>{money(d.total_revenue, cur)}</b></div>
      <h4>Expenses</h4>{d.expenses.map((r: any) => <div key={r.code} className="fs-row"><span>{r.code} {r.name}</span><b>{money(r.amount, cur)}</b></div>)}
      <div className="fs-row sub"><span>Total expenses</span><b>{money(d.total_expenses, cur)}</b></div>
      <div className="fs-row total"><span>Net profit / (loss)</span><b>{money(d.net_profit, cur)}</b></div>
    </div>}</Loadable></Card>;
}

function BalanceSheet() {
  const { hotel } = useAuth();
  const [asAt, setAsAt] = useState(today());
  const [scope, setScope] = useState(String(hotel!.id));
  const st = useLoad(() => get("/api/reports/balance-sheet", { as_at: asAt, hotel_id: scope }), [asAt, scope]);
  const cur = hotel!.currency;
  const sec = (title: string, rows: any[]) => <><h4>{title}</h4>{rows.map(r => <div key={r.code} className="fs-row"><span>{r.code} {r.name}</span><b>{money(r.amount, cur)}</b></div>)}</>;
  return <Card title="Balance sheet" actions={<><Scope value={scope} onChange={setScope} /><Input type="date" value={asAt} onChange={e => setAsAt(e.target.value)} /></>}>
    <Loadable state={st}>{d => <div className="grid-2">
      <div className="fs">{sec("Assets", d.assets)}<div className="fs-row total"><span>Total assets</span><b>{money(d.total_assets, cur)}</b></div></div>
      <div className="fs">{sec("Liabilities", d.liabilities)}<div className="fs-row sub"><span>Total liabilities</span><b>{money(d.total_liabilities, cur)}</b></div>
        {sec("Equity", d.equity)}<div className="fs-row"><span>Current period earnings</span><b>{money(d.current_earnings, cur)}</b></div>
        <div className="fs-row total"><span>Liabilities + equity</span><b>{money(d.total_liabilities + d.total_equity, cur)}</b></div>
        {d.balanced ? <Pill s="approved" text="Balanced" /> : <Pill s="failed" text="Out of balance" />}</div>
    </div>}</Loadable></Card>;
}

function Journal() {
  const { hotel, can } = useAuth();
  const [from, setFrom] = useState(addDays(today(), -30));
  const [source, setSource] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [manual, setManual] = useState(false);
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/journal`, { from, source }), [hotel?.id, from, source]);
  const cur = hotel!.currency;
  return <Card title="Journal entries" pad={false} actions={<>
    <Select value={source} onChange={e => setSource(e.target.value)}><option value="">All sources</option>{["folio", "payment", "manual", "reversal"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select>
    <Input type="date" value={from} onChange={e => setFrom(e.target.value)} />
    {can("accounting.post_manual") && <Button onClick={() => setManual(true)}>Manual entry</Button>}</>}>
    <Loadable state={st}>{d => <Table rows={d.items} onRow={e => setOpen(open === e.id ? null : e.id)} cols={[
      { h: "Number", r: e => <b>{e.number}</b> }, { h: "Date", r: e => fmtDate(e.entry_date) },
      { h: "Description", r: e => <>{e.description}{e.reversed && <> <Pill s="cancelled" text="Reversed" /></>}
        {open === e.id && <table className="mini"><tbody>{e.lines.map((l: any) => <tr key={l.id}><td>{l.account_code} {l.account_name}</td><td className="num">{l.debit ? money(l.debit, cur) : ""}</td><td className="num">{l.credit ? money(l.credit, cur) : ""}</td></tr>)}</tbody></table>}</> },
      { h: "Source", r: e => label(e.source) }, { h: "Amount", r: e => money(e.total, cur), cls: "num" }, { h: "By", r: e => e.created_by_name || "system" }]} />}</Loadable>
    {manual && <ManualJournal onClose={() => setManual(false)} onDone={() => { setManual(false); st.reload(); }} />}
  </Card>;
}

function ManualJournal({ onClose, onDone }: any) {
  const { hotel } = useAuth();
  const accts = useLoad(() => get("/api/accounts"), []);
  const [desc, setDesc] = useState("");
  const [ref, setRef] = useState("");
  const [date, setDate] = useState(today());
  const [lines, setLines] = useState<any[]>([{ account_id: "", debit: "", credit: "", memo: "" }, { account_id: "", debit: "", credit: "", memo: "" }]);
  const { busy, run } = useAction();
  const dr = lines.reduce((s, l) => s + (toMinor(l.debit) || 0), 0);
  const cr = lines.reduce((s, l) => s + (toMinor(l.credit) || 0), 0);
  const upd = (i: number, k: string, v: string) => setLines(ls => ls.map((l, j) => (j === i ? { ...l, [k]: v } : l)));
  return <Modal title="Manual journal entry" width={760} onClose={onClose} footer={<><span className={dr === cr && dr > 0 ? "pos" : "danger"}>Debits {money(dr, hotel!.currency)} · Credits {money(cr, hotel!.currency)}</span>
    <Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} disabled={dr !== cr || dr === 0 || !desc.trim()} onClick={async () => {
      const body = { description: desc, reference: ref || undefined, entry_date: date, lines: lines.filter(l => l.account_id).map(l => ({ account_id: Number(l.account_id), debit: toMinor(l.debit) || 0, credit: toMinor(l.credit) || 0, memo: l.memo })) };
      if (await run(() => post(`/api/hotels/${hotel!.id}/journal`, body), "Journal entry posted")) onDone();
    }}>Post entry</Button></>}>
    <div className="form-grid"><Field label="Description" wide><Input value={desc} onChange={e => setDesc(e.target.value)} placeholder="e.g. Diesel purchase for generator" /></Field>
      <Field label="Date"><Input type="date" value={date} onChange={e => setDate(e.target.value)} /></Field><Field label="Reference"><Input value={ref} onChange={e => setRef(e.target.value)} /></Field></div>
    <table className="jlines"><thead><tr><th>Account</th><th>Debit (₦)</th><th>Credit (₦)</th><th>Memo</th></tr></thead><tbody>
      {lines.map((l, i) => <tr key={i}><td><Select value={l.account_id} onChange={e => upd(i, "account_id", e.target.value)}><option value="">Select…</option>
        {(accts.data?.items || []).filter((a: any) => a.active).map((a: any) => <option key={a.id} value={a.id}>{a.code} {a.name}</option>)}</Select></td>
        <td><Input value={l.debit} onChange={e => upd(i, "debit", e.target.value)} disabled={!!l.credit} /></td>
        <td><Input value={l.credit} onChange={e => upd(i, "credit", e.target.value)} disabled={!!l.debit} /></td>
        <td><Input value={l.memo} onChange={e => upd(i, "memo", e.target.value)} /></td></tr>)}
    </tbody></table>
    <Button kind="ghost" onClick={() => setLines([...lines, { account_id: "", debit: "", credit: "", memo: "" }])}>+ Add line</Button>
  </Modal>;
}

function Accounts() {
  const { can } = useAuth();
  const st = useLoad(() => get("/api/accounts"), []);
  const [f, setF] = useState({ code: "", name: "", type: "expense" });
  const { busy, run } = useAction();
  return <Card title="Chart of accounts" pad={false} actions={can("accounting.manage_accounts") && <form className="row gap-s" onSubmit={async e => { e.preventDefault(); if (await run(() => post("/api/accounts", f), "Account added")) { setF({ code: "", name: "", type: "expense" }); st.reload(); } }}>
    <Input placeholder="Code" value={f.code} onChange={e => setF({ ...f, code: e.target.value })} style={{ width: 90 }} required />
    <Input placeholder="Account name" value={f.name} onChange={e => setF({ ...f, name: e.target.value })} required />
    <Select value={f.type} onChange={e => setF({ ...f, type: e.target.value })}>{["asset", "liability", "equity", "revenue", "expense"].map(t => <option key={t} value={t}>{label(t)}</option>)}</Select>
    <Button type="submit" busy={busy}>Add</Button></form>}>
    <Loadable state={st}>{d => <Table rows={d.items} cols={[{ h: "Code", r: a => <b>{a.code}</b> }, { h: "Name", r: a => a.name }, { h: "Type", r: a => label(a.type) },
      { h: "System use", r: a => (a.system_key ? <span className="muted small">{a.system_key}</span> : "") }, { h: "Status", r: a => <Pill s={a.active ? "active" : "deactivated"} /> }]} />}</Loadable></Card>;
}
