/**
 * Verified session authentication store (Bearer token + Account in localStorage).
 * Syncs the AI caller identity automatically so Web UI, Assistant, Voice and API always agree on who is connected.
 */
import { useSyncExternalStore } from "react";
import type { Account, AuthRole, DemoAccount, LoginResponse } from "@kit/shared";
import { caller } from "@/features/assistant/caller";

const AUTH_KEY = "kit.auth.v1";

interface AuthState {
  token: string | null;
  account: Account | null;
  checking: boolean;
}

function loadInitial(): AuthState {
  try {
    const raw = JSON.parse(localStorage.getItem(AUTH_KEY) ?? "null");
    if (raw && typeof raw.token === "string" && raw.account?.role) {
      return { token: raw.token, account: raw.account as Account, checking: false };
    }
  } catch { /* ignore storage errors */ }
  return { token: null, account: null, checking: false };
}

let state: AuthState = loadInitial();
const listeners = new Set<() => void>();

function syncCaller(acc: Account | null) {
  if (!acc) {
    caller.set({ role: "unknown" });
    return;
  }
  caller.set({
    role: acc.role,
    clientId: acc.role === "client" ? (acc.entityId ?? undefined) : undefined,
    supplierId: acc.role === "supplier" ? (acc.entityId ?? undefined) : undefined,
    actorName: acc.displayName,
    verified: true,
  });
}

// Keep caller synced on cold boot from persisted localStorage
syncCaller(state.account);

function persist(next: AuthState) {
  state = next;
  try {
    if (next.token && next.account) {
      localStorage.setItem(AUTH_KEY, JSON.stringify({ token: next.token, account: next.account }));
    } else {
      localStorage.removeItem(AUTH_KEY);
    }
  } catch { /* private mode */ }
  syncCaller(next.account);
  listeners.forEach((l) => l());
}

export const auth = {
  get: () => state,
  token: () => state.token,
  account: () => state.account,
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  },
  setSession(res: LoginResponse) {
    persist({ token: res.token, account: res.account, checking: false });
  },
  clear() {
    persist({ token: null, account: null, checking: false });
  },
  async login(username: string, password: string): Promise<Account> {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      let msg = "Identifiant ou mot de passe incorrect.";
      try {
        const j = await res.json();
        if (j?.error?.message) msg = j.error.message;
      } catch { /* ignore */ }
      throw new Error(msg);
    }
    const data = (await res.json()) as LoginResponse;
    persist({ token: data.token, account: data.account, checking: false });
    return data.account;
  },
  async loginDemo(demo: DemoAccount): Promise<Account> {
    return auth.login(demo.username, demo.demoPassword);
  },
  async logout(): Promise<void> {
    const tok = state.token;
    persist({ token: null, account: null, checking: false });
    if (tok) {
      try {
        await fetch("/api/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${tok}` } });
      } catch { /* ignore */ }
    }
  },
  async refreshMe(): Promise<Account | null> {
    if (!state.token) return null;
    try {
      const res = await fetch("/api/auth/me", { headers: { Authorization: `Bearer ${state.token}` } });
      if (!res.ok) {
        persist({ token: null, account: null, checking: false });
        return null;
      }
      const acc = (await res.json()) as Account;
      persist({ token: state.token, account: acc, checking: false });
      return acc;
    } catch {
      return state.account;
    }
  },
};

export const useAuth = () => useSyncExternalStore(auth.subscribe, auth.get);

/** Routes allowed per role. `client` and `supplier` are strictly scoped to their domain. */
export function canVisitRoute(role: AuthRole | undefined, path: string, entityId?: string | null): boolean {
  if (!role) return path.startsWith("/login");
  if (role === "admin") return true;
  if (role === "manager") return !path.startsWith("/accounts");
  if (role === "client") {
    if (path === "/" || path === "/voice" || path === "/prices" || path === "/history" || path === "/products" || path === "/stock") return true;
    if (path.startsWith("/orders") || path.startsWith("/invoices") || path.startsWith("/payments") || path.startsWith("/products/")) return true;
    if (path === "/clients") return true; // redirected to own client detail
    if (path.startsWith("/clients/")) return !entityId || path === `/clients/${entityId}`;
    return false;
  }
  if (role === "supplier") {
    if (path === "/" || path === "/voice" || path === "/products" || path === "/stock") return true;
    if (path.startsWith("/purchase-orders") || path.startsWith("/products/")) return true;
    if (path === "/suppliers") return true; // redirected to own supplier detail
    if (path.startsWith("/suppliers/")) return !entityId || path === `/suppliers/${entityId}`;
    return false;
  }
  return false;
}

export const AUTH_ROLE_LABEL: Record<AuthRole, string> = {
  client: "Client",
  supplier: "Fournisseur",
  manager: "Commercial",
  admin: "Admin unique",
};
