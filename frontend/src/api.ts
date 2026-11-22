// API client: token handling, JSON requests, typed errors, file downloads.

export class ApiError extends Error {
  status: number;
  code: string;
  details: any;
  constructor(status: number, code: string, message: string, details?: any) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const TOKEN_KEY = "ehms.token";
let token: string | null = (() => {
  try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
})();
let onUnauthorized: (() => void) | null = null;

export function setToken(t: string | null) {
  token = t;
  try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* storage unavailable */ }
}
export const getToken = () => token;
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn; }

export async function api<T = any>(method: string, path: string, body?: any, opts: { auth?: boolean } = {}): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (opts.auth !== false && token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "network", "Cannot reach the server. Check your connection and try again.");
  }
  const text = await res.text();
  const data = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) {
    const e = data && data.error ? data.error : { code: "http_" + res.status, message: res.statusText || "Request failed" };
    if (res.status === 401 && opts.auth !== false && onUnauthorized && !["invalid_credentials", "invalid_mfa_code"].includes(e.code)) onUnauthorized();
    throw new ApiError(res.status, e.code, e.message, e.details);
  }
  return data as T;
}

export const get = <T = any>(p: string, q?: Record<string, any>) => api<T>("GET", q ? `${p}?${qs(q)}` : p);
export const post = <T = any>(p: string, b: any = {}) => api<T>("POST", p, b);
export const patch = <T = any>(p: string, b: any = {}) => api<T>("PATCH", p, b);
export const del = <T = any>(p: string, b?: any) => api<T>("DELETE", p, b);
export const put = <T = any>(p: string, b: any = {}) => api<T>("PUT", p, b);

export function qs(q: Record<string, any>) {
  return Object.entries(q).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&");
}

/** Download/open an authenticated file (PDF, XLSX, CSV). */
export async function openFile(path: string, filename: string, inline = false) {
  const res = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    let msg = "Download failed";
    try { msg = (await res.json()).error.message; } catch { /* not json */ }
    throw new ApiError(res.status, "download_failed", msg);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  if (inline) {
    const w = window.open(url, "_blank");
    if (!w) triggerDownload(url, filename);
  } else triggerDownload(url, filename);
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
function triggerDownload(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
}

// ---------------------------------------------------------------- formatting
export function money(minor: number | null | undefined, currency = "NGN") {
  const v = (minor || 0) / 100;
  try {
    return new Intl.NumberFormat("en-NG", { style: "currency", currency, minimumFractionDigits: 2 }).format(v);
  } catch {
    return `${currency} ${v.toFixed(2)}`;
  }
}
/** Convert a user-entered major-unit amount ("12,500.50") to minor units (1250050). */
export function toMinor(input: string | number): number {
  const s = String(input).replace(/[,\s₦]/g, "");
  if (!/^-?\d+(\.\d{0,2})?$/.test(s)) return NaN;
  const [w, f = ""] = s.split(".");
  const sign = w.startsWith("-") ? -1 : 1;
  return sign * (Math.abs(parseInt(w, 10)) * 100 + parseInt((f + "00").slice(0, 2), 10));
}
export const fromMinor = (m: number | null | undefined) => (m == null ? "" : (m / 100).toFixed(2));

export function fmtDate(d?: string | null) {
  if (!d) return "—";
  const dt = new Date(d.length === 10 ? d + "T00:00:00" : d);
  return dt.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric" });
}
export function fmtDateTime(d?: string | null) {
  if (!d) return "—";
  return new Date(d).toLocaleString("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
export function addDays(iso: string, n: number) {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
export const label = (s?: string | null) => (s || "").replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
export const uid = () => (crypto as any).randomUUID ? (crypto as any).randomUUID() : Math.random().toString(36).slice(2) + Date.now().toString(36);
