/**
 * Chat conversation unified with the server session store (`sessions-store.ts`), shared with /voice.
 * Sending sends only `{ sessionId, messages: [latestUserMessage], currentPath }` — the server owns history & compaction.
 */
import { useSyncExternalStore } from "react";
import type { ChatMessage, ChatStreamEvent, SessionDetail } from "@kit/shared";
import { AiUnavailableError, getAiSession, streamChat, TurnRecorder } from "./ai-client";
import { caller, callerWire } from "./caller";
import { sessionsStore } from "./sessions-store";
import type { ToolRun } from "./tools";

export type Part = { kind: "text"; text: string } | { kind: "tool"; tool: ToolRun };

export type ChatItem =
  | { id: string; role: "user"; text: string; at: number }
  | { id: string; role: "assistant"; parts: Part[]; status: "streaming" | "done" | "error" | "stopped"; error?: string; ms?: number; at: number };

interface ChatState {
  items: ChatItem[];
  busy: boolean;
  unavailable: boolean;
  sessionId: string | null;
}

let state: ChatState = { items: [], busy: false, unavailable: false, sessionId: sessionsStore.activeId() };
let history: ChatMessage[] = [];
let controller: AbortController | undefined;
const listeners = new Set<() => void>();
let seq = 0;
let generation = 0;
const uid = () => `m${++seq}`;

function set(patch: Partial<ChatState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

function itemsFromDetail(d: SessionDetail): ChatItem[] {
  const out: ChatItem[] = [];
  const now = Date.now();
  for (const m of d.messages) {
    if (m.role === "user") {
      const clean = m.text.split("\n\n[", 1)[0].trim();
      if (clean) out.push({ id: uid(), role: "user", text: clean, at: now });
    } else if (m.role === "assistant" && m.text.trim()) {
      out.push({ id: uid(), role: "assistant", parts: [{ kind: "text", text: m.text }], status: "done", at: now });
    }
  }
  return out;
}

function updateAssistant(id: string, fn: (a: Extract<ChatItem, { role: "assistant" }>) => Extract<ChatItem, { role: "assistant" }>) {
  set({ items: state.items.map((it) => (it.id === id && it.role === "assistant" ? fn(it) : it)) });
}

function applyEvent(id: string, e: ChatStreamEvent) {
  updateAssistant(id, (a) => {
    const parts = [...a.parts];
    const last = parts[parts.length - 1];
    switch (e.type) {
      case "text":
        if (last?.kind === "text") parts[parts.length - 1] = { kind: "text", text: last.text + e.delta };
        else parts.push({ kind: "text", text: e.delta });
        return { ...a, parts };
      case "tool_call":
        parts.push({ kind: "tool", tool: { id: e.call.id, name: e.call.name, args: e.call.arguments } });
        return { ...a, parts };
      case "tool_result":
        return {
          ...a,
          parts: parts.map((p) => (p.kind === "tool" && p.tool.id === e.callId ? { kind: "tool", tool: { ...p.tool, ok: e.ok, ms: e.ms, result: e.result } } : p)),
        };
      case "done":
        if (!parts.some((p) => p.kind === "text") && e.message.content) parts.push({ kind: "text", text: e.message.content });
        return { ...a, parts, status: "done", ms: e.ms };
      case "error":
        return { ...a, status: "error", error: e.message };
    }
  });
}

export const chat = {
  async send(text: string) {
    const content = text.trim();
    if (!content || state.busy) return;
    // Mark busy immediately so concurrent syncFromActive() when opening the panel never clobbers the in-flight send.
    set({ busy: true, unavailable: false });
    const sid = await sessionsStore.ensure("chat");
    const detail = sessionsStore.get().activeDetail;
    const baseItems = (state.sessionId !== sid || state.items.length === 0) && detail && detail.id === sid
      ? itemsFromDetail(detail)
      : state.items;
    const assistantId = uid();
    set({
      sessionId: sid,
      busy: true,
      unavailable: false,
      items: [
        ...baseItems,
        { id: uid(), role: "user", text: content, at: Date.now() },
        { id: assistantId, role: "assistant", parts: [], status: "streaming", at: Date.now() },
      ],
    });
    const userMsg: ChatMessage = { role: "user", content };
    const recorder = new TurnRecorder();
    controller = new AbortController();
    const ctrl = controller;
    const gen = generation;
    try {
      const currentPath = typeof window !== "undefined" ? window.location.pathname : undefined;
      await streamChat(
        { sessionId: sid, currentPath, messages: [userMsg], mode: "chat", ...callerWire(caller.get()) },
        (e) => {
          recorder.push(e);
          applyEvent(assistantId, e);
        },
        ctrl.signal,
      );
      updateAssistant(assistantId, (a) => (a.status === "streaming" ? { ...a, status: "done" } : a));
    } catch (e) {
      const err = e as Error;
      if (err.name === "AbortError") updateAssistant(assistantId, (a) => ({ ...a, status: "stopped" }));
      else {
        updateAssistant(assistantId, (a) => ({ ...a, status: "error", error: err.message }));
        if (err instanceof AiUnavailableError) set({ unavailable: true });
      }
    } finally {
      if (gen !== generation) return; // eslint-disable-line no-unsafe-finally
      if (recorder.messages.length || state.items.find((i) => i.id === assistantId && i.role === "assistant" && i.parts.length)) {
        history = [...history, userMsg, ...recorder.finish()];
      }
      if (controller === ctrl) controller = undefined;
      set({ busy: false });
      void sessionsStore.refresh();
    }
  },
  async openSession(id: string) {
    generation++;
    controller?.abort();
    const d = await sessionsStore.open(id);
    if (!d) return;
    history = [];
    set({ sessionId: d.id, items: itemsFromDetail(d), busy: false, unavailable: false });
  },
  async syncFromActive() {
    const id = sessionsStore.activeId();
    if (!id) { set({ sessionId: null, items: [] }); return; }
    if (state.busy) return;
    const d = await getAiSession(id);
    if (d && !state.busy) set({ sessionId: d.id, items: itemsFromDetail(d) });
  },
  stop() {
    controller?.abort();
  },
  async reset() {
    generation++;
    controller?.abort();
    history = [];
    try {
      const created = await sessionsStore.createNew("chat");
      set({ sessionId: created.id, items: [], busy: false, unavailable: false });
    } catch {
      sessionsStore.setActiveId(null);
      set({ sessionId: null, items: [], busy: false, unavailable: false });
    }
  },
};

let lastIdentity = JSON.stringify(callerWire());
caller.subscribe(() => {
  const now = JSON.stringify(callerWire());
  if (now !== lastIdentity) {
    lastIdentity = now;
    generation++;
    controller?.abort();
    history = [];
    sessionsStore.setActiveId(null);
    set({ sessionId: null, items: [], busy: false, unavailable: false });
    void sessionsStore.refresh();
  }
});

// Keep Assistant view synced when another surface (Voix / SessionPicker) switches the active session.
sessionsStore.subscribe(() => {
  const nextId = sessionsStore.activeId();
  if (nextId !== state.sessionId && !state.busy) {
    if (!nextId) {
      history = [];
      set({ sessionId: null, items: [] });
    } else {
      void getAiSession(nextId).then((d) => {
        if (d && sessionsStore.activeId() === d.id && !state.busy) {
          set({ sessionId: d.id, items: itemsFromDetail(d) });
        }
      });
    }
  }
});

export function useChat(): ChatState {
  return useSyncExternalStore((l) => { listeners.add(l); return () => listeners.delete(l); }, () => state);
}
