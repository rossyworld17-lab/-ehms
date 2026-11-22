import React, { useEffect, useState } from "react";
import { fmtDate, fmtDateTime, get, label, money, patch, post, put, toMinor, fromMinor } from "../api";
import { useAuth } from "../state";
import { Button, Card, Empty, Field, Input, Kpi, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, useAction, useLoad } from "../ui";

export default function Inventory({ q }: { q: URLSearchParams }) {
  const { hotel, can } = useAuth();
  const [tab, setTab] = useState(q.get("tab") || "stock");
  useEffect(() => { const t = q.get("tab"); if (t) setTab(t); }, [q.get("tab")]);
  const stores = useLoad(() => get(`/api/hotels/${hotel!.id}/stores`), [hotel?.id]);
  const items = useLoad(() => get(`/api/hotels/${hotel!.id}/inventory/items`), [hotel?.id]);
  const alerts = useLoad(() => get(`/api/hotels/${hotel!.id}/inventory/alerts`), [hotel?.id]);
  const [modal, setModal] = useState<string | null>(null);
  const reload = () => { stores.reload(); items.reload(); alerts.reload(); };
  const cur = hotel!.currency;
  return (
    <div className="page">
      <div className="page-h"><div><h1>Inventory & stores</h1><p className="muted">Perpetual stock at weighted average cost · every movement is journalled</p></div>
        <div className="row gap-s wrap">
          {can("inventory.requisition") && <Button onClick={() => setModal("requisition")}>Request stock</Button>}
          {can("inventory.issue") && <Button kind="secondary" onClick={() => setModal("transfer")}>Transfer</Button>}
          {can("inventory.adjust") && <Button kind="secondary" onClick={() => setModal("adjust")}>Adjust / write off</Button>}
        </div></div>
      <div className="kpis">
        <Kpi title="Stock value" value={money((stores.data?.items || []).reduce((s: number, x: any) => s + x.stock_value, 0), cur)} sub={`${stores.data?.items.length || 0} stores`} tone="navy" />
        <Kpi title="Low stock items" value={alerts.data?.low_stock.length ?? "…"} sub="At or below reorder level" tone={alerts.data?.low_stock.length ? "gold" : undefined} />
        <Kpi title="Expiring within 30 days" value={alerts.data?.expiring.length ?? "…"} sub={`${(alerts.data?.expiring || []).filter((e: any) => e.expired).length} already expired`} />
        <Kpi title="Catalogue" value={items.data?.items.length ?? "…"} sub="Active items" />
      </div>
      <Tabs tabs={[{ id: "stock", label: "Stock by store" }, { id: "items", label: "Item catalogue" }, { id: "requisitions", label: "Requisitions" },
        { id: "movements", label: "Movements" }, { id: "counts", label: "Stock counts" }, { id: "alerts", label: "Alerts" }, ...(can("inventory.manage") ? [{ id: "stores", label: "Stores" }] : [])]} value={tab} onChange={setTab} />
      {tab === "stock" && <StockTab stores={stores.data?.items || []} />}
      {tab === "items" && <ItemsTab state={items} />}
      {tab === "requisitions" && <RequisitionsTab />}
      {tab === "movements" && <MovementsTab items={items.data?.items || []} stores={stores.data?.items || []} />}
      {tab === "counts" && <CountsTab stores={stores.data?.items || []} onPosted={reload} />}
      {tab === "alerts" && <Loadable state={alerts}>{a => <AlertsTab a={a} />}</Loadable>}
      {tab === "stores" && <StoresTab state={stores} />}
      {modal === "requisition" && <RequisitionModal stores={stores.data?.items || []} items={items.data?.items || []} onClose={() => setModal(null)} onDone={() => { setModal(null); setTab("requisitions"); }} />}
      {modal === "transfer" && <TransferModal stores={stores.data?.items || []} items={items.data?.items || []} onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
      {modal === "adjust" && <AdjustModal stores={stores.data?.items || []} items={items.data?.items || []} onClose={() => setModal(null)} onDone={() => { setModal(null); reload(); }} />}
    </div>
  );
}

function StockTab({ stores }: any) {
  const { hotel } = useAuth();
  const [store, setStore] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/inventory/stock`, { store_id: store }), [hotel?.id, store]);
  const cur = hotel!.currency;
  return <Card title={<Select value={store} onChange={e => setStore(e.target.value)} aria-label="Store"><option value="">All stores</option>{stores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>}
    actions={st.data && <b>{money(st.data.total_value, cur)}</b>} pad={false}>
    <Loadable state={st}>{d => <Table rows={d.items.filter((r: any) => r.quantity !== 0)} empty="No stock" onRow={r => location.hash = `#/inventory/items/${r.item_id}`} cols={[
      { h: "Store", r: r => r.store_name }, { h: "Item", r: r => <><b>{r.name}</b><div className="tiny muted">{r.code} · {label(r.category)}</div></> },
      { h: "On hand", r: r => `${r.quantity} ${r.unit}`, cls: "num" },
      { h: "Avg cost", r: r => money(r.quantity > 0 ? Math.round(r.value / r.quantity) : 0, cur), cls: "num" }, { h: "Value", r: r => money(r.value, cur), cls: "num" }]} />}</Loadable>
  </Card>;
}

function ItemsTab({ state }: any) {
  const { can, hotel } = useAuth();
  const [edit, setEdit] = useState<any>(null);
  const [filter, setFilter] = useState("");
  const cur = hotel!.currency;
  return <Loadable state={state}>{(d: any) => <Card title={<Input placeholder="Search items…" value={filter} onChange={e => setFilter(e.target.value)} />}
    actions={can("inventory.manage") && <Button onClick={() => setEdit({})}>New item</Button>} pad={false}>
    <Table rows={d.items.filter((i: any) => !filter || `${i.name} ${i.code} ${i.barcode || ""}`.toLowerCase().includes(filter.toLowerCase()))} onRow={i => location.hash = `#/inventory/items/${i.id}`} cols={[
      { h: "Code", r: i => i.code }, { h: "Item", r: i => <b>{i.name}</b> }, { h: "Category", r: i => label(i.category) }, { h: "Unit", r: i => i.unit },
      { h: "On hand", r: i => <span className={i.low_stock ? "danger" : ""}>{i.on_hand}</span>, cls: "num" }, { h: "Reorder at", r: i => i.reorder_level || "—", cls: "num" },
      { h: "Avg cost", r: i => money(i.avg_cost, cur), cls: "num" }, { h: "Value", r: i => money(i.stock_value, cur), cls: "num" },
      { h: "", r: i => <>{i.low_stock && <Pill s="rejected" text="Low" />} {i.track_expiry ? <Pill s="pending" text="Expiry" /> : null}
        {can("inventory.manage") && <button className="link small" onClick={e => { e.stopPropagation(); setEdit(i); }}>Edit</button>}</> }]} />
    {edit && <ItemModal item={edit} categories={d.categories} onClose={() => setEdit(null)} onDone={() => { setEdit(null); state.reload(); }} />}
  </Card>}</Loadable>;
}

function ItemModal({ item, categories, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ code: item.code || "", name: item.name || "", category: item.category || "food", unit: item.unit || "", barcode: item.barcode || "",
    last_cost: item.last_cost != null ? fromMinor(item.last_cost) : "", reorder_level: item.reorder_level ?? "", reorder_qty: item.reorder_qty ?? "",
    track_expiry: !!item.track_expiry, active: item.active ?? 1 });
  const { busy, run } = useAction();
  const go = async () => {
    const body: any = { ...f, last_cost: f.last_cost === "" ? undefined : toMinor(f.last_cost), reorder_level: f.reorder_level === "" ? 0 : f.reorder_level,
      reorder_qty: f.reorder_qty === "" ? 0 : f.reorder_qty, active: !!f.active, code: f.code || undefined };
    if (item.id) delete body.code;
    if (await run(() => item.id ? patch(`/api/inventory/items/${item.id}`, body) : post(`/api/hotels/${hotel!.id}/inventory/items`, body), "Item saved")) onDone();
  };
  return <Modal title={item.id ? `Edit ${item.name}` : "New inventory item"} width={640} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.name || !f.unit} onClick={go}>Save</Button></>}>
    <div className="form-grid">
      {!item.id && <Field label="Code" hint="Leave blank to generate"><Input value={f.code} onChange={e => setF({ ...f, code: e.target.value })} /></Field>}
      <Field label="Name" wide><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Category"><Select value={f.category} onChange={e => setF({ ...f, category: e.target.value })}>{categories.map((c: string) => <option key={c} value={c}>{label(c)}</option>)}</Select></Field>
      <Field label="Stock unit" hint="kg, litre, piece, bottle…"><Input value={f.unit} onChange={e => setF({ ...f, unit: e.target.value })} /></Field>
      <Field label="Barcode"><Input value={f.barcode} onChange={e => setF({ ...f, barcode: e.target.value })} /></Field>
      <Field label={`Standard cost per unit (${hotel!.currency})`}><Input inputMode="decimal" value={f.last_cost} onChange={e => setF({ ...f, last_cost: e.target.value })} /></Field>
      <Field label="Reorder level"><Input inputMode="decimal" value={f.reorder_level} onChange={e => setF({ ...f, reorder_level: e.target.value })} /></Field>
      <Field label="Reorder quantity"><Input inputMode="decimal" value={f.reorder_qty} onChange={e => setF({ ...f, reorder_qty: e.target.value })} /></Field>
      <label className="check"><input type="checkbox" checked={f.track_expiry} onChange={e => setF({ ...f, track_expiry: e.target.checked })} /> Track batches & expiry dates</label>
      {item.id && <label className="check"><input type="checkbox" checked={!!f.active} onChange={e => setF({ ...f, active: e.target.checked ? 1 : 0 })} /> Active</label>}
    </div></Modal>;
}

export function ItemDetail({ id }: { id: number }) {
  const { hotel } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/inventory/items/${id}`), [id]);
  return <div className="page"><Loadable state={st}>{d => <>
    <div className="page-h"><div><h1>{d.item.name}</h1><p className="muted">{d.item.code} · {label(d.item.category)} · unit: {d.item.unit}{d.item.barcode ? ` · barcode ${d.item.barcode}` : ""}</p></div>
      <a className="btn btn-secondary" href="#/inventory?tab=items">Back</a></div>
    <div className="grid-2">
      <Card title="Balances by store" pad={false}><Table rows={d.levels} cols={[{ h: "Store", r: l => l.store_name }, { h: "On hand", r: l => `${l.quantity} ${d.item.unit}`, cls: "num" },
        { h: "Value", r: l => money(l.value, cur), cls: "num" }]} /></Card>
      <Card title="Batches" pad={false}><Table rows={d.batches} empty="No batch stock" cols={[{ h: "Store", r: b => b.store_name }, { h: "Batch", r: b => b.batch_no || "—" },
        { h: "Expiry", r: b => fmtDate(b.expiry_date) }, { h: "Qty", r: b => b.quantity, cls: "num" }]} /></Card>
    </div>
    <Card title="Movement history (last 100)" pad={false}><Table rows={d.movements} cols={[{ h: "Date", r: m => m.business_date }, { h: "Type", r: m => label(m.movement_type) },
      { h: "Store", r: m => m.store_name }, { h: "Ref", r: m => m.source_ref || "—" }, { h: "Qty", r: m => <span className={m.quantity < 0 ? "danger" : "pos"}>{m.quantity > 0 ? "+" : ""}{m.quantity}</span>, cls: "num" },
      { h: "Value", r: m => money(m.value, cur), cls: "num" }, { h: "Balance", r: m => m.balance, cls: "num" }, { h: "By", r: m => m.user_name || "—" }, { h: "Reason", r: m => m.reason || "" }]} /></Card>
  </>}</Loadable></div>;
}

function RequisitionsTab() {
  const { hotel, can, user } = useAuth();
  const [status, setStatus] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/inventory/requisitions`, { status }), [hotel?.id, status]);
  const { busy, run } = useAction();
  const [reject, setReject] = useState<any>(null);
  const act = async (fn: () => Promise<any>, msg: string) => { if (await run(fn, msg)) st.reload(); };
  return <div className="stack">
    <div><Select value={status} onChange={e => setStatus(e.target.value)} aria-label="Status"><option value="">All</option>{["pending", "approved", "issued", "rejected"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select></div>
    <Loadable state={st}>{d => d.items.length ? d.items.map((r: any) => <Card key={r.id} title={<span>{r.number} <Pill s={r.status} /></span>}
      actions={<span className="small muted">{r.from_store} → {r.to_store || label(r.department)}</span>}>
      <p className="small muted">Requested by {r.requested_by_name} · {fmtDateTime(r.created_at)}{r.approved_by_name ? ` · decided by ${r.approved_by_name}` : ""}{r.note ? ` · ${r.note}` : ""}</p>
      <Table rows={r.lines} cols={[{ h: "Item", r: l => l.name }, { h: "Requested", r: l => `${l.requested} ${l.unit}`, cls: "num" },
        { h: "Available in store", r: l => <span className={l.available < l.requested ? "danger" : ""}>{l.available}</span>, cls: "num" }, { h: "Issued", r: l => l.issued || "—", cls: "num" }]} />
      <div className="row gap-s mt">
        {r.status === "pending" && can("inventory.approve") && r.requested_by !== user!.id && <>
          <Button busy={busy} onClick={() => act(() => post(`/api/inventory/requisitions/${r.id}/decide`, { decision: "approve" }), "Approved")}>Approve</Button>
          <Button kind="danger" onClick={() => setReject(r)}>Reject</Button></>}
        {r.status === "approved" && can("inventory.issue") && <Button kind="gold" busy={busy} onClick={() => act(() => post(`/api/inventory/requisitions/${r.id}/issue`, {}), "Stock issued")}>Issue stock</Button>}
      </div>
    </Card>) : <Empty text="No requisitions" />}</Loadable>
    {reject && <RejectModal title={`Reject ${reject.number}`} onClose={() => setReject(null)} onReject={async (note: string) => { if (await run(() => post(`/api/inventory/requisitions/${reject.id}/decide`, { decision: "reject", note }), "Rejected")) { setReject(null); st.reload(); } }} />}
  </div>;
}

export function RejectModal({ title, onClose, onReject }: any) {
  const [note, setNote] = useState("");
  return <Modal title={title} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button kind="danger" disabled={!note.trim()} onClick={() => onReject(note)}>Reject</Button></>}>
    <Field label="Reason (required)"><Textarea value={note} onChange={e => setNote(e.target.value)} /></Field></Modal>;
}

function LinesEditor({ items, lines, setLines, unitCost }: any) {
  return <>{lines.map((l: any, i: number) => { const it = items.find((x: any) => x.id === Number(l.item_id)); return <div key={i} className="form-grid tender">
    <Field label="Item"><Select value={l.item_id} onChange={e => setLines(lines.map((x: any, j: number) => j === i ? { ...x, item_id: e.target.value } : x))}>
      <option value="">Select…</option>{items.map((x: any) => <option key={x.id} value={x.id}>{x.name} ({x.on_hand} {x.unit})</option>)}</Select></Field>
    <Field label={`Quantity${it ? ` (${it.unit})` : ""}`}><Input inputMode="decimal" value={l.quantity} onChange={e => setLines(lines.map((x: any, j: number) => j === i ? { ...x, quantity: e.target.value } : x))} /></Field>
    {unitCost && <Field label="Unit cost"><Input inputMode="decimal" value={l.unit_cost || ""} onChange={e => setLines(lines.map((x: any, j: number) => j === i ? { ...x, unit_cost: e.target.value } : x))} /></Field>}
    {lines.length > 1 && <button className="link danger small self-end" onClick={() => setLines(lines.filter((_: any, j: number) => j !== i))}>Remove</button>}</div>; })}
    <button className="link small" onClick={() => setLines([...lines, { item_id: "", quantity: "" }])}>+ Add line</button></>;
}

function RequisitionModal({ stores, items, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const depts = ["kitchen", "bar", "housekeeping", "laundry", "maintenance", "front_office", "security", "admin", "other"];
  const [f, setF] = useState({ from_store_id: stores[0]?.id || "", target: "department", to_store_id: "", department: "housekeeping", note: "" });
  const [lines, setLines] = useState<any[]>([{ item_id: "", quantity: "" }]);
  const { busy, run } = useAction();
  const go = async () => {
    const body = { from_store_id: Number(f.from_store_id), note: f.note || undefined, lines: lines.filter(l => l.item_id && l.quantity),
      ...(f.target === "store" ? { to_store_id: Number(f.to_store_id) } : { department: f.department }) };
    if (await run(() => post(`/api/hotels/${hotel!.id}/inventory/requisitions`, body), "Requisition submitted")) onDone();
  };
  return <Modal title="Request stock" width={680} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button busy={busy} onClick={go}>Submit</Button></>}>
    <div className="form-grid">
      <Field label="From store"><Select value={f.from_store_id} onChange={e => setF({ ...f, from_store_id: e.target.value })}>{stores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
      <Field label="For"><Select value={f.target} onChange={e => setF({ ...f, target: e.target.value })}><option value="department">Consumption by a department</option><option value="store">Another store (transfer)</option></Select></Field>
      {f.target === "store" ? <Field label="To store"><Select value={f.to_store_id} onChange={e => setF({ ...f, to_store_id: e.target.value })}><option value="">Select…</option>{stores.filter((s: any) => String(s.id) !== String(f.from_store_id)).map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
        : <Field label="Department"><Select value={f.department} onChange={e => setF({ ...f, department: e.target.value })}>{depts.map(d => <option key={d} value={d}>{label(d)}</option>)}</Select></Field>}
      <Field label="Note" wide><Input value={f.note} onChange={e => setF({ ...f, note: e.target.value })} /></Field>
    </div>
    <LinesEditor items={items} lines={lines} setLines={setLines} />
  </Modal>;
}

function TransferModal({ stores, items, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ from_store_id: stores[0]?.id || "", to_store_id: stores[1]?.id || "" });
  const [lines, setLines] = useState<any[]>([{ item_id: "", quantity: "" }]);
  const { busy, run } = useAction();
  return <Modal title="Transfer stock between stores" width={680} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/inventory/transfers`, { from_store_id: Number(f.from_store_id), to_store_id: Number(f.to_store_id), lines: lines.filter(l => l.item_id && l.quantity) }), "Stock transferred")) onDone(); }}>Transfer</Button></>}>
    <div className="form-grid">
      <Field label="From"><Select value={f.from_store_id} onChange={e => setF({ ...f, from_store_id: e.target.value })}>{stores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
      <Field label="To"><Select value={f.to_store_id} onChange={e => setF({ ...f, to_store_id: e.target.value })}>{stores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
    </div>
    <LinesEditor items={items} lines={lines} setLines={setLines} />
  </Modal>;
}

function AdjustModal({ stores, items, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ kind: "wastage", direction: "out", item_id: "", store_id: stores[0]?.id || "", quantity: "", unit_cost: "", reason: "", batch_no: "", expiry_date: "" });
  const { busy, run } = useAction();
  const incoming = f.kind === "opening" || (f.kind === "adjustment" && f.direction === "in");
  const it = items.find((x: any) => x.id === Number(f.item_id));
  const go = async () => {
    const body: any = { kind: f.kind, direction: f.direction, item_id: Number(f.item_id), store_id: Number(f.store_id), quantity: f.quantity, reason: f.reason };
    if (incoming) { if (f.unit_cost) body.unit_cost = toMinor(f.unit_cost); if (f.batch_no) body.batch_no = f.batch_no; if (f.expiry_date) body.expiry_date = f.expiry_date; }
    if (await run(() => post(`/api/hotels/${hotel!.id}/inventory/adjustments`, body), "Stock adjusted")) onDone();
  };
  return <Modal title="Stock adjustment" width={640} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.item_id || !f.quantity || !f.reason.trim()} onClick={go}>Post</Button></>}>
    <div className="form-grid">
      <Field label="Type"><Select value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}><option value="wastage">Wastage / damaged / expired</option>
        <option value="adjustment">Adjustment</option><option value="opening">Opening balance</option></Select></Field>
      {f.kind === "adjustment" && <Field label="Direction"><Select value={f.direction} onChange={e => setF({ ...f, direction: e.target.value })}><option value="out">Decrease</option><option value="in">Increase</option></Select></Field>}
      <Field label="Store"><Select value={f.store_id} onChange={e => setF({ ...f, store_id: e.target.value })}>{stores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
      <Field label="Item"><Select value={f.item_id} onChange={e => setF({ ...f, item_id: e.target.value })}><option value="">Select…</option>{items.map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select></Field>
      <Field label={`Quantity${it ? ` (${it.unit})` : ""}`}><Input inputMode="decimal" value={f.quantity} onChange={e => setF({ ...f, quantity: e.target.value })} /></Field>
      {incoming && <Field label="Unit cost" hint="Blank uses the standard cost"><Input inputMode="decimal" value={f.unit_cost} onChange={e => setF({ ...f, unit_cost: e.target.value })} /></Field>}
      {incoming && it?.track_expiry ? <><Field label="Batch"><Input value={f.batch_no} onChange={e => setF({ ...f, batch_no: e.target.value })} /></Field>
        <Field label="Expiry date"><Input type="date" value={f.expiry_date} onChange={e => setF({ ...f, expiry_date: e.target.value })} /></Field></> : null}
      <Field label="Reason (required)" wide><Input value={f.reason} onChange={e => setF({ ...f, reason: e.target.value })} /></Field>
    </div>
    <p className="muted small">Write-offs and adjustments post to Inventory Shrinkage & Wastage; opening balances post to Owner's Equity.</p>
  </Modal>;
}

function MovementsTab({ items, stores }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ item_id: "", store_id: "", type: "" });
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/inventory/movements`, f), [hotel?.id, f.item_id, f.store_id, f.type]);
  const cur = hotel!.currency;
  return <Card title={<div className="row gap-s wrap">
    <Select value={f.store_id} onChange={e => setF({ ...f, store_id: e.target.value })}><option value="">All stores</option>{stores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>
    <Select value={f.item_id} onChange={e => setF({ ...f, item_id: e.target.value })}><option value="">All items</option>{items.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>
    <Select value={f.type} onChange={e => setF({ ...f, type: e.target.value })}><option value="">All types</option>{["receipt", "issue", "consumption", "transfer_in", "transfer_out", "adjustment", "wastage", "count", "opening"].map(t => <option key={t} value={t}>{label(t)}</option>)}</Select>
  </div>} pad={false}><Loadable state={st}>{d => <Table rows={d.items} empty="No movements" cols={[
    { h: "Date", r: m => m.business_date }, { h: "Type", r: m => label(m.movement_type) }, { h: "Item", r: m => m.name }, { h: "Store", r: m => m.store_name },
    { h: "Qty", r: m => <span className={m.quantity < 0 ? "danger" : "pos"}>{m.quantity > 0 ? "+" : ""}{m.quantity} {m.unit}</span>, cls: "num" },
    { h: "Value", r: m => money(m.value, cur), cls: "num" }, { h: "Ref", r: m => m.source_ref || "—" }, { h: "By", r: m => m.user_name || "—" }, { h: "Reason", r: m => m.reason || m.department || "" }]} />}</Loadable></Card>;
}

function CountsTab({ stores, onPosted }: any) {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/inventory/counts`), [hotel?.id]);
  const [open, setOpen] = useState<number | null>(null);
  const [store, setStore] = useState("");
  const { busy, run } = useAction();
  if (open) return <CountSheet id={open} onClose={() => { setOpen(null); st.reload(); onPosted(); }} />;
  return <Card title="Stock counts" actions={can("inventory.adjust") && <div className="row gap-s"><Select value={store} onChange={e => setStore(e.target.value)} aria-label="Store"><option value="">Store…</option>{stores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>
    <Button busy={busy} disabled={!store} onClick={async () => { const r = await run(() => post(`/api/hotels/${hotel!.id}/inventory/counts`, { store_id: Number(store) }), "Count sheet created"); if (r) setOpen(r.id); }}>Start count</Button></div>} pad={false}>
    <Loadable state={st}>{d => <Table rows={d.items} onRow={k => setOpen(k.id)} empty="No counts yet" cols={[{ h: "Count", r: k => k.number }, { h: "Store", r: k => k.store_name },
      { h: "Lines", r: k => k.lines, cls: "num" }, { h: "Status", r: k => <Pill s={k.status} /> }, { h: "By", r: k => k.created_by_name }, { h: "Date", r: k => fmtDateTime(k.created_at) }]} />}</Loadable></Card>;
}

function CountSheet({ id, onClose }: any) {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/inventory/counts/${id}`), [id]);
  const [vals, setVals] = useState<Record<number, string>>({});
  const { busy, run } = useAction();
  const draft = st.data?.count.status === "draft";
  const lines = () => Object.entries(vals).map(([item_id, counted]) => ({ item_id: Number(item_id), counted }));
  return <Loadable state={st}>{d => <Card title={<span>{d.count.number} — {d.count.store_name} <Pill s={d.count.status} /></span>} actions={<Button kind="secondary" onClick={onClose}>Back</Button>} pad={false}>
    <Table rows={d.lines} cols={[{ h: "Item", r: l => <><b>{l.name}</b><div className="tiny muted">{l.code}</div></> }, { h: "System qty", r: l => `${draft ? l.current : l.system} ${l.unit}`, cls: "num" },
      { h: "Counted", r: l => draft && can("inventory.adjust") ? <Input className="sm" inputMode="decimal" value={vals[l.item_id] ?? (l.counted ?? "")} onChange={e => setVals({ ...vals, [l.item_id]: e.target.value })} /> : (l.counted ?? "—") },
      { h: "Variance", r: l => { const c = vals[l.item_id] ?? l.counted; if (c === undefined || c === null || c === "") return "—"; const v = Number(c) - (draft ? l.current : l.system); return <span className={v < 0 ? "danger" : v > 0 ? "pos" : ""}>{v > 0 ? "+" : ""}{Math.round(v * 1000) / 1000}</span>; }, cls: "num" }]} />
    {draft && can("inventory.adjust") && <div className="row gap-s pad">
      <Button kind="secondary" busy={busy} onClick={async () => { if (await run(() => put(`/api/inventory/counts/${id}/lines`, { lines: lines() }), "Counts saved")) st.reload(); }}>Save counts</Button>
      <Button kind="gold" busy={busy} onClick={async () => { await put(`/api/inventory/counts/${id}/lines`, { lines: lines() }).catch(() => {}); const r = await run(() => post(`/api/inventory/counts/${id}/post`, {}), "Count posted — balances adjusted"); if (r) st.reload(); }}>Post count</Button>
      <span className="muted small">Posting adjusts each balance to the counted quantity and journals the variance.</span></div>}
  </Card>}</Loadable>;
}

function AlertsTab({ a }: any) {
  return <div className="grid-2">
    <Card title="Low stock" pad={false}><Table rows={a.low_stock} empty="Nothing below reorder level" cols={[{ h: "Item", r: i => i.name }, { h: "On hand", r: i => `${i.on_hand} ${i.unit}`, cls: "num" },
      { h: "Reorder level", r: i => i.reorder_level, cls: "num" }, { h: "Suggested order", r: i => i.reorder_qty, cls: "num" }]} /></Card>
    <Card title="Expiring within 30 days" pad={false}><Table rows={a.expiring} empty="Nothing expiring" cols={[{ h: "Item", r: e => e.name }, { h: "Store", r: e => e.store_name },
      { h: "Batch", r: e => e.batch_no || "—" }, { h: "Expiry", r: e => <span className={e.expired ? "danger" : ""}>{fmtDate(e.expiry_date)}{e.expired ? " (expired)" : ""}</span> }, { h: "Qty", r: e => e.quantity, cls: "num" }]} /></Card>
  </div>;
}

function StoresTab({ state }: any) {
  const { hotel } = useAuth();
  const [edit, setEdit] = useState<any>(null);
  const cur = hotel!.currency;
  return <Loadable state={state}>{(d: any) => <Card title="Stores" actions={<Button onClick={() => setEdit({})}>New store</Button>} pad={false}>
    <Table rows={d.items} cols={[{ h: "Code", r: s => s.code }, { h: "Name", r: s => s.name }, { h: "Kind", r: s => label(s.kind) },
      { h: "Items in stock", r: s => s.items_in_stock, cls: "num" }, { h: "Value", r: s => money(s.stock_value, cur), cls: "num" },
      { h: "Negative stock", r: s => s.allow_negative ? "Allowed" : "Blocked" }, { h: "Status", r: s => <Pill s={s.active ? "active" : "deactivated"} /> },
      { h: "", r: s => <button className="link small" onClick={() => setEdit(s)}>Edit</button> }]} />
    {edit && <StoreModal store={edit} kinds={d.kinds} onClose={() => setEdit(null)} onDone={() => { setEdit(null); state.reload(); }} />}
  </Card>}</Loadable>;
}

function StoreModal({ store, kinds, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ code: store.code || "", name: store.name || "", kind: store.kind || "main", allow_negative: !!store.allow_negative, active: store.active ?? 1 });
  const { busy, run } = useAction();
  return <Modal title={store.id ? `Edit ${store.name}` : "New store"} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.name || !f.code} onClick={async () => { if (await run(() => store.id ? patch(`/api/stores/${store.id}`, { ...f, active: !!f.active }) : post(`/api/hotels/${hotel!.id}/stores`, f), "Store saved")) onDone(); }}>Save</Button></>}>
    <div className="form-grid">
      {!store.id && <Field label="Code"><Input value={f.code} onChange={e => setF({ ...f, code: e.target.value })} /></Field>}
      <Field label="Name"><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Kind"><Select value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}>{kinds.map((k: string) => <option key={k} value={k}>{label(k)}</option>)}</Select></Field>
      <label className="check"><input type="checkbox" checked={f.allow_negative} onChange={e => setF({ ...f, allow_negative: e.target.checked })} /> Allow negative stock (sales are not blocked when stock runs out)</label>
      {store.id && <label className="check"><input type="checkbox" checked={!!f.active} onChange={e => setF({ ...f, active: e.target.checked ? 1 : 0 })} /> Active</label>}
    </div></Modal>;
}
