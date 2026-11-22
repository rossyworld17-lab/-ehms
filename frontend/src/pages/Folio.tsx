import React, { useEffect, useState } from "react";
import { fmtDate, fmtDateTime, get, label, money, openFile, post, toMinor, uid } from "../api";
import { navigate, useAuth, useRoute } from "../state";
import { Button, Card, Field, Input, Loadable, Modal, Pill, Select, Table, Textarea, errText, useAction, useLoad, useToast } from "../ui";

export default function Folio({ id }: { id: number }) {
  const { hotel, can } = useAuth();
  const [, q] = useRoute();
  const st = useLoad(() => get(`/api/folios/${id}`), [id]);
  const methods = useLoad(() => get(`/api/hotels/${hotel!.id}/payment-methods`), [hotel?.id]);
  const [modal, setModal] = useState<string | null>(q.get("settle") ? "pay" : null);
  const [reverse, setReverse] = useState<any>(null);
  const [due, setDue] = useState<any>(null);
  const toast = useToast();
  const gw = useLoad(() => get(`/api/payments/gateway-status`), []);
  useEffect(() => {
    const r = st.data?.reservation;
    if (r && r.status === "checked_in") get(`/api/reservations/${r.id}/checkout-preview`).then(setDue).catch(() => setDue(null)); else setDue(null);
  }, [st.data]);
  const cur = hotel!.currency;
  return (
    <div className="page">
      <Loadable state={st}>{f => {
        const open = f.status === "open";
        return <>
          <div className="page-h"><div><h1>Folio {f.number} <Pill s={f.status} /></h1>
            <p className="muted">{f.guest.first_name} {f.guest.last_name}{f.reservation && <> · <a href={`#/reservations/${f.reservation.id}`}>{f.reservation.reference}</a> · Room {f.reservation.room_number || "—"} · {fmtDate(f.reservation.arrival)} → {fmtDate(f.reservation.departure)}</>}</p></div>
            <div className="row gap-s wrap">
              {open && can("folio.post_charge") && <Button kind="secondary" onClick={() => setModal("charge")}>Post charge</Button>}
              {open && can("payments.receive") && <Button onClick={() => setModal("pay")}>Take payment</Button>}
              {open && can("payments.receive") && (gw.data?.providers || []).length > 0 && <Button kind="secondary" onClick={() => setModal("link")}>Payment link</Button>}
              {open && can("folio.adjust") && <Button kind="secondary" onClick={() => setModal("allowance")}>Allowance</Button>}
              {can("payments.refund_request") && (due ? due.balance_due < 0 : f.totals.balance < 0) && <Button kind="secondary" onClick={() => setModal("refund")}>Request refund</Button>}
              <Button kind="secondary" onClick={() => openFile(`/api/folios/${id}/invoice.pdf`, `${f.number}.pdf`, true).catch(e => toast("error", errText(e)))}>Invoice PDF</Button>
            </div></div>
          <div className="kpis">
            <div className="kpi"><div className="kpi-t">Charges</div><div className="kpi-v">{money(f.totals.charges + f.totals.adjustments, cur)}</div></div>
            <div className="kpi"><div className="kpi-t">Payments</div><div className="kpi-v">{money(f.totals.payments, cur)}</div></div>
            {f.totals.refunds > 0 && <div className="kpi"><div className="kpi-t">Refunds</div><div className="kpi-v">{money(f.totals.refunds, cur)}</div></div>}
            <div className={`kpi ${!due && f.totals.balance > 0 ? "kpi-gold" : ""}`}><div className="kpi-t">Balance (posted)</div><div className="kpi-v">{money(f.totals.balance, cur)}</div>
              <div className="kpi-s">{due ? "Room nights post nightly / at check-out" : f.totals.balance > 0 ? "Due from guest" : f.totals.balance < 0 ? "Guest in credit" : "Settled"}</div></div>
            {due && <div className={`kpi ${due.balance_due > 0 ? "kpi-gold" : "kpi-navy"}`}><div className="kpi-t">Due at check-out</div><div className="kpi-v">{money(due.balance_due, cur)}</div>
              <div className="kpi-s">{due.balance_due > 0 ? `Includes ${due.pending_room_nights.length} unposted room night(s)` : due.balance_due < 0 ? "Guest will be in credit — refund needed" : "Settled — ready to check out"}</div></div>}
          </div>
          <Card title="Transactions" pad={false}>
            <Table rows={f.lines} cols={[
              { h: "Date", r: l => fmtDate(l.business_date) },
              { h: "Description", r: l => <>{l.description}{l.reversed && <> <Pill s="cancelled" text="Reversed" /></>}<div className="muted small">{label(l.kind)} · {l.posted_by_name || "system"} · {fmtDateTime(l.posted_at)}</div></> },
              { h: "Net", r: l => l.kind === "payment" || l.kind === "refund" ? "" : money(l.net_amount, cur), cls: "num" },
              { h: "Svc", r: l => (l.service_charge ? money(l.service_charge, cur) : ""), cls: "num" },
              { h: "Tax", r: l => (l.tax_amount ? money(l.tax_amount, cur) : ""), cls: "num" },
              { h: "Amount", r: l => <b className={l.kind === "payment" ? "pos" : ""}>{l.kind === "payment" ? "−" : ""}{money(l.total_amount, cur)}</b>, cls: "num" },
              { h: "", r: l => open && can("folio.adjust") && l.kind === "charge" && !l.reversed ? <Button kind="ghost" onClick={() => setReverse(l)}>Reverse</Button> : null },
            ]} empty="No transactions yet" />
          </Card>
          {f.approvals.length > 0 && <Card title="Refund requests"><Table rows={f.approvals} cols={[
            { h: "Requested", r: a => fmtDateTime(a.created_at) }, { h: "Amount", r: a => money(a.amount, cur) }, { h: "Reason", r: a => a.reason },
            { h: "Status", r: a => <Pill s={a.status} /> }, { h: "Note", r: a => a.decision_note || "" }]} /></Card>}

          {modal === "charge" && <ChargeModal folio={f} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
          {modal === "pay" && <PayModal folio={f} methods={methods.data?.items || []} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
          {modal === "link" && <PaymentLinkModal folio={f} due={due ? due.balance_due : f.totals.balance} onClose={() => setModal(null)} />}
          {modal === "allowance" && <AllowanceModal folio={f} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
          {modal === "refund" && <RefundModal folio={f} methods={methods.data?.items || []} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
          {reverse && <ReverseModal folio={f} line={reverse} onClose={() => setReverse(null)} onDone={() => { setReverse(null); st.reload(); }} />}
        </>;
      }}</Loadable>
    </div>
  );
}

const DEPTS = [["fnb", "Restaurant / bar"], ["minibar", "Minibar"], ["laundry", "Laundry"], ["transport", "Transport"], ["events", "Events / conference"], ["spa", "Spa / gym"], ["other", "Other services"]];

function ChargeModal({ folio, onClose, onDone }: any) {
  const [f, setF] = useState({ department: "fnb", description: "", amount: "", quantity: 1, reference: "" });
  const { busy, run } = useAction();
  const amt = toMinor(f.amount);
  return <Modal title="Post a charge" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} disabled={!f.description.trim() || !(amt > 0)} onClick={async () => {
      if (await run(() => post(`/api/folios/${folio.id}/charges`, { department: f.department, description: f.description, amount: amt, quantity: Number(f.quantity), reference: f.reference || undefined }), "Charge posted")) onDone();
    }}>Post charge</Button></>}>
    <div className="form-grid">
      <Field label="Department"><Select value={f.department} onChange={e => setF({ ...f, department: e.target.value })}>{DEPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select></Field>
      <Field label="Reference (POS / docket no.)"><Input value={f.reference} onChange={e => setF({ ...f, reference: e.target.value })} /></Field>
      <Field label="Description" wide><Input value={f.description} onChange={e => setF({ ...f, description: e.target.value })} placeholder="e.g. Dinner — table 12" /></Field>
      <Field label="Unit price before tax (₦)" hint="Service charge and taxes are added automatically"><Input inputMode="decimal" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} /></Field>
      <Field label="Quantity"><Input type="number" min={1} value={f.quantity} onChange={e => setF({ ...f, quantity: Number(e.target.value) })} /></Field>
    </div></Modal>;
}

function PayModal({ folio, methods, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [due, setDue] = useState<number | null>(null);
  useEffect(() => {
    if (folio.reservation?.status === "checked_in") get(`/api/reservations/${folio.reservation.id}/checkout-preview`).then(p => setDue(p.balance_due)).catch(() => setDue(folio.totals.balance));
    else setDue(folio.totals.balance);
  }, []);
  const usable = methods.filter((m: any) => m.active && m.kind !== "online");
  const [f, setF] = useState({ method_id: "", amount: "", reference: "", note: "", company: "" });
  const [key] = useState(uid());
  const { busy, run } = useAction();
  useEffect(() => { if (due && due > 0 && !f.amount) setF(x => ({ ...x, amount: (due / 100).toFixed(2) })); }, [due]);
  const m = usable.find((x: any) => String(x.id) === f.method_id);
  const needRef = m && (m.kind === "bank_transfer" || m.kind === "card_pos");
  const amt = toMinor(f.amount);
  return <Modal title="Take payment" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} disabled={!m || !(amt > 0) || (needRef && !f.reference.trim())} onClick={async () => {
      const r = await run(() => post(`/api/folios/${folio.id}/payments`, { method_id: Number(f.method_id), amount: amt, reference: f.reference || undefined, note: f.note || undefined, company: f.company || undefined, idempotency_key: key }), "Payment recorded");
      if (r) onDone();
    }}>Record payment</Button></>}>
    <div className="stack">
      {due !== null && <p className="note">Amount due {folio.reservation?.status === "checked_in" ? "at check-out (including unposted room nights)" : "now"}: <b>{money(due, hotel!.currency)}</b></p>}
      <div className="form-grid">
        <Field label="Method"><Select value={f.method_id} onChange={e => setF({ ...f, method_id: e.target.value })}><option value="">Select…</option>
          {usable.map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}</Select></Field>
        <Field label="Amount (₦)"><Input inputMode="decimal" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label={needRef ? "Reference (required)" : "Reference"} hint={m?.kind === "card_pos" ? "Terminal approval code — never enter card numbers" : m?.kind === "bank_transfer" ? "Bank transfer reference" : undefined}>
          <Input value={f.reference} onChange={e => setF({ ...f, reference: e.target.value })} /></Field>
        {m?.kind === "city_ledger" && <Field label="Company to bill"><Input value={f.company} onChange={e => setF({ ...f, company: e.target.value })} /></Field>}
        <Field label="Note" wide><Input value={f.note} onChange={e => setF({ ...f, note: e.target.value })} /></Field>
      </div>
      <p className="small muted">Online card payments are confirmed automatically by the payment gateway once it is configured; they cannot be entered here.</p>
    </div></Modal>;
}

function AllowanceModal({ folio, onClose, onDone }: any) {
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const { busy, run } = useAction();
  return <Modal title="Grant an allowance (credit)" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} disabled={!(toMinor(amount) > 0) || !reason.trim()} onClick={async () => { if (await run(() => post(`/api/folios/${folio.id}/adjustments`, { amount: toMinor(amount), reason }), "Allowance posted")) onDone(); }}>Post allowance</Button></>}>
    <div className="form-grid"><Field label="Amount (₦)"><Input value={amount} onChange={e => setAmount(e.target.value)} /></Field>
      <Field label="Reason" wide><Textarea value={reason} onChange={e => setReason(e.target.value)} /></Field></div></Modal>;
}

function ReverseModal({ folio, line, onClose, onDone }: any) {
  const [reason, setReason] = useState("");
  const { busy, run } = useAction();
  return <Modal title="Reverse charge" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button kind="danger" busy={busy} disabled={!reason.trim()} onClick={async () => { if (await run(() => post(`/api/folios/${folio.id}/adjustments`, { line_id: line.id, reason }), "Charge reversed")) onDone(); }}>Reverse</Button></>}>
    <p>Reverse “{line.description}”? A reversing entry is posted; the original stays on record for audit.</p>
    <Field label="Reason"><Textarea value={reason} onChange={e => setReason(e.target.value)} /></Field></Modal>;
}

function RefundModal({ folio, methods, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const usable = methods.filter((m: any) => m.active && ["cash", "bank_transfer", "card_pos"].includes(m.kind));
  const [f, setF] = useState({ method_id: "", amount: ((-folio.totals.balance) / 100).toFixed(2), reason: "" });
  const { busy, run } = useAction();
  return <Modal title="Request refund" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} disabled={!f.method_id || !f.reason.trim() || !(toMinor(f.amount) > 0)} onClick={async () => {
      if (await run(() => post(`/api/folios/${folio.id}/refund-requests`, { method_id: Number(f.method_id), amount: toMinor(f.amount), reason: f.reason }), "Refund request sent for approval")) onDone();
    }}>Submit for approval</Button></>}>
    <div className="stack"><p className="note">Guest credit: <b>{money(-folio.totals.balance, hotel!.currency)}</b>. A different authorised user must approve the refund.</p>
      <div className="form-grid">
        <Field label="Refund method"><Select value={f.method_id} onChange={e => setF({ ...f, method_id: e.target.value })}><option value="">Select…</option>{usable.map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}</Select></Field>
        <Field label="Amount (₦)"><Input value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label="Reason" wide><Textarea value={f.reason} onChange={e => setF({ ...f, reason: e.target.value })} /></Field>
      </div></div></Modal>;
}

function PaymentLinkModal({ folio, due, onClose }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ amount: due > 0 ? (due / 100).toFixed(2) : "", email: folio.guest.email || "", send: true });
  const [link, setLink] = useState<any>(null);
  const { busy, run } = useAction();
  return <Modal title="Online payment link" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    {!link && <Button busy={busy} disabled={!(toMinor(f.amount) > 0) || !f.email} onClick={async () => { const r = await run(() => post(`/api/folios/${folio.id}/payment-link`, { amount: toMinor(f.amount), email: f.email, send: f.send }), "Payment link created"); if (r) setLink(r); }}>Create link</Button>}</>}>
    {link ? <><p>Share this secure link with the guest. The payment is added to the folio automatically once the provider confirms it.</p>
      <p className="mono small" style={{ wordBreak: "break-all" }}><a href={link.authorization_url} target="_blank" rel="noreferrer">{link.authorization_url}</a></p>
      <p className="muted small">{money(link.amount, hotel!.currency)} · {link.provider} · reference {link.reference}{f.send ? ` · emailed to ${f.email}` : ""}</p></> :
      <div className="form-grid"><Field label={`Amount (${hotel!.currency})`}><Input inputMode="decimal" value={f.amount} onChange={e => setF({ ...f, amount: e.target.value })} /></Field>
        <Field label="Guest email"><Input type="email" value={f.email} onChange={e => setF({ ...f, email: e.target.value })} /></Field>
        <label className="check"><input type="checkbox" checked={f.send} onChange={e => setF({ ...f, send: e.target.checked })} /> Email the link to the guest</label></div>}
  </Modal>;
}
