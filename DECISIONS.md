# DECISIONS.md — team-01 (Alpes Restauration)

Living document. Numbers in section 4 are **measured** (bench in `scripts/bench/`, raw tables in `scripts/bench/results.md`); everything
else is a decision or a hypothesis and is labelled as such. Last update: 2026-11-23 (V0).

## 1. Le problème (use case validé le 2026-11-23)

**Prise de commande entrante des clients CHR, voix → ERP, pour le commercial du matin (5 h – 9 h).**

| | |
|---|---|
| **Quoi** | Un client (restaurant, brasserie, cantine, hôtel d'altitude) appelle pour commander. L'agent vocal l'identifie, regarde stock et prix négocié, signale les pièges (client bloqué, rupture, pas de substitution), prépare un **brouillon** de commande, la relit, et ne la confirme qu'après un « oui » explicite. |
| **Pour qui** | Le commercial / l'ADV qui décroche tôt le matin chez Alpes Restauration : plusieurs appels courts, souvent les mains prises, le même vocabulaire de métier (« une meule », « comme d'hab », « du beaufort d'alpage »). Le client, lui, veut une réponse tout de suite et sans répéter. |
| **Pourquoi ça vaut le coup (hypothèse, non mesurée)** | Le téléphone est le premier canal de commande (38 % sur 12 mois, `data/context/01-entreprise.md`) et chaque commande est ressaisie à la main. L'enjeu est de ne plus ressaisir, de ne pas oublier une ligne, et de ne pas promettre un produit en rupture. Nous n'avons **pas** mesuré le gain de temps par appel : à chiffrer en démo (minutes par commande, à la main vs avec l'agent). |
| **Pourquoi la voix** | L'appelant parle déjà : le goulot est la saisie, pas la décision. La voix supprime l'écran entre l'appelant et l'ERP. Condition : la latence doit rester celle d'une conversation (cible < 1,5 s au premier son, voir §4), sinon un formulaire est meilleur. |

Garde-fous métier (non négociables) : l'agent n'agit que par les outils ; les règles (prix, stock, crédit) restent dans le backend ;
une commande se crée en brouillon et **ne se confirme jamais sans accord explicite** ; client bloqué = on n'enregistre rien.

## 2. Choix techniques

| Sujet | Choix | Pourquoi / limite |
|---|---|---|
| Architecture | Cascade STT → LLM → TTS en streaming sur `WS /voice` (kit inchangé) | Les chevauchements se gagnent à l'intérieur de la cascade ; pas de modèle « realtime » fourni par le kit. |
| STT | Soniox temps réel, audio envoyé pendant la parole (kit) | Au relâchement il ne reste que les derniers mots à finaliser : `sttMs` ≈ 1,2-1,9 s dans notre bench (voir §4, ce n'est pas « quelques centaines de ms »). |
| LLM | `claude-sonnet-5-5`, effort `low`, prompt cache Anthropic (kit) | V0.8 (Haiku 5.5) **non testé** à ce jour. |
| TTS | ElevenLabs Flash v2.5 REST `/stream` (kit) | TTFB 117-149 ms à chaud dans le bench. WebSocket TTS non fait (V2.3). |
| **Filler en code (V0.2)** | Au premier `ToolCallEvent` d'un tour, si rien n'a été dit, on joue un mp3 pré-synthétisé et varié (« Je regarde. », « Deux secondes. », « Je vérifie. »…), sans appel TTS à ce moment-là. Repli : synthèse à la volée. Le texte dit par le modèle avant l'outil est lu tout de suite (il était retenu jusqu'à la fin des outils). `VOICE_RULES` interdit au modèle d'écrire une phrase d'attente (pas de double filler). | **Le premier son est alors un filler, pas une information.** `timings.firstSoundKind` le dit ; `timings.answerMs` mesure le vrai début de la réponse. |
| **Warm-up (V0.3)** | À l'ouverture de session : 1 mot TTS (connexion TLS ouverte), 6 fillers synthétisés une fois par processus (96 Ko), requête LLM `max_tokens=1` avec le vrai prompt + outils (amorce le cache), keep-alive du cache toutes les ~230 s tant que l'appelant est actif (< 30 min d'inactivité), annulé à la déconnexion. Client HTTP : `keepalive_expiry` 120 s (5 s par défaut = TLS refait à chaque tour). | Tolérant aux pannes (jamais une erreur côté session). Coût : un ping ≈ 23,5 k tokens relus ≈ 0,002 € ; ~0,03 €/h de session active, plafonné à ~0,015 € après le dernier tour. |
| **Coupe au 1er segment (V0.4)** | Le premier segment TTS d'un tour (sans filler) est coupé à la première virgule (≥ 2 mots) ou après 6 mots ; ensuite phrase par phrase. « 18,50 » n'est jamais coupé. | Gain réel seulement quand le LLM streame lentement ; la prosodie du premier morceau peut être hachée : à écouter. |
| **Coût par tour (V0.5)** | `agent_done.cost` : tokens LLM (entrée / sortie / cache lu / cache écrit), secondes STT, caractères TTS, coût **estimé** € / $. Tarifs publics dans **un seul fichier** `apps/ai/app/pricing.py`. Affiché sur la page Voix (puces Cache et Coût) et dans les logs `[turn]`. | Estimation, pas une facture ; le préchauffage n'est pas dans le coût d'un tour. |
| Navigateur (V0.6) | Micro ouvert d'avance si la permission est déjà accordée, enregistreur démarré de façon synchrone à la pression (aucun `await` sur le chemin chaud). | **Pas de vrai pré-roll** : des morceaux WebM pris au milieu d'un enregistrement ne sont pas décodables sans leurs en-têtes. L'audio d'avant la pression n'est pas capté. Non testé avec un vrai micro. |
| Geste « maintenir pour parler » (V0.9) | Espace maintenu **ou** clic/toucher maintenu, partout (`lib/hold-to-talk.ts`). | Voir `scripts/ui-check/hold-to-talk.py` (17 cas, navigateur réel, sans quota). |

## 3. Ce qui a marché / ce qui n'a pas marché

**A marché**
- Le filler en code déplace le premier son de ~4,7 s à ~3,3 s (médiane) sans appel TTS : mais voir ci-dessous.
- Le préchauffage fonctionne : au démarrage d'une session le cache est lu (23,5 k tokens) et le TTS répond en ~120-170 ms.
- Le cache de prompt est bien utilisé en tour réel (`cacheRead` 23-71 k tokens par tour) : ~0,009-0,026 € par tour.
- Le bench rejoue un appelant synthétique en temps réel sur le vrai `WS /voice` : 6/6 scénarios réussis avant et après (aucune confirmation sans accord).

**N'a pas marché / limites honnêtes**
- **Le filler ne fait pas arriver la réponse plus tôt.** Médiane de la vraie réponse : 4,9 s après vs 4,7 s avant (écart dans le bruit, ±1-2 s sur le LLM d'un essai à l'autre). Le pire cas (8,4 s) est le scénario à trois tours d'outils.
- Le filler est borné par le STT (≈ 1,2-1,9 s) + le temps jusqu'au premier appel d'outil (0,9-2,3 s) : l'adaptateur Anthropic n'émet l'appel d'outil qu'à la fin du message du modèle.
- Sans outil (`prix_comte`), le premier son est la réponse du modèle : 4,7 s, dont 2,7 s de LLM sur un prompt de 23 k tokens : lent.
- Le STT a entendu « pâtes à tartiflette » pour « patates à tartiflette » ; l'agent a redemandé au lieu de se tromper (bon réflexe, mais un appel perdu).
- Un seul échantillon par scénario : médiane et pire cas portent sur 6 scénarios, pas sur 6 × N tours.
- Concaténer des segments mp3 ElevenLabs laisse un en-tête ID3 au milieu du flux (déjà le cas avant nous) : `ffmpeg` le signale, le décodage continue ; non vérifié dans un navigateur.
- Rien n'a été mesuré avec un vrai micro ni dans le navigateur (`perceivedMs` ci-dessous = ce que voit le bench au niveau de la socket, pas la lecture audio).

**Idées, pas encore faites** : filler dès le transcript final (avant le LLM) ; émettre l'appel d'outil dès le début du bloc `tool_use` ;
outils composites (V1.1) pour passer de 2-3 tours d'outils à 1 ; Haiku 5.5 (V0.8).

## 4. Mesures

Banc : `scripts/bench/bench.py` (6 scénarios en lecture seule, appelant synthétisé par ElevenLabs, rejoué en temps réel sur `WS /voice`,
trames de 100 ms webm/opus, sans bruit de fond). Valeurs en **ms, médiane (pire cas)** sur les 6 scénarios, 1 échantillon par scénario,
LLM `claude-sonnet-5-5`, STT Soniox, TTS ElevenLabs Flash v2.5.

**Ce que mesure chaque colonne.** t0 = relâchement de la touche (le bench envoie `audio_end`). `sttMs` : t0 → transcription finale.
`llmFirstTokenMs` : début de l'agent → premier token **de texte** (outils éventuels compris). `ttsFirstByteMs` : appel TTS → premier octet
de la première phrase **synthétisée** (un filler en cache n'en compte pas). `totalMs` : t0 → premier octet audio envoyé, **filler compris**.
`perceivedMs` : t0 → premier octet audio vu par le bench côté client (socket, pas la lecture dans le navigateur).
`answerMs` : t0 → premier octet de la **vraie réponse** (= `totalMs` quand il n'y a pas de filler).

| technique | sttMs | llmFirstTokenMs | ttsFirstByteMs | totalMs | perceivedMs | scénarios réussis |
|---|---|---|---|---|---|---|
| kit d'origine (code non modifié) | 1514 (1542) | 3162 (4849) | 155 (168) | 4676 (6227) — premier son = réponse | 4676 (6228) | 6/6 |
| + filler en code, warm-up, coupe virgule/6 mots, coût (V0.2-V0.5) | 1574 (1949) | 3076 (7087) | 140 (149) | 3343 (4658) — premier son = **filler** sur 5 tours/6 | 3344 (4658) | 6/6 |

Complément pour la même ligne « + filler… » : `answerMs` (début de la vraie réponse) = **4885 (8388)** contre 4676 (6227) avant ;
`firstToolCallMs` = 896, 970, 1822, 2132, 2302 ms ; coût estimé par tour = **0,0158 € (0,0259 €)** ; tokens lus dans le cache : 23-71 k par tour.

Lecture : cible du kit < 1,5 s au premier son, **non atteinte** (3,3 s médiane, filler compris). Ce qui reste : STT ≈ 1,5 s + LLM/outils ≈ 2-4 s.

Reproduire : `make up`, puis `uv run --with websockets scripts/bench/bench.py --label "ma technique"` (ajoute à `scripts/bench/results.md`) ;
`make reset` ensuite si un scénario a créé un brouillon.
