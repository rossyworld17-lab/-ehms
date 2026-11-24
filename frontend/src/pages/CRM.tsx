import React, { useEffect, useState } from "react";
import { api, fmtDate, fmtDateTime, get, label, money, patch, post, put, toMinor, fromMinor } from "../api";
import { useAuth } from "../state";
import { BarList, Button, Card, Empty, Field, Input, Kpi, LineChart, Loadable, Modal, Pill, Select, Spinner, Table, Tabs, Textarea, errText, useAction, useLoad } from "../ui";
import { Referrals } from "./Completion";
import { Enquiries } from "./WebsiteAdmin";

const PRIO: Record<string, string> = { urgent: "rejected", high: "maintenance", normal: "confirmed", low: "cancelled" };
const SENT: Record<string, string> = { positive: "approved", neutral: "pending", negative: "rejected" };

// ======================================================================== Guest relations
export default function CRM({ q }: { q: URLSearchParams }) {
  const { can } = useAuth();
  const [tab, setTab] = useState(q.get("tab") || "complaints");
  useEffect(() => { const t = q.get("tab"); if (t) setTab(t); }, [q.get("tab")]);
  return <div className="page">
    <div className="page-h"><div><h1>Guest relations</h1><p className="muted">Complaints, feedback, loyalty and campaigns</p></div></div>
    <Tabs tabs={[{ id: "complaints", label: "Complaints" }, { id: "feedback", label: "Feedback" }, { id: "insights", label: "Insights" }, { id: "loyalty", label: "Loyalty" },
      { id: "referrals", label: "Referrals" }, { id: "enquiries", label: "Website enquiries" }, ...(can("crm.campaigns") ? [{ id: "campaigns", label: "Campaigns" }] : [])]} value={tab} onChange={setTab} />
    {tab === "complaints" && <Complaints />}{tab === "feedback" && <Feedback />}{tab === "insights" && <Insights />}{tab === "loyalty" && <Loyalty />}{tab === "campaigns" && <Campaigns />}{tab === "enquiries" && <Enquiries />}{tab === "referrals" && (can("crm.view") ? <Referrals /> : <p className="muted">Referrals need guest relations access.</p>)}
  </div>;
}

function Complaints() {
  const { hotel } = useAuth();
  const [open, setOpen] = useState(true);
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/complaints`, { open: open ? 1 : "" }), [hotel?.id, open]);
  const [sel, setSel] = useState<number | null>(null);
  const [create, setCreate] = useState(false);
  return <Loadable state={st}>{d => <Card title={<label className="check"><input type="checkbox" checked={open} onChange={e => setOpen(e.target.checked)} /> Open only</label>}
    actions={<Button onClick={() => setCreate(true)}>Register complaint</Button>} pad={false}>
    <Table rows={d.items} onRow={x => setSel(x.id)} empty="No complaints" cols={[{ h: "No.", r: x => <><b>{x.number}</b>{x.escalation_level ? <> <Pill s="rejected" text={`Escalated ${x.escalation_level}`} /></> : null}</> },
      { h: "Guest / room", r: x => <>{x.guest || "—"}<div className="tiny muted">{x.room_number ? `Room ${x.room_number}` : ""}</div></> }, { h: "Category", r: x => `${label(x.category)} · ${label(x.department)}` },
      { h: "Priority", r: x => <Pill s={PRIO[x.priority]} text={label(x.priority)} /> }, { h: "Due", r: x => <span className={x.overdue ? "danger" : ""}>{fmtDateTime(x.due_at)}{x.overdue ? " (overdue)" : ""}</span> },
      { h: "Assigned", r: x => x.assigned_to_name || "—" }, { h: "Status", r: x => <Pill s={x.status === "open" ? "pending" : x.status === "in_progress" ? "in_progress" : "approved"} text={label(x.status)} /> }]} />
    {sel && <ComplaintModal id={sel} onClose={() => { setSel(null); st.reload(); }} />}
    {create && <NewComplaint categories={d.categories} onClose={() => setCreate(false)} onDone={() => { setCreate(false); st.reload(); }} />}
  </Card>}</Loadable>;
}

export function NewComplaint({ categories, onClose, onDone, reservationId }: any) {
  const { hotel } = useAuth();
  const inHouse = useLoad(() => get(`/api/hotels/${hotel!.id}/reservations`, { tab: "in_house" }).catch(() => ({ items: [] })), [hotel?.id]);
  const cats = categories || ["room", "cleanliness", "noise", "food", "service", "staff", "billing", "maintenance", "wifi", "security", "amenities", "other"];
  const [f, setF] = useState<any>({ category: "service", priority: "normal", channel: "in_person", description: "", reservation_id: reservationId || "" });
  const { busy, run } = useAction();
  return <Modal title="Register a complaint" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.description.trim()} onClick={async () => { const r = await run(() => post(`/api/hotels/${hotel!.id}/complaints`, { ...f, reservation_id: f.reservation_id ? Number(f.reservation_id) : undefined }), "Complaint registered"); if (r) onDone(r); }}>Register</Button></>}>
    <div className="form-grid">
      <Field label="In-house guest (optional)"><Select value={f.reservation_id} onChange={e => setF({ ...f, reservation_id: e.target.value })}><option value="">—</option>
        {(inHouse.data?.items || []).filter((r: any) => r.status === "checked_in").map((r: any) => <option key={r.id} value={r.id}>Room {r.room_number} — {r.first_name} {r.last_name}</option>)}</Select></Field>
      <Field label="Category"><Select value={f.category} onChange={e => setF({ ...f, category: e.target.value })}>{cats.map((c: string) => <option key={c} value={c}>{label(c)}</option>)}</Select></Field>
      <Field label="Priority" hint="Sets the response deadline: urgent 2 h, high 8 h, normal 24 h, low 72 h"><Select value={f.priority} onChange={e => setF({ ...f, priority: e.target.value })}>{["urgent", "high", "normal", "low"].map(p => <option key={p} value={p}>{label(p)}</option>)}</Select></Field>
      <Field label="Received via"><Select value={f.channel} onChange={e => setF({ ...f, channel: e.target.value })}>{["in_person", "phone", "email", "online_review", "social_media", "other"].map(p => <option key={p} value={p}>{label(p)}</option>)}</Select></Field>
      <Field label="What is the complaint?" wide><Textarea value={f.description} onChange={e => setF({ ...f, description: e.target.value })} /></Field>
    </div></Modal>;
}

function ComplaintModal({ id, onClose }: any) {
  const { can } = useAuth();
  const st = useLoad(() => get(`/api/complaints/${id}`), [id]);
  const [f, setF] = useState<any>({ note: "", status: "", resolution: "", compensation: "", guest_satisfied: "" });
  const { busy, run } = useAction();
  return <Modal title={st.data ? `${st.data.number} — ${label(st.data.category)}` : "Complaint"} width={720} onClose={onClose}><Loadable state={st}>{x => <>
    <div className="row gap-s wrap mb"><Pill s={PRIO[x.priority]} text={label(x.priority)} /><Pill s={x.status === "open" ? "pending" : x.status === "in_progress" ? "in_progress" : "approved"} text={label(x.status)} />
      <span className="small muted">{x.guest ? `${x.guest.first_name} ${x.guest.last_name}` : "Unknown guest"} · via {label(x.channel)} · due {fmtDateTime(x.due_at)}{x.first_response_at ? ` · first response ${fmtDateTime(x.first_response_at)}` : ""}</span></div>
    <p className="pre">{x.description}</p>{x.resolution && <p className="note">Resolution: {x.resolution}</p>}
    <h4>Updates</h4>{x.updates.map((u: any) => <p key={u.id} className="small"><b>{u.by_name || "System"}</b> · {fmtDateTime(u.created_at)}<br />{u.note}</p>)}
    {can("crm.complaints") && x.status !== "closed" && <div className="form-grid">
      <Field label="Response / note" wide><Textarea value={f.note} onChange={e => setF({ ...f, note: e.target.value })} /></Field>
      <Field label="Status"><Select value={f.status} onChange={e => setF({ ...f, status: e.target.value })}><option value="">(no change)</option>{["in_progress", "resolved", "closed"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select></Field>
      {["resolved", "closed"].includes(f.status) && <><Field label="Resolution" wide><Textarea value={f.resolution} onChange={e => setF({ ...f, resolution: e.target.value })} /></Field>
        <Field label="Compensation given (value)"><Input inputMode="decimal" value={f.compensation} onChange={e => setF({ ...f, compensation: e.target.value })} /></Field>
        <Field label="Guest satisfied?"><Select value={f.guest_satisfied} onChange={e => setF({ ...f, guest_satisfied: e.target.value })}><option value="">Not asked</option><option value="1">Yes</option><option value="0">No</option></Select></Field></>}
      <Button busy={busy} onClick={async () => { const b: any = {}; if (f.note) b.note = f.note; if (f.status) b.status = f.status; if (f.resolution) b.resolution = f.resolution;
        if (f.compensation) b.compensation = toMinor(f.compensation); if (f.guest_satisfied !== "") b.guest_satisfied = f.guest_satisfied === "1";
        if (await run(() => post(`/api/complaints/${id}/update`, b), "Updated")) { setF({ note: "", status: "", resolution: "", compensation: "", guest_satisfied: "" }); st.reload(); } }}>Save</Button>
    </div>}</>}</Loadable></Modal>;
}

function Feedback() {
  const { hotel, can } = useAuth();
  const [sent, setSent] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/feedback`, { sentiment: sent }), [hotel?.id, sent]);
  const [add, setAdd] = useState(false);
  const [f, setF] = useState<any>({ platform: "", overall: 5, cleanliness: "", service: "", nps: "", comments: "" });
  const { busy, run } = useAction();
  return <Loadable state={st}>{d => <Card title={<div className="row gap-s"><Select value={sent} onChange={e => setSent(e.target.value)}><option value="">All sentiment</option>{["positive", "neutral", "negative"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select>
    <span className="muted small">{d.surveys_awaiting_reply} survey(s) awaiting a reply</span></div>} actions={can("crm.complaints") && <Button kind="secondary" onClick={() => setAdd(true)}>Record review / comment card</Button>} pad={false}>
    <Table rows={d.items} empty="No feedback yet" cols={[{ h: "Received", r: x => fmtDate(x.submitted_at) }, { h: "Guest", r: x => <>{x.guest || "Anonymous"}<div className="tiny muted">{x.platform || label(x.source)}</div></> },
      { h: "Overall", r: x => "★".repeat(x.overall || 0) }, { h: "NPS", r: x => x.nps ?? "—", cls: "num" }, { h: "Comments", r: x => <span className="small">{x.comments || ""}</span> },
      { h: "Sentiment", r: x => x.sentiment ? <Pill s={SENT[x.sentiment]} text={label(x.sentiment)} /> : "—" }, { h: "Themes", r: x => <span className="tiny">{(x.themes || "").replace(/,/g, ", ")}</span> }]} />
    {add && <Modal title="Record feedback" onClose={() => setAdd(false)} footer={<><Button kind="secondary" onClick={() => setAdd(false)}>Cancel</Button>
      <Button busy={busy} onClick={async () => { const b: any = { overall: Number(f.overall) }; for (const k of ["cleanliness", "service", "nps"]) if (f[k] !== "") b[k] = Number(f[k]); if (f.comments) b.comments = f.comments; if (f.platform) b.platform = f.platform;
        if (await run(() => post(`/api/hotels/${hotel!.id}/feedback`, b), "Feedback recorded")) { setAdd(false); st.reload(); } }}>Save</Button></>}>
      <div className="form-grid"><Field label="Platform (blank for comment card)"><Input value={f.platform} onChange={e => setF({ ...f, platform: e.target.value })} placeholder="e.g. Google, TripAdvisor, Booking.com" /></Field>
        {["overall", "cleanliness", "service"].map(k => <Field key={k} label={`${label(k)} (1–5)`}><Input type="number" min={1} max={5} value={f[k]} onChange={e => setF({ ...f, [k]: e.target.value })} /></Field>)}
        <Field label="Likelihood to recommend (0–10)"><Input type="number" min={0} max={10} value={f.nps} onChange={e => setF({ ...f, nps: e.target.value })} /></Field>
        <Field label="Comments" wide><Textarea value={f.comments} onChange={e => setF({ ...f, comments: e.target.value })} /></Field></div></Modal>}
  </Card>}</Loadable>;
}

function Insights() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/crm/insights`), [hotel?.id]);
  return <Loadable state={st}>{d => <div className="stack">
    <div className="kpis"><Kpi title="Average rating" value={d.averages.overall ?? "—"} sub={`${d.responses} responses since ${fmtDate(d.from)}`} tone="navy" />
      <Kpi title="Net Promoter Score" value={d.nps ?? "—"} sub="promoters − detractors" tone="gold" />
      <Kpi title="Repeat-guest rate" value={d.retention.repeat_rate_pct != null ? `${d.retention.repeat_rate_pct}%` : "—"} sub={`${d.retention.repeat_guests} repeat of ${d.retention.guests_with_stays} guests`} />
      <Kpi title="Loyalty members" value={d.retention.loyalty_members} /><Kpi title="Complaints" value={d.complaints.total} sub={`${d.complaints.open} open · ${d.complaints.escalated} escalated`} />
      <Kpi title="First response" value={d.complaints.avg_first_response_hours != null ? `${d.complaints.avg_first_response_hours} h` : "—"} sub={d.complaints.avg_resolution_hours != null ? `resolution ${d.complaints.avg_resolution_hours} h` : ""} /></div>
    <div className="grid-2">
      <Card title="What guests talk about (recurring themes)"><BarList items={d.themes.map((t: any) => ({ label: `${label(t.theme)}${t.negative ? ` (${t.negative} negative)` : ""}`, value: t.mentions }))} />
        <p className="muted small">Themes and sentiment come from a transparent keyword analysis of comments; read the comments before acting.</p></Card>
      <Card title="Ratings by aspect"><BarList items={Object.entries(d.averages).filter(([, v]) => v != null).map(([k, v]: any) => ({ label: label(k), value: v }))} fmt={v => `${v} / 5`} color="#c8a96a" /></Card>
      <Card title="Complaints by category"><BarList items={Object.entries(d.complaints.by_category).map(([k, v]: any) => ({ label: label(k), value: v }))} /></Card>
      <Card title="Complaints by department"><BarList items={Object.entries(d.complaints.by_department).map(([k, v]: any) => ({ label: label(k), value: v }))} /></Card>
    </div></div>}</Loadable>;
}

function Loyalty() {
  const { hotel, can } = useAuth();
  const [qq, setQ] = useState("");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/loyalty`, { q: qq }), [hotel?.id, qq]);
  const [rules, setRules] = useState(false);
  return <Loadable state={st}>{d => <>
    <div className="kpis">{d.rules.tiers.map((t: any) => <Kpi key={t[0]} title={`${label(t[0])} (${t[1].toLocaleString()}+ pts)`} value={d.tiers[t[0]] || 0} />)}</div>
    <Card title={<Input placeholder="Search members…" value={qq} onChange={e => setQ(e.target.value)} />} actions={can("crm.manage") && <Button kind="secondary" onClick={() => setRules(true)}>Programme rules</Button>} pad={false}>
      <p className="small muted pad">Members earn 1 point per {money(d.rules.earn_per_points_kobo, hotel!.currency)} of net spend at check-out; each point is worth {money(d.rules.point_value_kobo, hotel!.currency)} when redeemed on a folio (minimum {d.rules.min_redeem_points}). Enrol guests from their profile.</p>
      <Table rows={d.items} onRow={m => location.hash = `#/guests/${m.guest_id}`} empty="No members" cols={[{ h: "Member", r: m => <><b>{m.first_name} {m.last_name}</b><div className="tiny muted">{m.member_no}</div></> },
        { h: "Tier", r: m => <Pill s={m.tier === "platinum" ? "vip_hold" : m.tier === "gold" ? "maintenance" : m.tier === "silver" ? "confirmed" : "cancelled"} text={label(m.tier)} /> },
        { h: "Points", r: m => m.points_balance.toLocaleString(), cls: "num" }, { h: "Lifetime", r: m => m.lifetime_points.toLocaleString(), cls: "num" }, { h: "Since", r: m => fmtDate(m.enrolled_at) }]} />
    </Card>
    {rules && <RulesModal rules={d.rules} onClose={() => setRules(false)} onDone={() => { setRules(false); st.reload(); }} />}
  </>}</Loadable>;
}

function RulesModal({ rules, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState({ earn: fromMinor(rules.earn_per_points_kobo), value: fromMinor(rules.point_value_kobo), min: rules.min_redeem_points });
  const { busy, run } = useAction();
  return <Modal title="Loyalty programme rules" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} onClick={async () => { if (await run(() => put(`/api/hotels/${hotel!.id}/loyalty/rules`, { earn_per_points_kobo: toMinor(f.earn), point_value_kobo: toMinor(f.value), min_redeem_points: Number(f.min) }), "Rules saved")) onDone(); }}>Save</Button></>}>
    <div className="form-grid"><Field label="Spend per point"><Input inputMode="decimal" value={f.earn} onChange={e => setF({ ...f, earn: e.target.value })} /></Field>
      <Field label="Value of one point"><Input inputMode="decimal" value={f.value} onChange={e => setF({ ...f, value: e.target.value })} /></Field>
      <Field label="Minimum redemption (points)"><Input type="number" value={f.min} onChange={e => setF({ ...f, min: e.target.value })} /></Field></div>
    <p className="muted small">Tiers: {rules.tiers.map((t: any) => `${label(t[0])} ${t[1]}+`).join(" · ")}. Tier bonus on earned points: {Object.entries(rules.tier_bonus_bp).map(([k, v]: any) => `${label(k)} +${v / 100}%`).join(", ")}.</p></Modal>;
}

function Campaigns() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/campaigns`), [hotel?.id]);
  const [create, setCreate] = useState(false);
  const { busy, run } = useAction();
  return <Loadable state={st}>{d => <Card title="Campaigns" actions={<Button onClick={() => setCreate(true)}>New campaign</Button>} pad={false}>
    <p className="small muted pad">Campaigns only reach guests who agreed to receive offers (marketing consent) and always include an opt-out line.</p>
    <Table rows={d.items} empty="No campaigns" cols={[{ h: "Campaign", r: k => <><b>{k.name}</b><div className="tiny muted">{label(k.channel)} · {k.promo_code ? `code ${k.promo_code}` : "no code"}</div></> },
      { h: "Segment", r: k => <span className="tiny">{Object.entries(k.segment).map(([a, b]) => `${label(a)}: ${b}`).join(", ") || "All consenting guests"}</span> },
      { h: "Status", r: k => <Pill s={k.status === "sent" ? "approved" : "draft"} text={label(k.status)} /> }, { h: "Recipients", r: k => k.recipients || "—", cls: "num" },
      { h: "Delivery", r: k => k.delivery ? Object.entries(k.delivery).map(([a, b]) => `${label(a)} ${b}`).join(", ") : "—" },
      { h: "Results", r: k => k.status === "sent" ? `${k.bookings_after} booking(s) by recipients${k.promo_uses != null ? `, ${k.promo_uses} code use(s)` : ""}` : "" },
      { h: "", r: k => k.status === "draft" && <Button busy={busy} onClick={async () => { if (confirm(`Send "${k.name}" now?`) && await run(() => post(`/api/campaigns/${k.id}/send`, {}), "Campaign queued")) st.reload(); }}>Send</Button> }]} />
    {create && <NewCampaign onClose={() => setCreate(false)} onDone={() => { setCreate(false); st.reload(); }} />}
  </Card>}</Loadable>;
}

function NewCampaign({ onClose, onDone }: any) {
  const { hotel } = useAuth();
  const [f, setF] = useState<any>({ name: "", channel: "email", subject: "", body: "Dear {guest},\n\n", promo_code: "" });
  const [seg, setSeg] = useState<any>({ vip: false, min_stays: "", tier: "", nationality: "", not_stayed_since: "", birthday_month: "" });
  const [count, setCount] = useState<any>(null);
  const { busy, run } = useAction();
  const segment = () => Object.fromEntries(Object.entries(seg).filter(([, v]) => v !== "" && v !== false));
  useEffect(() => { const t = setTimeout(() => post(`/api/hotels/${hotel!.id}/campaigns/preview`, { segment: segment() }).then(setCount).catch(() => setCount(null)), 300); return () => clearTimeout(t); }, [JSON.stringify(seg)]);
  return <Modal title="New campaign" width={720} onClose={onClose} footer={<><span className="grow muted small">{count ? `${count.count} consenting guest(s) match` : ""}</span><Button kind="secondary" onClick={onClose}>Cancel</Button>
    <Button busy={busy} disabled={!f.name || !f.body} onClick={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/campaigns`, { ...f, segment: segment(), promo_code: f.promo_code || undefined }), "Draft saved")) onDone(); }}>Save draft</Button></>}>
    <div className="form-grid">
      <Field label="Name"><Input value={f.name} onChange={e => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Channel"><Select value={f.channel} onChange={e => setF({ ...f, channel: e.target.value })}><option value="email">Email</option><option value="sms">SMS</option><option value="whatsapp">WhatsApp</option></Select></Field>
      <Field label="Promo code to mention"><Input value={f.promo_code} onChange={e => setF({ ...f, promo_code: e.target.value.toUpperCase() })} /></Field>
      {f.channel === "email" && <Field label="Subject" wide><Input value={f.subject} onChange={e => setF({ ...f, subject: e.target.value })} /></Field>}
      <Field label="Message (placeholders {guest}, {hotel}, {promo_code})" wide><Textarea rows={6} value={f.body} onChange={e => setF({ ...f, body: e.target.value })} /></Field>
    </div>
    <h4>Who should receive it?</h4>
    <div className="form-grid">
      <label className="check"><input type="checkbox" checked={seg.vip} onChange={e => setSeg({ ...seg, vip: e.target.checked })} /> VIP guests only</label>
      <Field label="Minimum completed stays"><Input type="number" value={seg.min_stays} onChange={e => setSeg({ ...seg, min_stays: e.target.value })} /></Field>
      <Field label="Loyalty tier"><Select value={seg.tier} onChange={e => setSeg({ ...seg, tier: e.target.value })}><option value="">Any</option>{["bronze", "silver", "gold", "platinum"].map(t => <option key={t} value={t}>{label(t)}</option>)}</Select></Field>
      <Field label="Nationality"><Input value={seg.nationality} onChange={e => setSeg({ ...seg, nationality: e.target.value })} /></Field>
      <Field label="Not stayed since (win-back)"><Input type="date" value={seg.not_stayed_since} onChange={e => setSeg({ ...seg, not_stayed_since: e.target.value })} /></Field>
      <Field label="Birthday month"><Select value={seg.birthday_month} onChange={e => setSeg({ ...seg, birthday_month: e.target.value })}><option value="">Any</option>{Array.from({ length: 12 }, (_, i) => <option key={i} value={i + 1}>{new Date(2000, i, 1).toLocaleString("en-GB", { month: "long" })}</option>)}</Select></Field>
    </div>
    {count?.sample?.length > 0 && <p className="tiny muted">e.g. {count.sample.join(", ")}</p>}
  </Modal>;
}

/** Loyalty card on the guest profile: enrol, statement, manual adjustment. */
export function GuestLoyalty({ guestId }: { guestId: number }) {
  const { can, hotel } = useAuth();
  const st = useLoad(() => get(`/api/guests/${guestId}/loyalty`), [guestId]);
  const { busy, run } = useAction();
  const [agree, setAgree] = useState(false);
  return <Card title="Loyalty"><Loadable state={st}>{d => !d.member ? <div>
    <p className="muted small">Not a member.</p>
    {can("guests.manage") && <><label className="check"><input type="checkbox" checked={agree} onChange={e => setAgree(e.target.checked)} /> The guest agreed to join the loyalty programme</label>
      <Button className="mt" busy={busy} disabled={!agree} onClick={async () => { if (await run(() => post(`/api/guests/${guestId}/loyalty/enrol`, { guest_agreed: true }), "Guest enrolled")) st.reload(); }}>Enrol</Button></>}
  </div> : <>
    <dl className="dl"><dt>Member no.</dt><dd>{d.member_no}</dd><dt>Tier</dt><dd><b>{label(d.tier)}</b>{d.next_tier ? ` · ${d.next_tier.points_needed.toLocaleString()} pts to ${label(d.next_tier.name)}` : ""}</dd>
      <dt>Points</dt><dd><b>{d.points_balance.toLocaleString()}</b> (worth {money(d.redeemable_value, hotel!.currency)})</dd><dt>Lifetime</dt><dd>{d.lifetime_points.toLocaleString()}</dd></dl>
    <Table rows={d.transactions.slice(0, 8)} cols={[{ h: "Date", r: t => fmtDate(t.created_at) }, { h: "Activity", r: t => <span className="small">{t.description}</span> }, { h: "Points", r: t => <span className={t.points < 0 ? "danger" : "pos"}>{t.points > 0 ? "+" : ""}{t.points}</span>, cls: "num" }]} />
  </>}</Loadable></Card>;
}

/** Public post-stay survey: /#/survey/<token> */
export function Survey({ token }: { token: string }) {
  const [info, setInfo] = useState<any>(null);
  const [loadErr, setLoadErr] = useState("");
  const [err, setErr] = useState("");
  const [f, setF] = useState<any>({ overall: 0, cleanliness: 0, service: 0, food: 0, value_for_money: 0, nps: "", comments: "" });
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api("GET", `/api/public/feedback/${token}`, undefined, { auth: false }).then(setInfo).catch(e => setLoadErr(errText(e))); }, [token]);
  const stars = (k: string) => <div className="stars">{[1, 2, 3, 4, 5].map(n => <button key={n} type="button" className={f[k] >= n ? "on" : ""} onClick={() => setF({ ...f, [k]: n })} aria-label={`${n} star`}>★</button>)}</div>;
  if (loadErr) return <div className="portal"><div className="portal-card center"><h2>Survey not found</h2><p>{loadErr}</p></div></div>;
  if (!info) return <Spinner />;
  return <div className="portal"><header className="portal-h"><div><h1>{info.hotel}</h1><p>Tell us about your stay</p></div></header>
    <div className="portal-card">{done || info.submitted ? <div className="center"><h2>Thank you!</h2><p>Your feedback helps us improve.</p></div> : <>
      <p>{info.guest ? `Dear ${info.guest}, ` : ""}thank you for staying with us. This takes about a minute.</p>
      {[["overall", "Overall stay"], ["cleanliness", "Cleanliness"], ["service", "Service & staff"], ["food", "Food & drink"], ["value_for_money", "Value for money"]].map(([k, l]) => <div key={k} className="row between mt"><span>{l}</span>{stars(k)}</div>)}
      <Field label="How likely are you to recommend us to a friend? (0 = not at all, 10 = extremely)"><div className="nps">{Array.from({ length: 11 }, (_, i) => <button key={i} type="button" className={f.nps === i ? "on" : ""} onClick={() => setF({ ...f, nps: i })}>{i}</button>)}</div></Field>
      <Field label="Anything you'd like to tell us?" wide><Textarea rows={4} value={f.comments} onChange={e => setF({ ...f, comments: e.target.value })} /></Field>
      {err && <p className="field-e">{err}</p>}
      <Button kind="gold" busy={busy} disabled={!f.overall} onClick={async () => { setBusy(true); setErr(""); try { const b: any = { overall: f.overall, comments: f.comments || undefined }; for (const k of ["cleanliness", "service", "food", "value_for_money"]) if (f[k]) b[k] = f[k]; if (f.nps !== "") b.nps = f.nps;
        await api("POST", `/api/public/feedback/${token}`, b, { auth: false }); setDone(true); } catch (e) { setErr(errText(e)); } finally { setBusy(false); } }}>Submit</Button></>}</div></div>;
}
