import React, { useEffect, useState } from "react";
import { ApiError, addDays, fmtDate, fmtDateTime, fromMinor, get, label, money, patch, post, toMinor } from "../api";
import { navigate, useAuth } from "../state";
import { Button, Card, Confirm, Empty, Field, Input, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, errText, useAction, useLoad, useToast } from "../ui";

const TABS = [{ id: "arrivals", label: "Arrivals" }, { id: "in_house", label: "In-house" }, { id: "departures", label: "Departures" },
  { id: "upcoming", label: "Upcoming" }, { id: "search", label: "Search" }];

export default function Reservations({ q }: { q: URLSearchParams }) {
  const { hotel, can } = useAuth();
  const [tab, setTab] = useState(q.get("tab") || "arrivals");
  const [search, setSearch] = useState(q.get("q") || "");
  const [term, setTerm] = useState(q.get("q") || "");
  const [audit, setAudit] = useState(false);
  const toast = useToast();
  useEffect(() => { if (q.get("tab")) setTab(q.get("tab")!); if (q.get("q") !== null) { setSearch(q.get("q") || ""); setTerm(q.get("q") || ""); } }, [q.toString()]);
  const params: any = tab === "search" ? { search: term } : tab === "upcoming" ? { status: "confirmed,tentative,waitlisted,enquiry" } : { view: tab };
  const st = useLoad(() => (tab === "search" && !term ? Promise.resolve({ items: [], business_date: "" }) : get(`/api/hotels/${hotel!.id}/reservations`, params)), [hotel?.id, tab, term]);
  const cur = hotel!.currency;
  return (
    <div className="page">
      <div className="page-h"><div><h1>Front desk & reservations</h1><p className="muted">Business date {st.data?.business_date || "…"}</p></div>
        <div className="row gap-s">
          {can("frontdesk.night_audit") && <Button kind="secondary" onClick={() => setAudit(true)}>Run night audit</Button>}
          {can("reservations.create") && <Button onClick={() => navigate("/reservations/new")}>New reservation</Button>}
        </div></div>
      <Tabs tabs={TABS} value={tab} onChange={t => { setTab(t); navigate(`/reservations?tab=${t}`); }} />
      {tab === "search" && <form className="row gap-s mb" onSubmit={e => { e.preventDefault(); setTerm(search); }}>
        <Input placeholder="Name, reference, phone, email, room number or company" value={search} onChange={e => setSearch(e.target.value)} style={{ flex: 1 }} autoFocus />
        <Button type="submit">Search</Button></form>}
      <Card pad={false}><Loadable state={st}>{d => (
        <Table rows={d.items} onRow={r => navigate(`/reservations/${r.id}`)} empty={tab === "search" && !term ? "Enter a search term" : "No reservations"} cols={[
          { h: "Reference", r: r => <b>{r.reference}</b> },
          { h: "Guest", r: r => <>{r.first_name} {r.last_name} {r.vip ? <Pill s="vip_hold" text="VIP" /> : null}<div className="muted small">{r.phone}</div></> },
          { h: "Stay", r: r => <>{fmtDate(r.arrival)} → {fmtDate(r.departure)}</> },
          { h: "Room", r: r => <>{r.room_number || <span className="muted">Unassigned</span>}<div className="muted small">{r.room_type_code}</div></> },
          { h: "Guests", r: r => `${r.adults}A${r.children ? ` ${r.children}C` : ""}` },
          { h: "Source", r: r => label(r.source) },
          { h: "Status", r: r => <Pill s={r.status} /> },
        ]} />)}</Loadable></Card>
      {audit && <Confirm title="Run night audit" confirmText="Run night audit" onClose={() => setAudit(false)}
        text={<p>This posts tonight's room charges to every in-house folio and moves the business date forward by one day. It cannot be undone.</p>}
        onConfirm={async () => {
          try {
            const r = await post(`/api/hotels/${hotel!.id}/night-audit`);
            toast("success", `Night audit complete: ${r.room_charges_posted} room charges posted. Business date is now ${r.new_business_date}.`);
            if (r.arrivals_not_checked_in.length) toast("info", `Arrivals not checked in: ${r.arrivals_not_checked_in.join(", ")} — review for no-show.`);
            setAudit(false); st.reload();
          } catch (e) { toast("error", errText(e)); }
        }} />}
    </div>
  );
}

// ------------------------------------------------------------------ new reservation
export function NewReservation({ q }: { q: URLSearchParams }) {
  const { hotel, can } = useAuth();
  const toast = useToast();
  const [bd, setBd] = useState("");
  const [f, setF] = useState<any>({ arrival: "", departure: "", adults: 1, children: 0, booking_type: q.get("type") || "individual", source: "front_desk",
    room_type_id: "", room_id: "", status: "confirmed", special_requests: "", company_name: "", nightly_rate: "", discount: "", deposit: "", overbook_reason: "", corporate_account_id: "" });
  const accounts = useLoad(() => get(`/api/hotels/${hotel!.id}/accounts/active`).catch(() => ({ items: [] })), [hotel?.id]);
  const [avail, setAvail] = useState<any>(null);
  const [quote, setQuote] = useState<any>(null);
  const [guestMode, setGuestMode] = useState<"search" | "new">("search");
  const [gq, setGq] = useState("");
  const [gres, setGres] = useState<any[]>([]);
  const [guest, setGuest] = useState<any>(null);
  const [ng, setNg] = useState<any>({ first_name: "", last_name: "", email: "", phone: "", nationality: "Nigerian", company: "" });
  const [dups, setDups] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: any) => setF((x: any) => ({ ...x, [k]: v }));

  useEffect(() => {
    get(`/api/hotels/${hotel!.id}`).then(h => { setBd(h.business_date); setF((x: any) => ({ ...x, arrival: h.business_date, departure: addDays(h.business_date, 1) })); });
  }, [hotel?.id]);
  useEffect(() => {
    if (!f.arrival || !f.departure || f.departure <= f.arrival) { setAvail(null); return; }
    get(`/api/hotels/${hotel!.id}/availability`, { arrival: f.arrival, departure: f.departure }).then(setAvail).catch(e => toast("error", errText(e)));
  }, [f.arrival, f.departure]);
  useEffect(() => {
    if (!f.room_type_id || !avail) { setQuote(null); return; }
    const body: any = { arrival: f.arrival, departure: f.departure, room_type_id: Number(f.room_type_id), adults: f.adults, children: f.children, booking_type: f.booking_type };
    if (f.nightly_rate) body.nightly_rate = toMinor(f.nightly_rate);
    if (f.discount) body.discount_amount = toMinor(f.discount);
    if (f.corporate_account_id) body.corporate_account_id = Number(f.corporate_account_id);
    post(`/api/hotels/${hotel!.id}/quote`, body).then(setQuote).catch(e => setQuote({ error: errText(e) }));
  }, [f.room_type_id, f.adults, f.children, f.nightly_rate, f.discount, f.booking_type, f.corporate_account_id, avail]);
  useEffect(() => {
    if (guestMode !== "search" || gq.trim().length < 2) { setGres([]); return; }
    const t = setTimeout(() => get("/api/guests", { search: gq }).then(r => setGres(r.items.slice(0, 8))).catch(() => setGres([])), 250);
    return () => clearTimeout(t);
  }, [gq, guestMode]);

  const selType = avail?.room_types.find((t: any) => String(t.id) === String(f.room_type_id));
  const rooms = (avail?.free_rooms || []).filter((r: any) => String(r.room_type_id) === String(f.room_type_id))
    .sort((a: any, b: any) => Number(b.hk_status === "inspected") - Number(a.hk_status === "inspected"));

  async function submit(force = false) {
    const body: any = { arrival: f.arrival, departure: f.departure, adults: Number(f.adults), children: Number(f.children), booking_type: f.booking_type,
      source: f.source, room_type_id: Number(f.room_type_id), status: f.status, special_requests: f.special_requests || undefined, company_name: f.company_name || undefined };
    if (f.room_id) body.room_id = Number(f.room_id);
    if (f.corporate_account_id) body.corporate_account_id = Number(f.corporate_account_id);
    if (f.nightly_rate) body.nightly_rate = toMinor(f.nightly_rate);
    if (f.discount) body.discount_amount = toMinor(f.discount);
    if (f.deposit) body.deposit_required = toMinor(f.deposit);
    if (f.overbook_reason) body.overbook_reason = f.overbook_reason;
    if (guest) body.guest_id = guest.id;
    else if (guestMode === "new") body.guest = { ...ng, force };
    else { toast("error", "Select a guest or create a new guest profile"); return; }
    if ([body.nightly_rate, body.discount_amount, body.deposit_required].some(v => v !== undefined && Number.isNaN(v))) { toast("error", "Enter amounts as numbers, e.g. 45000 or 45000.50"); return; }
    setBusy(true);
    try {
      const r = await post(`/api/hotels/${hotel!.id}/reservations`, body);
      toast("success", `Reservation ${r.reference} created`);
      (r.warnings || []).forEach((w: string) => toast("info", `Warning: ${label(w)}`));
      navigate(`/reservations/${r.id}`);
    } catch (e) {
      if (e instanceof ApiError && e.details?.duplicates) setDups(e.details.duplicates);
      else toast("error", errText(e));
    } finally { setBusy(false); }
  }

  const walkIn = f.booking_type === "walk_in";
  return (
    <div className="page narrow">
      <div className="page-h"><h1>New reservation</h1><Button kind="secondary" onClick={() => history.back()}>Cancel</Button></div>
      <Card title="1. Stay details"><div className="form-grid">
        <Field label="Arrival"><Input type="date" min={bd} value={f.arrival} onChange={e => { set("arrival", e.target.value); if (f.departure <= e.target.value) set("departure", addDays(e.target.value, 1)); }} /></Field>
        <Field label="Departure"><Input type="date" min={f.arrival ? addDays(f.arrival, 1) : bd} value={f.departure} onChange={e => set("departure", e.target.value)} /></Field>
        <Field label="Adults"><Input type="number" min={1} max={10} value={f.adults} onChange={e => set("adults", Number(e.target.value))} /></Field>
        <Field label="Children"><Input type="number" min={0} max={10} value={f.children} onChange={e => set("children", Number(e.target.value))} /></Field>
        <Field label="Booking type"><Select value={f.booking_type} onChange={e => { set("booking_type", e.target.value); if (e.target.value === "walk_in") set("source", "walk_in"); }}>
          {["individual", "walk_in", "corporate", "group", "travel_agent", "vip", "event"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select></Field>
        <Field label="Source"><Select value={f.source} onChange={e => set("source", e.target.value)}>
          {["front_desk", "walk_in", "phone", "email", "website", "travel_agent", "corporate", "ota", "other"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select></Field>
        <Field label="Status"><Select value={f.status} onChange={e => set("status", e.target.value)}>
          {["confirmed", "tentative", "waitlisted", "enquiry"].map(s => <option key={s} value={s}>{label(s)}</option>)}</Select></Field>
        {["corporate", "travel_agent", "group"].includes(f.booking_type) && (accounts.data?.items || []).length > 0 && <Field label="Account (negotiated rates)">
          <Select value={f.corporate_account_id} onChange={e => set("corporate_account_id", e.target.value)}><option value="">None</option>
            {(accounts.data?.items || []).filter((a: any) => f.booking_type !== "travel_agent" || a.kind === "travel_agent").map((a: any) => <option key={a.id} value={a.id}>{a.name}</option>)}</Select></Field>}
        {(f.booking_type === "corporate" || f.booking_type === "group") && <Field label="Company / group name"><Input value={f.company_name} onChange={e => set("company_name", e.target.value)} /></Field>}
      </div></Card>

      <Card title={`2. Room category${avail ? ` — ${avail.nights} night(s)` : ""}`}>
        {!avail ? <p className="muted">Choose valid dates to see availability.</p> : <div className="typegrid">
          {avail.room_types.map((t: any) => (
            <button key={t.id} type="button" className={`typecard ${String(f.room_type_id) === String(t.id) ? "on" : ""} ${t.available < 1 ? "soldout" : ""}`}
              onClick={() => { set("room_type_id", t.id); set("room_id", ""); }}>
              <b>{t.name}</b><span>{money(t.base_rate, hotel!.currency)} / night</span>
              <span className={t.available < 1 ? "danger" : "muted"}>{t.available < 1 ? "Sold out" : `${t.available} of ${t.total_rooms} available`}</span>
              <span className="muted small">Up to {t.max_occupancy} guests</span>
            </button>))}
        </div>}
        {selType && <div className="form-grid mt">
          <Field label="Assign room (optional)" hint={walkIn ? "Walk-ins need a ready (inspected) room" : "Can be assigned later"}>
            <Select value={f.room_id} onChange={e => set("room_id", e.target.value)}>
              <option value="">— Assign later —</option>
              {rooms.map((r: any) => <option key={r.id} value={r.id}>Room {r.number} · floor {r.floor} · {r.hk_status === "inspected" ? "Ready" : `${label(r.hk_status)} (not ready yet)`}</option>)}
            </Select></Field>
          {can("reservations.override_rate") && <Field label="Override nightly rate (₦)" hint="Leave blank for standard rates"><Input inputMode="decimal" value={f.nightly_rate} onChange={e => set("nightly_rate", e.target.value)} /></Field>}
          {can("reservations.override_rate") && <Field label="Discount on stay (₦)"><Input inputMode="decimal" value={f.discount} onChange={e => set("discount", e.target.value)} /></Field>}
          <Field label="Deposit required (₦)"><Input inputMode="decimal" value={f.deposit} onChange={e => set("deposit", e.target.value)} /></Field>
          {selType.available < 1 && can("reservations.overbook") && <Field label="Overbooking authorisation reason" wide><Input value={f.overbook_reason} onChange={e => set("overbook_reason", e.target.value)} /></Field>}
        </div>}
      </Card>

      <Card title="3. Guest" actions={!guest && <Tabs tabs={[{ id: "search", label: "Existing guest" }, ...(can("guests.manage") ? [{ id: "new", label: "New guest" }] : [])]} value={guestMode} onChange={v => setGuestMode(v as any)} />}>
        {guest ? <div className="row between"><div><b>{guest.first_name} {guest.last_name}</b> <span className="muted">{guest.email} · {guest.phone}</span></div>
          <Button kind="ghost" onClick={() => setGuest(null)}>Change</Button></div>
          : guestMode === "search" ? <>
            <Input placeholder="Type a name, email, phone or company" value={gq} onChange={e => setGq(e.target.value)} />
            <div className="picklist">{gres.map(g => <button key={g.id} type="button" onClick={() => setGuest(g)}>
              <b>{g.first_name} {g.last_name}</b> {g.vip && <Pill s="vip_hold" text="VIP" />}<span className="muted"> {g.email} · {g.phone} · {g.stays} stay(s)</span></button>)}
              {gq.length >= 2 && !gres.length && <p className="muted small">No match. {can("guests.manage") && <a href="#" onClick={e => { e.preventDefault(); setGuestMode("new"); }}>Create a new guest</a>}</p>}</div>
          </> : <div className="form-grid">
            <Field label="First name"><Input value={ng.first_name} onChange={e => setNg({ ...ng, first_name: e.target.value })} /></Field>
            <Field label="Last name"><Input value={ng.last_name} onChange={e => setNg({ ...ng, last_name: e.target.value })} /></Field>
            <Field label="Email"><Input type="email" value={ng.email} onChange={e => setNg({ ...ng, email: e.target.value })} /></Field>
            <Field label="Phone"><Input value={ng.phone} onChange={e => setNg({ ...ng, phone: e.target.value })} /></Field>
            <Field label="Nationality"><Input value={ng.nationality} onChange={e => setNg({ ...ng, nationality: e.target.value })} /></Field>
            <Field label="Company"><Input value={ng.company} onChange={e => setNg({ ...ng, company: e.target.value })} /></Field>
          </div>}
      </Card>

      <Card title="4. Requests & price">
        <Field label="Special requests"><Textarea value={f.special_requests} onChange={e => set("special_requests", e.target.value)} /></Field>
        {quote && (quote.error ? <p className="field-e">{quote.error}</p> : <div className="quote">
          <div><span>Room ({quote.nights.length} night{quote.nights.length > 1 ? "s" : ""})</span><b>{money(quote.room_total, quote.currency)}</b></div>
          {quote.discount > 0 && <div><span>Discount</span><b>−{money(quote.discount, quote.currency)}</b></div>}
          {quote.service_charge > 0 && <div><span>Service charge</span><b>{money(quote.service_charge, quote.currency)}</b></div>}
          <div><span>Taxes ({quote.taxes.map((t: any) => `${t.name} ${t.rate_bp / 100}%`).join(", ") || "none"})</span><b>{money(quote.tax, quote.currency)}</b></div>
          <div className="total"><span>Total</span><b>{money(quote.total, quote.currency)}</b></div>
        </div>)}
        <div className="row end mt"><Button busy={busy} disabled={!f.room_type_id || (!guest && guestMode === "search")} onClick={() => submit(false)}>Create reservation</Button></div>
      </Card>
      {dups && <Modal title="Possible duplicate guest" onClose={() => setDups(null)} footer={<>
        <Button kind="secondary" onClick={() => setDups(null)}>Back</Button><Button onClick={() => { setDups(null); submit(true); }}>Create new profile anyway</Button></>}>
        <p>These existing profiles look similar. Select one to avoid duplicates:</p>
        <div className="picklist">{dups.map(g => <button key={g.id} onClick={() => { setGuest(g); setDups(null); }}><b>{g.first_name} {g.last_name}</b> <span className="muted">{g.email} {g.phone}</span></button>)}</div>
      </Modal>}
    </div>
  );
}

// ------------------------------------------------------------------ reservation detail
export function ReservationDetail({ id }: { id: number }) {
  const { hotel, can } = useAuth();
  const st = useLoad(() => get(`/api/reservations/${id}`), [id]);
  const [modal, setModal] = useState<string | null>(null);
  const toast = useToast();
  const cur = hotel!.currency;
  return (
    <div className="page">
      <Loadable state={st}>{r => {
        const act = async (fn: () => Promise<any>, msg: string) => {
          try { const out = await fn(); toast("success", msg); (out?.warnings || []).forEach((w: string) => toast("info", w)); setModal(null); st.reload(); return out; }
          catch (e) { toast("error", errText(e)); }
        };
        const s = r.status;
        return <>
          <div className="page-h"><div><h1>{r.reference} <Pill s={s} /></h1>
            <p className="muted">{r.guest.first_name} {r.guest.last_name} · {label(r.booking_type)} · via {label(r.source)}</p></div>
            <div className="row gap-s wrap">
              {["tentative", "waitlisted", "enquiry"].includes(s) && can("reservations.modify") && <Button kind="secondary" onClick={() => act(() => post(`/api/reservations/${id}/confirm`), "Reservation confirmed")}>Confirm</Button>}
              {["tentative", "confirmed"].includes(s) && can("reservations.modify") && <Button kind="secondary" onClick={() => setModal("assign")}>{r.room ? "Change room" : "Assign room"}</Button>}
              {["tentative", "confirmed", "waitlisted", "enquiry", "checked_in"].includes(s) && can("reservations.modify") && <Button kind="secondary" onClick={() => setModal("modify")}>Modify</Button>}
              {["tentative", "confirmed"].includes(s) && can("frontdesk.checkin") && <Button kind="gold" onClick={() => setModal("checkin")}>Check in</Button>}
              {s === "checked_in" && can("frontdesk.room_move") && <Button kind="secondary" onClick={() => setModal("move")}>Room move</Button>}
              {s === "checked_in" && can("frontdesk.checkout") && <Button kind="gold" onClick={() => setModal("checkout")}>Check out</Button>}
              {r.folio && can("folio.view") && <Button kind="secondary" onClick={() => navigate(`/folio/${r.folio.id}`)}>Folio</Button>}
              {!r.folio && ["tentative", "confirmed"].includes(s) && can("payments.receive") && <Button kind="secondary" onClick={async () => { const f = await get(`/api/reservations/${id}/folio`).catch(e => toast("error", errText(e))); if (f) navigate(`/folio/${f.id}`); }}>Take deposit</Button>}
              {["tentative", "confirmed"].includes(s) && can("reservations.cancel") && <Button kind="danger" onClick={() => setModal("noshow")}>No-show</Button>}
              {["tentative", "confirmed", "waitlisted", "enquiry"].includes(s) && can("reservations.cancel") && <Button kind="danger" onClick={() => setModal("cancel")}>Cancel</Button>}
            </div></div>
          <div className="grid-3">
            <Card title="Stay"><dl className="dl">
              <dt>Arrival</dt><dd>{fmtDate(r.arrival)}</dd><dt>Departure</dt><dd>{fmtDate(r.departure)}</dd><dt>Nights</dt><dd>{r.nights}</dd>
              <dt>Room</dt><dd>{r.room ? `${r.room.number} (${r.room_type.name})` : <span className="muted">Unassigned — {r.room_type.name}</span>}</dd>
              <dt>Guests</dt><dd>{r.adults} adult(s), {r.children} child(ren)</dd>
              <dt>Rate</dt><dd>{money(r.nightly_rate, cur)} / night {r.rate_overridden ? <Pill s="vip_hold" text="Override" /> : null}</dd>
              {r.discount_amount > 0 && <><dt>Discount</dt><dd>{money(r.discount_amount, cur)}</dd></>}
              {r.deposit_required > 0 && <><dt>Deposit required</dt><dd>{money(r.deposit_required, cur)}</dd></>}
              {r.checked_in_at && <><dt>Checked in</dt><dd>{fmtDateTime(r.checked_in_at)}</dd></>}
              {r.checked_out_at && <><dt>Checked out</dt><dd>{fmtDateTime(r.checked_out_at)}</dd></>}
              {r.cancel_reason && <><dt>Cancellation</dt><dd>{r.cancel_reason}</dd></>}
            </dl></Card>
            <Card title="Guest" actions={can("guests.view") && <a href={`#/guests/${r.guest.id}`}>Profile</a>}><dl className="dl">
              <dt>Name</dt><dd>{r.guest.first_name} {r.guest.last_name} {r.guest.vip ? <Pill s="vip_hold" text="VIP" /> : null}</dd>
              <dt>Phone</dt><dd>{r.guest.phone || "—"}</dd><dt>Email</dt><dd>{r.guest.email || "—"}</dd>
              <dt>Company</dt><dd>{r.company_name || r.guest.company || "—"}</dd><dt>Nationality</dt><dd>{r.guest.nationality || "—"}</dd>
            </dl>{r.special_requests && <p className="note">“{r.special_requests}”</p>}</Card>
            <Card title="Folio">{r.folio ? <dl className="dl">
              <dt>Folio</dt><dd>{r.folio.number} <Pill s={r.folio.status} /></dd><dt>Charges</dt><dd>{money(r.folio.charges + r.folio.adjustments, cur)}</dd>
              <dt>Payments</dt><dd>{money(r.folio.payments, cur)}</dd><dt>Balance</dt><dd><b>{money(r.folio.balance, cur)}</b></dd>
            </dl> : <p className="muted">A folio opens at check-in or when a deposit is taken.</p>}</Card>
          </div>
          <div className="grid-2">
            <Card title="History"><ul className="timeline">{r.history.map((h: any, i: number) => <li key={i}><b>{label(h.action.split(".")[1])}</b> <span className="muted">by {h.user_name || "system / online"} · {fmtDateTime(h.created_at)}</span></li>)}</ul></Card>
            <Card title="Guest communications">{r.notifications.length ? <Table rows={r.notifications} cols={[
              { h: "Channel", r: n => label(n.channel) }, { h: "Subject", r: n => n.subject }, { h: "Status", r: n => <Pill s={n.status} /> }, { h: "When", r: n => fmtDateTime(n.created_at) }]} />
              : <Empty text="No messages sent" />}
              {r.notifications.some((n: any) => n.status === "not_configured") && <p className="small muted">“Not configured” means no email/SMS provider is set up yet, so the message was recorded but not sent.</p>}
            </Card>
          </div>

          {modal === "cancel" && <Confirm title="Cancel reservation" danger confirmText="Cancel reservation" needReason="Reason for cancellation" onClose={() => setModal(null)}
            text={<p>Cancel {r.reference} for {r.guest.first_name} {r.guest.last_name}? Any deposit must be refunded or a cancellation fee posted from the folio.</p>}
            onConfirm={reason => act(() => post(`/api/reservations/${id}/cancel`, { reason }), "Reservation cancelled")} />}
          {modal === "noshow" && <Confirm title="Mark as no-show" danger confirmText="Mark no-show" onClose={() => setModal(null)}
            text={<p>Mark {r.reference} as a no-show? This is only allowed on or after the arrival date.</p>}
            onConfirm={() => act(() => post(`/api/reservations/${id}/no-show`), "Marked as no-show")} />}
          {modal === "assign" && <AssignRoom r={r} onClose={() => setModal(null)} onDone={(room: string) => act(() => Promise.resolve(), `Room ${room} assigned`)} />}
          {modal === "modify" && <Modify r={r} onClose={() => setModal(null)} onSave={(body: any) => act(() => patch(`/api/reservations/${id}`, body), "Reservation updated")} />}
          {modal === "checkin" && <CheckIn r={r} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
          {modal === "move" && <RoomMove r={r} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
          {modal === "checkout" && <CheckOut r={r} onClose={() => setModal(null)} onDone={() => { setModal(null); st.reload(); }} />}
        </>;
      }}</Loadable>
    </div>
  );
}

function useFreeRooms(r: any, from: string, allTypes = false) {
  const { hotel } = useAuth();
  return useLoad(() => get(`/api/hotels/${hotel!.id}/availability`, { arrival: from, departure: r.departure, exclude_reservation_id: r.id, ...(allTypes ? {} : { room_type_id: r.room_type_id }) }), [r.id, from, allTypes]);
}

function AssignRoom({ r, onClose, onDone }: any) {
  const { can } = useAuth();
  const [all, setAll] = useState(false);
  const fr = useFreeRooms(r, r.arrival, all);
  const [room, setRoom] = useState("");
  const { busy, run } = useAction();
  return <Modal title="Assign room" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} disabled={!room} onClick={async () => { const out = await run(() => post(`/api/reservations/${r.id}/assign-room`, { room_id: Number(room) })); if (out) onDone(out.room?.number); }}>Assign</Button></>}>
    <Loadable state={fr}>{d => <div className="stack">
      {can("reservations.override_rate") && <label className="check"><input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} /> Show other categories (upgrade / change)</label>}
      <Select value={room} onChange={e => setRoom(e.target.value)}><option value="">Select a room…</option>
        {d.free_rooms.map((x: any) => <option key={x.id} value={x.id}>Room {x.number} · {x.room_type_code} · floor {x.floor} · {label(x.hk_status)}</option>)}</Select>
      {!d.free_rooms.length && <p className="muted">No free rooms for these dates.</p>}
    </div>}</Loadable></Modal>;
}

function Modify({ r, onClose, onSave }: any) {
  const { hotel, can } = useAuth();
  const inHouse = r.status === "checked_in";
  const [f, setF] = useState<any>({ arrival: r.arrival, departure: r.departure, adults: r.adults, children: r.children, room_type_id: r.room_type_id,
    special_requests: r.special_requests || "", nightly_rate: r.rate_overridden ? fromMinor(r.nightly_rate) : "", discount: fromMinor(r.discount_amount) });
  const types = useLoad(() => get(`/api/hotels/${hotel!.id}/room-types`), [hotel?.id]);
  const [busy, setBusy] = useState(false);
  return <Modal title={`Modify ${r.reference}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} onClick={async () => {
      setBusy(true);
      const body: any = inHouse ? { departure: f.departure, adults: Number(f.adults), children: Number(f.children), special_requests: f.special_requests }
        : { arrival: f.arrival, departure: f.departure, adults: Number(f.adults), children: Number(f.children), room_type_id: Number(f.room_type_id), special_requests: f.special_requests };
      if (!inHouse && can("reservations.override_rate")) { body.nightly_rate = f.nightly_rate ? toMinor(f.nightly_rate) : null; body.discount_amount = f.discount ? toMinor(f.discount) : 0; }
      await onSave(body); setBusy(false);
    }}>Save changes</Button></>}>
    <div className="form-grid">
      {!inHouse && <Field label="Arrival"><Input type="date" value={f.arrival} onChange={e => setF({ ...f, arrival: e.target.value })} /></Field>}
      <Field label={inHouse ? "Extend / shorten departure" : "Departure"}><Input type="date" value={f.departure} onChange={e => setF({ ...f, departure: e.target.value })} /></Field>
      <Field label="Adults"><Input type="number" min={1} value={f.adults} onChange={e => setF({ ...f, adults: e.target.value })} /></Field>
      <Field label="Children"><Input type="number" min={0} value={f.children} onChange={e => setF({ ...f, children: e.target.value })} /></Field>
      {!inHouse && <Field label="Room category"><Select value={f.room_type_id} onChange={e => setF({ ...f, room_type_id: e.target.value })}>
        {(types.data?.items || []).map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}</Select></Field>}
      {!inHouse && can("reservations.override_rate") && <Field label="Override nightly rate (₦)" hint="Blank = standard rate"><Input value={f.nightly_rate} onChange={e => setF({ ...f, nightly_rate: e.target.value })} /></Field>}
      {!inHouse && can("reservations.override_rate") && <Field label="Discount (₦)"><Input value={f.discount} onChange={e => setF({ ...f, discount: e.target.value })} /></Field>}
      <Field label="Special requests" wide><Textarea value={f.special_requests} onChange={e => setF({ ...f, special_requests: e.target.value })} /></Field>
    </div></Modal>;
}

function CheckIn({ r, onClose, onDone }: any) {
  const { hotel, can } = useAuth();
  const [bd, setBd] = useState(r.arrival);
  useEffect(() => { get(`/api/hotels/${hotel!.id}`).then(h => setBd(h.business_date)); }, []);
  const fr = useFreeRooms(r, bd < r.arrival ? r.arrival : bd);
  const [room, setRoom] = useState(r.room ? String(r.room.id) : "");
  const [idf, setIdf] = useState({ id_type: "", id_number: "" });
  const { busy, run } = useAction();
  const toast = useToast();
  const options = [...(r.room ? [{ ...r.room, room_type_code: r.room_type.code, current: true }] : []), ...((fr.data?.free_rooms || []).filter((x: any) => !r.room || x.id !== r.room.id))];
  const chosen = options.find((o: any) => String(o.id) === room);
  return <Modal title={`Check in ${r.guest.first_name} ${r.guest.last_name}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button kind="gold" busy={busy} disabled={!room} onClick={async () => {
      const body: any = { room_id: Number(room) };
      if (can("guests.identity.view") && idf.id_number) Object.assign(body, idf);
      const out = await run(() => post(`/api/reservations/${r.id}/check-in`, body), "Guest checked in");
      if (out) { (out.warnings || []).forEach((w: string) => toast("info", w)); onDone(); }
    }}>Check in</Button></>}>
    <div className="stack">
      <Field label="Room" hint="Only clean, inspected rooms can be used"><Select value={room} onChange={e => setRoom(e.target.value)}><option value="">Select…</option>
        {options.map((x: any) => <option key={x.id} value={x.id}>Room {x.number} · {x.room_type_code} · {label(x.hk_status)}{x.current ? " (assigned)" : ""}</option>)}</Select></Field>
      {chosen && chosen.hk_status !== "inspected" && <p className="field-e">This room is not inspected yet and cannot be used until housekeeping approves it.</p>}
      {can("guests.identity.view") && <div className="form-grid">
        <Field label="ID type"><Select value={idf.id_type} onChange={e => setIdf({ ...idf, id_type: e.target.value })}><option value="">—</option>
          {["National ID (NIN)", "International passport", "Driver's licence", "Voter's card"].map(t => <option key={t}>{t}</option>)}</Select></Field>
        <Field label="ID number" hint="Captured only where required by law"><Input value={idf.id_number} onChange={e => setIdf({ ...idf, id_number: e.target.value })} /></Field>
      </div>}
    </div></Modal>;
}

function RoomMove({ r, onClose, onDone }: any) {
  const { hotel, can } = useAuth();
  const [bd, setBd] = useState("");
  useEffect(() => { get(`/api/hotels/${hotel!.id}`).then(h => setBd(h.business_date)); }, []);
  const [all, setAll] = useState(false);
  const fr = useLoad(() => (bd ? get(`/api/hotels/${hotel!.id}/availability`, { arrival: bd, departure: r.departure, exclude_reservation_id: r.id, ...(all ? {} : { room_type_id: r.room_type_id }) }) : Promise.resolve(null)), [bd, all]);
  const [room, setRoom] = useState("");
  const [reason, setReason] = useState("");
  const { busy, run } = useAction();
  return <Modal title="Move guest to another room" onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} disabled={!room || !reason.trim()} onClick={async () => { if (await run(() => post(`/api/reservations/${r.id}/room-move`, { room_id: Number(room), reason }), "Guest moved")) onDone(); }}>Move guest</Button></>}>
    <div className="stack">
      {can("reservations.override_rate") && <label className="check"><input type="checkbox" checked={all} onChange={e => setAll(e.target.checked)} /> Allow other categories (complimentary upgrade keeps the current rate)</label>}
      <Select value={room} onChange={e => setRoom(e.target.value)}><option value="">Select a ready room…</option>
        {(fr.data?.free_rooms || []).filter((x: any) => x.hk_status === "inspected" && x.id !== r.room?.id).map((x: any) => <option key={x.id} value={x.id}>Room {x.number} · {x.room_type_code} · floor {x.floor}</option>)}</Select>
      <Field label="Reason"><Input value={reason} onChange={e => setReason(e.target.value)} /></Field>
    </div></Modal>;
}

function CheckOut({ r, onClose, onDone }: any) {
  const { hotel } = useAuth();
  const pv = useLoad(() => get(`/api/reservations/${r.id}/checkout-preview`), [r.id]);
  const { busy, run } = useAction();
  return <Modal title={`Check out ${r.guest.first_name} ${r.guest.last_name}`} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    {pv.data && pv.data.balance_due !== 0 && <Button kind="secondary" onClick={() => navigate(`/folio/${r.folio.id}?settle=1`)}>Go to folio to settle</Button>}
    <Button kind="gold" busy={busy} disabled={!pv.data || pv.data.balance_due !== 0} onClick={async () => { if (await run(() => post(`/api/reservations/${r.id}/check-out`, {}), "Guest checked out — room sent to housekeeping")) onDone(); }}>Complete check-out</Button></>}>
    <Loadable state={pv}>{d => <div className="stack">
      {d.early_departure && <p className="note">Early departure: only nights actually used will be charged.</p>}
      <div className="quote">
        <div><span>Current folio balance</span><b>{money(d.current_balance, hotel!.currency)}</b></div>
        <div><span>Room nights still to post ({d.pending_room_nights.length})</span><b>{money(d.pending_total, hotel!.currency)}</b></div>
        <div className="total"><span>Balance due at check-out</span><b>{money(d.balance_due, hotel!.currency)}</b></div>
      </div>
      {d.balance_due > 0 && <p className="muted">Collect {money(d.balance_due, hotel!.currency)} on the folio, then complete check-out.</p>}
      {d.balance_due < 0 && <p className="muted">The guest is in credit by {money(-d.balance_due, hotel!.currency)}. Request a refund on the folio first.</p>}
    </div>}</Loadable></Modal>;
}
