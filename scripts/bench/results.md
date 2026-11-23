# Bench results (append-only)

Produced by `scripts/bench/bench.py` (see its docstring). One real LLM turn per scenario, single sample: expect ±1 s of noise
on LLM figures (model behaviour varies: number of tool rounds, answer length). Medians/worst are across the 6 scenarios.

## baseline (kit d'origine, code non modifié)
_2026-11-23 21:38_ · llm `anthropic:claude-sonnet-5-5` · stt `soniox` · tts `elevenlabs` · noise none · t0 = audio_end sent (key release) · `clientFirstAudioMs` = t0 → first binary agent frame seen by the bench · no filler / cost fields exist yet in this code

| scenario | ok | sttMs | llm1stMs | llmTotMs | ttsFirstMs | totalMs | clientFirstMs | tools |
|---|---|---|---|---|---|---|---|---|
| stock_beaufort | ✅ | 1194 | 3568 | 3571 | 138 | 4903 | 4903 | get_product_stock |
| prix_comte | ❌ (see note) | 1521 | 524 | 992 | 161 | 2403 | 2403 | (none) |
| surnom_patates | ✅ | 1226 | 4849 | 4853 | 150 | 6227 | 6228 | get_product_stock |
| ambigu_reblochon | ✅ | 1542 | 558 | 2334 | 168 | 4045 | 4045 | get_product_stock ×2 |
| dhab_sans_confirmer | ✅ | 1508 | 4415 | 4419 | 139 | 6064 | 6065 | search, get_client, get_context |
| client_bloque_commande | ✅ | 1529 | 2756 | 2759 | 160 | 4448 | 4448 | search |
| **median** | 5/6 | 1514 | 3162 | 3165 | 155 | 4676 | 4676 | |
| **worst** | 5/6 | 1542 | 4849 | 4853 | 168 | 6227 | 6228 | |

Note (appended after the run): `prix_comte` was marked ❌ only because the first bench version required a tool call; the answer
("24 euros 50 le kilo au tarif catalogue") came straight from the catalogue in the prompt and is correct. The expectation was
relaxed afterwards → this baseline is **6/6** on the final scenario definitions. STT misheard "patates" as "pâtes" in `surnom_patates`
(the agent recovered by asking back). In `ambigu_reblochon` the model spontaneously said "Oui, je regarde." before its tools
(that is why its llm1stMs is only 558 ms, while totalMs stays at 4 s: that sentence was short and only the first sentence is spoken early).

Correction (appended): the sentence above is wrong. totalMs stayed at 4 s because `Speaker.SENTENCE` needs a space *after* the full stop
and the next text only arrives after the tools, so the model's own "Je regarde." was held back until the tools were done: a model-side
filler does NOT give an early first sound in the kit as shipped (it needs V0.2, and the comma cut V0.4 for the first segment).


## V0.2-V0.5 (filler en code + warm-up + coupe virgule + coût), voix de l'appelant propre, sans bruit
_2026-11-23 21:47_ · llm `anthropic:claude-sonnet-5-5` · stt `soniox` · tts `elevenlabs` · noise none · t0 = audio_end sent (key release) · `clientFirstAudioMs` = t0 → first binary agent frame seen by the bench · `answerMs` = t0 → first byte of the real answer (server; = totalMs when no filler)
Single sample per scenario (same 6 scenarios as the baseline, same synthesised caller audio). Server logs `[turn] …` carry the same numbers plus `tool1` = start of agent → first tool call announced (0.9 s, 1.0 s, 1.8 s, 2.1 s, 2.3 s on the five tool turns).

| scenario | ok | sttMs | llm1stMs | llmTotMs | ttsFirstMs | totalMs | answerMs | clientFirstMs | 1st sound | in/out/cacheR/cacheW tok | STT s | TTS chars | € | tools |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| stock_beaufort | ✅ | 1616 | 2117 | 2123 | 135 | 2512 | 3870 | 2514 | filler | 6/168/46982/254 | 4.0 | 252 | 0.0148 | get_product_stock |
| prix_comte | ✅ | 1580 | 2726 | 3603 | 149 | 4658 | 4658 | 4658 | answer | 4/197/23442/107 | 6.7 | 152 | 0.0094 | (none) |
| surnom_patates | ✅ | 1568 | 2423 | 2427 | 145 | 2539 | 4140 | 2540 | filler | 6/163/46987/444 | 4.0 | 184 | 0.0129 | search |
| ambigu_reblochon | ✅ | 1549 | 3427 | 3433 | 132 | 3371 | 5112 | 3373 | filler | 6/239/46971/522 | 2.9 | 274 | 0.0167 | get_product_stock ×2 |
| dhab_sans_confirmer | ✅ | 1182 | 7087 | 7091 | 117 | 3315 | 8388 | 3316 | filler | 8/369/71010/4078 | 5.6 | 223 | 0.0259 | search, get_client, get_context |
| client_bloque_commande | ✅ | 1949 | 4127 | 4130 | 147 | 4251 | 6226 | 4253 | filler | 6/234/47003/591 | 6.7 | 363 | 0.0200 | search |
| **median** | 6/6 | 1574 | 3076 | 3518 | 140 | 3343 | 4885 | 3344 | 5 filler / 1 answer | | | | 0.0158 | |
| **worst** | 6/6 | 1949 | 7087 | 7091 | 149 | 4658 | 8388 | 4658 | | | | | 0.0259 | |

Reading (honest): the FIRST SOUND (a canned filler on five of six turns) moved from a median of 4.7 s to 3.3 s (worst 6.2 s → 4.7 s),
but it is a filler, not information. The real ANSWER did not get faster: median 4.9 s vs 4.7 s before, worst 8.4 s vs 6.2 s (the
worst is the 3-tool-round scenario, which took 7.1 s of LLM this time; LLM time varies by ±1-2 s between runs of the same scenario, so
this is within noise, not a regression we can prove). The filler is bounded below by STT (~1.2-1.9 s) + time to the first tool call
(0.9-2.3 s): the Anthropic adapter yields `LLMToolCall` only when the whole model message has ended.
Estimated cost per turn: €0.009-0.026 (median €0.016), almost all LLM (23.5k-token prompt re-read at each model call).
Fillers with cached mp3: 0 TTS call at the moment; the 6 clips (96 KB) are synthesised once per process at first session open.
