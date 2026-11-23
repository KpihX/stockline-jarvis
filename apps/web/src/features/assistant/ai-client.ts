/** AI service client (proxied at /ai → :4100): health query, chat SSE stream, history rebuild from events. */
import { useQuery } from "@tanstack/react-query";
import type {
  ChatRequest, ChatStreamEvent, DashboardSuggestionsPayload, SessionDetail, SessionSummary,
} from "@kit/shared";
import { AI_BASE } from "@/lib/api";
import { auth } from "@/features/auth/auth-store";
import { callerWire } from "./caller";

function aiHeaders(extra?: Record<string, string>): Record<string, string> {
  const tok = auth.token();
  const c = callerWire();
  return {
    ...(tok ? { Authorization: `Bearer ${tok}` } : {}),
    ...(c.role && c.role !== "unknown" ? { "x-caller-role": c.role } : {}),
    ...(c.clientId ? { "x-caller-client-id": c.clientId } : {}),
    ...(c.supplierId ? { "x-caller-supplier-id": c.supplierId } : {}),
    ...(c.actorName ? { "x-actor-name": encodeURIComponent(c.actorName) } : {}),
    ...extra,
  };
}

export async function listAiSessions(q = ""): Promise<SessionSummary[]> {
  const sp = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
  const res = await fetch(`${AI_BASE}/sessions${sp}`, { headers: aiHeaders() });
  if (!res.ok) return [];
  return (await res.json()) as SessionSummary[];
}

export async function createAiSession(surface: "chat" | "voice", title?: string): Promise<SessionDetail> {
  const res = await fetch(`${AI_BASE}/sessions`, {
    method: "POST",
    headers: aiHeaders({ "content-type": "application/json" }),
    body: JSON.stringify({ surface, ...(title ? { title } : {}) }),
  });
  if (!res.ok) throw new Error(`Erreur création session (${res.status})`);
  return (await res.json()) as SessionDetail;
}

export async function getAiSession(id: string): Promise<SessionDetail | null> {
  const res = await fetch(`${AI_BASE}/sessions/${encodeURIComponent(id)}`, { headers: aiHeaders() });
  if (!res.ok) return null;
  return (await res.json()) as SessionDetail;
}

export async function renameAiSession(id: string, title: string): Promise<SessionDetail | null> {
  const res = await fetch(`${AI_BASE}/sessions/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: aiHeaders({ "content-type": "application/json" }),
    body: JSON.stringify({ title }),
  });
  if (!res.ok) return null;
  return (await res.json()) as SessionDetail;
}

export async function reopenAiSession(id: string): Promise<SessionDetail | null> {
  const res = await fetch(`${AI_BASE}/sessions/${encodeURIComponent(id)}/reopen`, {
    method: "POST",
    headers: aiHeaders(),
  });
  if (!res.ok) return null;
  return (await res.json()) as SessionDetail;
}

export async function deleteAiSession(id: string): Promise<boolean> {
  const res = await fetch(`${AI_BASE}/sessions/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: aiHeaders(),
  });
  return res.ok;
}

export async function fetchAiSuggestions(seed = 0, live = true): Promise<DashboardSuggestionsPayload> {
  const res = await fetch(`${AI_BASE}/suggestions?seed=${seed}&live=${live ? 1 : 0}`, { headers: aiHeaders() });
  if (!res.ok) throw new Error(`Suggestions indisponibles (${res.status})`);
  return (await res.json()) as DashboardSuggestionsPayload;
}

export interface AiHealth {
  ok: boolean;
  llm: { provider: string; model?: string };
  stt: { provider: string };
  tts: { provider: string };
}

export class AiUnavailableError extends Error {}

export async function fetchAiHealth(signal?: AbortSignal): Promise<AiHealth> {
  let res: Response;
  try {
    res = await fetch(`${AI_BASE}/health`, { signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new AiUnavailableError("Service IA injoignable");
  }
  if (!res.ok) throw new AiUnavailableError(`Service IA injoignable (${res.status})`);
  return (await res.json()) as AiHealth;
}

/** GET /ai/health, polled slowly so the panel recovers on its own once the service starts. */
export const useAiHealth = () =>
  useQuery({
    queryKey: ["ai", "health"],
    queryFn: ({ signal }) => fetchAiHealth(signal),
    retry: false,
    refetchInterval: (q) => (q.state.status === "error" ? 5_000 : 60_000),
    staleTime: 30_000,
  });

/** POST /ai/chat and call onEvent for each SSE `data:` line. Resolves when the stream ends. */
export async function streamChat(req: ChatRequest, onEvent: (e: ChatStreamEvent) => void, signal?: AbortSignal): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${AI_BASE}/chat`, {
      method: "POST",
      headers: aiHeaders({ "content-type": "application/json", accept: "text/event-stream" }),
      body: JSON.stringify(req),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new AiUnavailableError("Service IA injoignable (localhost:4100)");
  }
  if (!res.ok || !res.body) {
    let msg = `Service IA : erreur ${res.status}`;
    try {
      const j = await res.json();
      if (j?.error?.message) msg = j.error.message;
    } catch { /* not JSON */ }
    throw res.status >= 500 ? new AiUnavailableError(msg) : new Error(msg);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let i: number;
    while ((i = buf.search(/\r?\n\r?\n/)) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i).replace(/^\r?\n\r?\n/, "");
      const data = block.split(/\r?\n/).filter((l) => l.startsWith("data:")).map((l) => l.slice(5).replace(/^ /, "")).join("\n");
      if (!data) continue;
      try {
        onEvent(JSON.parse(data) as ChatStreamEvent);
      } catch { /* ignore malformed line */ }
    }
  }
}

export { TurnRecorder } from "./turn-recorder";
