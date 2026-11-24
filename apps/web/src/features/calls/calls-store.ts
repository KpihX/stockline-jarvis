/**
 * Global WhatsApp VoIP Call Desk & QR Pairing store (Manager & Admin only).
 * Owns SSE /ai/calls/stream, WebRTC Opus 48 kHz RTCPeerConnection, and WhatsApp Baileys state.
 */
import { useSyncExternalStore } from "react";
import type {
  CallConfigPayload,
  CallSession,
  CallTranscriptEntry,
  PhoneBinding,
  WaStatusPayload,
} from "@kit/shared";
import { AI_BASE } from "@/lib/api";
import { auth } from "@/features/auth/auth-store";
import { toast } from "@/ui";

export type WebRtcState = "idle" | "ringing" | "connecting" | "connected" | "disconnected" | "failed";

interface CallsState {
  activeCall: CallSession | null;
  recentCalls: CallSession[];
  selectedCallId: string | null;
  webrtcState: WebRtcState;
  busy: boolean;
  wa: WaStatusPayload;
  qrDataUrl: string;
  bindings: PhoneBinding[];
  iceServers: RTCIceServer[];
  streamOpen: boolean;
}

let state: CallsState = {
  activeCall: null,
  recentCalls: [],
  selectedCallId: null,
  webrtcState: "idle",
  busy: false,
  wa: { status: "disconnected", phone: "", qrReady: false },
  qrDataUrl: "",
  bindings: [],
  iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
  streamOpen: false,
};

const listeners = new Set<() => void>();
let eventSource: EventSource | null = null;
let pcRef: RTCPeerConnection | null = null;
let localStream: MediaStream | null = null;
let silentCtx: AudioContext | null = null;
let audioEl: HTMLAudioElement | null = null;
let activeToken: string | null = null;

function set(patch: Partial<CallsState>) {
  state = { ...state, ...patch };
  listeners.forEach((l) => l());
}

function authHeaders(): HeadersInit {
  const tok = auth.token();
  return tok ? { Authorization: `Bearer ${tok}`, "content-type": "application/json" } : { "content-type": "application/json" };
}

async function aiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${AI_BASE}${path}`, {
    ...init,
    headers: { ...authHeaders(), ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let msg = `Erreur ${res.status}`;
    try {
      const j = await res.json();
      msg = j?.error?.message || j?.detail || msg;
    } catch { /* ignore */ }
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

function closeWebRtcPeer() {
  if (pcRef) {
    try { pcRef.close(); } catch { /* ignore */ }
    pcRef = null;
  }
  localStream?.getTracks().forEach((t) => t.stop());
  localStream = null;
  if (silentCtx) {
    void silentCtx.close().catch(() => undefined);
    silentCtx = null;
  }
  if (audioEl) audioEl.srcObject = null;
  set({ webrtcState: "idle" });
}

function upsertRecent(call: CallSession) {
  const next = [call, ...state.recentCalls.filter((c) => c.callId !== call.callId)].slice(0, 30);
  set({ recentCalls: next });
}

function handleSsePayload(ev: Record<string, unknown>) {
  const type = String(ev.type || "");
  if (type === "stream.connected") {
    set({ streamOpen: true });
    return;
  }
  if (type === "wa.status") {
    const wa: WaStatusPayload = {
      status: (ev.status as WaStatusPayload["status"]) || "disconnected",
      phone: String(ev.phone || ""),
      qrReady: Boolean(ev.qrReady),
    };
    set({ wa });
    if (wa.status !== "connected" && wa.qrReady) void callsStore.refreshWa();
    else if (wa.status === "connected") set({ qrDataUrl: "" });
    return;
  }
  if (type === "call.incoming" && ev.call) {
    const call = ev.call as CallSession;
    upsertRecent(call);
    set({ activeCall: call, selectedCallId: call.callId, webrtcState: "ringing" });
    toast.info(`Appel WhatsApp entrant : ${call.clientName || call.phoneNumber}`);
    return;
  }
  if (type === "call.state") {
    const cid = String(ev.callId || "");
    const st = String(ev.status || "active") as CallSession["status"];
    const clientPatch = ev.client as { clientId: string; clientName: string } | undefined;
    if (state.activeCall?.callId === cid) {
      set({
        activeCall: {
          ...state.activeCall,
          status: st,
          ...(clientPatch ? { clientId: clientPatch.clientId, clientName: clientPatch.clientName, knownClient: true } : {}),
        },
      });
    }
    set({
      recentCalls: state.recentCalls.map((c) =>
        c.callId === cid
          ? { ...c, status: st, ...(clientPatch ? { clientId: clientPatch.clientId, clientName: clientPatch.clientName, knownClient: true } : {}) }
          : c,
      ),
    });
    return;
  }
  if (type === "call.transcript" && ev.entry) {
    const cid = String(ev.callId || "");
    const entry = ev.entry as CallTranscriptEntry;
    const upsertEntry = (c: CallSession): CallSession => {
      const existing = c.transcripts.some((t) => t.id === entry.id)
        ? c.transcripts.map((t) => (t.id === entry.id ? { ...t, ...entry } : t))
        : [...c.transcripts, entry];
      existing.sort((a, b) => String(a.ts || "").localeCompare(String(b.ts || "")) || a.seq - b.seq);
      return { ...c, transcripts: existing };
    };
    if (state.activeCall?.callId === cid) set({ activeCall: upsertEntry(state.activeCall) });
    set({ recentCalls: state.recentCalls.map((c) => (c.callId === cid ? upsertEntry(c) : c)) });
    return;
  }
  if (type === "call.copilot") {
    const cid = String(ev.callId || "");
    const patchCall = (c: CallSession): CallSession => ({
      ...c,
      copilotNote: String(ev.copilotNote ?? c.copilotNote ?? ""),
      linkedCommands: (ev.linkedCommands as CallSession["linkedCommands"]) ?? c.linkedCommands,
      warnings: (ev.warnings as CallSession["warnings"]) ?? c.warnings,
      committed: ((ev.linkedCommands as unknown[])?.length ?? 0) > 0 || c.committed,
    });
    if (state.activeCall?.callId === cid) set({ activeCall: patchCall(state.activeCall) });
    set({ recentCalls: state.recentCalls.map((c) => (c.callId === cid ? patchCall(c) : c)) });
    return;
  }
  if (type === "call.ended") {
    const cid = String(ev.callId || "");
    const st = (ev.status as CallSession["status"]) || "ended";
    if (state.activeCall?.callId === cid) {
      closeWebRtcPeer();
      set({ activeCall: null });
    }
    set({
      recentCalls: state.recentCalls.map((c) => (c.callId === cid ? { ...c, status: st, reason: String(ev.reason || "") } : c)),
    });
    void callsStore.refreshCalls();
    return;
  }
  if (type === "calls.reset") {
    closeWebRtcPeer();
    set({ activeCall: null, recentCalls: [], selectedCallId: null });
    return;
  }
  if (type === "call.error") {
    toast.error(String(ev.error || "Erreur sur l'appel WhatsApp"));
  }
}

export const callsStore = {
  get: () => state,
  subscribe(fn: () => void) {
    listeners.add(fn);
    return () => { listeners.delete(fn); };
  },
  bindAudioElement(el: HTMLAudioElement | null) {
    audioEl = el;
  },
  selectCall(callId: string | null) {
    set({ selectedCallId: callId });
  },
  connectStream() {
    const acc = auth.account();
    const tok = auth.token();
    if (!acc || (acc.role !== "manager" && acc.role !== "admin") || !tok) {
      this.disconnectStream();
      return;
    }
    if (eventSource && activeToken === tok) return;
    this.disconnectStream();
    activeToken = tok;
    const src = new EventSource(`${AI_BASE}/calls/stream?token=${encodeURIComponent(tok)}`);
    src.onopen = () => set({ streamOpen: true });
    src.onerror = () => set({ streamOpen: false });
    src.onmessage = (m) => {
      try {
        handleSsePayload(JSON.parse(m.data));
      } catch { /* ignore */ }
    };
    eventSource = src;
    void this.refreshCalls();
    void this.refreshConfig();
    void this.refreshWa();
  },
  disconnectStream() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
    activeToken = null;
    closeWebRtcPeer();
    set({ streamOpen: false, activeCall: null });
  },
  async refreshConfig() {
    try {
      const cfg = await aiFetch<CallConfigPayload>("/calls/config");
      set({ iceServers: cfg.iceServers?.length ? cfg.iceServers : state.iceServers, bindings: cfg.bindings || [] });
    } catch { /* ignore */ }
  },
  async refreshCalls() {
    try {
      const res = await aiFetch<{ items: CallSession[]; recent: CallSession[] }>("/calls/active");
      set({
        activeCall: res.items?.[0] ?? null,
        recentCalls: res.recent ?? [],
        selectedCallId: state.selectedCallId ?? res.items?.[0]?.callId ?? res.recent?.[0]?.callId ?? null,
      });
    } catch { /* ignore */ }
  },
  async refreshWa() {
    try {
      const wa = await aiFetch<WaStatusPayload>("/wa/status");
      set({ wa });
      if (wa.status !== "connected" && wa.qrReady) {
        try {
          const q = await aiFetch<{ qr: string }>("/wa/qr");
          set({ qrDataUrl: q.qr || "" });
        } catch {
          set({ qrDataUrl: "" });
        }
      } else if (wa.status === "connected") {
        set({ qrDataUrl: "" });
      }
    } catch {
      set({ wa: { status: "unavailable", phone: "", qrReady: false } });
    }
  },
  async connectWa(reset = false) {
    set({ busy: true });
    try {
      await aiFetch("/wa/connect", { method: "POST", body: JSON.stringify({ reset }) });
      await this.refreshWa();
      toast.success(reset ? "Nouveau QR WhatsApp demandé" : "Connexion WhatsApp relancée");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Service WhatsApp indisponible");
    } finally {
      set({ busy: false });
    }
  },
  async disconnectWa() {
    set({ busy: true });
    try {
      await aiFetch("/wa/disconnect", { method: "POST" });
      set({ qrDataUrl: "", wa: { status: "disconnected", phone: "", qrReady: false } });
      toast.info("WhatsApp déconnecté");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erreur de déconnexion");
    } finally {
      set({ busy: false });
    }
  },
  async answerCall(callId: string) {
    set({ busy: true });
    try {
      closeWebRtcPeer();
      set({ webrtcState: "connecting" });
      let stream: MediaStream;
      try {
        const micPromise = navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1, sampleRate: { ideal: 48000 } },
          video: false,
        });
        const timeoutPromise = new Promise<never>((_, rej) => setTimeout(() => rej(new Error("mic timeout")), 2500));
        stream = await Promise.race([micPromise, timeoutPromise]);
      } catch {
        const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
        const ctx = new Ctx();
        silentCtx = ctx;
        stream = ctx.createMediaStreamDestination().stream;
      }
      const isSim = state.activeCall?.callId === callId && state.activeCall.mode === "simulation";
      localStream = stream;
      if (isSim) stream.getAudioTracks().forEach((t) => { t.enabled = false; });
      const pc = new RTCPeerConnection({ iceServers: state.iceServers });
      pcRef = pc;
      for (const track of stream.getTracks()) pc.addTrack(track, stream);
      pc.ontrack = (ev) => {
        if (audioEl) {
          audioEl.srcObject = new MediaStream([ev.track]);
          void audioEl.play().catch(() => undefined);
        }
      };
      pc.onconnectionstatechange = () => {
        const st = (pc.connectionState || "connecting") as WebRtcState;
        set({ webrtcState: st });
      };
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      await new Promise<void>((resolve) => {
        if (pc.iceGatheringState === "complete") { resolve(); return; }
        const timer = window.setTimeout(() => resolve(), 1500);
        pc.onicegatheringstatechange = () => {
          if (pc.iceGatheringState === "complete") { window.clearTimeout(timer); resolve(); }
        };
      });
      const sdpOffer = pc.localDescription?.sdp || offer.sdp || "";
      const res = await aiFetch<{ sdpAnswer: string }>(`/calls/${encodeURIComponent(callId)}/accept`, {
        method: "POST",
        body: JSON.stringify({ sdpOffer }),
      });
      await pc.setRemoteDescription({ type: "answer", sdp: res.sdpAnswer });
      if (state.activeCall?.callId === callId) {
        set({ activeCall: { ...state.activeCall, status: "active", muted: isSim }, webrtcState: "connected" });
      }
      toast.success("Appel WhatsApp décroché (WebRTC Opus 48 kHz)");
    } catch (e) {
      closeWebRtcPeer();
      toast.error(e instanceof Error ? e.message : "Impossible de décrocher");
      void this.refreshCalls();
    } finally {
      set({ busy: false });
    }
  },
  async rejectCall(callId: string) {
    set({ busy: true });
    try {
      await aiFetch(`/calls/${encodeURIComponent(callId)}/reject`, { method: "POST", body: JSON.stringify({ reason: "declined" }) });
      closeWebRtcPeer();
      set({ activeCall: null });
      void this.refreshCalls();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erreur");
    } finally {
      set({ busy: false });
    }
  },
  async hangupCall(callId: string) {
    set({ busy: true });
    try {
      await aiFetch(`/calls/${encodeURIComponent(callId)}/hangup`, { method: "POST", body: JSON.stringify({ reason: "completed" }) });
      closeWebRtcPeer();
      set({ activeCall: null });
      void this.refreshCalls();
      toast.info("Appel terminé");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erreur");
    } finally {
      set({ busy: false });
    }
  },
  async toggleMute(callId: string, muted: boolean) {
    localStream?.getAudioTracks().forEach((t) => { t.enabled = !muted; });
    try {
      await aiFetch(`/calls/${encodeURIComponent(callId)}/mute`, { method: "POST", body: JSON.stringify({ muted }) });
      if (state.activeCall?.callId === callId) set({ activeCall: { ...state.activeCall, muted } });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erreur mute");
    }
  },
  async commitCall(callId: string) {
    set({ busy: true });
    try {
      const updated = await aiFetch<CallSession>(`/calls/${encodeURIComponent(callId)}/commit`, { method: "POST" });
      if (state.activeCall?.callId === callId) set({ activeCall: updated });
      upsertRecent(updated);
      toast.success("Analyse J.A.R.V.I.S / ERP mise à jour");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Erreur d'extraction");
    } finally {
      set({ busy: false });
    }
  },
  async confirmOrder(callId: string, orderId: string) {
    set({ busy: true });
    try {
      const updated = await aiFetch<CallSession>(
        `/calls/${encodeURIComponent(callId)}/orders/${encodeURIComponent(orderId)}/confirm`,
        { method: "POST" },
      );
      if (state.activeCall?.callId === callId) set({ activeCall: updated });
      upsertRecent(updated);
      toast.success("Commande confirmée dans l'ERP !");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Confirmation impossible");
    } finally {
      set({ busy: false });
    }
  },
  async simulateCall(phone: string, text: string, clientId?: string) {
    set({ busy: true });
    try {
      const res = await aiFetch<{ callId: string }>("/calls/simulate", {
        method: "POST",
        body: JSON.stringify({ phone, text, clientId: clientId || undefined }),
      });
      set({ busy: false, selectedCallId: res.callId });
      void this.refreshCalls();
      toast.success("Sonnerie d'appel simulée !");
    } catch (e) {
      set({ busy: false });
      toast.error(e instanceof Error ? e.message : "Simulation impossible");
    }
  },
  async injectText(callId: string, text: string, speaker: "client" | "manager") {
    try {
      await aiFetch(`/calls/${encodeURIComponent(callId)}/inject-text`, {
        method: "POST",
        body: JSON.stringify({ text, speaker }),
      });
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Injection échouée");
    }
  },
  async bindCallClient(callId: string, clientId: string) {
    try {
      const res = await aiFetch<PhoneBinding>(`/calls/${encodeURIComponent(callId)}/bind-client`, {
        method: "POST",
        body: JSON.stringify({ clientId }),
      });
      await Promise.all([this.refreshCalls(), this.refreshConfig()]);
      toast.success(`Numéro associé à ${res.clientName}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Association échouée");
    }
  },
  async bindPhone(phone: string, clientId: string) {
    try {
      const res = await aiFetch<PhoneBinding>("/calls/bind-phone", {
        method: "POST",
        body: JSON.stringify({ phone, clientId }),
      });
      await this.refreshConfig();
      toast.success(`Numéro ${res.phoneDigits} associé à ${res.clientName}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Association échouée");
    }
  },
  async resetTests() {
    set({ busy: true });
    try {
      await aiFetch("/calls/reset", { method: "POST" });
      closeWebRtcPeer();
      set({ activeCall: null, recentCalls: [], selectedCallId: null });
      toast.success("Tests réinitialisés (ERP + appels vidés, WhatsApp et n° 337 conservés)");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Réinitialisation échouée");
    } finally {
      set({ busy: false });
    }
  },
};

export const useCalls = () => useSyncExternalStore(callsStore.subscribe, callsStore.get);
