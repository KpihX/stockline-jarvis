/**
 * Unified active sessionId shared by Assistant (chat) and Voix (/voice).
 * Persisted in localStorage so switching surface or reloading the page keeps the exact same conversation.
 */
import { useSyncExternalStore } from "react";
import type { SessionDetail, SessionSummary } from "@kit/shared";
import { createAiSession, deleteAiSession, getAiSession, listAiSessions, renameAiSession, reopenAiSession } from "./ai-client";

const SID_KEY = "kit.activeSessionId";

interface SessionState {
  activeId: string | null;
  list: SessionSummary[];
  activeDetail: SessionDetail | null;
  loading: boolean;
  pendingVoiceText: string | null;
}

function loadSid(): string | null {
  try {
    return localStorage.getItem(SID_KEY) || null;
  } catch {
    return null;
  }
}

let state: SessionState = {
  activeId: loadSid(),
  list: [],
  activeDetail: null,
  loading: false,
  pendingVoiceText: null,
};
const listeners = new Set<() => void>();

function set(patch: Partial<SessionState>) {
  state = { ...state, ...patch };
  if ("activeId" in patch) {
    try {
      if (state.activeId) localStorage.setItem(SID_KEY, state.activeId);
      else localStorage.removeItem(SID_KEY);
    } catch { /* ignore */ }
  }
  listeners.forEach((l) => l());
}

export const sessionsStore = {
  get: () => state,
  activeId: () => state.activeId,
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  },
  setActiveId(id: string | null) {
    if (id !== state.activeId) set({ activeId: id });
  },
  setPendingVoiceText(text: string | null) {
    set({ pendingVoiceText: text });
  },
  consumePendingVoiceText(): string | null {
    const t = state.pendingVoiceText;
    if (t) set({ pendingVoiceText: null });
    return t;
  },
  async refresh(q = ""): Promise<SessionSummary[]> {
    set({ loading: true });
    try {
      const list = await listAiSessions(q);
      set({ list, loading: false });
      return list;
    } catch {
      set({ loading: false });
      return state.list;
    }
  },
  async ensure(surface: "chat" | "voice"): Promise<string> {
    if (state.activeId) {
      const d = await getAiSession(state.activeId);
      if (d) {
        set({ activeDetail: d });
        return d.id;
      }
    }
    const created = await createAiSession(surface);
    set({ activeId: created.id, activeDetail: created, list: [created, ...state.list] });
    return created.id;
  },
  async createNew(surface: "chat" | "voice", title?: string): Promise<SessionDetail> {
    const created = await createAiSession(surface, title);
    set({ activeId: created.id, activeDetail: created, list: [created, ...state.list.filter((x) => x.id !== created.id)] });
    return created;
  },
  async open(id: string): Promise<SessionDetail | null> {
    const d = await reopenAiSession(id);
    if (!d) return null;
    set({ activeId: d.id, activeDetail: d });
    void sessionsStore.refresh();
    return d;
  },
  async rename(id: string, title: string): Promise<void> {
    const d = await renameAiSession(id, title);
    if (!d) return;
    set({
      activeDetail: state.activeId === id ? d : state.activeDetail,
      list: state.list.map((s) => (s.id === id ? d : s)),
    });
  },
  async remove(id: string): Promise<void> {
    const ok = await deleteAiSession(id);
    if (!ok) return;
    const nextList = state.list.filter((s) => s.id !== id);
    const nextId = state.activeId === id ? (nextList[0]?.id ?? null) : state.activeId;
    set({ list: nextList, activeId: nextId, activeDetail: state.activeId === id ? null : state.activeDetail });
  },
};

export const useSessions = () => useSyncExternalStore(sessionsStore.subscribe, sessionsStore.get);
