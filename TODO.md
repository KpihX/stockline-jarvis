# TODO — J.A.R.V.I.S (Alpes Restauration) voice agent

Use case (validated 2026-11-23): **inbound order taking for CHR customers**, voice → ERP, for the morning salesperson (5h-9h).
Judging: Smart / Fast / Natural + use-case relevance. Submission **Tue 2026-11-24 17:30 (no exceptions)**, closing demo 18:00.
Code freeze target: Tue ~15:00. Real window ≈ 20 h.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done

## Baseline
- [~] Measure real timings: WS bench (typed turns) + 3 real voice turns (sttMs, llmFirstTokenMs, ttsFirstByteMs, totalMs, perceivedMs)
- [~] STT comparison: Soniox (kit) vs NVIDIA Riva Whisper/Parakeet (stock-ai) on `../assets/*.flac`

## STT lab (work dir: `tmp/stt-lab/`, git-ignored)
- [x] Reuse stock-ai's own STT bricks (`stockline_ai.api.stt`, key loaded by stock-ai itself, never read here)
- [x] First bench on the 2 user recordings: Whisper large-v3 (NVCF) 0.43-0.67 s, finds "Les Marseillais"; Soniox misses it on file 2 ("Les Maciers")
- [x] Parakeet diagnosed: `language=fr` is unavailable on NVCF; `multi` / `fr-FR` work (~0.5 s). My first bench failed because of that default.
- [ ] 20-sentence corpus (real clients/products, 2 TTS voices, clean + noisy): Soniox streaming vs Whisper vs Parakeet; metric = errors on entity words (client/product/quantity), not global WER
- [x] Hybrid STT: lexicon biasing -> deterministic phonetic/fuzzy resolver -> Jev picks among close candidates -> LLM receives raw text + resolved candidates
- [x] Lexicon: global (catalogue, aliases, CHR jargon) + per client (order history, client sheet); grows only from CONFIRMED orders; promote a pair seen across several clients
- [ ] NVIDIA bricks must stay optional in the jury repo (kit keys = Anthropic, Soniox, ElevenLabs, Jev); fallback = Soniox
- Note: "Les Marseillais" is not an Alpes Restauration client (94 clients checked): the 2 recordings test unknown-name robustness.
- Vocabulary (2026-11-24, details DECISIONS.md §5): `apps/ai/app/lexicon/` — phonetic resolver (candidates + score + margin, never rewrites), global + per-client lexicon (client sheet: contacts, places, usual basket), learned entries stored in the ERP context table (tag `vocab`), `learn_term` only after spelled / confirmed (yes) / order proof checked against the real conversation, promotion at 3 distinct clients (`lexicon/config.py`), decay, `forget_term` + `GET/DELETE /vocab`; STT terms client-first once the caller is known; Jev settles ambiguities (optional).
  - [x] Offline eval `scripts/bench/vocab_eval.py` on stored transcripts: entity recall soniox-plain 54→61/62, soniox-vocab 60→62/62, whisper-v3 52→62/62, parakeet 38→60/62; 0 wrong proposals on 80 transcripts + 12 negative sentences; resolver median 2.2 ms (host)
  - [ ] Re-run `tmp/stt-lab/run_soniox.py` with the new STT hint (client-first terms + jargon) to measure the real STT effect (quota)
  - [ ] Test with a real microphone, real accents and noise (the corpus is clean TTS)
  - [ ] Tune the thresholds on a bigger, independent corpus (they were set looking at the 20 sentences)
  - [ ] Optional: UI tab to list / delete learned entries (API + the client's Contexte tab exist); keep the learning across `make reset` (export / import not done)

## V0 — fast and measurable (~2 h)
- [x] V0.9 UI bug: "press Space" hint but only click-and-hold works -> make BOTH work (Space hold + pointer hold), fix labels (sub-agent)
- [x] V0.1 `DECISIONS.md` skeleton (use case/for whom/payoff/why voice · technical choices · worked/failed · measurements table)
- [x] V0.2 Filler in code on the first `ToolCallEvent` (varied, short, pre-synthesised mp3)
- [x] V0.3 Warm-up in `VoiceConnection.open()`: TTS (1 word) + LLM `max_tokens=1` + cache keep-alive ping every ~4 min
- [x] V0.4 First TTS segment cut at the comma (first sound sooner)
- [x] V0.5 Instrumentation: log `cacheRead` + cost per call (LLM tokens, STT seconds, TTS characters) for the "cheapest" prize
- [x] V0.6 Browser: persistent recorder + 300 ms pre-roll (no clipped first syllables)
- [x] V0.7 Scenario bench: synthesised caller (TTS) replayed over WS with noise, before/after table, median + worst case
- [ ] V0.8 Try `LLM_MODEL=claude-haiku-5-5` (no code) on the scenarios; keep if tool calls stay correct

  - V0.9 done: Space (hold) AND click/touch-and-hold both start/stop recording, on every page; labels say so (`lib/hold-to-talk.ts`, check: `scripts/ui-check/hold-to-talk.py`)
  - V0 notes (2026-11-23): first sound median 4.7 s → 3.3 s but it is a FILLER; real answer 4.7 s → 4.9 s (noise). See DECISIONS.md §4 and scripts/bench/results.md.
  - V0.7: the noise mix (`--noise 0.03`) is implemented but was NOT run (API quota); results are clean-audio only.
  - V0.6 has no true pre-roll (limitation documented in useVoiceSession.ts); not tested with a real microphone.

## Identity, roles and access (2026-11-23, after the live-session audit)
- [x] Declared identity (unknown / client / sales / direction): web selector (Voix, Assistant, Commande) → WS `start`, `/chat`, `/command`; persisted; changing it wipes the session
- [x] Server-side lock: `apps/ai/app/policy.py` (one table role × tool) enforced in `execute_tool`; order ownership + explicit-yes turn for a client; redaction of results
- [x] Public company card for client / unknown prompts, full context for sales / direction; identity + client sheet at the END (own cache block)
- [x] Client sheet preloaded at identification (1 tool round-trip fewer on an order: 4 → 3, see DECISIONS §6)
- [x] Unverified writes: provenance in `x-actor-name` + tags, client claims worded "Déclaré par le client (non vérifié)", low severity
- [x] `tests/test_access_policy.py` (every role × tool, prompts, sheet, enforcement), `scripts/bench/adversarial.py` (real model + `--probe`), `scripts/ui-check/caller-selector.py`
- [x] Real profile auth (`admin`, `manager`, `client`, `supplier`, `unknown`) + `/login` 1-click demo accounts + `/accounts` CRUD with strict single-admin invariant (`HTTP 409`, 2026-11-24)
- [x] Role-scoped UI pages (`orders`, `invoices`, `payments`, `purchase-orders`, `history`, `prices`, `dashboard`) + custom Client/Supplier/Manager-Admin AI-helped dashboards (`GET /suggestions`, rotating clickable cards -> Voix/Assistant)
- [x] Unified Assistant ↔ Voix SQLite sessions (`services/sessions.py` + `/sessions` REST + `list_past_sessions` / `recall_session` tools + `SessionPicker`), verified E2E via `browser-proxy`
- [x] Jev `jev_router.py` (`route_turn` 193.8 ms, `disambiguate` 162.3 ms, `confirm_action` 131.0 ms, `score_claim` 126.2 ms) + backend plausibility `warnings[]` (`season_closed`, `unusual_quantity`)
- [x] Swappable `LLM_PROVIDER=nvidia` (`nvidia/nemotron-3-ultra-550b-a55b`) live-verified after kit Anthropic cap (`total=3-21 ms` filler, `Perçu=38-39 ms`, `0.0018-0.0073 €/tour`)
- [ ] Optional: Production caller-ID / rate-limit `identify_caller`; filter lexicon hints per client
- [ ] Optional: Pre-populate `get_price` for habitual lines into the client sheet

## V1 — smart, fewer round-trips (~5 h)
- [ ] V1.1 Composite tools: `identify_caller` (client + sheet + history + alerts), `quote_product` (search + stock + client price + alternatives)
- [ ] V1.2 Lighter prompt: product glossary behind `search_context`, stable context for the cache
- [ ] V1.3 Missing tools: `update_order_line`, `remove_order_line`, `cancel_draft`, `usual_basket` ("comme d'hab") — check backend routes first
- [ ] V1.4 Jev: `is_yes` (confirmation), `pick_product` (ambiguity), routing of trivial turns without tools
- [ ] V1.5 Numbers/units/dates spoken by code ("dix-huit euros cinquante", "jeudi 26")
- [ ] V1.6 Trap scenarios: Beaufort `prd_0031` + diots `prd_0056` out of stock, blocked client, substitution refusal, change of mind (bar → cabillaud), credit limit

## V2 — natural, if time allows
- [ ] V2.1 Hands-free VAD via Soniox `<end>` tokens (Space kept as fallback)
- [ ] V2.2 Speculative LLM on a stable partial (read-only tools only, never writes)
- [ ] V2.3 ElevenLabs TTS over WebSocket
- [ ] V2.4 Barge-in: history = what was heard, not what was generated

## Delivery
- [x] `data/` seed bundled and `README.md` updated for `make setup` from a fresh clone
- [x] Dedicated repo `KpihX/stockline-jarvis` created and synced on `main`
- [x] `DECISIONS.md` finalized with proactivity thesis, architecture, and measured tables
- [x] Slides (`presentation/`, <= 5 min) + Demo video (`demo/stockline-jarvis-demo.mp4`, <= 2 min)
- [x] Live rehearsal & `make reset` before submission (Tue 17:30)

## Open questions
- NVIDIA/Nemotron: only usable with KpihX's own NVIDIA key (kit keys = Anthropic, Soniox, ElevenLabs, Jev).
- Dedicated private repo `KpihX/stockline-jarvis` created and synced on `main`.

## Session memory + latency (2026-11-23, details DECISIONS.md §6)
- [x] Session memory: SQLite under `$AI_STATE_DIR` (Docker volume `ai-state`), write-through per turn, restore on reconnect, TTL 12 h, cap 200, `reset` deletes, falls back to memory if the dir is missing/unwritable/corrupted; survives an uvicorn hot reload (checked live)
- [x] Compaction instead of `trim(40)`: last 6 turns verbatim, older ones → one deterministic summary of business facts (ids, order lines, prices, ERP errors, unverified claims), background task, cache prefix untouched; optional LLM refinement behind `COMPACT_LLM` (off)
- [x] Early filler at the final transcript (heuristic `turn_hints.py`, skipped for trivial turns / a filler < 10 s ago), never doubled by the model's text; kill-switches `VOICE_EARLY_FILLER`, `VOICE_TOOL_START`
- [x] Tool call announced at `content_block_start` (`LLMToolStart` → `ToolStartEvent` → `agent_tool {name}` then `{name, args}`), web + shared types updated
- [x] Measured A/B (4 real turns per variant): first sound median 3.3 s → 1.23 s (disjoint ranges); real answer NOT faster in a provable way (noise)
  - [ ] Replay a real 12+ turn call to see the compaction at work (only synthetic histories + 1 real turn so far)
  - [ ] Decide whether the browser keeps `sessionId` in `sessionStorage` (resume the call after F5)
  - [ ] Measure the early-filler false-positive rate on real calls; V2.2 speculative LLM is the only lever left on the real answer
