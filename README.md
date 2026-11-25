# Stockline × X-Forum — J.A.R.V.I.S (Alpes Restauration)

> **J.A.R.V.I.S — *Juste un Agent Rapide pour la Voix et l'Inventaire Stockline***  
> **La Proactivité comme Architecture** — Agent vocal temps réel + **appels WhatsApp VoIP WebRTC bicanaux (`/calls`)**, copilote ERP multi-rôles, décisions rapides TypeSafe Jev System One (`126–194 ms`), lexique phonétique auto-apprenant (`62/62`, `2,2 ms`), repli multi-LLM agnostique (`opencode-go → nvidia → anthropic`) et garde-fous métier déterministes (`season_closed`, `unusual_quantity`).

## Livrables officiels du Hackathon (J.A.R.V.I.S)

| Livrable | Emplacement dans le dépôt | Contenu & Chiffres clés |
|---|---|---|
| **1. `DECISIONS.md`** | **[`DECISIONS.md`](DECISIONS.md)** | Thèse (*La Proactivité comme Architecture*), cas d'usage (prise de commande matinale 5 h – 9 h), choix techniques, appels WhatsApp VoIP réels + repli multi-LLM, limites honnêtes et mesures (1er son **1,23 s**, STT cadencé **225 ms**, Jev **126–194 ms**, lexique **62/62** à 0 FP). |
| **2. Vidéo de démo (≤ 2 min)** | **[`demo/stockline-jarvis-demo.mp4`](demo/stockline-jarvis-demo.mp4)** | Parcours réel commenté de bout en bout (**1 min 55 s**, 1920×1080 30 fps, H.264/AAC) : connexion 1-clic → Dashboard Client IA → Voix piège (`season_closed` + Jev) → Assistant unifié → Fournisseur & Admin `409` → **appairage WhatsApp QR (`/settings`)** → **vrai appel WhatsApp bicanal (`337`) confirmé dans l'ERP (`326 € HT`)**. |
| **3. Slides (≤ 5 min)** | **[`presentation/build/Stockline-JARVIS-Alpes-Restauration.pdf`](presentation/build/Stockline-JARVIS-Alpes-Restauration.pdf)** · **[`.pptx`](presentation/build/Stockline-JARVIS-Alpes-Restauration.pptx)** | **9 slides** (budget oral **4,5 min** à 140 mpm, code source reproductible dans [`presentation/`](presentation/) via `make -C presentation build`), intégrant la centrale d'appels WhatsApp VoIP réelle et le repli multi-LLM. |
| **4. Code & Données (`./data/seed`)** | Racine du dépôt (`apps/`, `packages/`, `data/seed/`) | Graine complète d'**Alpes Restauration** (`data/seed/*.json` + `data/context/*.md`) incluse pour que **`make setup` fonctionne immédiatement après `git clone`** (`backend:4000`, `ai:4100`, `web:5173`, `wa:3001`). |

### Démarrage rapide Jury (1 commande)

```bash
# 1. Cloner et lancer (Docker recommandé : crée .env depuis .env.example si absent, construit et démarre backend:4000, ai:4100, web:5173, wa:3001)
make setup

# (Optionnel) Placer vos clés API réelles (OpenCode Go / NVIDIA / Anthropic / Soniox / ElevenLabs / Jev) dans .env puis :
make restart

# (Alternative sans Docker : Python 3.12 via uv + Node 22 / pnpm)
make local
```

Une fois démarré, ouvrez **http://localhost:5173** (la page `/login` propose **8 comptes de démo en connexion 1-clic**) :

| Profil | Identifiant (1-clic sur `/login`) | Mot de passe | Périmètre vérifié côté serveur |
|---|---|---|---|
| **Admin unique** | `@admin` (*Direction Alpes*) | `demo-admin` | Accès complet ERP + `/accounts` (invariant strict : 1 seul admin, `HTTP 409` sinon) |
| **Commercial** | `@thibault` (*Thibault Gros*) · `@emilie` (*Émilie Brun*) | `demo-thibault` · `demo-emilie` | Tout le métier ERP (commandes, clients, stocks, achats, tournées), sans `/accounts` |
| **Client CHR** | `@payet` (*Le Refuge Payet*) · `@leila` · `@igloo` | `demo-payet` · `demo-leila` · `demo-igloo` | Dashboard Client IA, ses commandes, ses habitudes, ses tarifs et factures uniquement |
| **Fournisseur** | `@chambaran` (*Volailles du Chambaran*) · `@perrier` | `demo-chambaran` · `demo-perrier` | Dashboard Fournisseur IA, ses bons d'achat et réceptions uniquement (zéro donnée client) |

Commandes de vérification et de remise à zéro :
- `make check` : vérification TypeScript (`tsc --noEmit`) + contrôle design-system.
- `make test` : **391 tests** unitaires et d'intégration du service IA (`apps/ai`), plus **59 tests** backend (`docker compose exec -T backend pytest -q` ou `cd apps/backend && uv run pytest -q`).
- `make reset` : réinitialise la base ERP SQLite à partir de `data/seed/` (et bouton **`Réinit tests (ERP + Appels)`** sur `/calls` pour remettre à zéro ERP + appels tout en conservant le QR WhatsApp et les numéros associés).
- `curl -s http://localhost:4100/jev/stats` : télémétrie temps réel de TypeSafe Jev System One (`p50_ms`, `p90_ms`, nombre d'appels).

---

# Voice ERP kit (Documentation de référence du kit)

A small but complete ERP for a food wholesaler, an AI service that reads and writes it through tools, and a
push-to-talk voice harness. Built for the Stockline voice hackathon: make the voice agent **smart, fast and natural**.

**Install and run: [SETUP.md](SETUP.md)** (French, step by step: Mac, Windows/WSL, Linux, without Docker,
troubleshooting). **The challenge: [BRIEF.md](BRIEF.md)** (French). How the food wholesale trade works:
[METIER.md](METIER.md). How the ERP works (pages, business rules, API): [ERP.md](ERP.md). How everything works under the
hood and how to extend it: [TECH.md](TECH.md) (French). Using a coding agent? Point it at [AGENTS.md](AGENTS.md). This
README covers the architecture, the configuration and how to extend the kit.

### Quelle doc lire ?

| Doc | À lire quand… |
|---|---|
| [GLOSSAIRE.md](GLOSSAIRE.md) | un mot technique vous échappe (Docker, port, token, STT, WebSocket…) |
| [FAQ.md](FAQ.md) | vous avez une question pratique : où coder, comment tester, clés, coûts, livrables |
| [SETUP.md](SETUP.md) | vous installez et lancez le kit, ou quelque chose ne démarre pas |
| [BRIEF.md](BRIEF.md) | vous voulez savoir ce qu'on attend de vous : le défi, les livrables, le jury |
| [METIER.md](METIER.md) | vous ne connaissez pas le métier de grossiste alimentaire ou son vocabulaire |
| [ERP.md](ERP.md) | vous cherchez ce que fait l'ERP : pages, cycles de vie, règles métier, aide-mémoire de l'API |
| [TECH.md](TECH.md) | vous codez : comment marchent l'ERP, le service IA, les outils `@tool`, la voix et le web, et comment les étendre |
| [GUIDE-VOIX.md](GUIDE-VOIX.md) | vous voulez un agent vocal plus rapide et plus naturel : métriques, mesures du kit, techniques et où les brancher |
| [GUIDE-AGENTS.md](GUIDE-AGENTS.md) | vous découvrez les agents LLM, ou voulez rendre le vôtre plus smart, rapide et moins cher : concepts, où ils vivent dans le kit, conseils |
| [AGENTS.md](AGENTS.md) | vous donnez le projet à un agent de code (Claude Code, Cursor, Codex…) |
| [DESIGN.md](DESIGN.md) | vous modifiez l'interface web |

Everything runs offline out of the box: with the `mock` providers the LLM, speech-to-text and text-to-speech are
deterministic fakes that still call the real ERP. Add your keys when you are ready.

> **J.A.R.V.I.S (Juste un Agent Rapide pour la Voix et l'Inventaire Stockline — Alpes Restauration) :** `data/seed` is bundled so `make setup` runs cleanly from a fresh clone.
> Key additions on `stockline-jarvis`:
> - **WhatsApp VoIP WebRTC Call Desk (`/calls` & `/settings`, `apps/wa`)**: real WhatsApp calls via Baileys VoIP + pure-TS `werift` Opus 48 kHz ↔ 16 kHz VAD bridge, live QR pairing, phone-to-ERP client binding (`calls.db`), bicanal live transcription, Jev turn chips, abstention-guarded J.A.R.V.I.S ERP copilot (`POST /ai/calls/{id}/orders/{ord}/confirm`), 1-click call simulator, and 1-click test reset (`POST /ai/calls/reset`).
> - **Agnostic OpenAI-compatible + ordered LLM fallback (`apps/ai/app/clients/fallback.py`)**: supports `opencode-go` (`https://opencode.ai/inference/go/openai/v1` with `x-opencode-session`), `nvidia` Nemotron, `anthropic` Claude, or comma-separated failover chains (`LLM_PROVIDER=opencode-go,nvidia,anthropic`).
> - **5-role authentication & strict single-admin** (`/login` with 1-click demo profiles: `admin`, `thibault`, `emilie`, `payet`, `leila`, `igloo`, `chambaran`, `perrier`; `/accounts` CRUD with `HTTP 409` on a 2nd admin).
> - **AI-helped personalised Dashboard** (`GET /ai/suggestions` + `WhatsAppCallsWidget`): live briefing + rotating clickable action cards routing directly to **Voix**, **Appels WhatsApp**, or **Assistant**.
> - **Unified Assistant ↔ Voix sessions** (`apps/ai/app/services/sessions.py` + `sessions.db`): list, search, rename, delete, resume, and continue a voice turn inside text Assistant (and vice-versa).
> - **Proactive intelligence & safety**: early filler at final transcript + tool start (`total` 1.23 s median audio / 21–39 ms post-transcript), phonetic lexicon resolver (`62/62`, 2.2 ms, confirmed-only learning, Soniox `MAX_TERMS_CHARS=10000`), TypeSafe Jev micro-decisions (`126–194 ms`), and deterministic backend plausibility warnings (`season_closed`, `unusual_quantity`).
> - **Deliverables**: [`DECISIONS.md`](DECISIONS.md) (thesis & measured tables), [`presentation/`](presentation/) (5-min deck-as-code), [`demo/`](demo/) (<= 2-min demo video), [`TEST_WHATSAPP_CALL.md`](TEST_WHATSAPP_CALL.md) (2-person real call script).

| Part | Path | Stack | Port |
|---|---|---|---|
| ERP backend | `apps/backend` | Python 3.12 · FastAPI · SQLite | 4000 |
| AI service (LLM / STT / TTS, agent, chat, voice, calls) | `apps/ai` | Python 3.12 · FastAPI · httpx | 4100 |
| Web app | `apps/web` | React · Vite · Tailwind (TypeScript) | 5173 |
| WhatsApp VoIP WebRTC bridge | `apps/wa` | Node 22 · TypeScript · Baileys VoIP + `werift` | 3001 (+ 40000-40020/udp) |
| Your company's data (seed, context docs) | `./data` (from your team zip, `DATA_DIR`) | JSON + Markdown | — |

In short: `make setup` the first time (Docker), `make up` / `make down` afterwards, `make local` / `make dev` without
Docker, `make restart` after editing `.env`, `make reset` to reload the ERP data, `make help` for every command.
Code changes reload live in both modes (uvicorn `--reload`, Vite HMR).

---

## Configuration: one `.env`

All three services read the single `.env` at the repo root (your team zip ships it; otherwise `make setup` copies
`.env.example`). Real environment variables win over the file. After a change: `make restart` (Docker) or restart
`make dev` (local). `GET localhost:4100/health` shows which providers are active. Never commit `.env` (it is git-ignored).

| Variable | Meaning |
|---|---|
| `DATA_DIR` | your company's data, relative to the repo root (`./data` in your team zip) |
| `WEB_PORT`, `API_PORT`, `AI_PORT` | ports on your machine (5173 / 4000 / 4100) |
| `ERP_API_URL` | where the AI service reaches the ERP in local mode (`http://localhost:4000`; Docker sets it itself) |
| `LLM_PROVIDER`, `LLM_FALLBACKS`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` | `opencode-go` (`https://opencode.ai/inference/go/openai/v1`, key `OPENCODE_API_KEY`) · `nvidia` (`nemotron-3-ultra-550b-a55b`, key `NVIDIA_API_KEY`) · `anthropic` (`ANTHROPIC_API_KEY` or `LLM_API_KEY`) · `deepseek` · `openai` · `gemini` · `openai-compatible` · `mock`. Supports comma-separated fallback chains (e.g. `LLM_PROVIDER=opencode-go,nvidia,anthropic`). **Clear `LLM_MODEL=`** when switching providers. |
| `OPENCODE_API_KEY`, `ANTHROPIC_API_KEY`, `LLM_INCLUDE_USAGE` | dedicated per-provider keys for fallback chains + optional `1`/`0` override for `stream_options.include_usage` on custom OpenAI-compatible servers |
| `LLM_EFFORT` | Anthropic: `low` (default) · `medium` · `high` · NVIDIA Nemotron: `none`/`low` (thinking off) · `medium`/`high` (thinking on) |
| `WA_PORT`, `WA_URL`, `WHATS_PROXY_STATE_DIR`, `ICE_SERVERS` | WhatsApp VoIP WebRTC bridge (`3001`, Docker `http://wa:3001`, persistent volume `wa-state:/wa-state`, STUN `stun:stun.l.google.com:19302`) |
| `STT_PROVIDER`, `STT_API_KEY`, `STT_MODEL`, `STT_LANGUAGE` | `soniox` · `deepgram` · `gradium` · `openai` · `nvidia` (optional, see below) · `mock` |
| `NVIDIA_API_KEY`, `NVIDIA_STT_FUNCTION_ID`, `NVIDIA_STT_URI`, `NVIDIA_STT_BOOST`, `NVIDIA_STT_STREAMING` | only for `STT_PROVIDER=nvidia`, all optional but the key |
| `AI_UV_SYNC_ARGS`, `AI_APT_PACKAGES` | Docker build only: extras for the `ai` image (`--extra nvidia`, `ffmpeg`); empty = stock image |
| `TTS_PROVIDER`, `TTS_API_KEY`, `TTS_MODEL`, `TTS_VOICE`, `TTS_LANGUAGE` | `elevenlabs` · `gradium` · `openai` · `mock` (the browser speaks the text) |
| `JEV_API_KEY`, `JEV_BASE_URL`, `JEV_MODEL` | optional Jev decision model (TypeSafe AI, `jev-latest`), used **next to** the LLM, not instead of it: choice / score / yes-no with probabilities. The default agent does not call it — see [apps/ai/README.md](apps/ai/README.md#jev-decision-model) |
| `AGENT_MAX_STEPS` | max model ↔ tool round-trips per turn (8) |
| `MOCK_STT_TEXT` | what the mock STT "hears", whatever you say (default "Bonjour, il vous reste du bar ?") |

An empty `*_MODEL` / `TTS_VOICE` picks the provider's default; the defaults are listed in
[apps/ai/README.md](apps/ai/README.md#environment). Your team `.env` lists every key your team received as comments at
the bottom: to switch provider, set `*_PROVIDER` and paste the matching key into `*_API_KEY`
([SETUP.md](SETUP.md#changer-de-modèle-ou-de-voix)).

### Switching the STT provider

One variable, `STT_PROVIDER`, then `make restart`. Everything else (live partials, vocabulary hint, fallbacks) is the
same code path: an adapter only implements `STTClient` (`clients/base.py`).

| `STT_PROVIDER` | Needs | Default model | Live (partials) | Vocabulary hint |
|---|---|---|---|---|
| `mock` | nothing | — | yes (simulated) | returned as the transcript |
| `soniox` | `STT_API_KEY` | `stt-rt-v6` | yes (WebSocket) | `context.terms` |
| `deepgram` | `STT_API_KEY` | `nova-3` | yes (WebSocket) | `keyterm` |
| `gradium` | `STT_API_KEY` | `default` | no (REST) | keyword boosting |
| `openai` | `STT_API_KEY` | `gpt-4o-mini-transcribe` | no (REST) | prompt |
| `nvidia` | `NVIDIA_API_KEY` (or `STT_API_KEY`) + the optional extra | `parakeet` (`whisper` = offline only) | Parakeet yes (Riva gRPC), Whisper no | Parakeet: Riva word boosting; Whisper: none |

**NVIDIA STT (optional; the jury repo runs without it).** `clients/nvidia.py` talks Riva gRPC to NVCF
(`grpc.nvcf.nvidia.com:443`), `nvidia-riva-client` is imported on first use. Without the package or the key, only
`STT_PROVIDER=nvidia` complains (clear message); every other provider is untouched.
- Local (`make dev`): `cd apps/ai && uv sync --extra nvidia`, and `ffmpeg` on the machine (it decodes the browser's
  WebM/Opus; WAV 16 kHz mono needs none).
- Docker: set `AI_UV_SYNC_ARGS=--extra nvidia` and `AI_APT_PACKAGES=ffmpeg` in `.env`, then `make rebuild`.
- `STT_MODEL`: `parakeet` (streaming + word boosting) or `whisper` (one blocking call on the whole recording, run in a
  thread, no boosting). Any other Riva function: `NVIDIA_STT_FUNCTION_ID`. `STT_LANGUAGE=fr` becomes `fr-FR` for Parakeet
  (`fr` alone is refused by the function; `multi` also works).
- `NVIDIA_STT_BOOST`: one boost score for all vocabulary terms (RNNT range 0.5–2.0, default 1.0, `0` = off).
  `NVIDIA_STT_STREAMING=auto|on|off` forces live recognition on or off.

---

## Architecture

```
                 HTTP /api/*  (x-actor: user)                   ┌─────────────────────────────────┐
   ┌──────────┐ ──────────────────────────────────────────────▶ │ apps/backend  :4000  FastAPI    │
   │ apps/web │ ◀──────────── SSE /api/events/stream ────────── │ routers → services → crud       │
   │  :5173   │                                                 │ SQLite + data pack              │
   │  React   │   POST /ai/chat (SSE) · /ai/command · WS /ai/voice └─────────────────────────────────┘
   │          │ ─────────────────────────────┐                                ▲
   └──────────┘                              ▼                                │ tools = HTTP /api/*
                                  ┌─────────────────────────────────┐         │ (x-actor: ai_chat | voice_agent)
                                  │ apps/ai  :4100  FastAPI         │ ────────┘
                                  │ STT → agent loop → TTS          │
                                  │ LLM ⇄ @tool functions           │ ──▶ LLM / STT / TTS providers (or mocks)
                                  └─────────────────────────────────┘
```

- The web app reaches both services through the Vite proxy (`/api` → backend, `/ai` → AI service).
- The AI service is just another ERP client: every tool is an HTTP call to the backend, so business rules live in one place.
- **The Python Pydantic schemas are the contract.** FastAPI publishes them at `/openapi.json`; `make types` generates
  the frontend's TypeScript types from them (`packages/shared/src/generated/`). Change a schema → `make types`.

### Backend (`apps/backend/app`)

| Folder | Role |
|---|---|
| `routers/` | thin FastAPI routers, one per resource (clients, orders, stock, pricing, context…) |
| `services/` | business rules: order lifecycle, FEFO stock reservation, price resolution, credit limits, invoicing, receivables, search |
| `crud/` | generic CRUD over the tables |
| `schemas/` | Pydantic models (camelCase JSON) = the API contract |
| `core/` | config, database, data pack loader, activity log (SSE) |
| `dependencies.py` | shared dependencies (the `x-actor` of each request…) |

### AI service (`apps/ai/app`)

| Folder | Role |
|---|---|
| `clients/` | abstract `LLMClient`, `STTClient`, `TTSClient` + one file per provider + `presets.py` + `fallback.py` + `factory.py` (from `.env`) |
| `agent/` | `loop.py` (the agent loop) and `prompts.py` (rules per mode + company context + business date) |
| `tools/` | the functions the model can call, declared with `@tool` |
| `routers/` | `/chat`, `/command`, `/voice` (WebSocket), `/calls/*` + `/wa/*` (WhatsApp VoIP + QR), `/sessions/*`, `/suggestions`, `/vocab`, `/stt`, `/tts`, `/health`, `/tools` |
| `services/` | `voice_session.py` (push-to-talk, barge-in, sentence-by-sentence TTS, timings), `calls.py` (WhatsApp VoIP + async STT/Jev + coalesced copilot), `sessions.py`, `command.py` |
| `schemas/` | the wire contract (chat events, voice messages) |

Details, protocols and the agent loop: [`apps/ai/README.md`](apps/ai/README.md).

---

## The agent

One turn = **system prompt + conversation → model → (tools in parallel → model)* → answer**, streamed as events
(`text`, `tool_call`, `tool_result`, `done`). Three modes share it:

| Mode | Where | Style |
|---|---|---|
| `chat` | Assistant panel (⌘J) | short markdown answers |
| `voice` | **Voix** page, `WS /voice` | 1–2 spoken sentences, numbers said out loud |
| `command` | hold Space (or click-and-hold the header "Voix" button) anywhere; ⌥Space too | acts immediately, one-line answer, can open a page |

### Add a tool

Write an async function with `@tool` in `apps/ai/app/tools/` — the signature becomes the JSON schema, the docstring
the description the model reads:

```python
@tool
async def list_overdue_invoices(ctx: ToolContext, client_id: str = Field(description="ex. cli_0012")) -> list[dict]:
    """Factures en retard d'un client. Use when the caller asks what they owe or why they are blocked."""
    invoices = await ctx.erp.get("/api/invoices", {"clientId": client_id, "status": "overdue"})
    return [{"number": i["number"], "balance": i["balance"], "daysOverdue": i["daysOverdue"]} for i in invoices]
```

Then import it in `apps/ai/app/tools/__init__.py`. Return small JSON (the model re-reads it every step) and raise on
errors: the loop turns exceptions into `{"error": …}` so the model can explain or retry. If the ERP lacks an
endpoint, add the rule in `apps/backend/app/services/` and the route in `apps/backend/app/routers/`.

### Add a provider

Subclass `LLMClient` / `STTClient` / `TTSClient` from `apps/ai/app/clients/base.py`, then add one line to
`clients/factory.py`. The existing adapters are plain `httpx` calls — read `openai.py` to see streaming end to end.

---

## The data pack

Your team zip ships **your company** in `./data` (`DATA_DIR=./data`): one of 24 fictional food wholesalers
(fish, fruit & veg, meat, dairy, drinks, frozen…), each with ~100 clients, its suppliers and products and 3 years of
history. Every team has a different one.

- `data/seed/*.json`: the ERP data (clients, products, lots, orders, invoices, payments, routes, events, prices, context).
- `data/context/*.md`: company knowledge (playbooks, glossary, pricing, delivery zones) — put whole into the system
  prompt and re-read every turn, so you can edit it live. `data/context/clients/` and `data/context/suppliers/`: persona sheets.

The data is anchored on a fixed business day, `meta.today` (`GET /api/meta`): new records are stamped on that day and
the web app shows relative times on that clock, whatever your real date is.

### Context table

Every piece of business knowledge is also a row of the **context table**, attached to an entity:
`{ id, entityType: company|client|supplier|product|category, entityId, kind, title, body (markdown), tags, source }`.
`kind`: policy · procedure · preference · fact · relationship · pricing · logistics · risk. `source`: seed · user ·
ai_chat · voice_agent.

- **API**: `GET /api/context?entityType=&entityId=&kind=&q=`, `GET /api/context/for?entityType=client&id=cli_0001`
  (its entries + related ones), `POST/PATCH/DELETE /api/context…`.
- **Agent tools**: `get_context`, `search_context`, `save_context` (remember a fact learned during a call).
- **Web**: **Contexte** page, a "Ce que l'agent sait" block on client and supplier pages, a Contexte tab on each.

---

## Voice

- **Voix** page (`/voice`): hold **Space** to talk as the caller, release to send (or type). Shows the transcript,
  streamed answer, tool calls, per-turn timings (STT, first LLM token, first audio byte, total) and the ERP changes live.
  Talking while the agent speaks interrupts it.
- **Hold Space, or click-and-hold the header "Voix" button**, on any page: one-shot voice command (⌥Space also works, even in a text field, where the OS lets Alt+Space through; "crée une commande pour l'Écume, 5 kilos de bar").
- **Live transcription**: the audio is streamed to the STT while the key is down (Soniox, Deepgram; the mock simulates it),
  so the caller's words appear as they are spoken (grey italic = provisional) and the final text is ready right after the
  release. Client / product names from the ERP are sent as STT vocabulary. See TECH.md « Transcription en direct ».
- Protocol: `WS /voice` and `WS /voice/command` (proxied as `/ai/voice…`), documented in `apps/ai/README.md`. Script it with `{type:"text"}` turns.

## Activity stream

Every ERP write logs an event with its actor from the `x-actor` header (`user` · `ai_chat` · `voice_agent`).
`GET /api/events`, live at `GET /api/events/stream` (SSE). The **Activité** page shows them; rows the agent touches
flash violet in every open page — so the ERP visibly updates during a call.

---

## Where to start

- **Fast**: streaming STT with partial transcripts, start the LLM before the caller finishes, speak the first sentence
  while the rest is generated, parallel and speculative tool calls, a fast model for easy turns.
- **Smart**: load the caller's context at call start (client entries, usual basket, open issues), retrieval or a graph
  over the context table, composite tools, a dialogue state for orders, deterministic code for quantities and dates.
- **Natural**: short turns, barge-in, fillers while tools run, reading back orders, French numbers and units, noise.

## Troubleshooting

Install and run problems (Docker, ports, WSL, mic, keys): [SETUP.md](SETUP.md#en-cas-de-problème). While coding:

| Symptom | Fix |
|---|---|
| New dependency not found | `make rebuild` (Docker) or `uv sync` / `pnpm install` (local) |
| Frontend type errors after a schema change | `make types` |
| A provider error in the voice UI | it reads `<provider> HTTP <status>: …` with a hint (bad key, quota, audio format); `make logs` shows the rest |

Design system of the web app: [`DESIGN.md`](DESIGN.md).
