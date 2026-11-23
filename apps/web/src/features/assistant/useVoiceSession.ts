/**
 * Push-to-talk voice session over WS /ai/voice (contract: VoiceClientMessage / VoiceServerMessage in @kit/shared).
 * Mic → MediaRecorder (webm/opus) chunks every 100 ms, streamed as binary frames between audio_start and audio_end:
 * the server transcribes them as they arrive and sends `transcript` final:false (live text) before the final one.
 * Agent audio: binary frames between agent_audio_start/end → one Blob → <audio>. Mock TTS → speechSynthesis (fr-FR).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { MOCK_TTS_MIME, type CallerRole, type TurnCost, type TurnTimings, type VoiceClientMessage, type VoiceServerMessage } from "@kit/shared";
import { AI_BASE } from "@/lib/api";
import { MIN_HOLD_MS } from "@/lib/hold-to-talk";
import { SegmentPlayer } from "./audio-player";
import { caller, callerWire, useCaller } from "./caller";
import type { ToolRun } from "./tools";

export type Conn = "connecting" | "ready" | "offline";
export type Activity = "idle" | "recording" | "thinking" | "speaking";
export type MicState = "unknown" | "granted" | "denied" | "unsupported";

export interface VoiceTurn {
  id: number;
  /** text: live while recording/transcribing (stable = its final words), definitive once status is "final". */
  caller: { text: string; stable?: string; at: number; status: "recording" | "transcribing" | "final"; typed?: boolean };
  agent: { text: string; at?: number; tools: ToolRun[]; done: boolean; error?: string; interrupted?: boolean };
  timings?: TurnTimings;
  /** Tokens / STT seconds / TTS characters of the turn + estimated price (server). */
  cost?: TurnCost;
  /** Client-side: caller release → agent audio actually starts playing (or speech synthesis starts). */
  perceivedMs?: number;
}

export interface Providers { llm: string; stt: string; tts: string; sessionId: string }

const REC_MIME = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
const wsUrl = () => `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${AI_BASE}/voice`;

export function useVoiceSession() {
  const [conn, setConn] = useState<Conn>("connecting");
  const [activity, setActivity] = useState<Activity>("idle");
  const [mic, setMic] = useState<MicState>("unknown");
  const [providers, setProviders] = useState<Providers>();
  const [turns, setTurns] = useState<VoiceTurn[]>([]);
  const [level, setLevel] = useState(0);
  const [lastError, setLastError] = useState<string>();
  const [effectiveRole, setEffectiveRole] = useState<CallerRole>(); // what the server enforces (its `ready` answer to our declared identity)

  const ws = useRef<WebSocket>();
  const sessionId = useRef<string>();
  const alive = useRef(true);
  const turnSeq = useRef(0);
  const currentTurn = useRef<number>();
  // mic
  const stream = useRef<MediaStream>();
  const micOpening = useRef<Promise<MediaStream | undefined>>();
  const recorder = useRef<MediaRecorder>();
  const pressed = useRef(false);
  const pressedAt = useRef(0);
  const audioCtx = useRef<AudioContext>();
  const analyser = useRef<AnalyserNode>();
  const raf = useRef<number>();
  // playback
  const player = useRef<SegmentPlayer>();
  const audioMime = useRef<string>();
  const discardAudio = useRef(false); // audio of an interrupted turn still draining
  const releasedAt = useRef<number>();
  const turnHasAudio = useRef(false);

  const patchTurn = useCallback((id: number | undefined, fn: (t: VoiceTurn) => VoiceTurn) => {
    if (id == null) return;
    setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)));
  }, []);

  const newTurn = useCallback((caller: VoiceTurn["caller"]) => {
    const id = ++turnSeq.current;
    const prev = currentTurn.current;
    currentTurn.current = id;
    turnHasAudio.current = false;
    audioMime.current = undefined;
    discardAudio.current = true;
    setTurns((ts) => [
      ...ts.map((t) => (t.id === prev && !t.agent.done ? { ...t, agent: { ...t.agent, done: true, interrupted: true } } : t)),
      { id, caller, agent: { text: "", tools: [], done: false } },
    ]);
    return id;
  }, []);

  const send = useCallback((m: VoiceClientMessage) => {
    if (ws.current?.readyState === WebSocket.OPEN) ws.current.send(JSON.stringify(m));
  }, []);

  // ── Playback ──
  const stopPlayback = useCallback(() => {
    try { window.speechSynthesis?.cancel(); } catch { /* ignore */ }
    const p = player.current;
    player.current = undefined;
    p?.stop();
    setActivity((a) => (a === "speaking" ? "idle" : a));
  }, []);

  const markPerceived = useCallback((id: number | undefined) => {
    const t0 = releasedAt.current;
    if (t0 == null) return;
    releasedAt.current = undefined;
    patchTurn(id, (t) => ({ ...t, perceivedMs: Math.round(performance.now() - t0) }));
  }, [patchTurn]);

  const speak = useCallback((text: string, id: number | undefined) => {
    const synth = window.speechSynthesis;
    if (!synth || !text.trim()) { setActivity("idle"); return; }
    stopPlayback();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "fr-FR";
    const fr = synth.getVoices().find((v) => v.lang?.toLowerCase().startsWith("fr"));
    if (fr) u.voice = fr;
    u.rate = 1.08;
    u.onstart = () => { setActivity("speaking"); markPerceived(id); };
    u.onend = u.onerror = () => setActivity((a) => (a === "speaking" ? "idle" : a));
    setActivity("speaking");
    synth.speak(u);
  }, [markPerceived, stopPlayback]);

  // ── Server messages ──
  const onMessage = useCallback((ev: MessageEvent) => {
    if (typeof ev.data !== "string") {
      if (!discardAudio.current) player.current?.push(ev.data as ArrayBuffer);
      return;
    }
    let m: VoiceServerMessage;
    try { m = JSON.parse(ev.data); } catch { return; }
    const id = currentTurn.current;
    switch (m.type) {
      case "ready":
        sessionId.current = m.sessionId;
        setProviders({ llm: m.llm, stt: m.stt, tts: m.tts, sessionId: m.sessionId });
        setEffectiveRole(m.role);
        setConn("ready");
        break;
      case "transcript": {
        const turn = id;
        if (!m.final) {
          // Live partial while the caller speaks (or just after the release): never over a final text.
          patchTurn(turn, (t) => (t.caller.status === "final" ? t : { ...t, caller: { ...t.caller, text: m.text, stable: m.stable ?? "" } }));
          break;
        }
        // Typed turns already show the caller text; the server echoes it as a transcript.
        if (turn == null) newTurn({ text: m.text, at: Date.now(), status: "final" });
        else patchTurn(turn, (t) => ({ ...t, caller: { ...t.caller, text: m.text, status: "final" } }));
        setActivity((a) => (a === "recording" ? a : "thinking"));
        break;
      }
      case "agent_text":
        patchTurn(id, (t) => ({ ...t, agent: { ...t.agent, text: t.agent.text + m.delta, at: t.agent.at ?? Date.now() } }));
        break;
      case "agent_tool":
        patchTurn(id, (t) => {
          const tools = [...t.agent.tools];
          if (m.ok === undefined) {
            // Three messages per tool: started (name only, as soon as the model begins the call), called (args), done (ok/ms).
            // A "called" message completes the entry its "started" message opened (same name, no args yet) instead of adding a second one.
            const started = m.args ? tools.findIndex((x) => x.name === m.name && x.args === undefined && x.ok === undefined) : -1;
            if (started >= 0) tools[started] = { ...tools[started], args: m.args };
            else tools.push({ id: `${t.id}-${tools.length}`, name: m.name, args: m.args });
          } else {
            const i = tools.findIndex((x) => x.name === m.name && x.ok === undefined);
            if (i >= 0) tools[i] = { ...tools[i], ok: m.ok, ms: m.ms };
            else tools.push({ id: `${t.id}-${tools.length}`, name: m.name, ok: m.ok, ms: m.ms });
          }
          return { ...t, agent: { ...t.agent, tools, at: t.agent.at ?? Date.now() } };
        });
        break;
      case "agent_audio_start":
        discardAudio.current = false;
        audioMime.current = m.mime;
        turnHasAudio.current = true;
        if (m.mime !== MOCK_TTS_MIME) {
          stopPlayback();
          const p: SegmentPlayer = new SegmentPlayer(m.mime, {
            onPlaying: () => { setActivity("speaking"); markPerceived(id); },
            onEnded: () => {
              if (player.current === p) player.current = undefined;
              setActivity((a) => (a === "speaking" ? "idle" : a));
            },
          });
          player.current = p;
        }
        break;
      case "agent_audio_end":
        // An interrupted turn's segment closes after the new turn started: drop it.
        if (discardAudio.current) break;
        player.current?.end();
        break;
      case "agent_done":
        patchTurn(id, (t) => ({ ...t, timings: m.timings, cost: m.cost, agent: { ...t.agent, done: true, text: t.agent.text || m.text } }));
        if (audioMime.current === MOCK_TTS_MIME && turnHasAudio.current) speak(m.text, id);
        else if (!turnHasAudio.current || !player.current) setActivity((a) => (a === "thinking" ? "idle" : a));
        audioMime.current = undefined;
        currentTurn.current = undefined;
        break;
      case "error":
        setLastError(m.message);
        if (id != null) patchTurn(id, (t) => ({ ...t, caller: { ...t.caller, status: "final" }, agent: { ...t.agent, done: true, error: m.message } }));
        currentTurn.current = undefined;
        setActivity((a) => (a === "thinking" ? "idle" : a));
        break;
    }
  }, [markPerceived, newTurn, patchTurn, speak, stopPlayback]);

  // ── Connection (auto-reconnect, same sessionId keeps the server-side history) ──
  const connect = useCallback(() => {
    if (!alive.current) return;
    ws.current?.close();
    setConn("connecting");
    const sock = new WebSocket(wsUrl());
    sock.binaryType = "arraybuffer";
    ws.current = sock;
    // The DECLARED identity (CallerBadge) rides on `start`; the server enforces it and echoes the effective role in `ready`.
    sock.onopen = () => sock.send(JSON.stringify({ type: "start", sessionId: sessionId.current, ...callerWire(caller.get()) } satisfies VoiceClientMessage));
    sock.onmessage = onMessage;
    sock.onclose = () => {
      if (ws.current !== sock) return;
      setConn("offline");
      setActivity((a) => (a === "speaking" ? a : "idle"));
      if (alive.current) window.setTimeout(() => { if (ws.current === sock) connect(); }, 3000);
    };
  }, [onMessage]);

  useEffect(() => {
    alive.current = true;
    connect();
    return () => {
      alive.current = false;
      const s = ws.current;
      ws.current = undefined;
      s?.close();
      stopPlayback();
      if (raf.current) cancelAnimationFrame(raf.current);
      try { recorder.current?.stop(); } catch { /* ignore */ }
      stream.current?.getTracks().forEach((t) => t.stop());
      void audioCtx.current?.close().catch(() => undefined);
    };
  }, [connect, stopPlayback]);

  // Another identity = another conversation: the server wipes the history on `start`, so the screen does too.
  const identity = callerWire(useCaller()); // the effective one: picking « Client » before a client changes nothing on the wire
  const identityKey = JSON.stringify(identity);
  const sentIdentity = useRef(identityKey);
  useEffect(() => {
    if (sentIdentity.current === identityKey) return;
    sentIdentity.current = identityKey;
    stopPlayback();
    currentTurn.current = undefined;
    setTurns([]);
    setActivity("idle");
    setLastError(undefined);
    send({ type: "start", sessionId: sessionId.current, ...callerWire(identity) });
  }, [identity, identityKey, send, stopPlayback]);

  // ── Mic ──
  const openMic = useCallback(async (): Promise<MediaStream | undefined> => {
    if (stream.current?.active) return stream.current;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") { setMic("unsupported"); return undefined; }
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      stream.current = s;
      setMic("granted");
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new Ctx();
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      ctx.createMediaStreamSource(s).connect(an);
      audioCtx.current = ctx;
      analyser.current = an;
      return s;
    } catch (e) {
      setMic((e as DOMException).name === "NotAllowedError" || (e as DOMException).name === "SecurityError" ? "denied" : "unsupported");
      return undefined;
    }
  }, []);

  /** One open at a time: the early warm-up and a first key press must not each ask for a stream. */
  const ensureMic = useCallback((): Promise<MediaStream | undefined> => {
    if (stream.current?.active) return Promise.resolve(stream.current);
    micOpening.current ??= openMic().finally(() => { micOpening.current = undefined; });
    return micOpening.current;
  }, [openMic]);

  const meter = useCallback(() => {
    const an = analyser.current;
    if (!an) return;
    const buf = new Uint8Array(an.fftSize);
    const tick = () => {
      an.getByteTimeDomainData(buf);
      let sum = 0;
      for (const v of buf) { const x = (v - 128) / 128; sum += x * x; }
      setLevel(Math.min(1, Math.sqrt(sum / buf.length) * 4));
      raf.current = requestAnimationFrame(tick);
    };
    tick();
  }, []);

  /**
   * Recorder start, with NOTHING awaited before it on the warm path: the mic stream stays open after the first press
   * (and is opened ahead of time when the permission is already granted, see the effect below), so the key-down handler
   * creates and starts the MediaRecorder synchronously and the first syllable is not lost to a promise round-trip.
   * Limitation (no clean pre-roll with MediaRecorder): a recorder restarted mid-stream cannot be replayed, because
   * WebM chunks taken from the middle of a running recording are not decodable without their cluster headers.
   * So audio before the key goes down is not captured, and the encoder's own start-up (tens of ms) is not hidden.
   */
  const beginRecording = useCallback((s: MediaStream) => {
    const mime = REC_MIME.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
    const rec = new MediaRecorder(s, mime ? { mimeType: mime } : undefined);
    recorder.current = rec;
    send({ type: "audio_start", mime: rec.mimeType || mime || "audio/webm" });
    rec.ondataavailable = (e) => { if (e.data.size && ws.current?.readyState === WebSocket.OPEN) ws.current.send(e.data); };
    rec.onstop = () => {
      // The last dataavailable fires before stop, so every chunk has been queued on the socket.
      send({ type: "audio_end" });
      releasedAt.current = performance.now();
    };
    void audioCtx.current?.resume();
    pressedAt.current = performance.now();
    rec.start(100); // a chunk every 100 ms: the STT hears the words while they are spoken
    newTurn({ text: "", at: Date.now(), status: "recording" });
    setActivity("recording");
    setLastError(undefined);
    meter();
  }, [meter, newTurn, send]);

  const startTalking = useCallback(() => {
    if (pressed.current || conn !== "ready") return;
    pressed.current = true;
    stopPlayback();
    const warm = stream.current;
    if (warm?.active) { beginRecording(warm); return; }
    // Cold path (first press ever: permission prompt): the only place we wait.
    void ensureMic().then((s) => {
      // Released while the permission prompt / mic warm-up was pending: do not record a stub.
      if (!s || !pressed.current) { pressed.current = false; return; }
      beginRecording(s);
    });
  }, [beginRecording, conn, ensureMic, stopPlayback]);

  // Permission already granted (earlier visit): open the mic now so even the first press takes the warm path.
  useEffect(() => {
    let cancelled = false;
    navigator.permissions?.query({ name: "microphone" as PermissionName })
      .then((p) => (!cancelled && p.state === "granted" ? ensureMic() : undefined))
      .then((s) => { if (s && !alive.current) s.getTracks().forEach((t) => t.stop()); }) // unmounted while opening: do not leak the mic
      .catch(() => undefined); // Safari / Firefox: no microphone permission query, the first press asks as before
    return () => { cancelled = true; };
  }, [ensureMic]);

  const stopTalking = useCallback(() => {
    if (!pressed.current) return;
    pressed.current = false;
    if (raf.current) cancelAnimationFrame(raf.current);
    setLevel(0);
    const rec = recorder.current;
    recorder.current = undefined;
    if (rec && rec.state !== "inactive" && performance.now() - pressedAt.current < MIN_HOLD_MS) {
      // A tap / accidental click, not an utterance: stop without sending the audio, tell the server to drop it, forget the turn.
      rec.ondataavailable = null;
      rec.onstop = null;
      rec.stop();
      send({ type: "audio_cancel" });
      const id = currentTurn.current;
      currentTurn.current = undefined;
      setTurns((ts) => ts.filter((t) => t.id !== id));
      setActivity("idle");
      return;
    }
    if (rec && rec.state !== "inactive") {
      rec.stop();
      patchTurn(currentTurn.current, (t) => ({ ...t, caller: { ...t.caller, status: "transcribing" } }));
      setActivity("thinking");
    }
  }, [patchTurn, send]);

  const sendText = useCallback((text: string) => {
    const v = text.trim();
    if (!v || conn !== "ready") return;
    stopPlayback();
    newTurn({ text: v, at: Date.now(), status: "final", typed: true });
    send({ type: "text", text: v });
    releasedAt.current = performance.now();
    setActivity("thinking");
    setLastError(undefined);
  }, [conn, newTurn, send, stopPlayback]);

  const reset = useCallback(() => {
    stopPlayback();
    send({ type: "reset" });
    currentTurn.current = undefined;
    setTurns([]);
    setActivity("idle");
    setLastError(undefined);
  }, [send, stopPlayback]);

  return {
    conn, activity, mic, providers, turns, level, lastError, effectiveRole,
    startTalking, stopTalking, sendText, stopPlayback, reset, reconnect: connect,
  };
}
