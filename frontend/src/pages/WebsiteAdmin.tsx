// Administration → Website (release 1.3): edit the public website without touching code. Changes are saved as a
// draft, previewed, then published; the public site shows only the published version.
import React, { useEffect, useState } from "react";
import { del, fmtDate, fmtDateTime, get, label, patch, post, put } from "../api";
import { useAuth } from "../state";
import { Button, Card, Confirm, Empty, Field, Input, Loadable, Modal, Pill, Select, Table, Tabs, Textarea, errText, useAction, useLoad, useToast } from "../ui";
import { WebsiteView } from "./Website";

const TEXT_GROUPS: { title: string; section?: string; fields: [string, string, boolean?][] }[] = [
  { title: "Top of the page", fields: [["announcement", "Announcement bar (optional, e.g. a special offer)"], ["hero_title", "Headline"], ["hero_subtitle", "Sub-headline", true]] },
  { title: "About", section: "about", fields: [["about_title", "Title"], ["about_body", "Text (leave an empty line between paragraphs)", true]] },
  { title: "Rooms", section: "rooms", fields: [["rooms_title", "Title"], ["rooms_intro", "Introduction", true]] },
  { title: "Restaurant & bar", section: "dining", fields: [["dining_title", "Title"], ["dining_body", "Text", true], ["dining_hours", "Opening hours"]] },
  { title: "Meetings & events", section: "events", fields: [["events_title", "Title"], ["events_body", "Text", true]] },
  { title: "Facilities", section: "facilities", fields: [["facilities_title", "Title"]] },
  { title: "Gallery", section: "gallery", fields: [["gallery_title", "Title"]] },
  { title: "Location", section: "location", fields: [["location_title", "Title"], ["directions", "Directions (landmarks, parking, airport distance)", true]] },
  { title: "Contact", section: "contact", fields: [["contact_title", "Title"], ["contact_intro", "Introduction", true], ["contact_hours", "Opening hours of reception"]] },
  { title: "Footer and search engines", fields: [["footer_note", "Footer note (e.g. RC number)"], ["seo_title", "Title shown in Google and on the browser tab (≤ 70)"], ["seo_description", "Description shown in Google (≤ 170)", true]] },
];
const SECTION_LABELS: Record<string, string> = { about: "About", highlights: "Highlights", rooms: "Rooms", dining: "Restaurant & bar", events: "Meetings & events",
  facilities: "Facilities", gallery: "Gallery", location: "Location", contact: "Contact form" };

export default function WebsiteAdmin() {
  const { hotel, can } = useAuth();
  const toast = useToast();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/website`), [hotel?.id]);
  const [doc, setDoc] = useState<any>(null);
  const [dirty, setDirty] = useState(false);
  const [tab, setTab] = useState("content");
  const [lang, setLang] = useState("en");
  const [preview, setPreview] = useState<any>(null);
  const [confirm, setConfirm] = useState<"publish" | "discard" | null>(null);
  const { busy, run } = useAction();
  useEffect(() => { if (st.data) { setDoc(JSON.parse(JSON.stringify(st.data.draft))); setDirty(false); } }, [st.data]);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const upd = (fn: (d: any) => void) => { const d = JSON.parse(JSON.stringify(doc)); fn(d); setDoc(d); setDirty(true); };
  const txt = (k: string) => doc?.text?.[lang]?.[k] ?? "";
  const setTxt = (k: string, v: any) => upd(d => { d.text[lang] = d.text[lang] || {}; d.text[lang][k] = v; });
  const save = async () => { const r = await run(() => put(`/api/hotels/${hotel!.id}/website`, { content: doc }), "Draft saved"); if (r) { setDirty(false); st.reload(); } return r; };
  if (!st.data || !doc) return <div className="page"><Loadable state={st}>{() => null}</Loadable></div>;
  const d = st.data;
  const media = d.media as any[];
  return (
    <div className="page">
      <div className="page-h"><div><h1>Website</h1>
        <p className="muted">Edit your public website — no coding needed. <a href={d.public_url} target="_blank" rel="noopener noreferrer">Open the live website ↗</a></p></div>
        <div className="row gap-s wrap">
          <Button kind="secondary" busy={busy} onClick={async () => { const r = await run(() => post(`/api/hotels/${hotel!.id}/website/preview`, { content: doc })); if (r) setPreview(r); }}>Preview</Button>
          <Button kind="secondary" busy={busy} disabled={!dirty} onClick={save}>Save draft</Button>
          <Button kind="gold" busy={busy} onClick={() => setConfirm("publish")}>Publish</Button>
        </div></div>
      <div className="website-status">
        {dirty ? <Pill s="pending" text="Unsaved changes" /> : d.unpublished_changes ? <Pill s="pending" text="Draft not yet published" /> : <Pill s="approved" text="Website up to date" />}
        <span className="small muted">{d.published_at ? `Published ${fmtDateTime(d.published_at)} by ${d.published_by || "—"}` : "Not published yet — the website shows the default text"}
          {d.updated_at ? ` · draft saved ${fmtDateTime(d.updated_at)} by ${d.updated_by || "—"}` : ""}</span>
        {d.published && d.unpublished_changes && !dirty && <button className="link-btn" onClick={() => setConfirm("discard")}>Discard draft changes</button>}
      </div>
      <Tabs tabs={[{ id: "content", label: "Text" }, { id: "images", label: `Images (${media.length})` }, { id: "settings", label: "Sections & links" },
        { id: "enquiries", label: `Enquiries${d.new_enquiries ? ` (${d.new_enquiries} new)` : ""}` }]} value={tab} onChange={setTab} />

      {tab === "content" && <>
        <div className="row gap-s mb"><span className="small">Language you are editing:</span>
          <Select value={lang} onChange={e => setLang(e.target.value)} aria-label="Language"><option value="en">English (main)</option><option value="fr">Français</option></Select>
          {lang === "fr" && <span className="small muted">Empty French fields show the English text.</span>}</div>
        <div className="grid-2">
          {TEXT_GROUPS.map(g => <Card key={g.title} title={<>{g.title}{g.section && doc.sections[g.section] === false && <> <Pill s="cancelled" text="Hidden" /></>}</>}>
            {g.fields.map(([k, l, multi]) => <Field key={k} label={l} hint={lang === "fr" && doc.text.en?.[k] ? `English: ${String(doc.text.en[k]).slice(0, 80)}${String(doc.text.en[k]).length > 80 ? "…" : ""}` : undefined}>
              {multi ? <Textarea rows={k.endsWith("_body") ? 6 : 3} value={txt(k)} onChange={e => setTxt(k, e.target.value)} maxLength={d.fields.text[k]} />
                : <Input value={txt(k)} onChange={e => setTxt(k, e.target.value)} maxLength={d.fields.text[k]} />}</Field>)}
          </Card>)}
          <Card title="Highlights (up to 6)">{((doc.text[lang]?.highlights) || []).map((h: any, i: number) => <div key={i} className="row gap-s mb">
            <Input placeholder="Title" value={h.title} onChange={e => upd(x => { x.text[lang].highlights[i].title = e.target.value; })} maxLength={60} />
            <Input placeholder="Short text" value={h.text} onChange={e => upd(x => { x.text[lang].highlights[i].text = e.target.value; })} maxLength={220} style={{ flex: 2 }} />
            <Button kind="ghost" aria-label="Remove highlight" onClick={() => upd(x => { x.text[lang].highlights.splice(i, 1); })}>×</Button></div>)}
            {((doc.text[lang]?.highlights) || []).length < 6 && <Button kind="secondary" onClick={() => upd(x => { x.text[lang] = x.text[lang] || {}; x.text[lang].highlights = [...(x.text[lang].highlights || []), { title: "", text: "" }]; })}>Add highlight</Button>}
          </Card>
          <Card title="Facilities list (one per line)"><Textarea rows={8} value={((doc.text[lang]?.facilities) || []).join("\n")}
            onChange={e => setTxt("facilities", e.target.value.split("\n"))} /></Card>
        </div>
      </>}

      {tab === "images" && <ImagesTab doc={doc} media={media} upd={upd} reload={st.reload} />}

      {tab === "settings" && <div className="grid-2">
        <Card title="Show these sections">{Object.keys(SECTION_LABELS).map(s => <label key={s} className="check"><input type="checkbox" checked={doc.sections[s] !== false}
          onChange={e => upd(x => { x.sections[s] = e.target.checked; })} /> {SECTION_LABELS[s]}</label>)}</Card>
        <Card title="Map and social media">
          <Field label="Google Maps link" hint="In Google Maps: Share → Copy link. Empty = EHMS searches your address."><Input value={doc.map_url} onChange={e => upd(x => { x.map_url = e.target.value; })} placeholder="https://maps.app.goo.gl/…" /></Field>
          {d.fields.social.map((k: string) => <Field key={k} label={k === "x" ? "X (Twitter)" : k === "whatsapp" ? "WhatsApp number" : k.charAt(0).toUpperCase() + k.slice(1)}>
            <Input value={doc.social[k] || ""} onChange={e => upd(x => { x.social[k] = e.target.value; })} placeholder={k === "whatsapp" ? "+234 803 000 0000" : `https://${k === "x" ? "x" : k}.com/…`} /></Field>)}
        </Card>
        <Card title="Comes from your hotel record">
          <p className="small">Hotel name, address, phone, email, logo, check-in/out times, rooms, prices and room photos are taken from Hotel settings and Rooms & rates, so they are always current.</p>
          <div className="row gap-s wrap">{can("admin.settings.manage") && <a className="btn btn-secondary" href="#/admin/hotel">Hotel settings</a>}{can("rooms.manage") && <a className="btn btn-secondary" href="#/admin/rooms">Rooms & photos</a>}</div>
        </Card>
      </div>}

      {tab === "enquiries" && <Enquiries />}

      {preview && <div className="site-preview" role="dialog" aria-label="Website preview">
        <div className="site-preview-bar"><b>Preview</b><span className="small">This is how the website will look after you publish. Links and the form are disabled.</span>
          <Button kind="secondary" onClick={() => setPreview(null)}>Close preview</Button></div>
        <div className="site-preview-body"><WebsiteView data={preview} preview /></div></div>}
      {confirm === "publish" && <Confirm title="Publish the website" confirmText="Publish" onClose={() => setConfirm(null)}
        text={<p>{dirty ? "Your changes will be saved and " : "The saved draft will be "}published on the public website immediately.</p>}
        onConfirm={async () => { if (dirty && !(await save())) return; if (await run(() => post(`/api/hotels/${hotel!.id}/website/publish`, {}), "Website published")) { setConfirm(null); st.reload(); } }} />}
      {confirm === "discard" && <Confirm title="Discard draft changes" danger confirmText="Discard" onClose={() => setConfirm(null)}
        text={<p>The draft goes back to what is published now. This cannot be undone.</p>}
        onConfirm={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/website/discard`, {}), "Draft discarded")) { setConfirm(null); st.reload(); } }} />}
    </div>
  );
}

function ImagesTab({ doc, media, upd, reload }: { doc: any; media: any[]; upd: (fn: (d: any) => void) => void; reload: () => void }) {
  const { hotel } = useAuth();
  const toast = useToast();
  const { busy, run } = useAction();
  const [caption, setCaption] = useState("");
  const slots: [string, string][] = [["hero", "Large photo at the top"], ["about", "About section"], ["dining", "Restaurant & bar"], ["events", "Meetings & events"]];
  async function upload(files: FileList) {
    for (const file of Array.from(files)) {
      if (file.size > 5 * 1024 * 1024) { toast("error", `${file.name}: images must be 5 MB or smaller`); continue; }
      const b64 = await new Promise<string>((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1] || ""); r.onerror = rej; r.readAsDataURL(file); });
      await run(() => post(`/api/hotels/${hotel!.id}/website/media`, { filename: file.name, content_base64: b64, caption: caption || file.name.replace(/\.[^.]+$/, "") }), `${file.name} uploaded`);
    }
    setCaption(""); reload();
  }
  const inGallery = (id: number) => doc.gallery.includes(id);
  return <>
    <Card title="Upload images" actions={<span className="small muted">JPEG, PNG or WebP · up to 5 MB each · wide photos (1600 px) look best</span>}>
      <div className="row gap wrap"><Input placeholder="Caption (optional)" value={caption} onChange={e => setCaption(e.target.value)} style={{ maxWidth: 320 }} />
        <input type="file" multiple accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={e => { if (e.target.files?.length) upload(e.target.files); e.currentTarget.value = ""; }} aria-label="Upload images" /></div>
    </Card>
    <div className="grid-2">
      <Card title="Where photos appear">{slots.map(([k, l]) => <Field key={k} label={l}>
        <Select value={doc.images[k] || ""} onChange={e => upd(x => { x.images[k] = e.target.value ? Number(e.target.value) : null; })}>
          <option value="">No photo</option>{media.map(m => <option key={m.id} value={m.id}>{m.caption || `Image ${m.id}`}</option>)}</Select></Field>)}
        <p className="small muted">Room photos are added per room category under Rooms & rates → Photos & videos.</p></Card>
      <Card title={`Gallery (${doc.gallery.length} chosen)`}><p className="small muted">Tick images to show them in the gallery, in the order you tick them.</p></Card>
    </div>
    {media.length ? <div className="media-grid">{media.map(m => <figure key={m.id} className={`media-tile ${inGallery(m.id) ? "picked" : ""}`}>
      <img src={m.url} alt={m.caption || ""} />
      <figcaption><input key={`${m.id}:${m.caption || ""}`} className="input" defaultValue={m.caption || ""} aria-label="Caption"
        onBlur={async e => { if (e.target.value !== (m.caption || "")) { await run(() => patch(`/api/website/media/${m.id}`, { caption: e.target.value }), "Caption saved"); reload(); } }} /></figcaption>
      <label className="check small"><input type="checkbox" checked={inGallery(m.id)} onChange={e => upd(x => { x.gallery = e.target.checked ? [...x.gallery, m.id] : x.gallery.filter((g: number) => g !== m.id); })} /> In gallery</label>
      <button className="x" aria-label="Delete image" onClick={async () => { if (window.confirm("Delete this image?") && await run(() => del(`/api/website/media/${m.id}`), "Image deleted")) reload(); }}>×</button>
    </figure>)}</div> : <Empty text="No images yet — upload the hotel's best photos." />}
  </>;
}

export function Enquiries() {
  const { hotel } = useAuth();
  const [status, setStatus] = useState("new");
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/website/enquiries`, status ? { status } : undefined), [hotel?.id, status]);
  const { busy, run } = useAction();
  const [sel, setSel] = useState<any>(null);
  const [note, setNote] = useState("");
  const setS = async (s: string) => { if (await run(() => post(`/api/website/enquiries/${sel.id}/status`, { status: s, note }), `Marked ${s}`)) { setSel(null); st.reload(); } };
  return <Card title={<Select value={status} onChange={e => setStatus(e.target.value)} aria-label="Status"><option value="new">New</option><option value="replied">Replied</option>
    <option value="closed">Closed</option><option value="spam">Spam</option><option value="">All</option></Select>} pad={false}>
    <Loadable state={st}>{d => <Table rows={d.items} onRow={e => { setSel(e); setNote(e.note || ""); }} empty="No enquiries" cols={[
      { h: "Received", r: e => fmtDateTime(e.created_at) }, { h: "From", r: e => <><b>{e.name}</b><div className="muted small">{e.email}{e.phone ? ` · ${e.phone}` : ""}</div></> },
      { h: "About", r: e => <>{label(e.kind)}{e.event_date && <div className="muted small">{fmtDate(e.event_date)}{e.guests ? ` · ${e.guests} guests` : ""}</div>}</> },
      { h: "Message", r: e => <span className="small">{(e.subject ? e.subject + " — " : "") + e.message.slice(0, 120)}{e.message.length > 120 ? "…" : ""}</span> },
      { h: "Status", r: e => <Pill s={e.status === "new" ? "pending" : e.status === "replied" ? "approved" : "cancelled"} text={label(e.status)} /> }]} />}</Loadable>
    {sel && <Modal title={`Enquiry from ${sel.name}`} onClose={() => setSel(null)} footer={<>
      <a className="btn btn-secondary" href={`mailto:${sel.email}?subject=${encodeURIComponent("Re: " + (sel.subject || "your enquiry"))}`}>Reply by email</a>
      <Button kind="ghost" busy={busy} onClick={() => setS("spam")}>Spam</Button><Button kind="secondary" busy={busy} onClick={() => setS("closed")}>Close</Button>
      <Button busy={busy} onClick={() => setS("replied")}>Mark replied</Button></>}>
      <dl className="dl"><dt>Email</dt><dd>{sel.email}</dd><dt>Phone</dt><dd>{sel.phone || "—"}</dd><dt>About</dt><dd>{label(sel.kind)}</dd>
        {sel.event_date && <><dt>Event date</dt><dd>{fmtDate(sel.event_date)} · {sel.guests || "?"} guests</dd></>}<dt>Offers by email</dt><dd>{sel.marketing_consent ? "Yes" : "No"}</dd></dl>
      <p className="note" style={{ whiteSpace: "pre-wrap" }}>{sel.message}</p>
      <Field label="Internal note"><Textarea value={note} onChange={e => setNote(e.target.value)} /></Field>
    </Modal>}
  </Card>;
}
