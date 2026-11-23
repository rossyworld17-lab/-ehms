declare const __APP_VERSION__: string;
import React, { useState } from "react";
import { api, ApiError, setToken } from "../api";
import { useAuth } from "../state";
import { Button, Field, Input } from "../ui";

export default function Login() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(""); setBusy(true);
    try {
      if (!mfaToken) {
        const r = await api<any>("POST", "/api/auth/login", { email, password }, { auth: false });
        if (r.mfa_required) { setMfaToken(r.token); setToken(r.token); }
        else { signIn(r.token, r.user); if (location.hash.startsWith("#/login")) location.hash = "#/"; }
      } else {
        const r = await api<any>("POST", "/api/auth/mfa/verify", { code });
        signIn(r.token, r.user);
        location.hash = "#/";
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "Sign-in failed");
    } finally { setBusy(false); }
  }

  return (
    <div className="auth-page">
      <div className="auth-art"><div><span className="logo lg">E</span><h1>Enterprise Hotel<br />Management System</h1>
        <p>Reservations, front office, housekeeping, folios, payments and accounting in one secure platform.</p></div></div>
      <form className="auth-card" onSubmit={submit}>
        <h2>{mfaToken ? "Two-step verification" : "Sign in"}</h2>
        {!mfaToken ? <>
          <Field label="Email"><Input type="email" autoComplete="username" value={email} onChange={e => setEmail(e.target.value)} required autoFocus /></Field>
          <Field label="Password"><Input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required /></Field>
        </> : <Field label="6-digit code from your authenticator app">
          <Input inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ""))} autoFocus required />
        </Field>}
        {err && <div className="field-e" role="alert">{err}</div>}
        <Button type="submit" busy={busy} className="full">{mfaToken ? "Verify" : "Sign in"}</Button>
        <div className="row between small">
          {mfaToken ? <a href="#/login" onClick={() => { setMfaToken(null); setToken(null); setCode(""); }}>Use a different account</a> : <a href="#/forgot">Forgot password?</a>}
          <span className="muted">Sessions end after inactivity. · EHMS v{__APP_VERSION__}</span>
        </div>
      </form>
    </div>
  );
}

export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [token, setTok] = useState("");
  const [pw, setPw] = useState("");
  const [stage, setStage] = useState<"request" | "reset" | "done">("request");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  async function go(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setMsg("");
    try {
      if (stage === "request") {
        const r = await api<any>("POST", "/api/auth/password-reset/request", { email }, { auth: false });
        setMsg(r.message); setStage("reset");
      } else {
        await api("POST", "/api/auth/password-reset/confirm", { token, new_password: pw }, { auth: false });
        setStage("done");
      }
    } catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  }
  return (
    <div className="auth-page single">
      <form className="auth-card" onSubmit={go}>
        <h2>Reset password</h2>
        {stage === "done" ? <><p>Your password has been changed. All sessions were signed out.</p><a className="btn btn-primary" href="#/login">Sign in</a></> : <>
          {stage === "request" && <Field label="Account email"><Input type="email" value={email} onChange={e => setEmail(e.target.value)} required /></Field>}
          {stage === "reset" && <>
            <Field label="Reset code (sent by email)"><Input value={token} onChange={e => setTok(e.target.value)} required /></Field>
            <Field label="New password" hint="At least 10 characters with upper- and lower-case letters and a digit"><Input type="password" value={pw} onChange={e => setPw(e.target.value)} required /></Field>
          </>}
          {msg && <p className="small muted">{msg}</p>}
          <Button type="submit" busy={busy} className="full">{stage === "request" ? "Send reset code" : "Set new password"}</Button>
          <a href="#/login" className="small">Back to sign in</a>
        </>}
      </form>
    </div>
  );
}
