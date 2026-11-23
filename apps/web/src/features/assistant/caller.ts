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
const ROLES: CallerRole[] = ["unknown", "client", "supplier", "manager", "admin", "sales", "direction"];

export const ROLE_LABEL: Record<CallerRole, string> = {
  unknown: "Non identifié",
  client: "Client",
  supplier: "Fournisseur",
  manager: "Commercial",
  admin: "Direction",
  sales: "Commercial",
  direction: "Direction",
};
export const ROLE_HELP: Record<CallerRole, string> = {
  unknown: "Catalogue, produits et prix catalogue seulement. Aucune écriture.",
  client: "Son compte seulement : ses commandes, ses habitudes et tarifs. Rien sur les autres clients ni les fournisseurs.",
  supplier: "Sa fiche fournisseur et ses bons d'achat seulement. Aucune donnée client ni prix de vente.",
  manager: "Accès complet au métier ERP (clients, stocks, achats, commandes, tournées).",
  admin: "Accès complet à l'ERP + gestion de l'administrateur unique et des comptes.",
  sales: "Accès complet à l'ERP.",
  direction: "Accès complet à l'ERP.",
};

/** What the user picked, shape-checked. */
function normalise(c: Partial<CallerIdentity> | undefined): CallerIdentity {
  const rawRole = ROLES.includes(c?.role as CallerRole) ? (c!.role as CallerRole) : "unknown";
  const role: CallerRole = rawRole === "sales" ? "manager" : rawRole === "direction" ? "admin" : rawRole;
  const clientId = typeof c?.clientId === "string" && /^cli_\d+$/.test(c.clientId) ? c.clientId : undefined;
  const supplierId = typeof c?.supplierId === "string" && /^sup_\d+$/.test(c.supplierId) ? c.supplierId : undefined;
  const actorName = typeof c?.actorName === "string" && c.actorName.trim() ? c.actorName.trim().slice(0, 80) : undefined;
  const verified = Boolean(c?.verified);
  if (role === "unknown") return { role };
  return {
    role,
    ...(clientId ? { clientId } : {}),
    ...(supplierId ? { supplierId } : {}),
    ...(actorName ? { actorName } : {}),
    ...(verified ? { verified } : {}),
  };
}

/** What goes on the wire, and what the server will enforce. */
export function effective(c: CallerIdentity): CallerIdentity {
  if (c.role === "client" && !c.clientId) return { role: "unknown" };
  if (c.role === "supplier" && !c.supplierId) return { role: "unknown" };
  return { ...c };
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

/** What goes on the wire (start message, chat / command body): the EFFECTIVE identity, optional fields left out. */
export const callerWire = (c: CallerIdentity = state): CallerIdentity => effective(c);

/** Short label for the badge: « Client · Le Refuge Payet », « Commercial · Thibault », « Non identifié ». */
export function callerLabel(c: CallerIdentity): string {
  if (c.role === "client" && !c.clientId) return "Client · à choisir";
  return c.role === "unknown" ? ROLE_LABEL.unknown : c.actorName ? `${ROLE_LABEL[c.role]} · ${c.actorName}` : ROLE_LABEL[c.role];
}
