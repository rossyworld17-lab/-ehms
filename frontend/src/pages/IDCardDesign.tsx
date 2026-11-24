// Administration → ID card design (release 1.4): administrators choose the layout, colours, wording and details of the
// staff ID card, upload the signature, see a live preview and an exact PDF proof before saving.
import React, { useEffect, useRef, useState } from "react";
import { ApiError, del, get, getToken, post, put } from "../api";
import { useAuth } from "../state";
import { Button, Card, Confirm, Field, Input, Loadable, Select, Textarea, useAction, useLoad } from "../ui";
import { useAuthImage } from "./IDCards";

type Design = {
  orientation: "landscape" | "portrait"; valid_years: number; colour: string; band_text: string; accent: string; title: string; footer_label: string;
  show_logo: boolean; show_hotel_name: boolean; show_department: boolean; show_staff_no: boolean; show_issue_date: boolean; show_expiry: boolean;
  show_address: boolean; show_phone: boolean; show_blood_group: boolean; show_signature: boolean; signature_label: string; back_note: string;
};
const KEYS: (keyof Design)[] = ["orientation", "valid_years", "colour", "band_text", "accent", "title", "footer_label", "show_logo", "show_hotel_name",
  "show_department", "show_staff_no", "show_issue_date", "show_expiry", "show_address", "show_phone", "show_blood_group", "show_signature",
  "signature_label", "back_note"];
const FRONT_SWITCHES: [keyof Design, string][] = [["show_logo", "Hotel logo"], ["show_hotel_name", "Hotel name"], ["show_department", "Department"],
  ["show_staff_no", "Staff number"], ["show_issue_date", "Issue date"], ["show_expiry", "Expiry date"]];
const BACK_SWITCHES: [keyof Design, string][] = [["show_address", "Hotel address"], ["show_phone", "Hotel phone"], ["show_blood_group", "Blood group"],
  ["show_signature", "Signature line"]];

async function postPdf(path: string, body: any) {
  const t = getToken();
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json", ...(t ? { Authorization: `Bearer ${t}` } : {}) }, body: JSON.stringify(body) });
  if (!res.ok) {
    let msg = "Preview failed";
    try { msg = (await res.json()).error.message; } catch { /* not json */ }
    throw new ApiError(res.status, "preview_failed", msg);
  }
  const url = URL.createObjectURL(await res.blob());
  if (!window.open(url, "_blank")) { const a = document.createElement("a"); a.href = url; a.download = "id-card-preview.pdf"; a.click(); }
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export default function IDCardDesign() {
  const { hotel } = useAuth();
  const st = useLoad(() => get(`/api/hotels/${hotel!.id}/id-cards/design`), [hotel?.id]);
  return <div className="page">
    <div className="page-h"><div><h1>ID card design</h1>
      <p className="muted">How staff ID cards look. HR prints them from Human resources → ID cards; every card printed after you save uses this design.</p></div></div>
    <Loadable state={st}>{d => <Designer saved={d} reload={st.reload} />}</Loadable>
  </div>;
}

function Designer({ saved, reload }: { saved: any; reload: () => void }) {
  const { hotel } = useAuth();
  const pick = (src: any) => Object.fromEntries(KEYS.map(k => [k, src[k]])) as Design;
  const [f, setF] = useState<Design>(pick(saved));
  const [sigV, setSigV] = useState(0);
  const [confirmReset, setConfirmReset] = useState(false);
  const { busy, run } = useAction();
  const fileRef = useRef<HTMLInputElement>(null);
  useEffect(() => setF(pick(saved)), [saved]);
  const dirty = KEYS.some(k => f[k] !== saved[k]);
  const set = (k: keyof Design, v: any) => setF(x => ({ ...x, [k]: v }));
  const sigUrl = useAuthImage(saved.has_signature ? `/api/hotels/${hotel!.id}/id-cards/signature` : null, sigV);
  const colour = (k: keyof Design, l: string, hint?: string) => <div className="field"><span className="field-l">{l}</span><div className="row gap-s">
    <input type="color" value={String(f[k])} aria-label={`${l} (picker)`} onChange={e => set(k, e.target.value.toUpperCase())} style={{ width: 44, height: 36, padding: 0, border: "none", background: "none" }} />
    <Input value={String(f[k])} aria-label={`${l} (code)`} onChange={e => set(k, e.target.value)} style={{ width: 110 }} /></div>{hint && <span className="field-h">{hint}</span>}</div>;
  const sw = ([k, l]: [keyof Design, string]) => <label key={k} className="check"><input type="checkbox" checked={!!f[k]} onChange={e => set(k, e.target.checked)} /> {l}</label>;

  return <div className="grid-2" style={{ alignItems: "start" }}>
    <div className="stack">
      <Card title="Layout and colours">
        <div className="stack">
          <div className="field" role="radiogroup" aria-label="Card shape"><span className="field-l">Card shape</span><div className="row gap">
            <label className="check"><input type="radio" name="orient" checked={f.orientation === "landscape"} onChange={() => set("orientation", "landscape")} /> Landscape (wide)</label>
            <label className="check"><input type="radio" name="orient" checked={f.orientation === "portrait"} onChange={() => set("orientation", "portrait")} /> Portrait (tall, for lanyards)</label>
          </div></div>
          <div className="row gap wrap">
            {colour("colour", "Main colour", "Header band and footer strip")}
            {colour("band_text", "Text on the band")}
            {colour("accent", "Job title colour")}
          </div>
          <Field label="Cards are valid for"><Select value={String(f.valid_years)} onChange={e => set("valid_years", Number(e.target.value))}>
            {[1, 2, 3, 4, 5].map(y => <option key={y} value={y}>{y} year{y > 1 ? "s" : ""}</option>)}</Select></Field>
        </div>
      </Card>
      <Card title="Front of the card">
        <div className="stack">
          <Field label="Title under the hotel name" hint="e.g. STAFF IDENTITY CARD, EMPLOYEE ID; leave empty for none"><Input value={f.title} maxLength={40} onChange={e => set("title", e.target.value)} /></Field>
          <Field label="Word in the footer strip" hint="e.g. STAFF, CREW, TEAM; leave empty for none"><Input value={f.footer_label} maxLength={16} onChange={e => set("footer_label", e.target.value)} /></Field>
          <div className="row gap wrap">{FRONT_SWITCHES.map(sw)}</div>
          <p className="small muted">The photo, full name and job title are always shown. The logo comes from Administration → Hotel settings{saved.has_logo ? "" : " (no logo uploaded yet)"}.</p>
        </div>
      </Card>
      <Card title="Back of the card">
        <div className="stack">
          <Field label="Text on the back" hint="Leave empty for the standard wording"><Textarea value={f.back_note} maxLength={300} onChange={e => set("back_note", e.target.value)} placeholder={saved.default_back_note} /></Field>
          <div className="row gap wrap">{BACK_SWITCHES.map(sw)}</div>
          {f.show_signature && <>
            <Field label="Words under the signature line"><Input value={f.signature_label} maxLength={60} onChange={e => set("signature_label", e.target.value)} /></Field>
            <div className="field"><span className="field-l">Signature image</span>
              <div className="row gap-s wrap">
                {sigUrl && <img src={sigUrl} alt="Signature" style={{ height: 40, maxWidth: 180, objectFit: "contain", background: "#fff", border: "1px solid var(--line, #e3e5e8)", borderRadius: 6 }} />}
                <input ref={fileRef} type="file" accept="image/png,image/jpeg" style={{ display: "none" }} onChange={async ev => {
                  const file = ev.target.files?.[0]; ev.target.value = "";
                  if (!file) return;
                  const b64 = await new Promise<string>((res, rej) => { const r = new FileReader(); r.onload = () => res(String(r.result).split(",")[1] || ""); r.onerror = rej; r.readAsDataURL(file); });
                  if (await run(() => post(`/api/hotels/${hotel!.id}/id-cards/signature`, { filename: file.name, content_base64: b64 }), "Signature saved")) { setSigV(v => v + 1); reload(); }
                }} />
                <Button kind="secondary" busy={busy} onClick={() => fileRef.current?.click()}>{saved.has_signature ? "Replace signature" : "Upload signature"}</Button>
                {saved.has_signature && <Button kind="ghost" busy={busy} onClick={async () => { if (await run(() => del(`/api/hotels/${hotel!.id}/id-cards/signature`), "Signature removed")) { setSigV(v => v + 1); reload(); } }}>Remove</Button>}
              </div><span className="field-h">Optional. A PNG with a transparent background looks best; without one, cards are signed by hand</span>
            </div></>}
        </div>
      </Card>
    </div>
    <div className="stack" style={{ position: "sticky", top: 16 }}>
      <Card title="Preview" actions={<div className="row gap-s wrap">
        <Button kind="secondary" busy={busy} onClick={() => run(() => postPdf(`/api/hotels/${hotel!.id}/id-cards/preview`, { design: f, layout: "card" }))}>Exact PDF proof</Button>
        <Button kind="ghost" busy={busy} onClick={() => run(() => postPdf(`/api/hotels/${hotel!.id}/id-cards/preview`, { design: f, layout: "a4" }))}>A4 sheet proof</Button></div>}>
        <div className="row gap wrap" style={{ justifyContent: "center", alignItems: "flex-start" }}>
          <CardFace side="front" d={f} saved={saved} logo={hotel!.logo_url} sig={sigUrl} />
          <CardFace side="back" d={f} saved={saved} logo={hotel!.logo_url} sig={sigUrl} />
        </div>
        <p className="small muted" style={{ marginTop: 12 }}>A close guide to the printed card; the PDF proof shows it exactly. Proofs are marked SAMPLE and are not valid cards.</p>
      </Card>
      <div className="row gap-s end">
        <Button kind="ghost" onClick={() => setConfirmReset(true)}>Standard design</Button>
        <Button kind="secondary" disabled={!dirty} onClick={() => setF(pick(saved))}>Undo changes</Button>
        <Button busy={busy} disabled={!dirty} onClick={async () => { if (await run(() => put(`/api/hotels/${hotel!.id}/id-cards/design`, f), "Card design saved")) reload(); }}>Save design</Button>
      </div>
    </div>
    {confirmReset && <Confirm title="Go back to the standard design?" text={<p>Colours, wording and switches return to the standard EHMS card. The signature image is kept.</p>}
      confirmText="Use standard design" onClose={() => setConfirmReset(false)}
      onConfirm={async () => { if (await run(() => post(`/api/hotels/${hotel!.id}/id-cards/design/reset`), "Standard design restored")) { setConfirmReset(false); reload(); } }} />}
  </div>;
}

// ---------------------------------------------------------------- live preview (HTML approximation of the PDF)
const MM = 3.6;   // pixels per millimetre in the preview

function CardFace({ side, d, saved, logo, sig }: { side: "front" | "back"; d: Design; saved: any; logo?: string | null; sig: string | null }) {
  const land = d.orientation === "landscape";
  const W = (land ? 85.6 : 54) * MM, H = (land ? 54 : 85.6) * MM;
  const h = saved.hotel || {};
  const box: React.CSSProperties = { width: W, height: H, borderRadius: 3 * MM, overflow: "hidden", position: "relative", background: "#fff", color: "#111827",
    boxShadow: "0 1px 4px rgba(0,0,0,.18)", fontFamily: "Helvetica, Arial, sans-serif", flex: "none" };
  const pt = (n: number) => n * MM * 0.3528;                  // PDF points → preview pixels
  const abs = (s: React.CSSProperties): React.CSSProperties => ({ position: "absolute", ...s });
  const contact = [d.show_address ? [h.address, h.city].filter(Boolean).join(", ") : "", d.show_phone && h.phone ? `Tel: ${h.phone}` : ""].filter(Boolean);
  const note = d.back_note || saved.default_back_note;
  const details = [d.show_staff_no && ["Staff No.", "EMP-0000"], d.show_issue_date && ["Issued", "2026-11-24"], d.show_expiry && ["Expires", `${2026 + d.valid_years}-11-24`]].filter(Boolean) as string[][];
  const photo = <div style={{ width: "100%", height: "100%", background: "#C9AE96", display: "grid", placeItems: "end center", overflow: "hidden" }}>
    <div style={{ width: "62%", height: "40%", background: "#2F4373", borderRadius: "40% 40% 0 0" }} /></div>;
  const logoEl = d.show_logo && logo ? <img src={logo} alt="" style={{ width: 9 * MM, height: 9 * MM, objectFit: "contain" }} /> : null;

  if (side === "front" && land) return <div style={box} aria-label="Front of the card">
    <div style={abs({ left: 0, right: 0, top: 0, height: 12 * MM, background: d.colour, color: d.band_text, display: "flex", alignItems: "center", gap: 2 * MM, padding: `0 ${4 * MM}px` })}>
      {logoEl}<div style={{ minWidth: 0 }}>{d.show_hotel_name && <div style={{ fontWeight: 700, fontSize: pt(9), whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{h.name}</div>}
        {d.title && <div style={{ fontSize: d.show_hotel_name ? pt(6.5) : pt(9), fontWeight: d.show_hotel_name ? 400 : 700 }}>{d.title}</div>}</div></div>
    <div style={abs({ left: 4 * MM, bottom: 8.5 * MM, width: 22 * MM, height: 27.5 * MM })}>{photo}</div>
    <div style={abs({ left: 29.5 * MM, right: 4 * MM, top: 14.5 * MM, lineHeight: 1.25 })}>
      <div style={{ fontWeight: 700, fontSize: pt(9.5) }}>ADAEZE EXAMPLE</div>
      <div style={{ fontWeight: 700, fontSize: pt(7.5), color: d.accent }}>Guest Service Officer</div>
      {d.show_department && <div style={{ fontSize: pt(6.8), color: "#4B5563" }}>Front Office</div>}
      <div style={{ marginTop: 1.3 * MM }}>{details.map(([l, v]) => <div key={l} style={{ fontSize: pt(6.6) }}><span style={{ color: "#6B7280", display: "inline-block", width: 13 * MM }}>{l}</span><b>{v}</b></div>)}</div>
    </div>
    <div style={abs({ left: 0, right: 0, bottom: 0, height: 4.2 * MM, background: d.colour, color: d.band_text, fontSize: pt(6.5), fontWeight: 700, display: "flex", justifyContent: "space-between", alignItems: "center", padding: `0 ${4 * MM}px` })}>
      <span>EMP-0000-01</span><span>{d.footer_label}</span></div>
  </div>;

  if (side === "front") return <div style={box} aria-label="Front of the card">
    <div style={abs({ left: 0, right: 0, top: 0, height: 20 * MM, background: d.colour, color: d.band_text, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 0.6 * MM, textAlign: "center" })}>
      {logoEl}{d.show_hotel_name && <div style={{ fontWeight: 700, fontSize: pt(8) }}>{h.name}</div>}{d.title && <div style={{ fontSize: pt(6.2) }}>{d.title}</div>}</div>
    <div style={abs({ left: (54 - 24) / 2 * MM, top: 22.5 * MM, width: 24 * MM, height: 30 * MM })}>{photo}</div>
    <div style={abs({ left: 3 * MM, right: 3 * MM, top: 55 * MM, textAlign: "center", lineHeight: 1.25 })}>
      <div style={{ fontWeight: 700, fontSize: pt(8.5) }}>ADAEZE EXAMPLE</div>
      <div style={{ fontWeight: 700, fontSize: pt(7), color: d.accent }}>Guest Service Officer</div>
      {d.show_department && <div style={{ fontSize: pt(6.4), color: "#4B5563" }}>Front Office</div>}
      {details.map(([l, v]) => <div key={l} style={{ fontSize: pt(6) }}><span style={{ color: "#6B7280" }}>{l}</span> <b>{v}</b></div>)}
    </div>
    <div style={abs({ left: 0, right: 0, bottom: 0, height: 4.2 * MM, background: d.colour, color: d.band_text, fontSize: pt(6), fontWeight: 700, display: "flex", justifyContent: "space-between", alignItems: "center", padding: `0 ${3.5 * MM}px` })}>
      <span>EMP-0000-01</span><span>{d.footer_label}</span></div>
  </div>;

  const qr = <div aria-label="QR code" style={{ width: "100%", height: "100%", background: "repeating-conic-gradient(#111 0% 25%, #fff 0% 50%) 0 0 / 12% 12%", outline: "2px solid #fff" }} />;
  const sigBlock = d.show_signature && <div>
    <div style={{ height: 6.5 * MM, display: "flex", alignItems: "flex-end" }}>{sig && <img src={sig} alt="" style={{ height: "100%", maxWidth: "70%", objectFit: "contain" }} />}</div>
    <div style={{ borderTop: "1px solid #9CA3AF", fontSize: pt(5.4), color: "#6B7280", paddingTop: 0.6 * MM }}>{d.signature_label}</div></div>;
  if (land) return <div style={box} aria-label="Back of the card">
    <div style={abs({ left: 0, right: 0, top: 0, height: 3 * MM, background: d.colour })} />
    <div style={abs({ right: 3.5 * MM, top: 6 * MM, width: 25 * MM, height: 25 * MM })}>{qr}</div>
    <div style={abs({ right: 3.5 * MM, top: 32 * MM, width: 25 * MM, textAlign: "center", fontSize: pt(5.6), color: "#4B5563" })}>Scan to verify this card</div>
    <div style={abs({ left: 4 * MM, width: 85.6 * MM - 36 * MM - 4 * MM, top: 5 * MM, lineHeight: 1.3 })}>
      <div style={{ fontWeight: 700, fontSize: pt(7) }}>{h.name}</div>
      {contact.map(c => <div key={c} style={{ fontSize: pt(6), color: "#4B5563" }}>{c}</div>)}
      <div style={{ fontSize: pt(5.8), marginTop: 1.2 * MM }}>{note}</div>
      {d.show_blood_group && <div style={{ fontSize: pt(6.2), fontWeight: 700 }}>Blood group: O+</div>}
    </div>
    <div style={abs({ left: 4 * MM, bottom: 4 * MM, width: 34 * MM })}>{sigBlock}</div>
    <div style={abs({ right: 3.5 * MM, bottom: 4 * MM, fontSize: pt(5.4), color: "#6B7280" })}>EMP-0000-01</div>
  </div>;
  return <div style={box} aria-label="Back of the card">
    <div style={abs({ left: 0, right: 0, top: 0, height: 3 * MM, background: d.colour })} />
    <div style={abs({ left: 3.5 * MM, right: 3.5 * MM, top: 5 * MM, textAlign: "center", lineHeight: 1.3 })}>
      <div style={{ fontWeight: 700, fontSize: pt(7) }}>{h.name}</div>
      {contact.map(c => <div key={c} style={{ fontSize: pt(5.8), color: "#4B5563" }}>{c}</div>)}
      <div style={{ fontSize: pt(5.5), marginTop: 1 * MM }}>{note}</div>
    </div>
    {d.show_blood_group && <div style={abs({ left: 0, right: 0, bottom: 46 * MM, textAlign: "center", fontSize: pt(6), fontWeight: 700 })}>Blood group: O+</div>}
    <div style={abs({ left: (54 - 22) / 2 * MM, bottom: 22 * MM, width: 22 * MM, height: 22 * MM })}>{qr}</div>
    <div style={abs({ left: 0, right: 0, bottom: 18 * MM, textAlign: "center", fontSize: pt(5.4), color: "#4B5563" })}>Scan to verify this card</div>
    <div style={abs({ left: 3.5 * MM, right: 3.5 * MM, bottom: 7 * MM })}>{sigBlock}</div>
    <div style={abs({ right: 3.5 * MM, bottom: 4 * MM, fontSize: pt(5.2), color: "#6B7280" })}>EMP-0000-01</div>
  </div>;
}
