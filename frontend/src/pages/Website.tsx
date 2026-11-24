// Public hotel website (release 1.3) — served at the main address. Content is edited in EHMS under
// Administration → Website; rooms, prices and contact details come from the live hotel record.
import React, { useEffect, useState } from "react";
import { api, money } from "../api";
import { LangSelect, useT } from "../i18n";
import { errText } from "../ui";

type Site = any;

export default function Website() {
  const [data, setData] = useState<Site | null>(null);
  const [err, setErr] = useState("");
  const hotel = new URLSearchParams(location.search).get("hotel");
  useEffect(() => {
    api("GET", `/api/public/site${hotel ? `?hotel=${encodeURIComponent(hotel)}` : ""}`, undefined, { auth: false }).then(setData).catch(e => setErr(errText(e)));
  }, [hotel]);
  if (err) return <div className="site-empty"><h1>Website unavailable</h1><p>{err}</p><a href="/staff">Staff login</a></div>;
  if (!data) return <div className="site-empty" aria-busy="true"><p>Loading…</p></div>;
  return <WebsiteView data={data} />;
}

export function WebsiteView({ data, preview }: { data: Site; preview?: boolean }) {
  const { t, lang } = useT();
  const c = data.content;
  const h = data.hotel;
  const tx = (k: string) => (c.text[lang]?.[k] || c.text.en?.[k] || "") as string;
  const list = (k: string) => ((c.text[lang]?.[k]?.length ? c.text[lang][k] : c.text.en?.[k]) || []) as any[];
  const on = (s: string) => c.sections[s] !== false;
  const [menu, setMenu] = useState(false);
  const [viewer, setViewer] = useState<{ items: any[]; i: number } | null>(null);
  useEffect(() => { if (!preview) document.title = tx("seo_title") || h.name; }, [lang, preview]);
  const nav = [["about", "About"], ["rooms", "Rooms"], ["dining", "Dining"], ["events", "Events"], ["gallery", "Gallery"], ["location", "Location"], ["contact", "Contact"]]
    .filter(([s]) => on(s) && (s !== "gallery" || data.gallery.length));
  const go = (id: string) => (e: React.MouseEvent) => { e.preventDefault(); setMenu(false); document.getElementById(`site-${id}`)?.scrollIntoView({ behavior: "smooth" }); };
  const book = preview ? undefined : data.booking_url;
  const para = (s: string) => s.split(/\n{2,}/).map((p, i) => <p key={i}>{p.split("\n").map((l, j) => <React.Fragment key={j}>{j > 0 && <br />}{l}</React.Fragment>)}</p>);
  const addr = [h.address, h.city, h.state, h.country].filter(Boolean).join(", ");
  const mapHref = c.map_url || (addr ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${h.name}, ${addr}`)}` : "");
  const social = Object.entries(c.social || {}).filter(([, v]) => v) as [string, string][];
  return (
    <div className="site" lang={lang}>
      {tx("announcement") && <div className="site-announce">{tx("announcement")}</div>}
      <header className="site-h">
        <a className="site-brand" href="#top" onClick={go("top")}>{h.logo_url ? <img src={h.logo_url} alt="" /> : <span className="logo">{h.name[0]}</span>}
          <span>{h.name}{h.star_rating ? <small>{"★".repeat(h.star_rating)}</small> : null}</span></a>
        <nav className={`site-nav ${menu ? "open" : ""}`} aria-label="Website">
          {nav.map(([id, l]) => <a key={id} href={`#${id}`} onClick={go(id)}>{t(l)}</a>)}
        </nav>
        <div className="site-actions">
          <LangSelect className="input lang-sel" />
          <a className="btn btn-gold" href={book} aria-disabled={!book}>{t("Book now")}</a>
          <button className="site-burger" aria-label={t("Menu")} aria-expanded={menu} onClick={() => setMenu(m => !m)}>☰</button>
        </div>
      </header>

      <section id="site-top" className="site-hero" style={data.image_urls.hero ? { backgroundImage: `linear-gradient(rgba(15,31,61,.55), rgba(15,31,61,.65)), url(${data.image_urls.hero})` } : undefined}>
        <div className="site-hero-in">
          <h1>{tx("hero_title")}</h1>
          {tx("hero_subtitle") && <p>{tx("hero_subtitle")}</p>}
          <div className="row gap-s wrap center-x"><a className="btn btn-gold big" href={book}>{t("Check availability")}</a>
            {on("contact") && <a className="btn btn-ghost light big" href="#contact" onClick={go("contact")}>{t("Contact us")}</a>}</div>
        </div>
      </section>

      {on("highlights") && list("highlights").length > 0 && <section className="site-strip"><div className="site-w site-highlights">
        {list("highlights").map((x: any, i: number) => <div key={i}><b>{x.title}</b><span>{x.text}</span></div>)}</div></section>}

      {on("about") && <section id="site-about" className="site-sec"><div className={`site-w ${data.image_urls.about ? "site-split" : "site-narrow"}`}>
        <div><h2>{tx("about_title")}</h2>{para(tx("about_body"))}</div>
        {data.image_urls.about && <img className="site-img" src={data.image_urls.about} alt="" />}</div></section>}

      {on("rooms") && data.rooms.length > 0 && <section id="site-rooms" className="site-sec alt"><div className="site-w">
        <h2>{tx("rooms_title")}</h2>{tx("rooms_intro") && <p className="site-lead">{tx("rooms_intro")}</p>}
        <div className="site-rooms">{data.rooms.map((r: any) => {
          const photos = (r.media || []).filter((m: any) => m.kind === "photo");
          const cover = photos[0]?.url || r.image_url;
          return <article key={r.id} className="site-room">
            <div className="site-room-img" style={cover ? { backgroundImage: `url(${cover})` } : undefined} role={photos.length ? "button" : undefined} tabIndex={photos.length ? 0 : undefined}
              onClick={() => photos.length && setViewer({ items: photos, i: 0 })} onKeyDown={e => { if (e.key === "Enter" && photos.length) setViewer({ items: photos, i: 0 }); }}
              aria-label={photos.length ? `${r.name}: ${photos.length} photo(s)` : undefined}>{!cover && <span>{r.code}</span>}</div>
            <div className="site-room-b"><h3>{r.name}</h3>{r.description && <p>{r.description}</p>}
              <p className="small muted">{[r.bed_config, r.size_sqm ? `${r.size_sqm} m²` : "", `${t("up to")} ${r.max_occupancy} ${t("guests")}`].filter(Boolean).join(" · ")}</p>
              {r.amenities && <p className="small">{r.amenities}</p>}
              <div className="row between"><span>{t("from")} <b>{money(r.from_rate, h.currency)}</b> <span className="small muted">{t("per night")}</span></span>
                <a className="btn btn-secondary" href={book}>{t("Book now")}</a></div></div>
          </article>;
        })}</div></div></section>}

      {on("dining") && <section id="site-dining" className="site-sec"><div className={`site-w ${data.image_urls.dining ? "site-split rev" : "site-narrow"}`}>
        {data.image_urls.dining && <img className="site-img" src={data.image_urls.dining} alt="" />}
        <div><h2>{tx("dining_title")}</h2>{para(tx("dining_body"))}{tx("dining_hours") && <p className="site-hours">{tx("dining_hours")}</p>}</div></div></section>}

      {on("events") && <section id="site-events" className="site-sec alt"><div className={`site-w ${data.image_urls.events ? "site-split" : "site-narrow"}`}>
        <div><h2>{tx("events_title")}</h2>{para(tx("events_body"))}
          {on("contact") && <a className="btn btn-primary" href="#contact" onClick={e => { go("contact")(e); setTimeout(() => (document.getElementById("enq-kind") as HTMLSelectElement | null)?.focus(), 400); }}>{t("Send an event enquiry")}</a>}</div>
        {data.image_urls.events && <img className="site-img" src={data.image_urls.events} alt="" />}</div></section>}

      {on("facilities") && list("facilities").length > 0 && <section className="site-sec"><div className="site-w"><h2>{tx("facilities_title")}</h2>
        <ul className="site-fac">{list("facilities").map((f: string, i: number) => <li key={i}>{f}</li>)}</ul></div></section>}

      {on("gallery") && data.gallery.length > 0 && <section id="site-gallery" className="site-sec alt"><div className="site-w"><h2>{tx("gallery_title")}</h2>
        <div className="site-gallery">{data.gallery.map((g: any, i: number) => <button key={g.id} onClick={() => setViewer({ items: data.gallery, i })} aria-label={g.caption || `Photo ${i + 1}`}>
          <img src={g.url} alt={g.caption || ""} loading="lazy" /></button>)}</div></div></section>}

      {on("location") && <section id="site-location" className="site-sec"><div className="site-w site-split">
        <div><h2>{tx("location_title")}</h2>{addr && <p><b>{addr}</b></p>}{tx("directions") && para(tx("directions"))}
          <p className="small muted">{t("Check-in from")} {h.check_in_time} · {t("Check-out by")} {h.check_out_time}</p>
          {mapHref && <a className="btn btn-secondary" href={mapHref} target="_blank" rel="noopener noreferrer">{t("Open in Google Maps")}</a>}</div>
        <div className="site-mapcard"><b>{h.name}</b><span>{addr}</span>{h.phone && <a href={`tel:${h.phone.replace(/\s/g, "")}`}>{h.phone}</a>}</div></div></section>}

      {on("contact") && <section id="site-contact" className="site-sec alt"><div className="site-w site-split">
        <div><h2>{tx("contact_title")}</h2>{tx("contact_intro") && <p>{tx("contact_intro")}</p>}
          <ul className="site-contact">{h.phone && <li>☎ <a href={`tel:${h.phone.replace(/\s/g, "")}`}>{h.phone}</a></li>}{h.email && <li>✉ <a href={`mailto:${h.email}`}>{h.email}</a></li>}
            {c.social?.whatsapp && <li>💬 <a href={`https://wa.me/${c.social.whatsapp.replace(/[^0-9]/g, "")}`} target="_blank" rel="noopener noreferrer">WhatsApp</a></li>}
            {tx("contact_hours") && <li>🕑 {tx("contact_hours")}</li>}</ul></div>
        <EnquiryForm hotel={h.code} disabled={preview} /></div></section>}

      <footer className="site-f"><div className="site-w site-f-in">
        <div><b>{h.name}</b><p className="small">{addr}</p>{tx("footer_note") && <p className="small">{tx("footer_note")}</p>}</div>
        <div className="site-f-links">{social.filter(([k]) => k !== "whatsapp").map(([k, v]) => <a key={k} href={v} target="_blank" rel="noopener noreferrer">{k === "x" ? "X" : k.charAt(0).toUpperCase() + k.slice(1)}</a>)}</div>
        <div className="site-f-links">
          {data.other_hotels?.map((o: any) => <a key={o.code} href={`/?hotel=${o.code}`}>{o.name}</a>)}
          <a href={book}>{t("Book now")}</a><a href={book}>{t("Find my booking")}</a>
          <a className="site-staff" href="/staff">{t("Staff login")}</a></div>
      </div><p className="site-copy">© {new Date().getFullYear()} {h.name} · Powered by EHMS</p></footer>

      {viewer && <div className="lightbox" role="dialog" aria-label="Photos" onClick={() => setViewer(null)} onKeyDown={e => { if (e.key === "Escape") setViewer(null); }}>
        <img src={viewer.items[viewer.i].url} alt={viewer.items[viewer.i].caption || ""} onClick={e => { e.stopPropagation(); setViewer({ ...viewer, i: (viewer.i + 1) % viewer.items.length }); }} />
        <p>{viewer.items[viewer.i].caption || ""} · {viewer.i + 1}/{viewer.items.length}</p>
        <button className="btn btn-ghost light" autoFocus onClick={() => setViewer(null)}>{t("Close")}</button></div>}
    </div>
  );
}

function EnquiryForm({ hotel, disabled }: { hotel: string; disabled?: boolean }) {
  const { t } = useT();
  const [f, setF] = useState({ kind: "general", name: "", email: "", phone: "", subject: "", message: "", event_date: "", guests: "", marketing_consent: false, website: "" });
  const [state, setState] = useState<{ ok?: string; err?: string; busy?: boolean }>({});
  return (
    <form className="site-form" onSubmit={async e => {
      e.preventDefault();
      if (disabled) return;
      setState({ busy: true });
      try {
        const r = await api<any>("POST", "/api/public/site/enquiries", { ...f, hotel, guests: f.guests || undefined, event_date: f.event_date || undefined }, { auth: false });
        setState({ ok: r.message }); setF({ ...f, message: "", subject: "" });
      } catch (er) { setState({ err: errText(er) }); }
    }}>
      <label>{t("Enquiry about")}<select id="enq-kind" className="input" value={f.kind} onChange={e => setF({ ...f, kind: e.target.value })}>
        <option value="general">{t("General enquiry")}</option><option value="rooms">{t("Rooms")}</option><option value="dining">{t("Dining")}</option><option value="event">{t("Event or meeting")}</option></select></label>
      <div className="site-form-row"><label>{t("Your name")}<input className="input" required value={f.name} onChange={e => setF({ ...f, name: e.target.value })} autoComplete="name" /></label>
        <label>{t("Email")}<input className="input" type="email" required value={f.email} onChange={e => setF({ ...f, email: e.target.value })} autoComplete="email" /></label></div>
      <div className="site-form-row"><label>{t("Phone")}<input className="input" value={f.phone} onChange={e => setF({ ...f, phone: e.target.value })} autoComplete="tel" /></label>
        {f.kind === "event" ? <label>{t("Event date")}<input className="input" type="date" value={f.event_date} onChange={e => setF({ ...f, event_date: e.target.value })} /></label>
          : <label>{t("Subject")}<input className="input" value={f.subject} onChange={e => setF({ ...f, subject: e.target.value })} /></label>}</div>
      {f.kind === "event" && <label>{t("Number of guests")}<input className="input" type="number" min={1} value={f.guests} onChange={e => setF({ ...f, guests: e.target.value })} /></label>}
      <label>{t("Message")}<textarea className="input" rows={4} required value={f.message} onChange={e => setF({ ...f, message: e.target.value })} /></label>
      <input className="hp" tabIndex={-1} autoComplete="off" aria-hidden="true" value={f.website} onChange={e => setF({ ...f, website: e.target.value })} name="website" />
      <label className="check"><input type="checkbox" checked={f.marketing_consent} onChange={e => setF({ ...f, marketing_consent: e.target.checked })} /> {t("Send me offers by email (optional)")}</label>
      <p className="small muted">{t("We use your details only to answer your enquiry.")}</p>
      {state.ok && <p className="site-ok" role="status">{state.ok}</p>}{state.err && <p className="field-e" role="alert">{state.err}</p>}
      <button className="btn btn-gold" type="submit" disabled={state.busy || disabled}>{disabled ? t("Preview — form disabled") : t("Send message")}</button>
    </form>
  );
}
