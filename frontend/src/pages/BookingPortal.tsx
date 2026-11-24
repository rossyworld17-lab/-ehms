import React, { useEffect, useState } from "react";
import { api, addDays, fmtDate, money } from "../api";
import { Button, Field, Input, Spinner, Textarea, errText } from "../ui";
import { LangSelect, useT } from "../i18n";

/** Public, mobile-friendly booking engine: #/book/<HOTEL_CODE> */
export default function BookingPortal({ code }: { code: string }) {
  const { t } = useT();
  const [viewer, setViewer] = useState<{ media: any[]; i: number } | null>(null);
  const [hotel, setHotel] = useState<any>(null);
  const [err, setErr] = useState("");
  const today = new Date().toISOString().slice(0, 10);
  const [s, setS] = useState({ arrival: addDays(today, 1), departure: addDays(today, 2), adults: 2, children: 0, promo_code: "", referral_code: "" });
  const [payOnline, setPayOnline] = useState(false);
  const [opts, setOpts] = useState<any>(null);
  const [choice, setChoice] = useState<any>(null);
  const [g, setG] = useState({ first_name: "", last_name: "", email: "", phone: "", special_requests: "", accept_terms: false, marketing_consent: false });
  const [done, setDone] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [manage, setManage] = useState({ open: false, reference: "", email: "", result: null as any });
  const pub = (m: string, p: string, b?: any) => api(m, p, b, { auth: false });

  useEffect(() => { pub("GET", `/api/public/hotels/${code}`).then(setHotel).catch(e => setErr(errText(e))); }, [code]);
  async function search(e?: React.FormEvent) {
    e?.preventDefault(); setBusy(true); setErr(""); setChoice(null);
    try { setOpts(await pub("GET", `/api/public/hotels/${code}/availability?arrival=${s.arrival}&departure=${s.departure}&adults=${s.adults}&children=${s.children}&promo_code=${encodeURIComponent(s.promo_code.trim())}`)); }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  async function book(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      const promo = choice.promo_error ? "" : s.promo_code.trim();
      const r = await pub("POST", `/api/public/hotels/${code}/bookings`, { ...s, promo_code: promo || undefined, referral_code: s.referral_code.trim() || undefined, ...g, room_type_id: choice.room_type_id, payment_option: payOnline ? "pay_online" : "pay_at_hotel" });
      if (r.authorization_url) { window.location.href = r.authorization_url; return; }
      setDone(r);
    }
    catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  }
  if (!hotel) return err ? <div className="empty"><h2>Hotel not found</h2><p>{err}</p></div> : <Spinner />;
  const cur = hotel.currency;
  return <div className="portal">
    <header className="portal-h"><div className="row gap-s">{hotel.logo_url && <img src={hotel.logo_url} alt="" className="portal-logo" />}<div><h1>{hotel.name}</h1><p>{[hotel.address, hotel.city].filter(Boolean).join(", ")} {hotel.star_rating ? "· " + "★".repeat(hotel.star_rating) : ""}</p></div></div>
      <div className="row gap-s"><LangSelect className="input lang-sel light" /><button className="btn btn-ghost light" onClick={() => setManage({ ...manage, open: !manage.open })}>{t("Find my booking")}</button></div></header>
    {manage.open && <form className="portal-card" onSubmit={async e => { e.preventDefault(); try { setManage({ ...manage, result: await pub("GET", `/api/public/bookings/${manage.reference.trim()}?email=${encodeURIComponent(manage.email)}`) }); } catch (er) { setManage({ ...manage, result: { error: errText(er) } }); } }}>
      <div className="form-grid"><Field label={t("Booking reference")}><Input value={manage.reference} onChange={e => setManage({ ...manage, reference: e.target.value })} required /></Field>
        <Field label="Email used for booking"><Input type="email" value={manage.email} onChange={e => setManage({ ...manage, email: e.target.value })} required /></Field></div>
      <Button type="submit">{t("Find my booking")}</Button>
      {manage.result && (manage.result.error ? <p className="field-e">{manage.result.error}</p> : <div className="mt"><p><b>{manage.result.reference}</b> · {manage.result.room_type} · {fmtDate(manage.result.arrival)} → {fmtDate(manage.result.departure)} · <b>{manage.result.status}</b></p>
        <a className="btn btn-secondary" href={`/api/public/bookings/${manage.result.reference}/confirmation.pdf?email=${encodeURIComponent(manage.email)}`} target="_blank" rel="noopener noreferrer">{t("Download confirmation")}</a>{" "}
        {["tentative", "confirmed"].includes(manage.result.status) && <Button kind="danger" onClick={async () => { try { const r = await pub("POST", `/api/public/bookings/${manage.result.reference}/cancel`, { email: manage.email }); setManage({ ...manage, result: { ...manage.result, status: r.status } }); } catch (er) { setErr(errText(er)); } }}>{t("Cancel booking")}</Button>}</div>)}
    </form>}
    {done ? <div className="portal-card center"><h2>Thank you!</h2><p>Your booking request <b>{done.reference}</b> has been received.</p>
      <p>Estimated total {money(done.total, done.currency)} — payable at the hotel.</p><p className="muted">{done.message} A confirmation will be sent to {g.email}.</p>
      <a className="btn btn-gold" href={`/api/public/bookings/${done.reference}/confirmation.pdf?email=${encodeURIComponent(g.email)}`} target="_blank" rel="noopener noreferrer">{t("Download confirmation")}</a></div> : <>
      <form className="portal-search" onSubmit={search}>
        <Field label={t("Arrival")}><Input type="date" min={today} value={s.arrival} onChange={e => setS({ ...s, arrival: e.target.value, departure: e.target.value >= s.departure ? addDays(e.target.value, 1) : s.departure })} /></Field>
        <Field label={t("Departure")}><Input type="date" min={addDays(s.arrival, 1)} value={s.departure} onChange={e => setS({ ...s, departure: e.target.value })} /></Field>
        <Field label={t("Adults")}><Input type="number" min={1} max={8} value={s.adults} onChange={e => setS({ ...s, adults: Number(e.target.value) })} /></Field>
        <Field label={t("Children")}><Input type="number" min={0} max={6} value={s.children} onChange={e => setS({ ...s, children: Number(e.target.value) })} /></Field>
        <Field label={t("Promo code")}><Input value={s.promo_code} onChange={e => setS({ ...s, promo_code: e.target.value })} placeholder="Optional" /></Field>
        <Field label={t("Referral code")}><Input value={s.referral_code} onChange={e => setS({ ...s, referral_code: e.target.value.toUpperCase() })} placeholder="REF-…" /></Field>
        <Button type="submit" kind="gold" busy={busy} className="self-end">{t("Check availability")}</Button>
      </form>
      {err && <p className="field-e portal-err">{err}</p>}
      {opts && !choice && <div className="portal-list">{opts.options.length ? opts.options.map((o: any) => (
        <div key={o.room_type_id} className="portal-room">
          {(() => { const media = (hotel.room_types.find((r: any) => r.id === o.room_type_id)?.media || []) as any[]; const photos = media.filter(m => m.kind === "photo");
            const cover = photos[0]?.url || o.image_url; const video = media.find(m => m.kind === "video");
            return <div className="portal-img" style={cover ? { backgroundImage: `url(${cover})` } : undefined} role={photos.length ? "button" : undefined}
              tabIndex={photos.length ? 0 : undefined} aria-label={photos.length ? `${o.name}: ${photos.length} photo(s)` : undefined}
              onClick={() => photos.length && setViewer({ media: photos, i: 0 })} onKeyDown={e => { if (e.key === "Enter" && photos.length) setViewer({ media: photos, i: 0 }); }}>
              {!cover && <span>{o.code}</span>}{photos.length > 1 && <em className="img-count">{photos.length} 📷</em>}
              {video && <a className="img-video" href={video.url} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()}>▶ {t("Watch video")}</a>}</div>; })()}
          <div className="portal-info"><h3>{o.name}</h3><p>{o.description}</p><p className="small muted">{o.amenities} · up to {o.max_occupancy} guests</p>
            {o.rooms_left && <p className="danger small">Only {o.rooms_left} left</p>}
            {o.price.discount > 0 && <p className="pos small">Promo code applied: −{money(o.price.discount, cur)}</p>}
            {o.promo_error && <p className="danger small">{o.promo_error}</p>}</div>
          <div className="portal-price"><b>{money(o.price.total, cur)}</b><span className="small muted">{opts.nights} night(s), incl. taxes & service charge</span>
            <Button kind="gold" onClick={() => setChoice(o)}>{t("Select")}</Button></div>
        </div>)) : <div className="portal-card"><p>{t("No rooms are available for these dates.")} Please try different dates or contact us on {hotel.phone}.</p></div>}</div>}
      {choice && <form className="portal-card" onSubmit={book}>
        <h3>{choice.name} · {fmtDate(s.arrival)} → {fmtDate(s.departure)}</h3>
        <div className="quote">
          <div><span>Room</span><b>{money(choice.price.room_total, cur)}</b></div>
          {choice.price.discount > 0 && <div><span>Promo discount</span><b>−{money(choice.price.discount, cur)}</b></div>}
          {choice.price.service_charge > 0 && <div><span>Service charge</span><b>{money(choice.price.service_charge, cur)}</b></div>}
          <div><span>Taxes</span><b>{money(choice.price.tax, cur)}</b></div><div className="total"><span>Total {payOnline ? "(pay now)" : "(pay at hotel)"}</span><b>{money(choice.price.total, cur)}</b></div></div>
        <div className="form-grid">
          <Field label={t("First name")}><Input value={g.first_name} onChange={e => setG({ ...g, first_name: e.target.value })} required /></Field>
          <Field label={t("Last name")}><Input value={g.last_name} onChange={e => setG({ ...g, last_name: e.target.value })} required /></Field>
          <Field label={t("Email")}><Input type="email" value={g.email} onChange={e => setG({ ...g, email: e.target.value })} required /></Field>
          <Field label={t("Phone")}><Input value={g.phone} onChange={e => setG({ ...g, phone: e.target.value })} required /></Field>
          <Field label={t("Special requests")} wide><Textarea value={g.special_requests} onChange={e => setG({ ...g, special_requests: e.target.value })} /></Field>
        </div>
        {hotel.cancellation_policy && <p className="small"><b>{t("Cancellation policy")}:</b> {hotel.cancellation_policy}</p>}
        <label className="check"><input type="checkbox" checked={g.accept_terms} onChange={e => setG({ ...g, accept_terms: e.target.checked })} /> I accept the booking terms and agree that my details are used to manage this booking, in line with the <a href="/privacy" target="_blank" rel="noopener">privacy notice</a>.</label>
        <label className="check"><input type="checkbox" checked={g.marketing_consent} onChange={e => setG({ ...g, marketing_consent: e.target.checked })} /> Send me offers by email (optional)</label>
        {hotel.online_payment_available ? <div className="row gap wrap">
          <label className="check"><input type="radio" name="pay" checked={!payOnline} onChange={() => setPayOnline(false)} /> {t("Pay at the hotel")}</label>
          <label className="check"><input type="radio" name="pay" checked={payOnline} onChange={() => setPayOnline(true)} /> Pay now online (card / bank transfer) — confirms instantly</label>
        </div> : <p className="small muted">Online payment is not yet available — you will pay at the hotel.</p>}
        <div className="row gap-s"><Button kind="secondary" type="button" onClick={() => setChoice(null)}>Back</Button><Button kind="gold" type="submit" busy={busy} disabled={!g.accept_terms}>{payOnline ? "Continue to secure payment" : "Request booking"}</Button></div>
      </form>}
    </>}
    {viewer && <div className="lightbox" role="dialog" aria-label="Photos" onClick={() => setViewer(null)} onKeyDown={e => { if (e.key === "Escape") setViewer(null); }}>
      <img src={viewer.media[viewer.i].url} alt={viewer.media[viewer.i].caption || ""} onClick={e => { e.stopPropagation(); setViewer({ ...viewer, i: (viewer.i + 1) % viewer.media.length }); }} />
      <p>{viewer.media[viewer.i].caption} · {viewer.i + 1}/{viewer.media.length}</p><button className="btn btn-ghost light" autoFocus onClick={() => setViewer(null)}>{t("Close")}</button></div>}
    <footer className="portal-f">{t("Check-in from")} {hotel.check_in_time} · {t("Check-out by")} {hotel.check_out_time} · {hotel.phone} · {hotel.email}</footer>
  </div>;
}

/** Page the payment provider returns the guest to: /payment-return?reference=… (Paystack) or ?tx_ref=… (Flutterwave). */
export function PaymentReturn() {
  const p = new URLSearchParams(window.location.search);
  const ref = p.get("reference") || p.get("trxref") || p.get("tx_ref") || "";
  const [r, setR] = useState<any>(null);
  const [err, setErr] = useState("");
  const check = () => api("GET", `/api/public/payments/${encodeURIComponent(ref)}`, undefined, { auth: false }).then(setR).catch(e => setErr(errText(e)));
  useEffect(() => { if (ref) check(); else setErr("No payment reference was supplied."); }, [ref]);
  return <div className="portal"><div className="portal-card center">
    {err ? <><h2>We could not check this payment</h2><p>{err}</p></> : !r ? <Spinner text="Confirming your payment with the provider…" /> :
      r.status === "success" ? <><h2>Payment received — thank you!</h2><p>{money(r.amount, r.currency)} was received{r.booking ? <> for booking <b>{r.booking.reference}</b> at {r.booking.hotel_name}, which is now <b>{r.booking.status}</b></> : ""}.</p>
        {r.booking && <a className="btn btn-gold" href={`/#/book/${r.booking.hotel_code}`}>Back to the hotel</a>}</> :
      r.status === "pending" ? <><h2>Payment not completed yet</h2><p>The provider has not confirmed this payment. If you completed it, wait a moment and check again.</p><Button onClick={check}>Check again</Button></> :
      <><h2>Payment not successful</h2><p>No money was taken for reference {ref}{r.status === "amount_mismatch" ? " (the amount did not match; the hotel will contact you)" : ""}. Your booking, if any, is held as pay at hotel.</p></>}
  </div></div>;
}
