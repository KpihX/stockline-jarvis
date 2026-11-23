/**
 * Contract of the AI service (apps/ai, default http://localhost:4100).
 *
 *  GET  /health                         → { ok, llm: {provider, model}, stt: {provider}, tts: {provider} }
 *  GET  /tools                          → ToolInfo[]  (tools the harness exposes to the model)
 *  POST /chat                           body ChatRequest → text/event-stream of ChatStreamEvent (one JSON per `data:` line)
 *  WS   /voice                          bidirectional, see VoiceClientMessage / VoiceServerMessage
 *  POST /stt                            raw audio body (audio/webm | audio/wav) → { text, ms }
 *  POST /tts                            body { text, voice? } → audio bytes (audio/mpeg or audio/wav), header x-ms
 *  POST /command[?speak=1]              single-turn voice COMMAND (stateless, act-first, one-line answer).
 *                                       body = raw audio (content-type audio/webm|wav…, header x-mock-text for the mock STT)
 *                                       or JSON { text, actorName? } → text/event-stream of CommandStreamEvent:
 *                                       transcript → (text | tool_call | tool_result)* → navigate? → speech? → done (with timings) | error.
 *                                       speak=1 → a `speech` event (base64 audio; MOCK_TTS_MIME = speak the text in the browser).
 *  WS   /voice/command[?speak=1]        the same command with LIVE transcription: send audio_start {mime, hint?}, binary frames
 *                                       while the key is down, audio_end (or one { type: "text" }); receive CommandStreamEvent JSON
 *                                       (transcript final=false while speaking, then the POST /command events). Closed after done | error.
 */

export type ChatRole = "system" | "user" | "assistant" | "tool";

export interface ChatMessage {
  role: ChatRole;
  content: string;
  toolCallId?: string; // for role "tool"
  toolCalls?: ToolCall[]; // for role "assistant"
  name?: string;
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface ToolInfo {
  name: string;
  description: string;
  parameters: Record<string, unknown>; // JSON schema
}

/**
 * Who is on the line. DECLARED by the UI selector (the demo has no caller-ID / telephony), ENFORCED by the AI service (apps/ai/app/policy.py):
 * unknown (default) = catalogue only, no write · client = ONE client (clientId required, else downgraded to unknown) · sales / direction = everything.
 * Production would replace the declaration by caller-ID / authentication; the server-side table would not change.
 */
export type CallerRole = "unknown" | "client" | "sales" | "direction";

export interface CallerIdentity {
  role: CallerRole;
  clientId?: string; // client: the client they are · sales / direction: the client they are working on (optional)
  actorName?: string; // declared name: shown as the author of the ERP writes of the session
}

export interface ChatRequest extends Partial<CallerIdentity> {
  messages: ChatMessage[]; // full conversation so far (no system message; the harness adds it)
  mode?: "chat" | "voice" | "command"; // voice → short spoken-style answers; command → single-turn, act-first, one line
  // identity (optional: absent = unknown): role / clientId / actorName here, or the x-caller-role / x-caller-client-id / x-actor-name headers
}

export type ChatStreamEvent =
  | { type: "text"; delta: string }
  | { type: "tool_call"; call: ToolCall }
  | { type: "tool_result"; callId: string; name: string; ok: boolean; result: unknown; ms: number }
  | { type: "done"; message: ChatMessage; usage?: { inputTokens?: number; outputTokens?: number; cacheCreationInputTokens?: number; cacheReadInputTokens?: number }; ms: number; timings?: TurnTimings }
  | { type: "error"; message: string };

// ── Voice (push-to-talk, two tracks: the human "caller" and the agent) ──

export type VoiceClientMessage =
  | ({ type: "start"; sessionId?: string } & Partial<CallerIdentity>) // opens a conversation. Another identity on the same sessionId wipes its history
  | { type: "audio_start"; mime: string; hint?: string } // caller pressed space (hint: optional STT vocabulary; mock STT returns it)
  | { type: "audio_end" } // caller released space; binary frames sent in between (every 100–250 ms) are the utterance, streamed to the STT as they arrive
  | { type: "audio_cancel" } // instead of audio_end: released right after audio_start (a tap / accidental click): drop it, no turn
  | { type: "text"; text: string } // typed instead of spoken (debug)
  | { type: "reset" };

export interface TurnTimings {
  sttMs?: number;
  llmFirstTokenMs?: number;
  llmTotalMs?: number;
  ttsFirstByteMs?: number;
  totalMs?: number; // end of caller speech → first agent audio byte (a filler counts: see firstSoundKind)
  firstToolCallMs?: number; // start of the agent → first tool call announced by the model
  firstSoundKind?: "filler" | "answer"; // what totalMs measures: a canned wait phrase, or the real answer
  answerMs?: number; // end of caller speech → first byte of the REAL answer (= totalMs when there is no filler)
}

/** What a voice turn consumed + an ESTIMATED price (constants in apps/ai/app/pricing.py: list prices, not an invoice). */
export interface TurnCost {
  llmInputTokens?: number; // uncached input tokens
  llmOutputTokens?: number;
  llmCacheReadTokens?: number;
  llmCacheCreationTokens?: number;
  sttSeconds?: number;
  ttsChars?: number; // cached fillers excluded
  estimatedUsd?: number;
  estimatedEur?: number;
}

export type VoiceServerMessage =
  | ({ type: "ready"; sessionId: string; stt: string; tts: string; llm: string } & CallerIdentity) // role = the identity the server will ENFORCE (client without clientId → unknown)
  // While the caller speaks (streaming STT): final=false, the whole text heard so far, resent as words are recognised;
  // `stable` = its leading part made of final words (won't change). Then once final=true: what the agent answers.
  | { type: "transcript"; track: "caller"; text: string; final: boolean; stable?: string }
  | { type: "agent_text"; delta: string }
  | { type: "agent_tool"; name: string; ok?: boolean; ms?: number; args?: Record<string, unknown> } // up to 3 per tool: started (name only) → called (args) → done (ok, ms)
  | { type: "agent_audio_start"; mime: string } // binary frames follow
  | { type: "agent_audio_end" }
  | { type: "agent_done"; text: string; timings: TurnTimings; cost?: TurnCost }
  | { type: "error"; message: string };

/**
 * Mime returned by the AI service's mock TTS (no key configured): the bytes are a short silent WAV.
 * Clients should ignore the audio and speak the agent text with the browser's speechSynthesis instead.
 */
export const MOCK_TTS_MIME = "audio/x-mock-wav";

// ── Voice command (POST /command: one utterance → one action → one line) ──

/** JSON body of POST /command (or send raw audio instead). */
export interface CommandRequest extends Partial<CallerIdentity> {
  text: string; // raw-audio bodies declare the identity with the x-caller-role / x-caller-client-id headers; WS /voice/command with ?role=&clientId=&actorName=
}

export type CommandStreamEvent =
  | ChatStreamEvent
  // final (default true) comes before the agent's events; ms = STT time, 0 for typed text.
  // WS /ai/voice/command also sends final=false ones while the user speaks (text so far, `stable` = final words).
  | { type: "transcript"; text: string; ms: number; final?: boolean; stable?: string }
  | { type: "navigate"; path: string; label?: string } // the user asked to SEE an entity: web route to open (e.g. /products/prd_0012)
  | { type: "speech"; mime: string; audio: string; ms: number }; // ?speak=1: base64 audio of the answer; mime MOCK_TTS_MIME → speechSynthesis

// ── Vocabulary (GET /ai/vocab, DELETE /ai/vocab/{id}): what the voice agent learned, per client ──

/** One learned "what was heard → what it means". Stored as a context-table row (tag "vocab"); `id` = that row (ctx_…). */
export interface VocabEntry {
  id: string | null;
  heard: string; // « Paillet »
  etype: "client" | "product" | "contact" | "place";
  eid: string | null;
  label: string; // the canonical name: « Le Refuge Payet »
  scope: string; // "global" or a client id (cli_…)
  count: number;
  firstSeen: string;
  lastSeen: string;
  source: "spelled" | "confirmed" | "order"; // the proof it was learned from
  clients: string[]; // distinct clients that confirmed it (3 → promoted to global)
  confidence: number;
  expired?: boolean; // never reused for too long: ignored, removed by POST /ai/vocab/prune
}
