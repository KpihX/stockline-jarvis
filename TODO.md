# TODO — team-01 (Alpes Restauration) voice agent

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
- [ ] Hybrid STT: lexicon biasing -> deterministic phonetic/fuzzy resolver -> Jev picks among close candidates -> LLM receives raw text + resolved candidates
- [ ] Lexicon: global (catalogue, aliases, CHR jargon) + per client (order history, client sheet); grows only from CONFIRMED orders; promote a pair seen across several clients
- [ ] NVIDIA bricks must stay optional in the jury repo (kit keys = Anthropic, Soniox, ElevenLabs, Jev); fallback = Soniox
- Note: "Les Marseillais" is not a team-01 client (94 clients checked): the 2 recordings test unknown-name robustness.

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
- [ ] README: how to restore `data/` next to the Makefile (seed is git-ignored)
- [ ] Private repo + jury as collaborators (decide: dedicated repo vs branch of `stock-ai`)
- [ ] Video 2 min (real end-to-end call) · slides 5 min · rehearse live demo
- [ ] Submit before Tue 17:30

## Open questions
- NVIDIA/Nemotron: only usable with KpihX's own NVIDIA key (kit keys = Anthropic, Soniox, ElevenLabs, Jev).
- Dedicated private repo or keep `feat/team-01-kit` inside `stock-ai`?
