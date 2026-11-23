import React, { useEffect, useMemo, useState } from "react";
import { api, fmtDateTime, get, label, money, openFile, patch, post, put, toMinor, fromMinor } from "../api";
import { useAuth } from "../state";
import { Button, Card, Confirm, Empty, Field, Input, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, useAction, useLoad, useToast, errText } from "../ui";
import { TableBookings } from "./Completion";

// ======================================================================== POS terminal
export default function Pos() {
  const { hotel, can, user } = useAuth();
  const cur = hotel!.currency;
  const outlets = useLoad(() => get(`/api/hotels/${hotel!.id}/pos/outlets`), [hotel?.id]);
  const [outletId, setOutletId] = useState<number | null>(() => { try { return Number(localStorage.getItem("ehms.outlet")) || null; } catch { return null; } });
  const outlet = useMemo(() => outlets.data?.items.find((o: any) => o.id === outletId) || outlets.data?.items.find((o: any) => o.active && o.kind === "restaurant" && o.tables.length)
    || outlets.data?.items.find((o: any) => o.active && o.tables.length) || outlets.data?.items.find((o: any) => o.active), [outlets.data, outletId]);
  useEffect(() => { if (outlet) try { localStorage.setItem("ehms.outlet", String(outlet.id)); } catch { /* ignore */ } }, [outlet?.id]);
  const orders = useLoad(() => (outlet ? get(`/api/hotels/${hotel!.id}/pos/orders`, { outlet_id: outlet.id, status: "open" }) : Promise.resolve({ items: [] })), [outlet?.id]);
  const shift = useLoad(() => (outlet && can("pos.shift") ? get(`/api/hotels/${hotel!.id}/pos/shifts`, { mine: 1, status: "open", outlet_id: outlet.id }) : Promise.resolve({ items: [] })), [outlet?.id]);
  const menu = useLoad(() => (outlet ? get(`/api/hotels/${hotel!.id}/pos/menu`, { outlet_id: outlet.id }) : Promise.resolve(null)), [outlet?.id]);
  const [orderId, setOrderId] = useState<number | null>(null);
  const [newOrder, setNewOrder] = useState<null | { type: string; table?: any }>(null);
  const [shiftModal, setShiftModal] = useState<"open" | "close" | null>(null);
  const myShift = shift.data?.items?.[0];
  const reloadAll = () => { orders.reload(); outlets.reload(); shift.reload(); };
  const [view, setView] = useState<"terminal" | "bookings">("terminal");

  return (
    <div className="page">
      <div className="page-h"><div><h1>Point of sale</h1><p className="muted">Restaurant, bar and in-room dining</p></div>
        <div className="row gap-s wrap">
          <Loadable state={outlets}>{d => <Select value={outlet?.id || ""} onChange={e => { setOutletId(Number(e.target.value)); setOrderId(null); }} aria-label="Outlet">
            {d.items.filter((o: any) => o.active).map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}</Select>}</Loadable>
          {can("pos.shift") && (myShift
            ? <button className="chip" onClick={() => setShiftModal("close")} title="Close shift">Shift {myShift.number} · cash {money(myShift.expected_cash_now, cur)} — Close</button>
            : <Button kind="gold" onClick={() => setShiftModal("open")} disabled={!outlet}>Open shift</Button>)}
          <Button kind="secondary" onClick={reloadAll}>Refresh</Button>
        </div></div>
      <Tabs tabs={[{ id: "terminal", label: "Orders & tables" }, { id: "bookings", label: "Table bookings" }]} value={view} onChange={v => setView(v as any)} />
      {view === "bookings" && outlets.data && <TableBookings outlets={outlets.data.items.filter((o: any) => o.active)} />}
      {view === "terminal" && !outlets.loading && !outlet && <Empty text="No outlets are configured yet.">{can("pos.manage") && <a href="#/pos/setup">Set up outlets and menus</a>}</Empty>}
      {view === "terminal" && outlet && <div className="pos-grid">
        <div className="stack">
          <Card title="Tables" actions={<div className="row gap-s">
            {can("pos.order") && <Button kind="secondary" onClick={() => setNewOrder({ type: "takeaway" })}>Takeaway</Button>}
            {can("pos.order") && <Button kind="secondary" onClick={() => setNewOrder({ type: "room_service" })}>Room service</Button>}</div>}>
            {outlet.tables.length ? <div className="tablegrid">
              {outlet.tables.filter((t: any) => t.active).map((t: any) => {
                const open = (orders.data?.items || []).filter((o: any) => o.table_id === t.id);
                return <button key={t.id} className={`tbl ${open.length ? "busy" : ""} ${open.some((o: any) => o.id === orderId) ? "on" : ""}`}
                  onClick={() => open.length ? setOrderId(open[0].id) : can("pos.order") && setNewOrder({ type: "dine_in", table: t })}>
                  <b>{t.code}</b><span>{open.length ? money(open.reduce((s: number, o: any) => s + o.subtotal, 0), cur) : `${t.seats} seats`}</span>
                  {open.some((o: any) => o.ready_items > 0) && <i className="dot-ready" title="Items ready to serve" />}
                </button>;
              })}</div> : <p className="muted small">This outlet has no tables (takeaway / room service only).</p>}
          </Card>
          <Card title={`Open orders (${orders.data?.items.length || 0})`} pad={false}>
            <Table rows={orders.data?.items || []} onRow={o => setOrderId(o.id)} empty="No open orders"
              cols={[{ h: "Order", r: o => <><b>{o.number.split("-").pop()}</b> {o.ready_items > 0 && <Pill s="ready" text={`${o.ready_items} ready`} />}</> },
                { h: "Where", r: o => o.table_code ? `Table ${o.table_code}` : o.room_number ? `Room ${o.room_number}` : label(o.order_type) },
                { h: "Guest", r: o => o.guest_name || "—" }, { h: "Amount", r: o => money(o.subtotal, cur), cls: "num" }]} />
          </Card>
        </div>
        <div>{orderId ? <OrderPanel key={orderId} id={orderId} menu={menu.data} outlet={outlet} openOrders={orders.data?.items || []} shift={myShift}
          onChange={reloadAll} onClose={() => setOrderId(null)} onOpen={(id: number) => setOrderId(id)} />
          : <Card><Empty text="Select a table or order, or start a new one." /></Card>}</div>
      </div>}
      {newOrder && outlet && <NewOrderModal outlet={outlet} type={newOrder.type} table={newOrder.table} onClose={() => setNewOrder(null)}
        onDone={(id: number) => { setNewOrder(null); setOrderId(id); orders.reload(); }} />}
      {shiftModal === "open" && outlet && <OpenShift outlet={outlet} onClose={() => setShiftModal(null)} onDone={() => { setShiftModal(null); shift.reload(); }} />}
      {shiftModal === "close" && myShift && <CloseShift shift={myShift} onClose={() => setShiftModal(null)} onDone={() => { setShiftModal(null); shift.reload(); }} />}
    </div>
  );
}

function NewOrderModal({ outlet, type, table, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [covers, setCovers] = useState(2);
  const [guest, setGuest] = useState("");
  const [q, setQ] = useState("");
  const [resId, setResId] = useState<number | null>(null);
  const inHouse = useLoad(() => (type === "room_service" ? get(`/api/hotels/${hotel!.id}/pos/in-house`, { q }) : Promise.resolve({ items: [] })), [q, type]);
  const { busy, run } = useAction();
  const go = async () => {
    const r = await run(() => post(`/api/hotels/${hotel!.id}/pos/orders`, { outlet_id: outlet.id, order_type: type, table_id: table?.id, covers,
      guest_name: guest || undefined, reservation_id: resId || undefined }), "Order opened");
    if (r) onDone(r.id);
  };
  return <Modal title={type === "dine_in" ? `New order — table ${table.code}` : type === "room_service" ? "New room-service order" : "New takeaway order"} onClose={onClose}
    footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button busy={busy} disabled={type === "room_service" && !resId} onClick={go}>Open order</Button></>}>
    <div className="form-grid">
      {type === "dine_in" && <Field label="Covers"><Input type="number" min={1} value={covers} onChange={e => setCovers(Number(e.target.value))} /></Field>}
      {type !== "room_service" && <Field label="Guest name (optional)"><Input value={guest} onChange={e => setGuest(e.target.value)} /></Field>}
      {type === "room_service" && <Field label="Find in-house guest" wide hint="Room number or guest name"><Input value={q} onChange={e => setQ(e.target.value)} placeholder="e.g. 204 or Okafor" /></Field>}
    </div>
    {type === "room_service" && <div className="picklist">{(inHouse.data?.items || []).map((g: any) =>
      <button key={g.reservation_id} className={resId === g.reservation_id ? "on" : ""} onClick={() => setResId(g.reservation_id)}>
        <b>Room {g.room_number}</b> {g.guest} <span className="muted small">· departs {g.departure}</span></button>)}
      {!inHouse.loading && !inHouse.data?.items.length && <p className="muted small">No checked-in guests match.</p>}</div>}
  </Modal>;
}

function OrderPanel({ id, menu, outlet, openOrders, shift, onChange, onClose, onOpen }: any) {
  const { hotel, can } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/pos/orders/${id}`), [id]);
  const { busy, run } = useAction();
  const [cat, setCat] = useState<number | null>(null);
  const [modal, setModal] = useState<string | null>(null);
  const [voidItem, setVoidItem] = useState<any>(null);
  const o = st.data;
  const setO = (d: any) => { st.setData(d); onChange(); };
  const act = async (fn: () => Promise<any>, msg?: string) => { const r = await run(fn, msg); if (r) setO(r.original || r); return r; };
  const cats = (menu?.categories || []).filter((c: any) => c.active);
  const curCat = cat ?? cats[0]?.id;
  const items = (menu?.items || []).filter((m: any) => m.category_id === curCat);
  if (!o) return <Card><Loadable state={st}>{() => null}</Loadable></Card>;
  const open = o.status === "open";
  const unsent = o.items.filter((i: any) => i.kitchen_status === "new").length;
  return (
    <Card title={<span>{o.number} <Pill s={o.status} /></span>} actions={<button className="x" onClick={onClose} aria-label="Close order">×</button>}>
      <div className="row between wrap small muted mb">
        <span>{o.table ? `Table ${o.table.code}` : label(o.order_type)}{o.reservation ? ` · Room ${o.reservation.room_number} — ${o.reservation.guest}` : o.guest_name ? ` · ${o.guest_name}` : ""} · {o.covers} cover(s)</span>
        <span>Opened by {o.waiter || "—"}</span>
      </div>
      {open && can("pos.order") && <>
        <Tabs tabs={cats.map((c: any) => ({ id: String(c.id), label: c.name }))} value={String(curCat)} onChange={v => setCat(Number(v))} />
        <div className="menugrid">
          {items.map((m: any) => <button key={m.id} className="menubtn" disabled={!m.available || busy}
            onClick={() => act(() => post(`/api/pos/orders/${id}/items`, { menu_item_id: m.id, quantity: 1 }))}>
            <b>{m.name}</b><span>{m.available ? money(m.price, cur) : "Sold out"}</span></button>)}
          {!items.length && <p className="muted small">No items in this category.</p>}
        </div>
      </>}
      <div className="orderlines">
        {o.items.map((i: any) => <div key={i.id} className={`oline ${i.kitchen_status === "void" ? "void" : ""}`}>
          <div className="grow"><b>{i.quantity} × {i.name}</b>{i.notes && <div className="tiny muted">{i.notes}</div>}
            {i.kitchen_status === "void" && <div className="tiny danger">Void: {i.void_reason}</div>}</div>
          <Pill s={i.kitchen_status} />
          <span className="num">{money(i.quantity * i.unit_price, cur)}</span>
          {open && i.kitchen_status === "new" && can("pos.order") && <span className="row gap-s">
            <button className="icon-btn sm" onClick={() => i.quantity > 1 ? act(() => patch(`/api/pos/order-items/${i.id}`, { quantity: i.quantity - 1 })) : act(() => api("DELETE", `/api/pos/order-items/${i.id}`))} aria-label="Less">−</button>
            <button className="icon-btn sm" onClick={() => act(() => patch(`/api/pos/order-items/${i.id}`, { quantity: i.quantity + 1 }))} aria-label="More">+</button></span>}
          {open && i.kitchen_status === "ready" && can("pos.order") && <Button kind="secondary" busy={busy} onClick={async () => { if (await run(() => post(`/api/kitchen/items/${i.id}/status`, { status: "served" }), "Served")) st.reload(); }}>Served</Button>}
          {open && !["new", "void"].includes(i.kitchen_status) && can("pos.void") && <button className="link danger small" onClick={() => setVoidItem(i)}>Void</button>}
        </div>)}
        {!o.items.length && <p className="muted small">No items yet — tap the menu above.</p>}
      </div>
      <div className="totals">
        <div><span>Subtotal</span><b>{money(o.totals.subtotal, cur)}</b></div>
        {o.totals.discount > 0 && <div><span>Discount {o.discount_reason ? `(${o.discount_reason})` : ""}</span><b>−{money(o.totals.discount, cur)}</b></div>}
        {o.totals.service_charge > 0 && <div><span>Service charge</span><b>{money(o.totals.service_charge, cur)}</b></div>}
        <div><span>Tax</span><b>{money(o.totals.tax, cur)}</b></div>
        <div className="grand"><span>Total</span><b>{money(o.totals.total, cur)}</b></div>
        {o.payments.map((p: any) => <div key={p.id} className="small"><span>{p.method_name || `Charged to room (${p.folio_number})`}</span><b>{money(p.amount, cur)}</b></div>)}
      </div>
      <div className="row gap-s wrap mt">
        {open && can("pos.order") && <Button disabled={!unsent} busy={busy} onClick={() => act(() => post(`/api/pos/orders/${id}/send`), "Sent to kitchen")}>Send to kitchen{unsent ? ` (${unsent})` : ""}</Button>}
        {open && can("pos.settle") && <Button kind="gold" disabled={!o.items.length || unsent > 0} onClick={() => setModal("settle")} title={unsent ? "Send all items first" : ""}>Settle</Button>}
        <Button kind="secondary" onClick={() => openFile(`/api/pos/orders/${id}/receipt.pdf`, `${o.number}.pdf`, true).catch(() => {})}>{open ? "Print bill" : "Receipt"}</Button>
        {open && can("pos.discount") && <Button kind="ghost" onClick={() => setModal("discount")}>Discount</Button>}
        {open && can("pos.order") && <Button kind="ghost" onClick={() => setModal("split")}>Split bill</Button>}
        {open && can("pos.order") && openOrders.length > 1 && <Button kind="ghost" onClick={() => setModal("merge")}>Merge</Button>}
        {open && can("pos.order") && outlet.tables.length > 0 && <Button kind="ghost" onClick={() => setModal("move")}>Move table</Button>}
        {open && can("pos.void") && <Button kind="danger" onClick={() => setModal("void")}>Void order</Button>}
      </div>
      {modal === "settle" && <SettleModal o={o} shift={shift} onClose={() => setModal(null)} onDone={(r: any) => { setModal(null); setO(r); }} />}
      {modal === "discount" && <DiscountModal o={o} onClose={() => setModal(null)} onDone={(r: any) => { setModal(null); setO(r); }} />}
      {modal === "split" && <SplitModal o={o} onClose={() => setModal(null)} onDone={(r: any) => { setModal(null); setO(r.original); onOpen(r.new_order.id); }} />}
      {modal === "merge" && <PickModal title="Merge another order into this one" options={openOrders.filter((x: any) => x.id !== id).map((x: any) => ({ id: x.id, label: `${x.number} · ${x.table_code ? "Table " + x.table_code : label(x.order_type)} · ${money(x.subtotal, cur)}` }))}
        onClose={() => setModal(null)} onPick={(src: number) => act(() => post(`/api/pos/orders/${id}/merge`, { source_order_id: src }), "Orders merged").then(r => r && setModal(null))} />}
      {modal === "move" && <PickModal title="Move to table" options={outlet.tables.filter((t: any) => t.active && t.id !== o.table_id).map((t: any) => ({ id: t.id, label: `${t.code} · ${t.area || ""}${t.open_orders ? " (has an open order)" : ""}` }))}
        onClose={() => setModal(null)} onPick={(tid: number) => act(() => post(`/api/pos/orders/${id}/move-table`, { table_id: tid }), "Order moved").then(r => r && setModal(null))} />}
      {modal === "void" && <Confirm title={`Void ${o.number}?`} text="All items are voided and the order is closed without payment. This is recorded in the audit trail." danger needReason="Reason" confirmText="Void order"
        onClose={() => setModal(null)} onConfirm={async (reason: string) => { if (await run(() => post(`/api/pos/orders/${id}/void`, { reason }), "Order voided")) { setModal(null); onChange(); onClose(); } }} />}
      {voidItem && <Confirm title={`Void ${voidItem.quantity} × ${voidItem.name}?`} text="The kitchen has already received this item. Voids are reported on the shift and audit trail." danger needReason="Reason" confirmText="Void item"
        onClose={() => setVoidItem(null)} onConfirm={async (reason: string) => { const r = await act(() => post(`/api/pos/order-items/${voidItem.id}/void`, { reason }), "Item voided"); if (r) setVoidItem(null); }} />}
    </Card>
  );
}

function SettleModal({ o, shift, onClose, onDone }: any) {
  const { hotel, can } = useAuth();
  const cur = hotel!.currency;
  const methods = useLoad(() => get(`/api/hotels/${hotel!.id}/payment-methods`).catch(() => ({ items: [] })), [hotel?.id]);
  const posMethods = (methods.data?.items || []).filter((m: any) => m.active && ["cash", "card_pos", "bank_transfer"].includes(m.kind));
  const [rows, setRows] = useState<any[]>([{ kind: o.reservation_id && can("pos.post_to_room") ? "room" : "", amount: fromMinor(o.totals.total), reference: "" }]);
  const [resId, setResId] = useState<number | null>(o.reservation_id || null);
  const [q, setQ] = useState("");
  const toast = useToast();
  const needsRoom = rows.some(r => r.kind === "room");
  const inHouse = useLoad(() => (needsRoom && !o.reservation_id ? get(`/api/hotels/${hotel!.id}/pos/in-house`, { q }) : Promise.resolve({ items: [] })), [needsRoom, q]);
  const { busy, run } = useAction();
  useEffect(() => {
    const dflt = posMethods.find((m: any) => m.kind === "cash") || posMethods[0];
    if (!rows[0].kind && dflt) setRows(r => [{ ...r[0], kind: String(dflt.id) }, ...r.slice(1)]);
  }, [posMethods.length]);
  const paid = rows.reduce((s, r) => s + (toMinor(r.amount) || 0), 0);
  const due = o.totals.total;
  const kindOf = (r: any) => r.kind === "room" ? "room" : posMethods.find((m: any) => String(m.id) === r.kind)?.kind;
  const go = async () => {
    const tenders = rows.map(r => r.kind === "room" ? { tender: "room", reservation_id: resId, amount: toMinor(r.amount) }
      : { tender: "method", method_id: Number(r.kind), amount: toMinor(r.amount), reference: r.reference || undefined });
    const res = await run(() => post(`/api/pos/orders/${o.id}/settle`, { tenders }));
    if (res) toast("success", res.change > 0 ? `Order settled — give change of ${money(res.change, cur)}` : "Order settled");
    if (res) onDone(res);
  };
  return <Modal title={`Settle ${o.number} — ${money(due, cur)}`} width={640} onClose={onClose}
    footer={<><span className="muted small grow">{paid >= due ? (paid > due ? `Change: ${money(paid - due, cur)}` : "Exact amount") : `Remaining: ${money(due - paid, cur)}`}</span>
      <Button kind="secondary" onClick={onClose}>Cancel</Button><Button kind="gold" busy={busy} disabled={paid < due || (needsRoom && !resId)} onClick={go}>Confirm payment</Button></>}>
    {!shift && rows.some(r => r.kind && r.kind !== "room") && <p className="note">You need an open cashier shift at this outlet to take cash, card or transfer payments.</p>}
    {rows.map((r, i) => <div key={i} className="form-grid tender">
      <Field label="Tender"><Select value={r.kind} onChange={e => setRows(rows.map((x, j) => j === i ? { ...x, kind: e.target.value } : x))}>
        <option value="">Select…</option>{posMethods.map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}
        {can("pos.post_to_room") && <option value="room">Charge to room</option>}</Select></Field>
      <Field label={`Amount (${cur})`}><Input inputMode="decimal" value={r.amount} onChange={e => setRows(rows.map((x, j) => j === i ? { ...x, amount: e.target.value } : x))} /></Field>
      {["card_pos", "bank_transfer"].includes(kindOf(r)) && <Field label="Slip / transfer reference"><Input value={r.reference} onChange={e => setRows(rows.map((x, j) => j === i ? { ...x, reference: e.target.value } : x))} /></Field>}
      {rows.length > 1 && <button className="link danger small self-end" onClick={() => setRows(rows.filter((_, j) => j !== i))}>Remove</button>}
    </div>)}
    <button className="link small" onClick={() => setRows([...rows, { kind: "", amount: due > paid ? fromMinor(due - paid) : "", reference: "" }])}>+ Split payment</button>
    {needsRoom && (o.reservation ? <p className="note">Charging to room {o.reservation.room_number} — {o.reservation.guest}</p> : <>
      <Field label="Find in-house guest (room number or name)" wide><Input value={q} onChange={e => setQ(e.target.value)} /></Field>
      <div className="picklist">{(inHouse.data?.items || []).map((g: any) => <button key={g.reservation_id} className={resId === g.reservation_id ? "on" : ""} onClick={() => setResId(g.reservation_id)}>
        <b>Room {g.room_number}</b> {g.guest}</button>)}</div></>)}
  </Modal>;
}

function DiscountModal({ o, onClose, onDone }: any) {
  const [mode, setMode] = useState("percent");
  const [value, setValue] = useState("10");
  const [reason, setReason] = useState(o.discount_reason || "");
  const { busy, run } = useAction();
  const go = async (remove = false) => {
    const body = remove ? { amount: 0 } : mode === "percent" ? { percent: Number(value), reason } : { amount: toMinor(value), reason };
    const r = await run(() => post(`/api/pos/orders/${o.id}/discount`, body), remove ? "Discount removed" : "Discount applied");
    if (r) onDone(r);
  };
  return <Modal title="Discount" onClose={onClose} footer={<>{o.discount_amount > 0 && <Button kind="ghost" onClick={() => go(true)}>Remove discount</Button>}
    <Button kind="secondary" onClick={onClose}>Cancel</Button><Button busy={busy} disabled={!reason.trim()} onClick={() => go()}>Apply</Button></>}>
    <div className="form-grid">
      <Field label="Type"><Select value={mode} onChange={e => setMode(e.target.value)}><option value="percent">Percentage</option><option value="amount">Fixed amount</option></Select></Field>
      <Field label={mode === "percent" ? "Percent" : "Amount"}><Input value={value} onChange={e => setValue(e.target.value)} /></Field>
      <Field label="Reason (required)" wide><Input value={reason} onChange={e => setReason(e.target.value)} placeholder="e.g. Manager's courtesy, loyalty guest" /></Field>
    </div></Modal>;
}

function SplitModal({ o, onClose, onDone }: any) {
  const [sel, setSel] = useState<number[]>([]);
  const { busy, run } = useAction();
  const items = o.items.filter((i: any) => i.kitchen_status !== "void");
  return <Modal title="Split bill — choose items for the new bill" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!sel.length || sel.length >= items.length} onClick={async () => { const r = await run(() => post(`/api/pos/orders/${o.id}/split`, { item_ids: sel }), "Bill split"); if (r) onDone(r); }}>Create new bill</Button></>}>
    {items.map((i: any) => <label key={i.id} className="check"><input type="checkbox" checked={sel.includes(i.id)} onChange={e => setSel(e.target.checked ? [...sel, i.id] : sel.filter(x => x !== i.id))} /> {i.quantity} × {i.name}</label>)}
  </Modal>;
}

function PickModal({ title, options, onPick, onClose }: any) {
  return <Modal title={title} onClose={onClose}><div className="picklist">{options.map((op: any) => <button key={op.id} onClick={() => onPick(op.id)}>{op.label}</button>)}
    {!options.length && <p className="muted small">Nothing to choose from.</p>}</div></Modal>;
}

function OpenShift({ outlet, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [float, setFloat] = useState("0");
  const { busy, run } = useAction();
  return <Modal title={`Open shift — ${outlet.name}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={isNaN(toMinor(float))} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/pos/shifts`, { outlet_id: outlet.id, opening_float: toMinor(float) }), "Shift opened")) onDone(); }}>Open shift</Button></>}>
    <Field label={`Opening cash float (${hotel!.currency})`} hint="The cash in your drawer before your first sale"><Input inputMode="decimal" value={float} onChange={e => setFloat(e.target.value)} /></Field>
  </Modal>;
}

function CloseShift({ shift, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/pos/shifts/${shift.id}`), [shift.id]);
  const [counted, setCounted] = useState("");
  const [note, setNote] = useState("");
  const { busy, run } = useAction();
  const variance = st.data && counted !== "" ? toMinor(counted) - st.data.expected_cash_now : 0;
  return <Modal title={`Close shift ${shift.number}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button kind="gold" busy={busy} disabled={counted === "" || isNaN(toMinor(counted)) || (variance !== 0 && !note.trim())}
      onClick={async () => { if (await run(() => post(`/api/pos/shifts/${shift.id}/close`, { counted_cash: toMinor(counted), note: note || undefined }), "Shift closed")) onDone(); }}>Close shift</Button></>}>
    <Loadable state={st}>{s => <>
      <dl className="dl">
        <dt>Opening float</dt><dd>{money(s.opening_float, cur)}</dd>
        {s.tenders.map((t: any) => <React.Fragment key={t.method}><dt>{t.method} ({t.count})</dt><dd>{money(t.amount, cur)}</dd></React.Fragment>)}
        <dt>Orders settled</dt><dd>{s.orders_settled} · {money(s.sales_total, cur)}</dd>
        <dt>Discounts given</dt><dd>{money(s.discounts, cur)}</dd>
        <dt>Items you voided</dt><dd>{s.voided_items}</dd>
        <dt><b>Expected cash in drawer</b></dt><dd><b>{money(s.expected_cash_now, cur)}</b></dd>
      </dl>
      <div className="form-grid mt">
        <Field label={`Counted cash (${cur})`}><Input inputMode="decimal" value={counted} onChange={e => setCounted(e.target.value)} /></Field>
        {counted !== "" && <Field label="Variance"><div className={variance < 0 ? "danger big" : "big"}>{money(variance, cur)}</div></Field>}
        {variance !== 0 && counted !== "" && <Field label="Explain the variance (required)" wide><Textarea value={note} onChange={e => setNote(e.target.value)} /></Field>}
      </div></>}</Loadable>
  </Modal>;
}

// ======================================================================== Kitchen display
export function Kitchen() {
  const { hotel, can } = useAuth();
  const [station, setStation] = useState(() => { try { return localStorage.getItem("ehms.station") || ""; } catch { return ""; } });
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/kitchen/tickets`, { station }), [hotel?.id, station]);
  const [now, setNow] = useState(Date.now());
  const toast = useToast();
  useEffect(() => { const t = setInterval(() => { st.reload(); setNow(Date.now()); }, 10000); return () => clearInterval(t); }, [station]);
  useEffect(() => { try { localStorage.setItem("ehms.station", station); } catch { /* ignore */ } }, [station]);
  const mins = (iso: string) => Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60000));
  const setStatus = async (itemId: number, status: string) => {
    try { await post(`/api/kitchen/items/${itemId}/status`, { status }); st.reload(); } catch (e) { toast("error", errText(e)); }
  };
  return (
    <div className="page">
      <div className="page-h"><div><h1>Kitchen display</h1><p className="muted">Refreshes every 10 seconds · oldest tickets first</p></div>
        <div className="row gap-s"><Select value={station} onChange={e => setStation(e.target.value)} aria-label="Station">
          <option value="">All stations</option>{["kitchen", "grill", "pastry", "bar"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select>
          <Button kind="secondary" onClick={st.reload}>Refresh</Button></div></div>
      <Loadable state={st}>{d => d.tickets.length ? <div className="tickets">
        {d.tickets.map((t: any) => {
          const age = mins(t.sent_at);
          return <div key={t.order_id} className={`ticket ${age >= 20 ? "late" : age >= 10 ? "warn" : ""}`}>
            <div className="ticket-h"><b>{t.table ? `Table ${t.table}` : t.room ? `Room ${t.room}` : label(t.order_type)}</b><span>{age} min</span></div>
            <div className="tiny muted">{t.number} · {t.outlet}{t.waiter ? ` · ${t.waiter}` : ""}</div>
            {t.items.map((i: any) => <div key={i.id} className={`titem ti-${i.kitchen_status}`}>
              <div className="grow"><b>{i.quantity} × {i.name}</b> {i.priority === 1 && <Pill s="rejected" text="Rush" />}{i.notes && <div className="small">{i.notes}</div>}
                <div className="tiny muted">{label(i.station)} · {label(i.kitchen_status)}</div></div>
              {can("kitchen.update") && i.kitchen_status === "sent" && <Button kind="secondary" onClick={() => setStatus(i.id, "preparing")}>Start</Button>}
              {can("kitchen.update") && ["sent", "preparing"].includes(i.kitchen_status) && <Button onClick={() => setStatus(i.id, "ready")}>Ready</Button>}
              {can("pos.order") && i.kitchen_status === "ready" && <Button kind="gold" onClick={() => setStatus(i.id, "served")}>Served</Button>}
            </div>)}
          </div>;
        })}</div> : <Empty text="No orders waiting. New orders appear here when service staff send them." />}</Loadable>
    </div>
  );
}

// ======================================================================== POS setup
export function PosSetup() {
  const { can } = useAuth();
  const [tab, setTab] = useState("menu");
  return <div className="page">
    <div className="page-h"><div><h1>POS setup</h1><p className="muted">Outlets, tables, menu, recipes and cashier shifts</p></div></div>
    <Tabs tabs={[{ id: "menu", label: "Menu & recipes" }, { id: "outlets", label: "Outlets & tables" }, { id: "shifts", label: "Cashier shifts" }, ...(can("kitchen.view") ? [{ id: "perf", label: "Kitchen performance" }] : [])]} value={tab} onChange={setTab} />
    {tab === "menu" && <MenuSetup />}
    {tab === "outlets" && <OutletSetup />}
    {tab === "shifts" && <Shifts />}
    {tab === "perf" && <KitchenPerf />}
  </div>;
}

function MenuSetup() {
  const { hotel, can } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/pos/menu`, { all: 1 }), [hotel?.id]);
  const stores = useLoad(() => (can("inventory.view") ? get(`/api/hotels/${hotel!.id}/stores`) : Promise.resolve({ items: [] })), [hotel?.id]);
  const [edit, setEdit] = useState<any>(null);
  const [recipe, setRecipe] = useState<any>(null);
  const [newCat, setNewCat] = useState(false);
  const { run } = useAction();
  return <Loadable state={st}>{d => <Card title="Menu items" actions={can("pos.manage") && <div className="row gap-s"><Button kind="secondary" onClick={() => setNewCat(true)}>New category</Button><Button onClick={() => setEdit({})}>New item</Button></div>} pad={false}>
    <Table rows={d.items} cols={[
      { h: "Item", r: m => <><b>{m.name}</b><div className="tiny muted">{m.code} · {d.categories.find((c: any) => c.id === m.category_id)?.name}</div></> },
      { h: "Station", r: m => label(m.station) }, { h: "Price", r: m => money(m.price, cur), cls: "num" },
      { h: "Recipe cost", r: m => m.recipe ? <span title={m.recipe.map((r: any) => `${r.quantity} ${r.unit} ${r.item_name}`).join("\n")}>{money(m.recipe_cost, cur)} {m.price ? <span className="muted tiny">({Math.round(m.recipe_cost * 100 / m.price)}%)</span> : null}</span> : "—", cls: "num" },
      { h: "Issues from", r: m => m.issue_store_name || <span className="muted">Outlet store</span> },
      { h: "Status", r: m => !m.active ? <Pill s="deactivated" text="Inactive" /> : m.available ? <Pill s="available" /> : <Pill s="rejected" text="Sold out" /> },
      { h: "", r: m => can("pos.manage") && <span className="row gap-s"><button className="link small" onClick={() => setEdit(m)}>Edit</button><button className="link small" onClick={() => setRecipe(m)}>Recipe</button>
        <button className="link small" onClick={async () => { if (await run(() => post(`/api/pos/menu-items/${m.id}/availability`, { available: !m.available }), m.available ? "Marked sold out" : "Available again")) st.reload(); }}>{m.available ? "Sold out" : "Available"}</button></span> },
    ]} />
    {edit && <MenuItemModal item={edit} categories={d.categories} stations={d.stations} stores={stores.data?.items || []} onClose={() => setEdit(null)} onDone={() => { setEdit(null); st.reload(); }} />}
    {recipe && <RecipeModal item={recipe} onClose={() => setRecipe(null)} onDone={() => { setRecipe(null); st.reload(); }} />}
    {newCat && <NewCategory onClose={() => setNewCat(false)} onDone={() => { setNewCat(false); st.reload(); }} />}
  </Card>}</Loadable>;
}

function NewCategory({ onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ name: "", kind: "food" });
  const { busy, run } = useAction();
  return <Modal title="New menu category" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.name.trim()} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/pos/menu-categories`, f), "Category created")) onDone(); }}>Create</Button></>}>
    <div className="form-grid"><Field label="Name"><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Kind"><Select value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}><option value="food">Food</option><option value="beverage">Beverage</option><option value="other">Other</option></Select></Field></div></Modal>;
}

function MenuItemModal({ item, categories, stations, stores, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ name: item.name || "", category_id: item.category_id || categories[0]?.id || "", price: item.price != null ? fromMinor(item.price) : "",
    station: item.station || "kitchen", description: item.description || "", issue_store_id: item.issue_store_id || "", active: item.active ?? 1 });
  const { busy, run } = useAction();
  const go = async () => {
    const body = { ...f, price: toMinor(f.price), category_id: Number(f.category_id), issue_store_id: f.issue_store_id ? Number(f.issue_store_id) : null, active: !!f.active };
    const r = await run(() => item.id ? patch(`/api/pos/menu-items/${item.id}`, body) : post(`/api/hotels/${hotel!.id}/pos/menu-items`, body), "Menu item saved");
    if (r) onDone();
  };
  return <Modal title={item.id ? `Edit ${item.name}` : "New menu item"} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.name.trim() || isNaN(toMinor(f.price))} onClick={go}>Save</Button></>}>
    <div className="form-grid">
      <Field label="Name" wide><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Category"><Select value={f.category_id} onChange={e => setF({ ...f, category_id: e.target.value })}>{categories.map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}</Select></Field>
      <Field label={`Price (${hotel!.currency})`} hint="Before service charge and exclusive taxes"><Input inputMode="decimal" value={f.price} onChange={e => setF({ ...f, price: e.target.value })} /></Field>
      <Field label="Preparation station"><Select value={f.station} onChange={e => setF({ ...f, station: e.target.value })}>{stations.map((s: string) => <option key={s} value={s}>{s === "none" ? "None (ready immediately)" : label(s)}</option>)}</Select></Field>
      <Field label="Issue ingredients from" hint="Leave as outlet store unless this item is stocked elsewhere (e.g. drinks from the bar)">
        <Select value={f.issue_store_id} onChange={e => setF({ ...f, issue_store_id: e.target.value })}><option value="">Outlet's store</option>{stores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
      <Field label="Description" wide><Input value={f.description} onChange={e => setF({ ...f, description: e.target.value })} /></Field>
      {item.id && <label className="check"><input type="checkbox" checked={!!f.active} onChange={e => setF({ ...f, active: e.target.checked ? 1 : 0 })} /> Active on the menu</label>}
    </div></Modal>;
}

function RecipeModal({ item, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const inv = useLoad(() => get(`/api/hotels/${hotel!.id}/inventory/items`), [hotel?.id]);
  const [lines, setLines] = useState<any[]>((item.recipe || []).map((r: any) => ({ item_id: r.item_id, quantity: String(r.quantity) })));
  const { busy, run } = useAction();
  const items = inv.data?.items || [];
  const cost = lines.reduce((s, l) => { const it = items.find((i: any) => i.id === Number(l.item_id)); return s + (it ? Math.round(Number(l.quantity || 0) * it.avg_cost) : 0); }, 0);
  return <Modal title={`Recipe — ${item.name} (per portion)`} width={640} onClose={onClose} footer={<><span className="muted small grow">Estimated cost {money(cost, hotel!.currency)} per portion</span>
    <Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} onClick={async () => { if (await run(() => put(`/api/pos/menu-items/${item.id}/recipe`, { lines: lines.filter(l => l.item_id) }), "Recipe saved")) onDone(); }}>Save recipe</Button></>}>
    <p className="muted small">Selling this item deducts these quantities from stock at settlement.</p>
    {lines.map((l, i) => { const it = items.find((x: any) => x.id === Number(l.item_id)); return <div key={i} className="form-grid tender">
      <Field label="Ingredient"><Select value={l.item_id} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, item_id: e.target.value } : x))}>
        <option value="">Select…</option>{items.map((x: any) => <option key={x.id} value={x.id}>{x.name} ({x.unit})</option>)}</Select></Field>
      <Field label={`Quantity${it ? ` (${it.unit})` : ""}`}><Input inputMode="decimal" value={l.quantity} onChange={e => setLines(lines.map((x, j) => j === i ? { ...x, quantity: e.target.value } : x))} /></Field>
      <button className="link danger small self-end" onClick={() => setLines(lines.filter((_, j) => j !== i))}>Remove</button></div>; })}
    <button className="link small" onClick={() => setLines([...lines, { item_id: "", quantity: "" }])}>+ Add ingredient</button>
  </Modal>;
}

function OutletSetup() {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/pos/outlets`), [hotel?.id]);
  const stores = useLoad(() => (can("inventory.view") ? get(`/api/hotels/${hotel!.id}/stores`) : Promise.resolve({ items: [] })), [hotel?.id]);
  const [edit, setEdit] = useState<any>(null);
  const [table, setTable] = useState<any>(null);
  return <Loadable state={st}>{d => <div className="stack">
    {can("pos.manage") && <div><Button onClick={() => setEdit({})}>New outlet</Button></div>}
    {d.items.map((o: any) => <Card key={o.id} title={<span>{o.name} <span className="muted small">{label(o.kind)} · {o.code}</span> {!o.active && <Pill s="deactivated" text="Inactive" />}</span>}
      actions={can("pos.manage") && <div className="row gap-s"><Button kind="secondary" onClick={() => setTable(o)}>Add table</Button><Button kind="ghost" onClick={() => setEdit(o)}>Edit</Button></div>}>
      <p className="small">Ingredients issue from: <b>{o.store_name || "— not set (recipe deduction will block settlement)"}</b></p>
      <div className="row gap-s wrap">{o.tables.map((t: any) => <span key={t.id} className="chip">{t.code} · {t.seats} seats{t.area ? ` · ${t.area}` : ""}</span>)}
        {!o.tables.length && <span className="muted small">No tables</span>}</div>
    </Card>)}
    {edit && <OutletModal outlet={edit} kinds={d.kinds} stores={stores.data?.items || []} onClose={() => setEdit(null)} onDone={() => { setEdit(null); st.reload(); }} />}
    {table && <TableModal outlet={table} onClose={() => setTable(null)} onDone={() => { setTable(null); st.reload(); }} />}
  </div>}</Loadable>;
}

function OutletModal({ outlet, kinds, stores, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ code: outlet.code || "", name: outlet.name || "", kind: outlet.kind || "restaurant", store_id: outlet.store_id || "", active: outlet.active ?? 1 });
  const { busy, run } = useAction();
  const go = async () => {
    const body = { ...f, store_id: f.store_id ? Number(f.store_id) : null, active: !!f.active };
    if (await run(() => outlet.id ? patch(`/api/pos/outlets/${outlet.id}`, body) : post(`/api/hotels/${hotel!.id}/pos/outlets`, body), "Outlet saved")) onDone();
  };
  return <Modal title={outlet.id ? `Edit ${outlet.name}` : "New outlet"} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button><Button busy={busy} disabled={!f.name || !f.code} onClick={go}>Save</Button></>}>
    <div className="form-grid">
      {!outlet.id && <Field label="Code"><Input value={f.code} onChange={e => setF({ ...f, code: e.target.value })} /></Field>}
      <Field label="Name"><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Kind"><Select value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}>{kinds.map((k: string) => <option key={k} value={k}>{label(k)}</option>)}</Select></Field>
      <Field label="Issuing store"><Select value={f.store_id} onChange={e => setF({ ...f, store_id: e.target.value })}><option value="">None</option>{stores.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select></Field>
      {outlet.id && <label className="check"><input type="checkbox" checked={!!f.active} onChange={e => setF({ ...f, active: e.target.checked ? 1 : 0 })} /> Active</label>}
    </div></Modal>;
}

function TableModal({ outlet, onClose, onDone }: any) {
  const [f, setF] = useState({ code: "", area: "", seats: 4 });
  const { busy, run } = useAction();
  return <Modal title={`Add table — ${outlet.name}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.code} onClick={async () => { if (await run(() => post(`/api/pos/outlets/${outlet.id}/tables`, f), "Table added")) onDone(); }}>Add</Button></>}>
    <div className="form-grid"><Field label="Table code"><Input value={f.code} onChange={e => setF({ ...f, code: e.target.value })} /></Field>
      <Field label="Area"><Input value={f.area} onChange={e => setF({ ...f, area: e.target.value })} /></Field>
      <Field label="Seats"><Input type="number" value={f.seats} onChange={e => setF({ ...f, seats: Number(e.target.value) })} /></Field></div></Modal>;
}

function Shifts() {
  const { hotel } = useAuth();
  const cur = hotel!.currency;
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/pos/shifts`), [hotel?.id]);
  return <Loadable state={st}>{d => <Card pad={false}><Table rows={d.items} empty="No shifts yet" cols={[
    { h: "Shift", r: s => <><b>{s.number}</b><div className="tiny muted">{s.outlet_name}</div></> }, { h: "Cashier", r: s => s.cashier },
    { h: "Opened", r: s => fmtDateTime(s.opened_at) }, { h: "Closed", r: s => fmtDateTime(s.closed_at) }, { h: "Status", r: s => <Pill s={s.status} /> },
    { h: "Float", r: s => money(s.opening_float, cur), cls: "num" }, { h: "Expected", r: s => money(s.expected_cash ?? s.expected_cash_now, cur), cls: "num" },
    { h: "Counted", r: s => s.counted_cash != null ? money(s.counted_cash, cur) : "—", cls: "num" },
    { h: "Variance", r: s => s.variance != null ? <span className={s.variance < 0 ? "danger" : ""} title={s.note || ""}>{money(s.variance, cur)}</span> : "—", cls: "num" }]} /></Card>}</Loadable>;
}

function KitchenPerf() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/kitchen/performance`), [hotel?.id]);
  return <Loadable state={st}>{d => <Card title={`Kitchen performance ${d.from}${d.to !== d.from ? " to " + d.to : ""}`} pad={false}>
    <Table rows={d.items} empty="No completed kitchen items for this date" cols={[{ h: "Station", r: s => label(s.station) }, { h: "Portions", r: s => s.items, cls: "num" },
      { h: "Average prep time", r: s => `${s.avg_minutes} min`, cls: "num" }, { h: "Slowest", r: s => `${s.slowest_minutes} min`, cls: "num" }]} /></Card>}</Loadable>;
}
