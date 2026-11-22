import React, { useEffect, useState } from "react";
import { fmtDate, fmtDateTime, get, label, money, patch, post, toMinor, fromMinor, uid } from "../api";
import { useAuth } from "../state";
import { BarList, Button, Card, Field, Input, Kpi, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, useAction, useLoad, useToast } from "../ui";
import { DocumentsPanel } from "./Documents";
import { RejectModal } from "./Inventory";

export default function Procurement({ q }: { q: URLSearchParams }) {
  const [tab, setTab] = useState(q.get("tab") || "overview");
  useEffect(() => { const t = q.get("tab"); if (t) setTab(t); }, [q.get("tab")]);
  return (
    <div className="page">
      <div className="page-h"><div><h1>Procurement</h1><p className="muted">Requisition → quotation → purchase order → goods received → invoice → payment</p></div></div>
      <Tabs tabs={[{ id: "overview", label: "Overview" }, { id: "requisitions", label: "Requisitions & quotes" }, { id: "orders", label: "Purchase orders" },
        { id: "invoices", label: "Supplier invoices" }, { id: "suppliers", label: "Suppliers" }]} value={tab} onChange={setTab} />
      {tab === "overview" && <Overview go={setTab} />}
      {tab === "requisitions" && <Requisitions />}
      {tab === "orders" && <Orders />}
      {tab === "invoices" && <Invoices />}
      {tab === "suppliers" && <Suppliers />}
    </div>
  );
}

function Overview({ go }: any) {
  const { hotel } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/procurement/summary`), [hotel?.id]);
  return <Loadable state={st}>{d => <>
    <div className="kpis">
      <Kpi title="Awaiting approval" value={d.pending_approval.requisitions + d.pending_approval.purchase_orders + d.pending_approval.invoices}
        sub={`${d.pending_approval.requisitions} requisitions · ${d.pending_approval.purchase_orders} POs · ${d.pending_approval.invoices} invoices`} tone="gold" />
      <Kpi title="Open purchase orders" value={(d.po_status.approved || 0) + (d.po_status.partially_received || 0)} sub={`${d.po_status.partially_received || 0} partially received`} />
      <Kpi title="Payables" value={money(d.payables_total, cur)} sub={`${money(d.ageing["1_30"] + d.ageing["31_60"] + d.ageing["61_90"] + d.ageing.over_90, cur)} overdue`} tone="navy" />
    </div>
    <div className="grid-2">
      <Card title="Payables ageing"><BarList items={[["current", "Not yet due"], ["1_30", "1–30 days overdue"], ["31_60", "31–60 days"], ["61_90", "61–90 days"], ["over_90", "Over 90 days"]].map(([k, l]) => ({ label: l, value: d.ageing[k] }))} fmt={v => money(v, cur)} /></Card>
      <Card title={`Spend by supplier (${d.from} to ${d.to})`}>{d.spend_by_supplier.length ? <BarList items={d.spend_by_supplier.map((s: any) => ({ label: `${s.supplier} (${s.deliveries})`, value: s.value }))} fmt={v => money(v, cur)} color="#c8a96a" /> : <p className="muted small">No goods received this period.</p>}</Card>
    </div>
    <div className="row gap-s"><Button kind="secondary" onClick={() => go("orders")}>Purchase orders</Button><Button kind="secondary" onClick={() => go("invoices")}>Invoices</Button></div>
  </>}</Loadable>;
}

// ------------------------------------------------------------------ requisitions & quotes
function Requisitions() {
  const { hotel, can } = useAuth();
  const cur = hotel!.currency;
  const [status, setStatus] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/procurement/requisitions`, { status }), [hotel?.id, status]);
  const [open, setOpen] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  if (open) return <RequisitionDetail id={open} onClose={() => { setOpen(null); st.reload(); }} />;
  return <Card title={<Select value={status} onChange={e => setStatus(e.target.value)} aria-label="Status"><option value="">All requisitions</option>{["submitted", "approved", "ordered", "rejected"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select>}
    actions={can("procurement.requisition") && <Button onClick={() => setCreating(true)}>New requisition</Button>} pad={false}>
    <Loadable state={st}>{d => <Table rows={d.items} onRow={r => setOpen(r.id)} empty="No requisitions" cols={[{ h: "Number", r: r => <b>{r.number}</b> },
      { h: "Department", r: r => label(r.department) }, { h: "Requested by", r: r => r.requested_by_name }, { h: "Needed by", r: r => fmtDate(r.needed_by) },
      { h: "Estimate", r: r => money(r.estimated_total, cur), cls: "num" }, { h: "Quotes", r: r => r.quotes, cls: "num" }, { h: "Status", r: r => <Pill s={r.status} /> }]} />}</Loadable>
    {creating && <NewRequisition onClose={() => setCreating(false)} onDone={(id: number) => { setCreating(false); setOpen(id); }} />}
  </Card>;
}

function useStoresItems() {
  const { hotel } = useAuth();
  const stores = useLoad(() => get(`/api/hotels/${hotel!.id}/stores`).catch(() => ({ items: [] })), [hotel?.id]);
  const items = useLoad(() => get(`/api/hotels/${hotel!.id}/inventory/items`).catch(() => ({ items: [] })), [hotel?.id]);
  return { stores: stores.data?.items || [], items: items.data?.items || [] };
}

function NewRequisition({ onClose, onDone }: any) {
  const { hotel } = useAuth();
  const { stores, items } = useStoresItems();
  const [f, setF] = useState({ department: "kitchen", store_id: "", needed_by: "", justification: "" });
  const [lines, setLines] = useState<any[]>([{ item_id: "", description: "", quantity: "", est_unit_cost: "" }]);
  const { busy, run } = useAction();
  const go = async () => {
    const body = { ...f, store_id: f.store_id ? Number(f.store_id) : undefined, needed_by: f.needed_by || undefined,
      lines: lines.filter(l => (l.item_id || l.description) && l.quantity).map(l => ({ item_id: l.item_id ? Number(l.item_id) : undefined, description: l.description || undefined,
        quantity: l.quantity, est_unit_cost: l.est_unit_cost ? toMinor(l.est_unit_cost) : undefined })) };
    const r = await run(() => post(`/api/hotels/${hotel!.id}/procurement/requisitions`, body), "Requisition submitted for approval");
    if (r) onDone(r.id);
  };
  return <Modal title="New purchase requisition" width={760} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button busy={busy} onClick={go}>Submit</Button></>}>
    <div className="form-grid">
      <Field label="Department"><Select value={f.department} onChange={e => setF({ ...f, department: e.target.value })}>{["kitchen", "bar", "housekeeping", "laundry", "maintenance", "front_office", "admin", "security", "marketing"].map(d => <option key={d} value={d}>{label(d)}</option>)}</Select></Field>
      <Field label="Deliver to store"><Select value={f.store_id} onChange={e => setF({ ...f, store_id: e.target.value })}><option value="">—</option>{stores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
      <Field label="Needed by"><Input type="date" value={f.needed_by} onChange={e => setF({ ...f, needed_by: e.target.value })} /></Field>
      <Field label="Justification" wide><Input value={f.justification} onChange={e => setF({ ...f, justification: e.target.value })} /></Field>
    </div>
    {lines.map((l, i) => <div key={i} className="form-grid tender">
      <Field label="Stock item"><Select value={l.item_id} onChange={e => { const it = items.find((x: any) => x.id === Number(e.target.value)); setLines(lines.map((x, j) => j === i ? { ...x, item_id: e.target.value, est_unit_cost: it ? fromMinor(it.last_cost) : x.est_unit_cost } : x)); }}>
        <option value="">Non-stock (describe)</option>{items.map((x: any) => <option key={x.id} value={x.id}>{x.name} ({x.unit})</option>)}</Select></Field>
      {!l.item_id && <Field label="Description"><Input value={l.description} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, description: e.target.value } : x))} /></Field>}
      <Field label="Quantity"><Input inputMode="decimal" value={l.quantity} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, quantity: e.target.value } : x))} /></Field>
      <Field label="Est. unit cost"><Input inputMode="decimal" value={l.est_unit_cost} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, est_unit_cost: e.target.value } : x))} /></Field>
      {lines.length > 1 && <button className="link danger small self-end" onClick={() => setLines(lines.filter((_, j) => j !== i))}>Remove</button>}
    </div>)}
    <button className="link small" onClick={() => setLines([...lines, { item_id: "", description: "", quantity: "", est_unit_cost: "" }])}>+ Add line</button>
  </Modal>;
}

function RequisitionDetail({ id, onClose }: any) {
  const { hotel, can, user } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/procurement/requisitions/${id}`), [id]);
  const { busy, run } = useAction();
  const [modal, setModal] = useState<string | null>(null);
  const [quoteForPo, setQuoteForPo] = useState<any>(null);
  return <Loadable state={st}>{r => <Card title={<span>{r.number} <Pill s={r.status} /></span>} actions={<Button kind="secondary" onClick={onClose}>Back</Button>}>
    <p className="small muted">{label(r.department)} · {r.justification || "No justification"} · needed by {fmtDate(r.needed_by)} · estimate {money(r.estimated_total, cur)}{r.decision_note ? ` · note: ${r.decision_note}` : ""}</p>
    <h4>Price comparison</h4>
    <div className="table-wrap"><table className="table">
      <thead><tr><th>Line</th><th className="num">Qty</th>{r.quotes.map((q: any) => <th key={q.id} className="num">{q.supplier_name}<div className="tiny muted">{q.reference || ""} {q.delivery_days ? `· ${q.delivery_days}d` : ""}</div></th>)}</tr></thead>
      <tbody>{r.comparison.map((c: any) => <tr key={c.line_id}><td>{c.description}</td><td className="num">{c.quantity}</td>
        {r.quotes.map((q: any) => { const off = c.offers.find((o: any) => o.quote_id === q.id); return <td key={q.id} className={`num ${c.best_quote_id === q.id ? "best" : ""}`}>{off ? money(off.unit_cost, cur) : "—"}</td>; })}</tr>)}
        {r.quotes.length > 0 && <tr><td><b>Total</b></td><td />{r.quotes.map((q: any) => <td key={q.id} className="num"><b>{money(q.total, cur)}</b> <Pill s={q.status} /></td>)}</tr>}</tbody>
    </table></div>
    {!r.quotes.length && <p className="muted small">No quotations recorded yet.</p>}
    {r.purchase_orders.length > 0 && <p className="small">Purchase orders: {r.purchase_orders.map((p: any) => `${p.number} (${label(p.status)})`).join(", ")}</p>}
    <div className="row gap-s wrap mt">
      {r.status === "submitted" && can("procurement.approve") && r.requested_by !== user!.id && <>
        <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/procurement/requisitions/${id}/decide`, { decision: "approve" }), "Requisition approved")) st.reload(); }}>Approve</Button>
        <Button kind="danger" onClick={() => setModal("reject")}>Reject</Button></>}
      {r.status === "approved" && can("procurement.order") && <>
        <Button kind="secondary" onClick={() => setModal("quote")}>Record quotation</Button>
        {r.quotes.map((q: any) => <Button key={q.id} kind="gold" onClick={() => setQuoteForPo(q)}>PO from {q.supplier_name}</Button>)}
        {!r.quotes.length && <Button kind="gold" onClick={() => setQuoteForPo({})}>Raise PO at estimate</Button>}</>}
    </div>
    {modal === "reject" && <RejectModal title={`Reject ${r.number}`} onClose={() => setModal(null)} onReject={async (note: string) => { if (await run(() => post(`/api/procurement/requisitions/${id}/decide`, { decision: "reject", note }), "Rejected")) { setModal(null); st.reload(); } }} />}
    {modal === "quote" && <QuoteModal r={r} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
    {quoteForPo && <PoFromModal r={r} quote={quoteForPo.id ? quoteForPo : null} onClose={() => setQuoteForPo(null)} onDone={() => { setQuoteForPo(null); st.reload(); }} />}
  </Card>}</Loadable>;
}

function useSuppliers() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/procurement/suppliers`), [hotel?.id]);
  return (st.data?.items || []).filter((s: any) => s.active);
}

function QuoteModal({ r, onClose, onDone }: any) {
  const suppliers = useSuppliers();
  const [f, setF] = useState({ supplier_id: "", reference: "", valid_until: "", delivery_days: "" });
  const [costs, setCosts] = useState<Record<number, string>>({});
  const { busy, run } = useAction();
  const go = async () => {
    const body = { supplier_id: Number(f.supplier_id), reference: f.reference || undefined, valid_until: f.valid_until || undefined, delivery_days: f.delivery_days ? Number(f.delivery_days) : undefined,
      lines: Object.entries(costs).filter(([, v]) => v !== "").map(([lid, v]) => ({ requisition_line_id: Number(lid), unit_cost: toMinor(v) })) };
    if (await run(() => post(`/api/procurement/requisitions/${r.id}/quotes`, body), "Quotation recorded")) onDone();
  };
  return <Modal title={`Quotation for ${r.number}`} width={640} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button busy={busy} disabled={!f.supplier_id} onClick={go}>Save quotation</Button></>}>
    <div className="form-grid">
      <Field label="Supplier"><Select value={f.supplier_id} onChange={e => setF({ ...f, supplier_id: e.target.value })}><option value="">Select…</option>{suppliers.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
      <Field label="Quote reference"><Input value={f.reference} onChange={e => setF({ ...f, reference: e.target.value })} /></Field>
      <Field label="Valid until"><Input type="date" value={f.valid_until} onChange={e => setF({ ...f, valid_until: e.target.value })} /></Field>
      <Field label="Delivery (days)"><Input type="number" value={f.delivery_days} onChange={e => setF({ ...f, delivery_days: e.target.value })} /></Field>
    </div>
    {r.lines.map((l: any) => <Field key={l.id} label={`${l.description} — ${l.quantity} ${l.unit || ""} · unit price`}><Input inputMode="decimal" value={costs[l.id] ?? ""} onChange={e => setCosts({ ...costs, [l.id]: e.target.value })} /></Field>)}
  </Modal>;
}

function PoFromModal({ r, quote, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const { stores } = useStoresItems();
  const suppliers = useSuppliers();
  const [f, setF] = useState({ store_id: r.store_id || "", expected_date: "", supplier_id: "", note: "" });
  const { busy, run } = useAction();
  const go = async () => {
    const body: any = { store_id: Number(f.store_id), expected_date: f.expected_date || undefined, note: f.note || undefined };
    if (quote) body.quote_id = quote.id; else { body.requisition_id = r.id; body.supplier_id = Number(f.supplier_id); }
    const res = await run(() => post(`/api/hotels/${hotel!.id}/procurement/purchase-orders`, body), "Purchase order raised");
    if (res) onDone();
  };
  return <Modal title={quote ? `Purchase order from ${quote.supplier_name}` : "Purchase order at estimated prices"} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.store_id || (!quote && !f.supplier_id)} onClick={go}>Raise PO</Button></>}>
    <div className="form-grid">
      {!quote && <Field label="Supplier"><Select value={f.supplier_id} onChange={e => setF({ ...f, supplier_id: e.target.value })}><option value="">Select…</option>{suppliers.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>}
      <Field label="Deliver to store"><Select value={f.store_id} onChange={e => setF({ ...f, store_id: e.target.value })}><option value="">Select…</option>{stores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
      <Field label="Expected delivery"><Input type="date" value={f.expected_date} onChange={e => setF({ ...f, expected_date: e.target.value })} /></Field>
      <Field label="Note" wide><Input value={f.note} onChange={e => setF({ ...f, note: e.target.value })} /></Field>
    </div>
    <p className="muted small">The order goes to an approver. Orders above the high-value threshold need a senior approver.</p>
  </Modal>;
}

// ------------------------------------------------------------------ purchase orders
function Orders() {
  const { hotel, can } = useAuth();
  const cur = hotel!.currency;
  const [status, setStatus] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/procurement/purchase-orders`, { status }), [hotel?.id, status]);
  const [open, setOpen] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  if (open) return <PoDetail id={open} onClose={() => { setOpen(null); st.reload(); }} />;
  return <Card title={<Select value={status} onChange={e => setStatus(e.target.value)} aria-label="Status"><option value="">All purchase orders</option>
    {["pending_approval", "approved", "partially_received", "received", "closed", "cancelled", "rejected"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select>}
    actions={<div className="row gap-s">{st.data && <span className="muted small">High-value threshold {money(st.data.settings.high_value_threshold, cur)}</span>}
      {can("procurement.order") && <Button onClick={() => setCreating(true)}>Direct PO</Button>}</div>} pad={false}>
    <Loadable state={st}>{d => <Table rows={d.items} onRow={p => setOpen(p.id)} empty="No purchase orders" cols={[{ h: "PO", r: p => <b>{p.number}</b> },
      { h: "Supplier", r: p => p.supplier_name }, { h: "Store", r: p => p.store_name }, { h: "Ordered", r: p => fmtDate(p.order_date) }, { h: "Expected", r: p => fmtDate(p.expected_date) },
      { h: "Total", r: p => money(p.total, cur), cls: "num" }, { h: "Approval", r: p => p.approval_level === "high" ? <Pill s="maintenance" text="High value" /> : "Standard" },
      { h: "Status", r: p => <Pill s={p.status} /> }]} />}</Loadable>
    {creating && <DirectPo onClose={() => setCreating(false)} onDone={() => { setCreating(false); st.reload(); }} />}
  </Card>;
}

function DirectPo({ onClose, onDone }: any) {
  const { hotel } = useAuth();
  const { stores, items } = useStoresItems();
  const suppliers = useSuppliers();
  const [f, setF] = useState({ supplier_id: "", store_id: "", expected_date: "", note: "" });
  const [lines, setLines] = useState<any[]>([{ item_id: "", description: "", quantity: "", unit_cost: "", expense_key: "exp_admin" }]);
  const { busy, run } = useAction();
  const total = lines.reduce((s, l) => s + Math.round(Number(l.quantity || 0) * (toMinor(l.unit_cost || "0") || 0)), 0);
  const go = async () => {
    const body = { supplier_id: Number(f.supplier_id), store_id: Number(f.store_id), expected_date: f.expected_date || undefined, note: f.note || undefined,
      lines: lines.filter(l => (l.item_id || l.description) && l.quantity).map(l => ({ item_id: l.item_id ? Number(l.item_id) : undefined, description: l.description || undefined,
        quantity: l.quantity, unit_cost: toMinor(l.unit_cost || "0"), expense_key: l.item_id ? undefined : l.expense_key })) };
    if (await run(() => post(`/api/hotels/${hotel!.id}/procurement/purchase-orders`, body), "Purchase order raised")) onDone();
  };
  return <Modal title="Direct purchase order" width={820} onClose={onClose} footer={<><span className="grow muted small">Total {money(total, hotel!.currency)}</span><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.supplier_id || !f.store_id} onClick={go}>Raise PO</Button></>}>
    <div className="form-grid">
      <Field label="Supplier"><Select value={f.supplier_id} onChange={e => setF({ ...f, supplier_id: e.target.value })}><option value="">Select…</option>{suppliers.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
      <Field label="Deliver to store"><Select value={f.store_id} onChange={e => setF({ ...f, store_id: e.target.value })}><option value="">Select…</option>{stores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
      <Field label="Expected delivery"><Input type="date" value={f.expected_date} onChange={e => setF({ ...f, expected_date: e.target.value })} /></Field>
      <Field label="Note"><Input value={f.note} onChange={e => setF({ ...f, note: e.target.value })} /></Field>
    </div>
    {lines.map((l, i) => <div key={i} className="form-grid tender">
      <Field label="Item"><Select value={l.item_id} onChange={e => { const it = items.find((x: any) => x.id === Number(e.target.value)); setLines(lines.map((x, j) => j === i ? { ...x, item_id: e.target.value, unit_cost: it ? fromMinor(it.last_cost) : x.unit_cost } : x)); }}>
        <option value="">Service / non-stock</option>{items.map((x: any) => <option key={x.id} value={x.id}>{x.name} ({x.unit})</option>)}</Select></Field>
      {!l.item_id && <Field label="Description"><Input value={l.description} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, description: e.target.value } : x))} /></Field>}
      {!l.item_id && <Field label="Expense account"><Select value={l.expense_key} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, expense_key: e.target.value } : x))}>
        {["exp_admin", "exp_maintenance", "exp_utilities", "exp_fuel", "exp_food", "exp_supplies", "exp_marketing", "exp_security"].map(k => <option key={k} value={k}>{label(k.replace("exp_", ""))}</option>)}</Select></Field>}
      <Field label="Qty"><Input inputMode="decimal" value={l.quantity} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, quantity: e.target.value } : x))} /></Field>
      <Field label="Unit cost"><Input inputMode="decimal" value={l.unit_cost} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, unit_cost: e.target.value } : x))} /></Field>
      {lines.length > 1 && <button className="link danger small self-end" onClick={() => setLines(lines.filter((_, j) => j !== i))}>Remove</button>}
    </div>)}
    <button className="link small" onClick={() => setLines([...lines, { item_id: "", description: "", quantity: "", unit_cost: "", expense_key: "exp_admin" }])}>+ Add line</button>
  </Modal>;
}

function PoDetail({ id, onClose }: any) {
  const { hotel, can, user } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/procurement/purchase-orders/${id}`), [id]);
  const { busy, run } = useAction();
  const [modal, setModal] = useState<string | null>(null);
  return <Loadable state={st}>{po => <Card title={<span>{po.number} <Pill s={po.status} /> {po.approval_level === "high" && <Pill s="maintenance" text="High value" />}</span>} actions={<Button kind="secondary" onClick={onClose}>Back</Button>}>
    <p className="small muted">{po.supplier.name} · deliver to {po.store.name} · ordered {fmtDate(po.order_date)} · expected {fmtDate(po.expected_date)} · raised by {po.created_by_name}{po.approved_by_name ? ` · decided by ${po.approved_by_name}` : ""}{po.decision_note ? ` · ${po.decision_note}` : ""}</p>
    <Table rows={po.lines} cols={[{ h: "Line", r: l => <>{l.description}{!l.item_id && <div className="tiny muted">Service · {label((l.expense_key || "").replace("exp_", ""))}</div>}</> },
      { h: "Ordered", r: l => `${l.quantity} ${l.unit || ""}`, cls: "num" }, { h: "Received", r: l => l.received, cls: "num" }, { h: "Outstanding", r: l => l.outstanding, cls: "num" },
      { h: "Unit cost", r: l => money(l.unit_cost, cur), cls: "num" }, { h: "Total", r: l => money(l.line_total, cur), cls: "num" }]} />
    <div className="totals"><div className="grand"><span>Order total</span><b>{money(po.total, cur)}</b></div><div><span>Received value</span><b>{money(po.received_value, cur)}</b></div></div>
    {po.receipts.length > 0 && <><h4>Goods received</h4><Table rows={po.receipts} cols={[{ h: "GRN", r: g => g.number }, { h: "Date", r: g => g.business_date }, { h: "Delivery note", r: g => g.delivery_note || "—" },
      { h: "Received by", r: g => g.received_by_name }, { h: "Value", r: g => money(g.value, cur), cls: "num" }]} /></>}
    {po.invoices.length > 0 && <><h4>Invoices</h4><Table rows={po.invoices} cols={[{ h: "Invoice", r: i => `${i.number} (${i.invoice_no})` }, { h: "Amount", r: i => money(i.amount, cur), cls: "num" },
      { h: "Match", r: i => <Pill s={i.match_status} /> }, { h: "Status", r: i => <Pill s={i.status} /> }]} /></>}
    <div className="row gap-s wrap mt">
      {po.status === "pending_approval" && can("procurement.approve") && po.created_by !== user!.id && (po.approval_level !== "high" || can("procurement.approve_high")) && <>
        <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/procurement/purchase-orders/${id}/decide`, { decision: "approve" }), "Purchase order approved")) st.reload(); }}>Approve</Button>
        <Button kind="danger" onClick={() => setModal("reject")}>Reject</Button></>}
      {po.status === "pending_approval" && po.approval_level === "high" && can("procurement.approve") && !can("procurement.approve_high") && <span className="note small">Above the high-value threshold — needs a senior approver.</span>}
      {["approved", "partially_received"].includes(po.status) && can("procurement.receive") && <Button kind="gold" onClick={() => setModal("receive")}>Receive goods</Button>}
      {!["received", "closed", "cancelled", "rejected"].includes(po.status) && can("procurement.order") && <Button kind="ghost" onClick={() => setModal("cancel")}>{po.status === "partially_received" ? "Close short" : "Cancel PO"}</Button>}
    </div>
    {modal === "reject" && <RejectModal title={`Reject ${po.number}`} onClose={() => setModal(null)} onReject={async (note: string) => { if (await run(() => post(`/api/procurement/purchase-orders/${id}/decide`, { decision: "reject", note }), "Rejected")) { setModal(null); st.reload(); } }} />}
    {modal === "cancel" && <RejectModal title={po.status === "partially_received" ? `Close ${po.number} short` : `Cancel ${po.number}`} onClose={() => setModal(null)} onReject={async (reason: string) => { if (await run(() => post(`/api/procurement/purchase-orders/${id}/cancel`, { reason }), "Done")) { setModal(null); st.reload(); } }} />}
    {modal === "receive" && <ReceiveModal po={po} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
  </Card>}</Loadable>;
}

function ReceiveModal({ po, onClose, onDone }: any) {
  const lines = po.lines.filter((l: any) => l.outstanding > 0);
  const [vals, setVals] = useState<Record<number, any>>(Object.fromEntries(lines.map((l: any) => [l.id, { quantity: String(l.outstanding), rejected: "", batch_no: "", expiry_date: "" }])));
  const [dn, setDn] = useState("");
  const { busy, run } = useAction();
  const set = (id: number, k: string, v: string) => setVals({ ...vals, [id]: { ...vals[id], [k]: v } });
  const go = async () => {
    const body = { delivery_note: dn || undefined, lines: lines.map((l: any) => ({ po_line_id: l.id, quantity: vals[l.id].quantity || 0, rejected: vals[l.id].rejected || 0,
      batch_no: vals[l.id].batch_no || undefined, expiry_date: vals[l.id].expiry_date || undefined })) };
    if (await run(() => post(`/api/procurement/purchase-orders/${po.id}/receive`, body), "Goods received into stock")) onDone();
  };
  return <Modal title={`Receive goods — ${po.number}`} width={860} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button kind="gold" busy={busy} onClick={go}>Post GRN</Button></>}>
    <Field label="Supplier delivery note no."><Input value={dn} onChange={e => setDn(e.target.value)} /></Field>
    {lines.map((l: any) => <div key={l.id} className="form-grid tender">
      <Field label={`${l.description} (outstanding ${l.outstanding} ${l.unit || ""})`}><Input inputMode="decimal" value={vals[l.id].quantity} onChange={e => set(l.id, "quantity", e.target.value)} /></Field>
      <Field label="Rejected"><Input inputMode="decimal" value={vals[l.id].rejected} onChange={e => set(l.id, "rejected", e.target.value)} /></Field>
      {l.track_expiry ? <><Field label="Batch"><Input value={vals[l.id].batch_no} onChange={e => set(l.id, "batch_no", e.target.value)} /></Field>
        <Field label="Expiry date (required)"><Input type="date" value={vals[l.id].expiry_date} onChange={e => set(l.id, "expiry_date", e.target.value)} /></Field></> : null}
    </div>)}
  </Modal>;
}

// ------------------------------------------------------------------ invoices
function Invoices() {
  const { hotel, can, user } = useAuth();
  const cur = hotel!.currency;
  const [status, setStatus] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/procurement/invoices`, { status }), [hotel?.id, status]);
  const [modal, setModal] = useState<any>(null);
  const { busy, run } = useAction();
  return <Card title={<Select value={status} onChange={e => setStatus(e.target.value)} aria-label="Status"><option value="">All invoices</option>{["pending_approval", "approved", "part_paid", "paid", "rejected"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select>}
    actions={can("procurement.invoice") && <Button onClick={() => setModal({ kind: "new" })}>Record invoice</Button>} pad={false}>
    <Loadable state={st}>{d => <Table rows={d.items} empty="No supplier invoices" cols={[{ h: "Invoice", r: i => <><b>{i.number}</b><div className="tiny muted">Supplier ref {i.invoice_no}</div></> },
      { h: "Supplier", r: i => i.supplier_name }, { h: "PO", r: i => i.po_number || "—" }, { h: "Due", r: i => fmtDate(i.due_date) },
      { h: "Amount", r: i => money(i.amount, cur), cls: "num" }, { h: "Outstanding", r: i => money(i.outstanding, cur), cls: "num" },
      { h: "Match", r: i => <span title={i.match_status === "variance" ? `Received ${money(i.received_value, cur)}, variance ${money(i.variance, cur)}` : ""}><Pill s={i.match_status} text={i.match_status === "variance" ? `Variance ${money(i.variance, cur)}` : undefined} /></span> },
      { h: "Status", r: i => <Pill s={i.status} /> },
      { h: "", r: i => <span className="row gap-s">
        {i.status === "pending_approval" && can("procurement.invoice_approve") && i.created_by !== user!.id && <>
          <Button busy={busy} onClick={() => setModal({ kind: "approve", inv: i })}>Approve</Button>
          <Button kind="ghost" onClick={() => setModal({ kind: "reject", inv: i })}>Reject</Button></>}
        {["approved", "part_paid"].includes(i.status) && can("procurement.pay") && <Button kind="gold" onClick={() => setModal({ kind: "pay", inv: i })}>Pay</Button>}</span> }]} />}</Loadable>
    {modal?.kind === "new" && <InvoiceModal onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
    {modal?.kind === "approve" && <ApproveInvoice inv={modal.inv} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
    {modal?.kind === "reject" && <RejectModal title={`Reject ${modal.inv.number}`} onClose={() => setModal(null)} onReject={async (note: string) => { if (await run(() => post(`/api/procurement/invoices/${modal.inv.id}/decide`, { decision: "reject", note }), "Invoice rejected")) { setModal(null); st.reload(); } }} />}
    {modal?.kind === "pay" && <PayModal inv={modal.inv} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
  </Card>;
}

function InvoiceModal({ onClose, onDone }: any) {
  const { hotel } = useAuth();
  const suppliers = useSuppliers();
  const [f, setF] = useState({ supplier_id: "", po_id: "", invoice_no: "", invoice_date: new Date().toISOString().slice(0, 10), due_date: "", amount: "", expense_key: "exp_utilities", note: "" });
  const toast = useToast();
  const pos = useLoad(() => (f.supplier_id ? get(`/api/hotels/${hotel!.id}/procurement/purchase-orders`, { supplier_id: f.supplier_id, status: "partially_received,received,closed" }) : Promise.resolve({ items: [] })), [f.supplier_id]);
  const { busy, run } = useAction();
  const go = async () => {
    const body: any = { supplier_id: Number(f.supplier_id), invoice_no: f.invoice_no, invoice_date: f.invoice_date, due_date: f.due_date || undefined, amount: toMinor(f.amount), note: f.note || undefined };
    if (f.po_id) body.po_id = Number(f.po_id); else body.expense_key = f.expense_key;
    const r = await run(() => post(`/api/hotels/${hotel!.id}/procurement/invoices`, body));
    if (r) { toast(r.match_status === "variance" ? "error" : "success", r.match_status === "matched" ? "Invoice matches the goods received." : r.match_status === "variance" ? `Invoice differs from goods received by ${money(r.variance, hotel!.currency)} — the approver must explain the variance.` : "Invoice recorded without a purchase order — awaiting approval."); onDone(); }
  };
  return <Modal title="Record supplier invoice" width={640} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.supplier_id || !f.invoice_no || isNaN(toMinor(f.amount))} onClick={go}>Record</Button></>}>
    <div className="form-grid">
      <Field label="Supplier"><Select value={f.supplier_id} onChange={e => setF({ ...f, supplier_id: e.target.value, po_id: "" })}><option value="">Select…</option>{suppliers.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
      <Field label="Purchase order" hint="Matched against goods received"><Select value={f.po_id} onChange={e => setF({ ...f, po_id: e.target.value })}><option value="">No PO (expense)</option>{(pos.data?.items || []).map((p: any) => <option key={p.id} value={p.id}>{p.number} · {money(p.total, hotel!.currency)}</option>)}</Select></Field>
      {!f.po_id && <Field label="Expense account"><Select value={f.expense_key} onChange={e => setF({ ...f, expense_key: e.target.value })}>{["exp_utilities", "exp_fuel", "exp_maintenance", "exp_admin", "exp_marketing", "exp_security", "exp_food", "exp_supplies"].map(k => <option key={k} value={k}>{label(k.replace("exp_", ""))}</option>)}</Select></Field>}
      <Field label="Supplier's invoice no."><Input value={f.invoice_no} onChange={e => setF({ ...f, invoice_no: e.target.value })} /></Field>
      <Field label="Invoice date"><Input type="date" value={f.invoice_date} onChange={e => setF({ ...f, invoice_date: e.target.value })} /></Field>
      <Field label="Due date" hint="Blank uses the supplier's terms"><Input type="date" value={f.due_date} onChange={e => setF({ ...f, due_date: e.target.value })} /></Field>
      <Field label={`Amount (${hotel!.currency})`}><Input inputMode="decimal" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} /></Field>
      <Field label="Note" wide><Input value={f.note} onChange={e => setF({ ...f, note: e.target.value })} /></Field>
    </div></Modal>;
}

function ApproveInvoice({ inv, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const cur = hotel!.currency;
  const [note, setNote] = useState("");
  const { busy, run } = useAction();
  return <Modal title={`Approve ${inv.number}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={inv.match_status === "variance" && !note.trim()} onClick={async () => { if (await run(() => post(`/api/procurement/invoices/${inv.id}/decide`, { decision: "approve", note: note || undefined }), "Invoice approved and posted to payables")) onDone(); }}>Approve</Button></>}>
    <dl className="dl"><dt>Supplier</dt><dd>{inv.supplier_name}</dd><dt>Invoice amount</dt><dd>{money(inv.amount, cur)}</dd>
      {inv.po_number && <><dt>Goods received (uninvoiced)</dt><dd>{money(inv.received_value, cur)}</dd><dt>Variance</dt><dd className={inv.variance ? "danger" : ""}>{money(inv.variance, cur)}</dd></>}</dl>
    <Field label={inv.match_status === "variance" ? "Explain why the variance is acceptable (required)" : "Note (optional)"}><Textarea value={note} onChange={e => setNote(e.target.value)} /></Field>
  </Modal>;
}

function PayModal({ inv, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const cur = hotel!.currency;
  const methods = useLoad(() => get(`/api/hotels/${hotel!.id}/payment-methods`), [hotel?.id]);
  const opts = (methods.data?.items || []).filter((m: any) => m.active && ["cash", "bank_transfer"].includes(m.kind));
  const [f, setF] = useState({ method_id: "", amount: fromMinor(inv.outstanding), reference: "" });
  const [key] = useState(uid());
  const { busy, run } = useAction();
  const gross = toMinor(f.amount) || 0;
  const wht = Math.round(gross * (inv.wht_bp || 0) / 10000);
  return <Modal title={`Pay ${inv.supplier_name} — ${inv.number}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button kind="gold" busy={busy} disabled={!f.method_id || !gross} onClick={async () => { if (await run(() => post(`/api/procurement/invoices/${inv.id}/payments`, { method_id: Number(f.method_id), amount: gross, reference: f.reference || undefined, idempotency_key: key }), "Payment recorded")) onDone(); }}>Record payment</Button></>}>
    <div className="form-grid">
      <Field label="Pay from"><Select value={f.method_id} onChange={e => setF({ ...f, method_id: e.target.value })}><option value="">Select…</option>{opts.map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></Field>
      <Field label={`Amount applied (${cur})`} hint={`Outstanding ${money(inv.outstanding, cur)}`}><Input inputMode="decimal" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} /></Field>
      <Field label="Transfer reference"><Input value={f.reference} onChange={e => setF({ ...f, reference: e.target.value })} /></Field>
    </div>
    <dl className="dl"><dt>Withholding tax ({(inv.wht_bp || 0) / 100}%)</dt><dd>{money(wht, cur)}</dd><dt><b>Net paid to supplier</b></dt><dd><b>{money(gross - wht, cur)}</b></dd></dl>
  </Modal>;
}

// ------------------------------------------------------------------ suppliers
function Suppliers() {
  const { hotel, can } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/procurement/suppliers`), [hotel?.id]);
  const [edit, setEdit] = useState<any>(null);
  return <Card title="Suppliers" actions={can("procurement.suppliers") && <Button onClick={() => setEdit({})}>New supplier</Button>} pad={false}>
    <Loadable state={st}>{d => <Table rows={d.items} empty="No suppliers" cols={[{ h: "Supplier", r: s => <><b>{s.name}</b><div className="tiny muted">{s.code} · {s.category || "—"}</div></> },
      { h: "Contact", r: s => <>{s.contact_name || "—"}<div className="tiny muted">{[s.phone, s.email].filter(Boolean).join(" · ")}</div></> },
      { h: "Terms", r: s => `${s.payment_terms_days} days` }, { h: "WHT", r: s => `${s.wht_bp / 100}%` },
      { h: "Deliveries", r: s => s.performance.deliveries, cls: "num" }, { h: "On time", r: s => s.performance.on_time_pct != null ? `${s.performance.on_time_pct}%` : "—", cls: "num" },
      { h: "Rejected", r: s => s.performance.rejected_pct != null ? `${s.performance.rejected_pct}%` : "—", cls: "num" },
      { h: "Balance owed", r: s => money(s.balance, cur), cls: "num" }, { h: "Status", r: s => <Pill s={s.active ? "active" : "deactivated"} /> },
      { h: "", r: s => can("procurement.suppliers") && <button className="link small" onClick={() => setEdit(s)}>Edit</button> }]} />}</Loadable>
    {edit && <SupplierModal s={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); st.reload(); }} />}
  </Card>;
}

function SupplierModal({ s, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState<any>({ name: s.name || "", category: s.category || "", contact_name: s.contact_name || "", phone: s.phone || "", email: s.email || "", address: s.address || "",
    tax_id: s.tax_id || "", bank_name: s.bank_name || "", bank_account_name: s.bank_account_name || "", bank_account_number: s.bank_account_number || "",
    payment_terms_days: s.payment_terms_days ?? 30, wht_pct: (s.wht_bp ?? 0) / 100, active: s.active ?? 1 });
  const { busy, run } = useAction();
  const go = async () => {
    const body: any = { ...f, wht_bp: Math.round(Number(f.wht_pct) * 100), payment_terms_days: Number(f.payment_terms_days), active: !!f.active };
    delete body.wht_pct;
    if (s.id && String(body.bank_account_number).startsWith("•")) delete body.bank_account_number;
    if (await run(() => s.id ? patch(`/api/procurement/suppliers/${s.id}`, body) : post(`/api/hotels/${hotel!.id}/procurement/suppliers`, body), "Supplier saved")) onDone();
  };
  const fld = (k: string, l: string, wide = false) => <Field label={l} wide={wide}><Input value={f[k]} onChange={e => setF({ ...f, [k]: e.target.value })} /></Field>;
  return <Modal title={s.id ? `Edit ${s.name}` : "New supplier"} width={720} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button busy={busy} disabled={!f.name.trim()} onClick={go}>Save</Button></>}>
    <div className="form-grid">
      {fld("name", "Name", true)}{fld("category", "Category")}{fld("contact_name", "Contact person")}{fld("phone", "Phone")}{fld("email", "Email")}{fld("address", "Address", true)}
      {fld("tax_id", "Tax ID (TIN)")}{fld("bank_name", "Bank")}{fld("bank_account_name", "Account name")}{fld("bank_account_number", "Account number")}
      <Field label="Payment terms (days)"><Input type="number" value={f.payment_terms_days} onChange={e => setF({ ...f, payment_terms_days: e.target.value })} /></Field>
      <Field label="Withholding tax %" hint="Deducted from payments; confirm the applicable rate"><Input inputMode="decimal" value={f.wht_pct} onChange={e => setF({ ...f, wht_pct: e.target.value })} /></Field>
      {s.id && <label className="check"><input type="checkbox" checked={!!f.active} onChange={e => setF({ ...f, active: e.target.checked ? 1 : 0 })} /> Active</label>}
    </div>
    {s.id && <div className="mt"><DocumentsPanel entityType="supplier" entityId={s.id} defaultCategory="contract" title="Contracts & documents" /></div>}</Modal>;
}
