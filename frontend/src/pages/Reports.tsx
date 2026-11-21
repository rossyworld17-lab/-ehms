import React, { useEffect, useState } from "react";
import { addDays, get, openFile, qs } from "../api";
import { useAuth } from "../state";
import { Button, Card, Field, Input, Loadable, Table, errText, useLoad, useToast } from "../ui";

export default function Reports() {
  const { hotel } = useAuth();
  const list = useLoad(() => get(`/api/hotels/${hotel!.id}/reports`), [hotel?.id]);
  const [code, setCode] = useState("");
  const [bd, setBd] = useState("");
  const [p, setP] = useState<any>({});
  const [result, setResult] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  useEffect(() => { get(`/api/hotels/${hotel!.id}`).then(h => { setBd(h.business_date); setP({ date: h.business_date, from: addDays(h.business_date, -30), to: h.business_date }); }); }, [hotel?.id]);
  const params = () => (code === "occupancy" ? { from: p.from, to: p.to } : code === "outstanding_balances" ? {} : { date: p.date });
  async function runReport(c = code) {
    setBusy(true); setResult(null);
    try { setResult(await get(`/api/hotels/${hotel!.id}/reports/${c}`, params())); } catch (e) { toast("error", errText(e)); } finally { setBusy(false); }
  }
  const dl = (fmt: string) => openFile(`/api/hotels/${hotel!.id}/reports/${code}?${qs({ ...params(), format: fmt })}`, `${code}.${fmt}`).catch(e => toast("error", errText(e)));
  return <div className="page">
    <div className="page-h"><div><h1>Reports</h1><p className="muted">Run, view and export to Excel, CSV or PDF</p></div></div>
    <div className="grid-side">
      <Card title="Reports"><Loadable state={list}>{d => <div className="picklist">{d.items.map((r: any) =>
        <button key={r.code} className={code === r.code ? "on" : ""} onClick={() => { setCode(r.code); setResult(null); }}>{r.name}{r.financial && <span className="muted small"> · financial</span>}</button>)}</div>}</Loadable></Card>
      <div>{code ? <Card title={list.data?.items.find((r: any) => r.code === code)?.name} actions={result && <>
        <Button kind="secondary" onClick={() => dl("xlsx")}>Excel</Button><Button kind="secondary" onClick={() => dl("csv")}>CSV</Button><Button kind="secondary" onClick={() => dl("pdf")}>PDF</Button></>}>
        <div className="row gap-s wrap mb">
          {code === "occupancy" ? <><Field label="From"><Input type="date" value={p.from} onChange={e => setP({ ...p, from: e.target.value })} /></Field>
            <Field label="To"><Input type="date" value={p.to} onChange={e => setP({ ...p, to: e.target.value })} /></Field></>
            : code !== "outstanding_balances" && <Field label="Date"><Input type="date" value={p.date || bd} onChange={e => setP({ ...p, date: e.target.value })} /></Field>}
          <Button busy={busy} onClick={() => runReport()} className="self-end">Run report</Button>
        </div>
        {result && <><h4>{result.title}</h4><Table rows={result.rows.map((r: any[], i: number) => ({ id: i, r }))} cols={result.columns.map((c: string, i: number) => ({ h: c, r: (row: any) => row.r[i] }))} empty="No rows for this selection" /></>}
      </Card> : <Card><p className="muted">Choose a report on the left.</p></Card>}</div>
    </div>
  </div>;
}
