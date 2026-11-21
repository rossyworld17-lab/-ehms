import React, { useState } from "react";
import { fmtDateTime, get, label, money, post } from "../api";
import { useAuth } from "../state";
import { Button, Card, Confirm, Loadable, Pill, Table, Tabs, errText, useLoad, useToast } from "../ui";

export default function Approvals() {
  const { hotel, can, user } = useAuth();
  const [status, setStatus] = useState("pending");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/approvals`, { status }), [hotel?.id, status]);
  const [decide, setDecide] = useState<{ a: any; d: "approve" | "reject" } | null>(null);
  const toast = useToast();
  return <div className="page">
    <div className="page-h"><div><h1>Approvals</h1><p className="muted">Maker-checker control: a request cannot be approved by the person who raised it</p></div></div>
    <Tabs tabs={[{ id: "pending", label: "Pending" }, { id: "approved", label: "Approved" }, { id: "rejected", label: "Rejected" }]} value={status} onChange={setStatus} />
    <Card pad={false}><Loadable state={st}>{d => <Table rows={d.items} cols={[
      { h: "Type", r: a => label(a.kind) }, { h: "Folio", r: a => a.folio_number ? <a href={`#/folio/${a.entity_id}`}>{a.folio_number}</a> : "—" },
      { h: "Amount", r: a => money(a.amount, hotel!.currency), cls: "num" }, { h: "Reason", r: a => a.reason },
      { h: "Requested by", r: a => <>{a.requested_by_name}<div className="muted small">{fmtDateTime(a.created_at)}</div></> },
      { h: "Status", r: a => <><Pill s={a.status} />{a.decided_by_name && <div className="muted small">{a.decided_by_name}{a.decision_note ? `: ${a.decision_note}` : ""}</div>}</> },
      { h: "", r: a => a.status === "pending" && can("payments.refund_approve") && a.requested_by !== user!.id ? <div className="row gap-s">
        <Button onClick={() => setDecide({ a, d: "approve" })}>Approve</Button><Button kind="danger" onClick={() => setDecide({ a, d: "reject" })}>Reject</Button></div>
        : a.status === "pending" && a.requested_by === user!.id ? <span className="muted small">Awaiting another approver</span> : null },
    ]} empty="No requests" />}</Loadable></Card>
    {decide && <Confirm title={decide.d === "approve" ? "Approve refund" : "Reject refund"} danger={decide.d === "reject"} confirmText={decide.d === "approve" ? "Approve & pay out" : "Reject"}
      needReason={decide.d === "reject" ? "Reason for rejection" : undefined} onClose={() => setDecide(null)}
      text={<p>{label(decide.a.kind)} of <b>{money(decide.a.amount, hotel!.currency)}</b> on folio {decide.a.folio_number}: “{decide.a.reason}”.{decide.d === "approve" ? " Approving records the refund and posts it to the ledger." : ""}</p>}
      onConfirm={async note => {
        try { await post(`/api/approvals/${decide.a.id}/decide`, { decision: decide.d, note: note || undefined }); toast("success", decide.d === "approve" ? "Refund approved and recorded" : "Request rejected"); setDecide(null); st.reload(); }
        catch (e) { toast("error", errText(e)); }
      }} />}
  </div>;
}
