/**
 * Who is on the line — the DECLARED identity, shared by the voice call, the chat panel and the voice command.
 *
 * The hackathon has no telephony / caller-ID, so the person running the demo picks who is calling (CallerBadge). The AI service
 * does not take this on faith for what the MODEL says: it enforces what the role may do (apps/ai/app/policy.py). Production would
 * replace this selector by caller-ID / authentication; nothing else would change.
 * Persisted in localStorage (last choice survives a reload). Module-level store, like chat-store.
 */
import { useSyncExternalStore } from "react";
import type { CallerIdentity, CallerRole } from "@kit/shared";

const KEY = "kit.caller";
const ROLES: CallerRole[] = ["unknown", "client", "sales", "direction"];

export const ROLE_LABEL: Record<CallerRole, string> = { unknown: "Non identifié", client: "Client", sales: "Commercial", direction: "Direction" };
export const ROLE_HELP: Record<CallerRole, string> = {
  unknown: "Catalogue, produits et prix catalogue seulement. Aucune écriture.",
  client: "Son compte seulement : ses commandes, ses habitudes. Rien sur les autres clients ni les fournisseurs.",
  sales: "Accès complet à l'ERP.",
  direction: "Accès complet à l'ERP.",
};

/** A client without a client id is nobody: same normalisation as the server (Caller.declare). */
function normalise(c: Partial<CallerIdentity> | undefined): CallerIdentity {
  const role = ROLES.includes(c?.role as CallerRole) ? (c!.role as CallerRole) : "unknown";
  const clientId = typeof c?.clientId === "string" && /^cli_\d+$/.test(c.clientId) ? c.clientId : undefined;
  const actorName = typeof c?.actorName === "string" && c.actorName.trim() ? c.actorName.trim().slice(0, 80) : undefined;
  if (role === "unknown" || (role === "client" && !clientId)) return { role: "unknown" };
  return { role, ...(clientId ? { clientId } : {}), ...(actorName ? { actorName } : {}) };
}

function load(): CallerIdentity {
  try {
    return normalise(JSON.parse(localStorage.getItem(KEY) ?? "null") ?? undefined);
  } catch {
    return { role: "unknown" };
  }
}

let state: CallerIdentity = load();
const listeners = new Set<() => void>();

export const caller = {
  get: () => state,
  set(next: Partial<CallerIdentity>) {
    const n = normalise(next);
    if (JSON.stringify(n) === JSON.stringify(state)) return;
    state = n;
    try { localStorage.setItem(KEY, JSON.stringify(n)); } catch { /* private mode: keep it in memory */ }
    listeners.forEach((l) => l());
  },
  subscribe(l: () => void) {
    listeners.add(l);
    return () => { listeners.delete(l); };
  },
};

export const useCaller = (): CallerIdentity => useSyncExternalStore(caller.subscribe, caller.get);

/** What goes on the wire (start message, chat / command body): optional fields left out. */
export const callerWire = (c: CallerIdentity = state): CallerIdentity => ({ ...c });

/** Short label for the badge: « Client · Le Refuge Payet », « Commercial · Thibault », « Non identifié ». */
export function callerLabel(c: CallerIdentity): string {
  return c.role === "unknown" ? ROLE_LABEL.unknown : c.actorName ? `${ROLE_LABEL[c.role]} · ${c.actorName}` : ROLE_LABEL[c.role];
}
