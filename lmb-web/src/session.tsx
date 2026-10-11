import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, setCsrf } from "./api";
import type { Catalog, Me } from "./types";

interface Ctx {
  me: Me | null;
  catalog: Catalog | null;
  needTotp: boolean;
  ready: boolean;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
}

const SessionCtx = createContext<Ctx | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [needTotp, setNeedTotp] = useState(false);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const m = await api.get<Me>("/auth/me");
      setCsrf(m.csrf_token);
      setMe(m);
      try {
        setCatalog(await api.get<Catalog>("/catalog"));
        setNeedTotp(false);
      } catch (e) {
        if (e instanceof ApiError && e.status === 403 && !m.totp_enabled) setNeedTotp(true);
      }
    } catch {
      setMe(null);
      setCsrf(null);
    } finally {
      setReady(true);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout");
    } finally {
      setMe(null);
      setCatalog(null);
      setCsrf(null);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return <SessionCtx.Provider value={{ me, catalog, needTotp, ready, refresh, logout }}>{children}</SessionCtx.Provider>;
}

export function useSession(): Ctx {
  const c = useContext(SessionCtx);
  if (!c) throw new Error("SessionProvider отсутствует");
  return c;
}
