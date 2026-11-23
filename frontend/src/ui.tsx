import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { ApiError, label } from "./api";

// ---------------------------------------------------------------- toasts
type Toast = { id: number; kind: "success" | "error" | "info"; text: string };
const ToastCtx = createContext<(kind: Toast["kind"], text: string) => void>(() => {});
export const useToast = () => useContext(ToastCtx);
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setItems(i => [...i, { id, kind, text }]);
    setTimeout(() => setItems(i => i.filter(t => t.id !== id)), kind === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map(t => <div key={t.id} className={`toast toast-${t.kind}`} onClick={() => setItems(i => i.filter(x => x.id !== t.id))}>{t.text}</div>)}
      </div>
    </ToastCtx.Provider>
  );
}

export function errText(e: any): string {
  if (e instanceof ApiError) {
    if (e.details?.duplicates) return e.message;
    if (e.details?.reservations) return `${e.message} (${e.details.reservations.join(", ")})`;
    if (e.details?.balance !== undefined) return e.message;
    return e.message;
  }
  return e?.message || "Something went wrong";
}

// ---------------------------------------------------------------- data hook
export function useLoad<T>(fn: () => Promise<T>, deps: any[]): { data: T | null; error: string | null; loading: boolean; reload: () => void; setData: (d: T) => void } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    fn().then(d => { if (live) setData(d); }).catch(e => { if (live) setError(errText(e)); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, loading, reload: () => setN(x => x + 1), setData };
}

/** Wraps an async action with busy state and toast feedback. */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = useCallback(async <T,>(fn: () => Promise<T>, success?: string): Promise<T | undefined> => {
    setBusy(true);
    try {
      const r = await fn();
      if (success) toast("success", success);
      return r;
    } catch (e) {
      toast("error", errText(e));
      return undefined;
    } finally {
      setBusy(false);
    }
  }, [toast]);
  return { busy, run };
}

// ---------------------------------------------------------------- primitives
export function Button({ kind = "primary", busy, children, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { kind?: "primary" | "secondary" | "ghost" | "danger" | "gold"; busy?: boolean }) {
  return <button {...p} className={`btn btn-${kind} ${p.className || ""}`} disabled={busy || p.disabled}>{busy ? <span className="spinner sm" /> : null}{children}</button>;
}

export function Card({ title, actions, children, className, pad = true }: { title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={`card ${className || ""}`}>
      {(title || actions) && <header className="card-h"><h3>{title}</h3><div className="row gap-s">{actions}</div></header>}
      <div className={pad ? "card-b" : ""}>{children}</div>
    </section>
  );
}

export function Field({ label: l, hint, error, children, wide }: { label: string; hint?: string; error?: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <label className={`field ${wide ? "wide" : ""}`}>
      <span className="field-l">{l}</span>
      {children}
      {hint && !error && <span className="field-h">{hint}</span>}
      {error && <span className="field-e">{error}</span>}
    </label>
  );
}

export const Input = (p: React.InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={`input ${p.className || ""}`} />;
export const Select = (p: React.SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={`input ${p.className || ""}`} />;
export const Textarea = (p: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea rows={3} {...p} className={`input ${p.className || ""}`} />;

export function Spinner({ text }: { text?: string }) {
  return <div className="center pad-l muted"><span className="spinner" /> {text || "Loading…"}</div>;
}
export function Empty({ text, children }: { text: string; children?: React.ReactNode }) {
  return <div className="empty"><p>{text}</p>{children}</div>;
}
export function ErrorBox({ text, onRetry }: { text: string; onRetry?: () => void }) {
  return <div className="errorbox"><span>{text}</span>{onRetry && <Button kind="secondary" onClick={onRetry}>Retry</Button>}</div>;
}

export function Loadable<T>({ state, children }: { state: { data: T | null; error: string | null; loading: boolean; reload: () => void }; children: (d: T) => React.ReactNode }) {
  if (state.error) return <ErrorBox text={state.error} onRetry={state.reload} />;
  if (state.loading && !state.data) return <Spinner />;
  if (!state.data) return null;
  return <>{children(state.data)}</>;
}

const STATUS_CLASS: Record<string, string> = {
  available: "green", inspected: "green", confirmed: "blue", checked_in: "navy", occupied: "navy", reserved: "blue", in_house: "navy",
  tentative: "amber", waitlisted: "amber", enquiry: "grey", pending: "amber", in_progress: "violet", cleaning: "violet", completed: "teal", clean: "teal",
  dirty: "red", rejected: "red", cancelled: "grey", no_show: "red", checked_out: "grey", out_of_order: "red", out_of_service: "red", maintenance: "orange",
  blocked: "grey", vip_hold: "gold", active: "green", suspended: "amber", deactivated: "grey", open: "blue", closed: "grey", approved: "green",
  queued: "blue", sent: "green", failed: "red", not_configured: "amber",
  settled: "green", voided: "grey", merged: "grey", new: "amber", preparing: "violet", ready: "green", served: "grey", void: "grey",
  pending_approval: "amber", partially_received: "violet", received: "green", ordered: "teal", submitted: "amber", issued: "green",
  part_paid: "violet", paid: "green", posted: "green", draft: "amber", matched: "green", variance: "orange", no_po: "blue", selected: "green",
};
export function Pill({ s, text }: { s: string; text?: string }) {
  return <span className={`pill pill-${STATUS_CLASS[s] || "grey"}`}>{text || label(s)}</span>;
}

export function Modal({ title, onClose, children, footer, width = 560 }: { title: string; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode; width?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", k);
    ref.current?.querySelector<HTMLElement>("input,select,textarea,button")?.focus();
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" style={{ maxWidth: width }} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <header className="modal-h"><h3>{title}</h3><button className="x" onClick={onClose} aria-label="Close">×</button></header>
        <div className="modal-b">{children}</div>
        {footer && <footer className="modal-f">{footer}</footer>}
      </div>
    </div>
  );
}

export function Confirm({ title, text, confirmText = "Confirm", danger, onConfirm, onClose, needReason }: {
  title: string; text: React.ReactNode; confirmText?: string; danger?: boolean; needReason?: string;
  onConfirm: (reason: string) => Promise<any> | void; onClose: () => void;
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={title} onClose={onClose} width={460} footer={<>
      <Button kind="secondary" onClick={onClose}>Back</Button>
      <Button kind={danger ? "danger" : "primary"} busy={busy} disabled={!!needReason && !reason.trim()}
        onClick={async () => { setBusy(true); try { await onConfirm(reason.trim()); } finally { setBusy(false); } }}>{confirmText}</Button>
    </>}>
      <div className="stack">{text}{needReason && <Field label={needReason}><Textarea value={reason} onChange={e => setReason(e.target.value)} /></Field>}</div>
    </Modal>
  );
}

export function Tabs({ tabs, value, onChange }: { tabs: { id: string; label: React.ReactNode }[]; value: string; onChange: (id: string) => void }) {
  return <div className="tabs" role="tablist">{tabs.map(t => <button key={t.id} role="tab" aria-selected={value === t.id} className={value === t.id ? "on" : ""} onClick={() => onChange(t.id)}>{t.label}</button>)}</div>;
}

export function Kpi({ title, value, sub, tone }: { title: string; value: React.ReactNode; sub?: React.ReactNode; tone?: string }) {
  return <div className={`kpi ${tone ? "kpi-" + tone : ""}`}><div className="kpi-t">{title}</div><div className="kpi-v">{value}</div>{sub && <div className="kpi-s">{sub}</div>}</div>;
}

export function Table({ cols, rows, empty = "Nothing to show", onRow, rowKey }: {
  cols: { h: React.ReactNode; r: (row: any) => React.ReactNode; cls?: string }[]; rows: any[]; empty?: string; onRow?: (row: any) => void; rowKey?: (row: any) => any;
}) {
  if (!rows.length) return <Empty text={empty} />;
  return (
    <div className="table-wrap"><table className="table">
      <thead><tr>{cols.map((c, i) => <th key={i} className={c.cls}>{c.h}</th>)}</tr></thead>
      <tbody>{rows.map((row, i) => (
        <tr key={rowKey ? rowKey(row) : row.id ?? i} onClick={onRow ? () => onRow(row) : undefined} className={onRow ? "clickable" : ""}
          tabIndex={onRow ? 0 : undefined} onKeyDown={onRow ? e => { if (e.key === "Enter") onRow(row); } : undefined}>
          {cols.map((c, j) => <td key={j} className={c.cls}>{c.r(row)}</td>)}
        </tr>))}
      </tbody>
    </table></div>
  );
}

// ---------------------------------------------------------------- charts (SVG, no dependency)
export function LineChart({ data, series, height = 200, fmt = (v: number) => String(v) }: {
  data: any[]; series: { key: string; label: string; color: string }[]; height?: number; fmt?: (v: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const w = 640, pad = { l: 46, r: 10, t: 10, b: 24 };
  const max = Math.max(1, ...data.flatMap(d => series.map(s => d[s.key] || 0)));
  const x = (i: number) => pad.l + (i * (w - pad.l - pad.r)) / Math.max(1, data.length - 1);
  const y = (v: number) => pad.t + (1 - v / max) * (height - pad.t - pad.b);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map(f => f * max);
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${w} ${height}`} role="img" aria-label={series.map(s => s.label).join(", ")} onMouseLeave={() => setHover(null)}>
        {ticks.map((t, i) => <g key={i}><line x1={pad.l} x2={w - pad.r} y1={y(t)} y2={y(t)} className="grid" /><text x={pad.l - 6} y={y(t) + 4} textAnchor="end" className="axis">{fmt(t)}</text></g>)}
        {data.map((d, i) => { const st = Math.ceil(data.length / 8); const last = i === data.length - 1 && (data.length - 1) % st >= st / 2;
          return (i % st === 0 || last) && <text key={i} x={x(i)} y={height - 6} textAnchor="middle" className="axis">{String(d.label).slice(5)}</text>; })}
        {series.map(s => <polyline key={s.key} fill="none" stroke={s.color} strokeWidth={2.2} points={data.map((d, i) => `${x(i)},${y(d[s.key] || 0)}`).join(" ")} />)}
        {data.map((_, i) => <rect key={i} x={x(i) - (w / data.length) / 2} y={0} width={w / data.length} height={height} fill="transparent" onMouseEnter={() => setHover(i)} />)}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={height - pad.b} className="hoverline" />}
        {hover !== null && series.map(s => <circle key={s.key} cx={x(hover)} cy={y(data[hover][s.key] || 0)} r={4} fill={s.color} />)}
      </svg>
      <div className="legend">{series.map(s => <span key={s.key}><i style={{ background: s.color }} />{s.label}{hover !== null ? `: ${fmt(data[hover][s.key] || 0)}` : ""}</span>)}
        {hover !== null && <span className="muted">{data[hover].label}</span>}</div>
    </div>
  );
}

export function BarList({ items, fmt = (v: number) => String(v), color = "var(--navy)" }: { items: { label: string; value: number }[]; fmt?: (v: number) => string; color?: string }) {
  const max = Math.max(1, ...items.map(i => i.value));
  if (!items.length) return <Empty text="No data yet" />;
  return <div className="barlist">{items.map(i => (
    <div key={i.label} className="barlist-row"><span className="barlist-l">{i.label}</span>
      <span className="barlist-bar"><i style={{ width: `${(i.value / max) * 100}%`, background: color }} /></span><span className="barlist-v">{fmt(i.value)}</span></div>))}
  </div>;
}

/** Page navigation for lists the server returns a page at a time ({ total, page, pages }). */
export function Pager({ page, pages, total, onPage }: { page: number; pages: number; total: number; onPage: (p: number) => void }) {
  if (!total || pages <= 1) return total ? <div className="pager muted small">{total} result{total === 1 ? "" : "s"}</div> : null;
  return (
    <nav className="pager" aria-label="Pages">
      <Button kind="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page">‹</Button>
      <span className="small">Page {page} of {pages} · {total} results</span>
      <Button kind="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page">›</Button>
    </nav>
  );
}
