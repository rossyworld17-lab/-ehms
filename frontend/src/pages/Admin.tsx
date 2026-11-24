import React, { useEffect, useMemo, useState } from "react";
import { fmtDateTime, get, label, patch, post, put } from "../api";
import { useAuth } from "../state";
import { Button, Card, Confirm, Field, Input, Loadable, Modal, Pager, Pill, Select, Table, Tabs, errText, useAction, useLoad, useToast } from "../ui";

export function Users() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const st = useLoad(() => get("/api/admin/users", { search: q }), [q]);
  const [edit, setEdit] = useState<any>(null);
  const [sessions, setSessions] = useState<any>(null);
  const [confirm, setConfirm] = useState<any>(null);
  const [temp, setTemp] = useState<string | null>(null);
  const toast = useToast();
  return <div className="page">
    <div className="page-h"><div><h1>Users & access</h1><p className="muted">Accounts, roles, hotel assignments and sessions</p></div>
      {can("admin.users.manage") && <Button onClick={() => setEdit({})}>New user</Button>}</div>
    <Input placeholder="Search users" value={q} onChange={e => setQ(e.target.value)} className="mb" />
    <Card pad={false}><Loadable state={st}>{d => <Table rows={d.items} cols={[
      { h: "Name", r: u => <><b>{u.full_name}</b><div className="muted small">{u.email}</div></> },
      { h: "Roles", r: u => u.roles.map((r: any) => r.name).join(", ") || "—" },
      { h: "Hotels", r: u => (u.all_hotels ? "All hotels" : u.hotels.map((h: any) => h.code).join(", ") || "—") },
      { h: "MFA", r: u => (u.mfa_enabled ? <Pill s="active" text="On" /> : <span className="muted">Off</span>) },
      { h: "Last sign-in", r: u => fmtDateTime(u.last_login_at) },
      { h: "Status", r: u => <>{<Pill s={u.status} />}{u.locked && <Pill s="failed" text="Locked" />}</> },
      { h: "", r: u => can("admin.users.manage") && <div className="row gap-s">
        <Button kind="ghost" onClick={() => setEdit(u)}>Edit</Button>
        {can("admin.sessions.manage") && <Button kind="ghost" onClick={() => setSessions(u)}>Sessions</Button>}
        <Button kind="ghost" onClick={() => setConfirm({ u, kind: "reset" })}>Reset password</Button>
        {u.mfa_enabled && <Button kind="ghost" onClick={() => setConfirm({ u, kind: "mfa" })}>Reset two-step</Button>}
        {u.status === "active" ? <Button kind="ghost" onClick={() => setConfirm({ u, kind: "suspended" })}>Suspend</Button> : <Button kind="ghost" onClick={() => setConfirm({ u, kind: "active" })}>Activate</Button>}
      </div> }]} />}</Loadable></Card>
    {edit && <UserForm u={edit} onClose={() => setEdit(null)} onSaved={(t?: string) => { setEdit(null); st.reload(); if (t) setTemp(t); }} />}
    {sessions && <SessionsModal u={sessions} onClose={() => setSessions(null)} />}
    {confirm && <Confirm title={confirm.kind === "reset" ? "Reset password" : confirm.kind === "mfa" ? "Reset two-step verification" : `${label(confirm.kind === "active" ? "activate" : "suspend")} user`} danger={confirm.kind !== "active"}
      text={<p>{confirm.kind === "reset" ? `Issue a temporary password for ${confirm.u.full_name}? Their current sessions will end.` : confirm.kind === "mfa" ? `Remove ${confirm.u.full_name}'s two-step verification (for a lost or replaced phone)? Their sessions end and they set it up again at their next sign-in. Do this only after confirming who is asking.` : `${confirm.kind === "active" ? "Re-activate" : "Suspend"} ${confirm.u.full_name}?`}</p>}
      onClose={() => setConfirm(null)} onConfirm={async () => {
        try {
          if (confirm.kind === "reset") { const r = await post(`/api/admin/users/${confirm.u.id}/reset-password`); setTemp(r.temporary_password); }
          else if (confirm.kind === "mfa") { await post(`/api/admin/users/${confirm.u.id}/reset-mfa`); toast("success", "Two-step verification removed"); }
          else { await post(`/api/admin/users/${confirm.u.id}/status`, { status: confirm.kind }); toast("success", "User updated"); }
          setConfirm(null); st.reload();
        } catch (e) { toast("error", errText(e)); }
      }} />}
    {temp && <Modal title="Temporary password" onClose={() => setTemp(null)}><p>Share this securely with the user. They must change it after signing in.</p><p className="mono big">{temp}</p></Modal>}
  </div>;
}

function UserForm({ u, onClose, onSaved }: any) {
  const { user } = useAuth();
  const roles = useLoad(() => get("/api/admin/roles"), []);
  const hotels = useLoad(() => get("/api/hotels"), []);
  const isNew = !u.id;
  const [f, setF] = useState<any>({ email: u.email || "", full_name: u.full_name || "", phone: u.phone || "", password: "", all_hotels: !!u.all_hotels,
    role_ids: (u.roles || []).map((r: any) => r.id), hotel_ids: (u.hotels || []).map((h: any) => h.id) });
  const { busy, run } = useAction();
  const toggle = (k: string, id: number) => setF((x: any) => ({ ...x, [k]: x[k].includes(id) ? x[k].filter((i: number) => i !== id) : [...x[k], id] }));
  return <Modal title={isNew ? "New user" : `Edit ${u.full_name}`} width={720} onClose={onClose} footer={<><Button kind="secondary" onClick={onClose}>Close</Button>
    <Button busy={busy} onClick={async () => {
      const body: any = { full_name: f.full_name, phone: f.phone, role_ids: f.role_ids, hotel_ids: f.hotel_ids, all_hotels: f.all_hotels };
      if (isNew) { body.email = f.email; if (f.password) body.password = f.password; }
      const r = await run(() => (isNew ? post("/api/admin/users", body) : patch(`/api/admin/users/${u.id}`, body)), "User saved");
      if (r) onSaved(r.temporary_password);
    }}>Save</Button></>}>
    <div className="form-grid">
      <Field label="Full name"><Input value={f.full_name} onChange={e => setF({ ...f, full_name: e.target.value })} /></Field>
      <Field label="Email"><Input type="email" value={f.email} disabled={!isNew} onChange={e => setF({ ...f, email: e.target.value })} /></Field>
      <Field label="Phone"><Input value={f.phone} onChange={e => setF({ ...f, phone: e.target.value })} /></Field>
      {isNew && <Field label="Initial password" hint="Leave blank to generate a temporary one"><Input type="password" value={f.password} onChange={e => setF({ ...f, password: e.target.value })} /></Field>}
    </div>
    <h4>Roles</h4>
    <div className="checks">{(roles.data?.items || []).map((r: any) => <label key={r.id} className="check"><input type="checkbox" checked={f.role_ids.includes(r.id)} onChange={() => toggle("role_ids", r.id)} /> {r.name}</label>)}</div>
    <h4>Hotel access</h4>
    {user!.all_hotels && <label className="check"><input type="checkbox" checked={f.all_hotels} onChange={e => setF({ ...f, all_hotels: e.target.checked })} /> All hotels in the organisation</label>}
    {!f.all_hotels && <div className="checks">{(hotels.data?.items || []).map((h: any) => <label key={h.id} className="check"><input type="checkbox" checked={f.hotel_ids.includes(h.id)} onChange={() => toggle("hotel_ids", h.id)} /> {h.name}</label>)}</div>}
  </Modal>;
}

function SessionsModal({ u, onClose }: any) {
  const st = useLoad(() => get(`/api/admin/users/${u.id}/sessions`), [u.id]);
  const { busy, run } = useAction();
  return <Modal title={`Active sessions — ${u.full_name}`} width={720} onClose={onClose}>
    <Loadable state={st}>{d => <Table rows={d.items} empty="No active sessions" cols={[
      { h: "Started", r: s => fmtDateTime(s.created_at) }, { h: "Last active", r: s => fmtDateTime(s.last_seen_at) }, { h: "IP", r: s => s.ip || "—" },
      { h: "Device", r: s => <span className="small">{(s.user_agent || "").slice(0, 60)}</span> },
      { h: "", r: s => <Button kind="danger" busy={busy} onClick={async () => { if (await run(() => post(`/api/admin/sessions/${s.id}/revoke`), "Session revoked")) st.reload(); }}>Revoke</Button> }]} />}</Loadable>
  </Modal>;
}

export function Roles() {
  const { can, user } = useAuth();
  const roles = useLoad(() => get("/api/admin/roles"), []);
  const perms = useLoad(() => get("/api/admin/permissions"), []);
  const [sel, setSel] = useState<any>(null);
  const [draft, setDraft] = useState<string[]>([]);
  const [newRole, setNewRole] = useState<string | null>(null);
  const { busy, run } = useAction();
  const modules = useMemo(() => {
    const m: Record<string, any[]> = {};
    (perms.data?.items || []).forEach((p: any) => { (m[p.module] = m[p.module] || []).push(p); });
    return m;
  }, [perms.data]);
  const editable = can("admin.roles.manage");
  return <div className="page">
    <div className="page-h"><div><h1>Roles & permissions</h1><p className="muted">Role templates for every hotel function. Custom roles are supported.</p></div>
      {editable && <Button onClick={() => setNewRole("")}>New role</Button>}</div>
    <div className="grid-side">
      <Card title="Roles"><Loadable state={roles}>{d => <div className="picklist">{d.items.map((r: any) =>
        <button key={r.id} className={sel?.id === r.id ? "on" : ""} onClick={() => { setSel(r); setDraft(r.permissions); }}>{r.name}<span className="muted small"> · {r.user_count} user(s){r.is_system ? "" : " · custom"}</span></button>)}</div>}</Loadable></Card>
      <Card title={sel ? sel.name : "Select a role"} actions={sel && editable && <Button busy={busy} onClick={async () => { if (await run(() => put(`/api/admin/roles/${sel.id}`, { permissions: draft }), "Role updated")) roles.reload(); }}>Save permissions</Button>}>
        {sel ? <div className="permgrid">{Object.entries(modules).map(([m, ps]) => <div key={m} className="permmod"><h4>{label(m)}</h4>
          {ps.map(p => <label key={p.code} className="check" title={p.code}><input type="checkbox" disabled={!editable || !user!.permissions.includes(p.code)} checked={draft.includes(p.code)}
            onChange={() => setDraft(d => (d.includes(p.code) ? d.filter(x => x !== p.code) : [...d, p.code]))} /> {p.description}</label>)}</div>)}</div>
          : <p className="muted">Choose a role to view or edit its permissions.</p>}
      </Card>
    </div>
    {newRole !== null && <Modal title="New role" onClose={() => setNewRole(null)} footer={<Button busy={busy} disabled={!newRole.trim()} onClick={async () => {
      const r = await run(() => post("/api/admin/roles", { name: newRole, permissions: [] }), "Role created"); if (r) { setNewRole(null); roles.reload(); }
    }}>Create</Button>}><Field label="Role name"><Input value={newRole} onChange={e => setNewRole(e.target.value)} /></Field></Modal>}
  </div>;
}

export function AuditLog() {
  const [tab, setTab] = useState("audit");
  const [f, setF] = useState({ entity: "", action: "", from: "", to: "" });
  const [page, setPage] = useState(1);
  useEffect(() => setPage(1), [f.entity, f.action, f.from, f.to]);
  const audit = useLoad(() => (tab === "audit" ? get("/api/admin/audit-logs", { ...f, page, page_size: 100 }) : get("/api/admin/login-attempts")), [tab, f.entity, f.action, f.from, f.to, page]);
  return <div className="page">
    <div className="page-h"><div><h1>Audit trail</h1><p className="muted">Append-only record of significant actions — cannot be edited or deleted</p></div></div>
    <Tabs tabs={[{ id: "audit", label: "Activity" }, { id: "logins", label: "Sign-in history" }]} value={tab} onChange={setTab} />
    {tab === "audit" && <div className="row gap-s wrap mb">
      <Select value={f.entity} onChange={e => setF({ ...f, entity: e.target.value })}><option value="">All records</option>
        {["reservation", "folio", "payment", "approval", "guest", "user", "role", "room", "hotel", "tax_rule", "journal_entry", "housekeeping_task", "session"].map(x => <option key={x} value={x}>{label(x)}</option>)}</Select>
      <Input placeholder="Action e.g. frontdesk.check_in" value={f.action} onChange={e => setF({ ...f, action: e.target.value })} />
      <Input type="date" value={f.from} onChange={e => setF({ ...f, from: e.target.value })} aria-label="From" />
      <Input type="date" value={f.to} onChange={e => setF({ ...f, to: e.target.value })} aria-label="To" /></div>}
    <Card pad={false}><Loadable state={audit}>{d => tab === "audit" ? <><Table rows={d.items} cols={[
      { h: "When", r: a => fmtDateTime(a.created_at) }, { h: "User", r: a => a.user_name || "System / guest" }, { h: "Action", r: a => <code>{a.action}</code> },
      { h: "Record", r: a => `${label(a.entity)} ${a.reference || a.entity_id || ""}` },
      { h: "Change", r: a => <details><summary className="small">view</summary>{a.old_value && <pre className="pre">before: {a.old_value}</pre>}{a.new_value && <pre className="pre">after: {a.new_value}</pre>}</details> },
      { h: "IP", r: a => a.ip || "—" }]} /><Pager page={d.page || 1} pages={d.pages || 1} total={d.total || 0} onPage={setPage} /></> : <Table rows={d.items} cols={[
      { h: "When", r: a => fmtDateTime(a.created_at) }, { h: "Email", r: a => a.email }, { h: "Result", r: a => <Pill s={a.success ? "approved" : "failed"} text={a.success ? "Success" : "Failed"} /> },
      { h: "Reason", r: a => label(a.reason) }, { h: "IP", r: a => a.ip || "—" }]} />}</Loadable></Card>
  </div>;
}
