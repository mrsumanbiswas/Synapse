import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getToken, onUnauthorized, setToken, type Role, type Session, type User } from "./api";

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (email: string, password: string) => Promise<User>;
  register: (name: string, email: string, password: string) => Promise<User>;
  logout: () => void;
  refresh: () => Promise<void>;
  can: (role: Role) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);
const RANK: Record<Role, number> = { viewer: 0, curator: 1, admin: 2 };

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(!getToken());
  const client = useQueryClient();

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    client.removeQueries({ queryKey: ["me"] });
  }, [client]);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setReady(true);
      return;
    }
    try {
      setUser(await api<User>("/auth/me"));
    } catch {
      setToken(null);
      setUser(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    onUnauthorized(logout);
    void refresh();
  }, [logout, refresh]);

  const startSession = useCallback((session: Session) => {
    setToken(session.access_token);
    setUser(session.user);
    return session.user;
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      user,
      ready,
      login: async (email, password) => startSession(await api<Session>("/auth/login", { method: "POST", json: { email, password } })),
      register: async (name, email, password) =>
        startSession(await api<Session>("/auth/register", { method: "POST", json: { name, email, password } })),
      logout,
      refresh,
      can: (role) => (user ? RANK[user.role] >= RANK[role] : false),
    }),
    [user, ready, startSession, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
