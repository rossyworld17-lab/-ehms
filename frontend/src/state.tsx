import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, get, setToken, setUnauthorizedHandler, getToken } from "./api";

export type Hotel = { id: number; code: string; name: string; currency: string; timezone: string; logo_url?: string | null };
export type User = {
  id: number; email: string; full_name: string; permissions: string[]; roles: { id: number; code: string; name: string }[];
  hotels: Hotel[]; mfa_enabled: boolean; must_change_password: number; all_hotels: boolean; language?: string; mfa_enrollment_required?: boolean; mfa_policy?: string;
};

type Auth = {
  user: User | null; ready: boolean; hotel: Hotel | null; setHotelId: (id: number) => void;
  can: (p: string) => boolean; signIn: (token: string, user: User) => void; signOut: () => Promise<void>; refresh: () => Promise<void>;
};
const Ctx = createContext<Auth>(null as any);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [hotelId, setHotelIdState] = useState<number | null>(() => {
    try { const v = localStorage.getItem("ehms.hotel"); return v ? Number(v) : null; } catch { return null; }
  });

  const clear = useCallback(() => { setToken(null); setUser(null); }, []);
  useEffect(() => { setUnauthorizedHandler(clear); }, [clear]);

  const refresh = useCallback(async () => {
    if (!getToken()) { setReady(true); return; }
    try { setUser(await get<User>("/api/auth/me")); } catch { clear(); } finally { setReady(true); }
  }, [clear]);
  useEffect(() => { refresh(); }, [refresh]);

  const hotel = useMemo(() => {
    if (!user || !user.hotels.length) return null;
    return user.hotels.find(h => h.id === hotelId) || user.hotels[0];
  }, [user, hotelId]);

  const value: Auth = {
    user, ready, hotel,
    setHotelId: (id: number) => { setHotelIdState(id); try { localStorage.setItem("ehms.hotel", String(id)); } catch { /* ignore */ } },
    can: (p: string) => !!user && user.permissions.includes(p),
    signIn: (t: string, u: User) => { setToken(t); setUser(u); },
    signOut: async () => { try { await api("POST", "/api/auth/logout"); } catch { /* already gone */ } clear(); location.hash = "#/login"; },
    refresh,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

// ---------------------------------------------------------------- hash router
export function useRoute(): [string, URLSearchParams] {
  const read = () => {
    const h = location.hash.replace(/^#/, "") || "/";
    const [path, q = ""] = h.split("?");
    return [path, new URLSearchParams(q)] as [string, URLSearchParams];
  };
  const [r, setR] = useState(read);
  useEffect(() => {
    const on = () => setR(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return r;
}
export const navigate = (to: string) => { location.hash = to.startsWith("#") ? to : "#" + to; };
