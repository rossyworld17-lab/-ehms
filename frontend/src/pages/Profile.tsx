import React, { useState } from "react";
import { fmtDateTime, get, post } from "../api";
import { useAuth } from "../state";
import { Button, Card, Field, Input, Loadable, Pill, Table, useAction, useLoad } from "../ui";

export default function Profile() {
  const { user, refresh } = useAuth();
  const [pw, setPw] = useState({ current_password: "", new_password: "", confirm: "" });
  const [setup, setSetup] = useState<any>(null);
  const [code, setCode] = useState("");
  const [disable, setDisable] = useState({ password: "", code: "" });
  const sessions = useLoad(() => get("/api/auth/sessions"), []);
  const { busy, run } = useAction();
  return <div className="page narrow">
    <div className="page-h"><div><h1>My profile & security</h1><p className="muted">{user!.full_name} · {user!.email}</p></div></div>
    {!!user!.must_change_password && <div className="note">Please set a new password — your current one was issued by an administrator.</div>}
    <Card title="Roles & access"><p>{user!.roles.map(r => <Pill key={r.id} s="confirmed" text={r.name} />)}</p>
      <p className="muted small">Hotels: {user!.all_hotels ? "All hotels in the organisation" : user!.hotels.map(h => h.name).join(", ")}</p></Card>
    <Card title="Change password"><div className="form-grid">
      <Field label="Current password"><Input type="password" value={pw.current_password} onChange={e => setPw({ ...pw, current_password: e.target.value })} /></Field>
      <Field label="New password" hint="10+ characters, upper & lower case and a digit"><Input type="password" value={pw.new_password} onChange={e => setPw({ ...pw, new_password: e.target.value })} /></Field>
      <Field label="Confirm new password" error={pw.confirm && pw.confirm !== pw.new_password ? "Passwords do not match" : undefined}><Input type="password" value={pw.confirm} onChange={e => setPw({ ...pw, confirm: e.target.value })} /></Field>
    </div><Button busy={busy} disabled={!pw.current_password || !pw.new_password || pw.new_password !== pw.confirm} onClick={async () => {
      if (await run(() => post("/api/auth/password", { current_password: pw.current_password, new_password: pw.new_password }), "Password changed. Other sessions were signed out.")) { setPw({ current_password: "", new_password: "", confirm: "" }); refresh(); }
    }}>Change password</Button></Card>
    <Card title="Two-step verification (MFA)">
      {user!.mfa_enabled ? <>
        <p><Pill s="active" text="Enabled" /> A code from your authenticator app is required at every sign-in.</p>
        <div className="form-grid"><Field label="Password"><Input type="password" value={disable.password} onChange={e => setDisable({ ...disable, password: e.target.value })} /></Field>
          <Field label="Current code"><Input value={disable.code} onChange={e => setDisable({ ...disable, code: e.target.value })} /></Field></div>
        <Button kind="danger" busy={busy} onClick={async () => { if (await run(() => post("/api/auth/mfa/disable", disable), "MFA disabled")) refresh(); }}>Disable MFA</Button>
      </> : setup ? <>
        <p>1. In Google Authenticator, Microsoft Authenticator or similar, choose <b>Enter a setup key</b> and type this key:</p>
        <p className="mono big">{setup.secret.match(/.{1,4}/g).join(" ")}</p>
        <p className="small muted">Or open this link on your phone: <a href={setup.otpauth_uri}>add to authenticator</a></p>
        <Field label="2. Enter the 6-digit code shown in the app"><Input inputMode="numeric" maxLength={6} value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ""))} /></Field>
        <Button busy={busy} disabled={code.length !== 6} onClick={async () => { if (await run(() => post("/api/auth/mfa/enable", { code }), "MFA enabled")) { setSetup(null); refresh(); } }}>Turn on MFA</Button>
      </> : <><p className="muted">Protect your account with a time-based code from an authenticator app.</p>
        <Button busy={busy} onClick={async () => { const s = await run(() => post("/api/auth/mfa/setup")); if (s) setSetup(s); }}>Set up MFA</Button></>}
    </Card>
    <Card title="My active sessions" pad={false}><Loadable state={sessions}>{d => <Table rows={d.items} cols={[
      { h: "Started", r: s => fmtDateTime(s.created_at) }, { h: "Last active", r: s => fmtDateTime(s.last_seen_at) }, { h: "IP", r: s => s.ip || "—" },
      { h: "", r: s => (s.current ? <Pill s="active" text="This device" /> : null) }]} />}</Loadable></Card>
  </div>;
}
