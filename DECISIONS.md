# DECISIONS.md — J.A.R.V.I.S (Alpes Restauration)

> **J.A.R.V.I.S — *Juste un Agent Rapide pour la Voix et l'Inventaire Stockline***
>
> **Thèse directrice — La Proactivité comme architecture :** un agent vocal utile dans un ERP ne subit pas l'appel comme un chatbot passif ; il **précharge** l'identité et les habitudes avant la première phrase, **anticipe** la latence par filler précoce et routage rapide (Jev), **alerte** sur les pièges métier (saison fermée, quantité anormale, rupture, impayé) par règles backend déterministes, **apprend** le vocabulaire client uniquement sur preuve confirmée, et **unifie** le tableau de bord, l'Assistant et la Voix sur une mémoire persistante.

Living document. Numbers in §4, §5.4, §6.4, §7–§9 are **measured** (`scripts/bench/`, `scripts/bench/results.md`, live Docker stack captures); everything else is a decision or a hypothesis and is labelled as such. Last update: 2026-11-24.

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

## 5. Vocabulaire évolutif et personnalisé (2026-11-24)

**Le problème.** Le laboratoire STT (`tmp/stt-lab/`, 20 phrases réelles, 62 mots d'entité) a montré que Soniox **avec** le vocabulaire de l'entreprise
retrouve 60/62 entités (97 %), contre 54/62 sans, 52/62 pour Whisper large-v3 et 38/62 pour Parakeet. Les ratés qui restent sont des **quasi-homophones
d'entrées qui existent déjà au catalogue** (« Paillet » pour *Le Refuge Payet*, « à Promont » pour *Apremont*, « Liglou » pour *L'Igloo*, « ma graie »
pour *magret*, « Tombe de Savoie » pour *tomme*). Un indice STT ne les rattrape pas : il faut une étape déterministe **après** le STT, et un vocabulaire
qui **apprend** de chaque client sans jamais deviner. Décision déjà prise : on garde Soniox + vocabulaire ; aucune brique NVIDIA n'est requise.

### 5.1 Ce qui a été fait (tout dans `apps/ai/app/lexicon/`, un module par rôle)

| Brique | Rôle | Fichier |
|---|---|---|
| Phonétique française légère | clé phonétique (accents, lettres muettes, `ill`/`y`, `-et`, nasales, homophones), distance d'édition pondérée, ni dépendance ni dictionnaire | `phonetic.py` |
| Résolveur déterministe | chaque groupe de 1 à 5 mots du transcript est comparé au lexique : candidats + **score** + **marge**, statuts `exact` / `resolved` / `ambiguous`. Ne réécrit **jamais** le transcript | `resolver.py` |
| Lexique global | noms de clients, de produits, alias de l'ERP + jargon CHR / Savoie (`catalogue.py`, `JARGON`) | `catalogue.py` |
| Lexique client | contacts (nom complet + prénom), ville et zone de livraison, produits habituels avec quantité et unité (*a priori* de score + « commande habituelle ≈ 10 kg »), + ce que l'agent a appris | `catalogue.py` |
| Apprentissage | une entrée = « mots entendus → entité » (type + id), portée (client ou global), compteur, première / dernière vue, preuve, confiance | `learned.py` |
| Garde « confirmé seulement » | relit la **vraie conversation** (pas l'affirmation de l'agent) avant d'écrire | `guard.py` |
| Décision Jev (optionnelle) | choisit entre candidats proches, ou rejette un faux ami ; sinon l'agent demande | `decide.py` |
| Persistance et caches | lecture / écriture ERP, TTL, `learn`, `forget`, `prune`, promotion | `store.py` |
| Branchement tour de parole | `annotate()` (bloc `[Lexique …]`), `caller_of()` | `runtime.py` |
| Outils de l'agent | `resolve_mention`, `learn_term`, `forget_term` | `tools/vocabulary.py` |
| API d'administration | `GET /vocab`, `GET /vocab/resolve`, `DELETE /vocab/{id}`, `POST /vocab/prune`, `POST /vocab/refresh` | `routers/vocab.py` |
| Tous les seuils, en **un seul** fichier | `PROMOTE_MIN_CLIENTS=3`, `EXPIRE_UNUSED_DAYS=30`, `EXPIRE_USED_DAYS=180`, `ACCEPT_SCORE=0.80`, `MIN_MARGIN=0.06`, `JEV_MIN_CONFIDENCE=0.75`… | `config.py` |

**Deux niveaux.** *Global* = catalogue + alias + jargon + entrées promues. *Client* = fiche client (contacts, lieux, panier habituel) + entrées apprises pour lui.

**Persistance : dans l'ERP, sans nouvelle table ni route backend.** Une entrée apprise est une ligne de la table de contexte (`/api/context`) : `kind=fact`,
tags `["vocab", "vocab:<type>"]`, `source=voice_agent` (posé par le backend d'après `x-actor`), rattachée au client concerné (`entityType=client` + `entityId`),
ou à `company` pour le global. Le titre se lit dans l'UI (*Vocabulaire : « Paillet » → Le Refuge Payet*), le corps contient une phrase lisible puis **une ligne de
JSON** pour la machine. Elle apparaît donc dans l'onglet Contexte du client et se supprime à la main (`DELETE /api/context/{id}`). Les outils `get_context` /
`search_context` **les masquent** au modèle (`tools/context.py`, `is_vocab`) : ce sont des notes pour le résolveur, pas pour le prompt. Le lexique survit à un
rechargement du service IA (seuls les caches sont en mémoire, TTL 60 s pour les entrées apprises, 120 s par client, 300 s pour le catalogue).

**Cas particulier voulu : un nom de client appris est global dès la première fois** (la ligne reste rattachée à ce client). L'appelant dit son propre nom **avant**
d'être identifié ; une entrée « réservée à ce client » ne servirait donc jamais au moment où on en a besoin.

**`make reset`.** `POST /api/admin/reset` remplace la table `contextEntries` par la graine : **les entrées apprises disparaissent** (démo remise à zéro). Les fichiers
de graine ne sont jamais écrits : la graine reste intacte. Les caches du service IA notent le reset sous 60 s, ou tout de suite avec `POST /ai/vocab/refresh`. Choix à
discuter si on veut garder l'apprentissage entre deux démos (pas d'export / import fait).

### 5.2 Apprendre seulement d'un événement confirmé (règle absolue)

`learn_term` demande une **preuve** (`spelled` | `confirmed` | `order`) et `guard.py` la vérifie sur la conversation réelle (`ToolContext.messages`) :

- `confirmed` : l'appelant a dit les mots **pendant l'appel** (le bloc `[Lexique …]` ne compte pas), l'agent a **répété le nom de l'entité**, et le **dernier** message
  de l'appelant est un oui (Jev `is_yes` si une clé existe, sinon liste de mots prudente ; « non » ou flou ⇒ refus) ;
- `spelled` : un message **postérieur** de l'appelant épelle des lettres qui correspondent au nom (« P A Y E T », « P comme Pierre… ») ;
- `order` : la commande est **confirmée dans l'ERP** (pas brouillon), du même client, et le produit y figure (lu par l'outil, pas affirmé).

Refus aussi : mots déjà exacts, mots qui désignent déjà une **autre** entité du catalogue (« magret » ne peut pas devenir autre chose), client ou produit inconnu de
l'ERP ; le nom canonique vient de l'ERP, pas du modèle. Chaque refus renvoie une phrase française que l'agent peut appliquer (« demande d'épeler »).

**Promotion** : une paire confirmée par ≥ 3 **clients distincts** (`PROMOTE_MIN_CLIENTS`) devient une entrée globale (un seul client qui confirme dix fois ne compte pas).
**Péremption** : une entrée confirmée une seule fois et jamais revue après 30 jours (2 fois ou plus : 180 jours) est ignorée à la lecture et supprimée par `POST /vocab/prune`.
**Désapprendre** : `forget_term` (outil), `DELETE /vocab/{id}` (API), `DELETE /api/context/{id}` (ERP). Exemple :
`curl -s :4100/vocab?clientId=cli_0082` puis `curl -s -X DELETE :4100/vocab/ctx_1106`.

### 5.3 Utilisation à l'exécution

1. **Biais STT.** Dès que l'appelant est identifié (un appel d'outil `get_client`, `create_draft_order`, `get_price`… sur un `cli_…`), `Conversation.client_id` est posé et sa fiche
   est préchargée en tâche de fond. L'indice de **chaque énoncé** est reconstruit à `audio_start` : `terms` du client **en premier**, puis le global (budget `MAX_TERMS_CHARS=6000` de
   Soniox, premiers termes servis d'abord). Premier tour = global seul. Cache froid ⇒ on attend au plus 350 ms puis on part en global seul (jamais de départ retardé). Les formes
   *mal entendues* ne sont **jamais** envoyées comme termes (elles biaiseraient vers l'erreur) : seuls les noms canoniques le sont.
2. **Résolveur** sur le transcript final, en pur Python : bloc `[Lexique : aide à l'écoute, ce n'est pas ce que l'appelant a dit]` ajouté **à la fin** du message de l'appelant (le préfixe en cache
   reste identique ; le prompt système change **une fois**). Le transcript montré à l'appelant et gardé en historique reste brut. Seuls les quasi-homophones, les ambiguïtés et les clients entendus
   exactement (leur id évite un `search`) y figurent.
3. **Décision.** `ambiguous` ⇒ avec Jev : « lequel, ou aucun des deux ? » (≥ 0,75 ⇒ `resolved`, « aucun » ⇒ la mention est retirée) ; sans clé ou incertain ⇒ l'agent **demande et propose d'épeler**. Jamais de
   devinette. Règles de `VOICE_RULES` : répéter le nom proposé, « pouvez-vous épeler ? » si la marge est faible, `learn_term` seulement après un oui / une épellation.

### 5.4 Résultats mesurés (hors ligne, transcripts enregistrés, sans appel API)

Rejeu des **vrais transcripts** de `tmp/stt-lab/results/*.json` dans le résolveur (`scripts/bench/vocab_eval.py`). « Sûr » = entité retrouvée de façon exacte ou proposée avec marge ;
A = lexique global seul ; B = + lexique client (fiche) ; C = B + leçons apprises (rejeu : chaque bonne proposition est supposée confirmée lors d'un appel précédent).

| Moteur | Brut | A global | B + client | C + appris | Propositions fausses (A / B / C) |
|---|---|---|---|---|---|
| soniox sans vocabulaire | 54/62 | **61/62** | 61/62 | 61/62 | 0 / 0 / 0 |
| soniox + vocabulaire (réel) | 60/62 | **62/62** | 62/62 | 62/62 | 0 / 0 / 0 |
| whisper-large-v3 | 52/62 | **62/62** | 62/62 | 62/62 | 0 / 0 / 0 |
| parakeet | 38/62 | **60/62** | 60/62 | 60/62 | 0 / 0 / 0 |

- Les 5 quasi-homophones cités sont tous rattrapés (Paillet→Payet, Promont→Apremont, Liglou→Igloo, graie→magret, Tombe→tomme). Restent : « annulez » (pas une entité du lexique) et, pour Parakeet,
  « d'eux » pour « œufs » et « compter » pour « comté ».
- **Faux positifs** : 0 proposition fausse sur les 80 transcripts (4 moteurs × 20 phrases), 0 sur 12 phrases négatives inventées (des mots qui ressemblent à un produit ou un client : « magnet », « salle »,
  « salon », « Rémi », « col », « plats du jour »…). Au début, 7 de ces mots déclenchaient une ambiguïté (« salle » → *salade*) ; des seuils plus stricts pour les mots isolés l'ont supprimée.
- **Latence** du résolveur : médiane **2,2 ms**, p95 5,0 ms, max 7,8 ms sur 240 phrases (559 formes, machine de dev). Dans le conteneur IA : 9 à 20 ms (phrase de 15 à 22 mots, mesuré par `GET /vocab/resolve`). Négligeable face à
  un tour de 3 à 5 s. Jev n'est appelé que pour une mention ambiguë et coupé à 1,2 s.
- **Bout en bout réel** (2 sessions sur `WS /voice`, 3 tours LLM réels ; texte **tapé** auquel j'ai joint le bloc `[Lexique …]` produit par le même code, donc ni STT ni micro réels) : l'agent répète « Le Refuge Payet, c'est bien ça ? », attend le « oui », appelle `learn_term(confirmed)` ; la ligne apparaît dans `/api/context?tag=vocab` ;
  pour « duos de Savoie », alors ambigu, il a répondu « pouvez-vous me préciser de quel produit il s'agit, ou me l'épeler ? » (depuis, la forme courte « Diots de Savoie » du catalogue le résout directement). Lignes de test supprimées ensuite.

### 5.5 Limites honnêtes

- **Rien n'a été mesuré avec un vrai micro, de vrais accents ni du bruit** : le corpus est de la voix de synthèse (2 voix TTS, propre). Le gain réel dépend de ce que les STT déforment vraiment.
- **Seuils réglés en regardant ces 20 phrases** (surapprentissage possible). Contrôle : 14 déformations plausibles **inventées après coup** (« Bofort d'alpage », « Taillefère », « mirtilles »…) : brut 5, résolu 13/14 au premier essai ; l'échec (« fondue » exacte
  masquait « La Fondue de Taillefère ») a été corrigé ensuite, donc 14/14 n'est **pas** un chiffre en aveugle.
- Sur ce corpus **B = A** : les noms de clients sont déjà dans le lexique global. Le lexique client sert aux prénoms de contacts, aux lieux, à l'*a priori* du panier habituel et aux entrées apprises, ce que ce corpus ne teste pas (couvert par les tests unitaires). **C = B** parce que la promotion ne change que des cas déjà résolus ; le gain d'une leçon apprise
  (statut `exact`, sans reconfirmation) n'est pas visible dans un score de rappel.
- Les ajouts d'indice STT (client d'abord, jargon) n'ont **pas** été remesurés avec Soniox (quota) ; seul le résolveur est évalué sur des transcripts déjà enregistrés.
- Jev : une clé est configurée sur le service ; `is_yes` a tourné en réel une fois (garde de `learn_term`), mais `choose` (trancher une ambiguïté) n'a été exercé qu'avec un faux client : aucun de mes exemples réels n'est resté ambigu.
- Détection de l'appelant : heuristique (un appel d'outil sur un `cli_…`). Si l'agent consulte un autre client, le biais STT suit ce client jusqu'à correction.
- Pas de bruit de plusieurs clients à la fois, pas d'interface d'administration (API + `curl` + onglet Contexte du client), pas d'export de la graine d'apprentissage.

Reproduire : `make up`, puis `cd apps/ai && uv run python ../../scripts/bench/vocab_eval.py` (lit l'ERP en **lecture seule** et `tmp/stt-lab/results/*.json`) ; `VERBOSE=1` liste les ratés restants.

## 6. Mémoire de session, compaction, filler précoce (2026-11-23)

Constat (captures `tmp/captures/*pre-restart/`) : l'historique des conversations était un dictionnaire en mémoire, **perdu à chaque rechargement** d'uvicorn (le navigateur se reconnecte avec le même `sessionId`, le serveur repart d'une conversation vide), et coupé à 40 messages sans égard pour ce qu'ils contenaient.

### 6.1 Mémoire persistante (`services/memory.py`)

- **SQLite** `$AI_STATE_DIR/sessions.db` (Docker : volume `ai-state` monté sur `/state` ; sans Docker : `<repo>/.state/`, ignoré par git). Une ligne par `sessionId` : `meta` (JSON de tous les champs sérialisables de `Conversation` : acteur, **identité déclarée**, `client_id`, bloc de session figé, `facts`) et `history` (les `ChatMessage` en JSON, `tool_calls` et résultats d'outils inclus, donc exactement ce que `sanitize_history` attend).
- **Écriture immédiate** après chaque tour validé (et après chaque compaction) : au pire on perd le tour en cours, qui n'était de toute façon pas encore dans l'historique. Chargement à la reconnexion avec le même `sessionId` ; `reset` supprime la ligne.
- **TTL** `SESSION_TTL_HOURS` (12 h par défaut, rafraîchi à chaque tour) et **plafond** `SESSION_MAX` (200) avec éviction des plus anciennes. L'identité déclarée est restaurée avec la conversation : sinon la reconnexion (`start` avec le même rôle) y verrait un « changement d'identité » et **effacerait** l'historique.
- **Jamais bloquant** : dossier absent ou en lecture seule, base verrouillée ou corrompue → une seule ligne de log, puis mémoire seule comme avant. Un fichier qui n'est pas une base est déplacé en `sessions.db.corrupt-<heure>` et recréé ; une ligne illisible est supprimée.
- **Blocs de raisonnement (« thinking ») : non persistés.** Ils restent en mémoire (`_thinking_by_call`) et l'API Messages ne les exige que pour le tour d'outils **en cours** ; on ne stocke que des tours complets, donc un historique rechargé contient d'anciens tours d'outils sans leur thinking, et l'API les accepte (vérifié en réel, §6.4). Seule conséquence : le préfixe du cache de prompt de la conversation est réécrit une fois après un rechargement.

### 6.2 Compaction à la place du `trim(40)` (`services/compaction.py`)

- On garde les **6 derniers tours tels quels** (`COMPACT_KEEP_TURNS`) ; au-delà de **12 tours** (`COMPACT_TRIGGER_TURNS`) ou de ~48 000 caractères (`COMPACT_MAX_CHARS`) les tours plus anciens sont remplacés par **un seul message** (rôle `user`, suivi d'un « Bien noté. » `assistant` pour garder l'alternance). L'hystérésis (12 → 6) fait réécrire le cache de conversation une fois tous les ~6 tours, pas à chaque tour.
- Le résumé est **extractif et déterministe** (Python pur, ~1 ms, aucun appel modèle) : client concerné (id + nom), **état de chaque commande** (n°, statut, date, lignes avec produit, quantité, prix, total, alertes ERP : ce que l'ERP a dit, pas ce que quelqu'un a affirmé), actions d'écriture et leurs erreurs, derniers prix/stocks constatés, demandes de l'appelant ayant déclenché un outil, **déclarations chiffrées de l'appelant marquées « NON vérifié »**, chiffres annoncés par l'agent, question restée en attente. Les candidats de recherche non choisis, les politesses, le bloc `[Lexique …]` disparaissent. Borné à 3 200 caractères.
- Les coupes se font sur une frontière de tour : un appel d'outil n'est jamais séparé de son résultat (testé à chaque longueur d'historique). `facts` est conservé avec la conversation : une 2ᵉ compaction **fusionne** au lieu de relire le texte du premier résumé.
- **Hors chemin critique** : la compaction est lancée en tâche de fond après le commit du tour (`memory.compact_later`) ; si un nouveau tour a modifié l'historique entre-temps elle abandonne, et `memory.commit` rebase un tour en cours sur un historique compacté entre-temps (rien perdu, rien dupliqué).
- **Cache de prompt** : le résumé est dans `messages`, jamais dans le prompt système ; outils + système restent identiques octet pour octet et le point de cache posé sur le dernier bloc (`mark_last_block`) continue de fonctionner.
- **Raffinement par LLM** (`COMPACT_LLM=1`, **désactivé par défaut**) : un appel de plus par compaction, en tâche de fond ; la réponse n'est acceptée que si elle commence par la marque, est plus courte et **garde tous les identifiants** ; sinon le résumé déterministe reste.

### 6.3 Latence : filler au transcript final et annonce d'outil précoce

- **Filler avant le LLM.** Dès le transcript final, `turn_hints.should_prefill` (regex, quelques µs) joue le filler pré-synthétisé si le tour va probablement utiliser l'ERP (mots stock / prix / commande / quantité / client / jours…, un chiffre, ou une vraie phrase de 5 mots ou plus qui n'est pas de la politesse). Pas de filler pour bonjour / merci / oui-non / au revoir, ni si un filler a été joué il y a moins de 10 s sur la connexion (rythme d'une prise de commande rapide). Un faux « oui » coûte un « Je regarde. » avant une réponse directe ; un faux « non » ne coûte rien : le filler part de toute façon à l'appel d'outil comme avant.
- **Jamais doublé** : si le filler est déjà en file, le texte que le modèle écrit **avant son premier outil** n'est pas prononcé (il reste affiché). Le texte entre deux tours d'outils, lui, est toujours dit.
- **Annonce d'outil dès `content_block_start`** : `clients/anthropic.py` émet `LLMToolStart(name)` quand le bloc `tool_use` commence (le nom est connu, les arguments arrivent encore), puis `LLMToolCall` dès `content_block_stop` (arguments complets) au lieu de la fin du message. `run_agent(announce_tools=True)` (voix seulement : `POST /chat` ne le voit pas) en tire un `ToolStartEvent` ; la session vocale envoie alors `agent_tool {name}` (sans `args`), puis `{name, args}`, puis `{name, ok, ms}`. Le web raccorde le 2ᵉ message au 1ᵉʳ (`useVoiceSession.ts`) ; `packages/shared/src/ai.ts` documente les trois messages. Les adaptateurs OpenAI / Gemini n'émettent rien de tel : ils gardent le comportement précédent.
- **Interrupteurs** : `VOICE_EARLY_FILLER=0` et `VOICE_TOOL_START=0` rétablissent l'ancien comportement (utile en démo si le filler gêne, et c'est ce qui a permis le A/B ci-dessous).
- Test existant modifié **volontairement** : `test_anthropic_stream_thinking_tools_and_replay` attendait `[texte, usage, appel]` ; l'ordre est maintenant `[texte, début d'outil, appel, usage]`.

### 6.4 Mesures réelles (2026-11-23, voix synthétique de l'appelant, Soniox + ElevenLabs + claude-sonnet-5-5)

A/B **sur le même code**, deux services locaux simultanés (A : `VOICE_EARLY_FILLER=0 VOICE_TOOL_START=0` ; B : défaut), passes entrelacées A B A B, 2 scénarios en lecture seule (`stock_beaufort`, `surnom_patates`), 2 passes = **4 tours réels par variante** (+ 2 tours pour la persistance, 1 pour le résumé : 11 tours LLM au total).

| | A avant (filler au 1ᵉʳ outil) | B après | |
|---|---|---|---|
| premier son `totalMs` (médiane) | **3 297 ms** (2 578 · 3 228 · 3 366 · 9 618) | **1 234 ms** (1 199 · 1 228 · 1 239 · 1 633) | plages disjointes : gain réel ≈ −2,1 s |
| vraie réponse `answerMs` (médiane) | 6 146 ms (5 378 · 5 855 · 6 438 · 18 538) | 4 826 ms (4 193 · 4 715 · 4 936 · 7 271) | **dans le bruit** : dominée par le LLM (`llm1st` 2,9-5,5 s de chaque côté, un tour A a pris 16,7 s côté API, un autre a fait 3 outils) |
| 1ᵉʳ outil annoncé `tool1` (médiane) | 1 725 ms | 889 ms | indicatif (n = 4, voir ci-dessous) |

- Le premier son vaut désormais STT + ~10-30 ms (`sttMs` 1,2-1,7 s) : c'est la borne basse du filler, il ne descendra plus que par le STT. **C'est toujours un filler, pas une information** (`firstSoundKind: filler`) ; la réponse réelle n'est pas plus rapide de façon démontrable.
- `tool1` plus tôt de ~0,7-1 s sur 3 tours sur 4 : plausible (durée de génération des arguments entre début et fin de bloc), mais n = 4 : je ne le revendique pas. Il ne pilote plus le premier son que sur les tours que l'heuristique rate.
- Aucun coût LLM supplémentaire (€0,009-0,017 par tour, comme avant) ; la compaction déterministe n'appelle aucun modèle.
- **Persistance, réel** : session `e2e-mem-1` sur la pile Docker : tour 1 (outil, « du Beaufort d'alpage en stock ? »), **rechargement à chaud d'uvicorn** (déclenché par une modification de fichier), reconnexion avec le même `sessionId`, tour 2 (« le prix de ce produit dont on parlait ») → l'agent parle bien du Beaufort chalet d'alpage, aucune erreur 400 malgré l'absence du thinking du tour 1. Le volume `ai-state` contenait bien la base ; `reset` a vidé la ligne.
- **Résumé accepté par l'API, réel** : un historique compacté (résumé + « Bien noté. » + 6 tours) injecté dans une session a été accepté par Anthropic ; l'agent a refusé de détailler la commande à une identité « non identifiée » : la politique d'accès (`policy.py`) s'applique à ce que contient le résumé comme au reste.

### 6.5 Limites honnêtes

- La **compaction n'a été exercée que sur des historiques synthétiques** (tests) et sur un seul tour réel ; aucune vraie conversation de plus de 12 tours n'a été rejouée. Les seuils (6 / 12 tours, 48 000 caractères) sont des choix raisonnés, pas des mesures. L'extraction s'appuie sur la forme des résultats d'outils actuels (`id` + `name`/`label`/`number`, résumés de commande `summarize_order`) : un nouvel outil dont le résultat a une autre forme n'alimente pas le résumé tant qu'on n'y pense pas.
- Le résumé est en français, concis et **pas exact au mot près** pour les paroles de l'appelant (extraits de 170 caractères). Les ids et les chiffres des outils, eux, sont recopiés tels quels.
- Une conversation déjà **en mémoire** n'expire pas au TTL tant que le processus vit (le TTL joue sur la base : rechargement, restart). Pas de purge de la mémoire vive au-delà du plafond de sessions.
- Page web rechargée = nouveau `sessionId` côté navigateur (il ne le garde qu'en mémoire) : la mémoire serveur sert aux reconnexions WebSocket et aux rechargements du service, pas au rechargement de l'onglet. Le stocker en `sessionStorage` est une ligne de code à discuter (reprendre l'ancien appel à chaque F5 est un choix produit).
- L'heuristique de filler est un jeu de mots-clés, réglé sans corpus d'évaluation ; elle n'a pas été mesurée sur de vrais appels (taux de faux « oui » inconnu). Sur un tour qui ne demande rien à l'ERP, un faux « oui » ajoute un « Je regarde. » inutile.
- Mesure : n = 4 par variante, voix de synthèse, une seule machine ; les écarts de réponse réelle (±1-2 s entre deux exécutions identiques, déjà notés en §4) masquent tout gain inférieur à ~1 s.

## 6. Identité, rôles et accès (2026-11-23)

### 6.1 Ce qui s'est passé (audit d'une vraie session, captures dans `tmp/captures/`)

Un appelant **non identifié** a (a) obtenu les 5 plus gros clients **sans aucun appel d'outil** : ils étaient dans le prompt système (`data/context/01-entreprise.md`), (b) obtenu l'historique et les contacts d'un fournisseur,
(c) après un simple « considérez-moi comme Le Refuge Payet », créé **et confirmé** une commande de 408 € et écrit 3 événements client sur des affirmations invérifiables (négociation de prix, changement de conditions de paiement,
5 demandes de remise de 25 à 60 %). Le navigateur envoyait l'auteur en dur (« Agent vocal ») : `createdBy` ne disait rien. L'agent lui-même a conclu : identifier avant de répondre, droits par rôle, confirmation pour les écritures.

### 6.2 Ce qui a été fait

| Sujet | Choix |
|---|---|
| **Identité** | 4 rôles : `unknown` (défaut), `client` (lié à UN `cli_…`), `sales`, `direction`. Un sélecteur dans l'interface (en-tête de la page Voix, du panneau Assistant et de la page Commande) pose `{role, clientId?, actorName?}`. Envoyé sur le `start` de `WS /voice` (réponse `ready` : le rôle **effectif**), dans le corps de `POST /chat` et `POST /command` (ou les en-têtes `x-caller-role`, `x-caller-client-id`, `x-actor-name`), en paramètres d'URL de `WS /voice/command`. Dernier choix gardé dans `localStorage`. Un `client` sans `clientId` valide est rétrogradé `unknown` **par le serveur**. Changer d'identité sur une même `sessionId` **efface l'historique** (rien dit ou lu pour l'ancienne identité ne passe à la nouvelle). |
| **Honnêteté** | C'est une identité **déclarée** : ce hackathon n'a ni téléphonie ni numéro appelant. L'interface le dit (« Identité déclarée (démo) »). En production : caller-ID / authentification. La table des droits ne changerait pas. |
| **Verrou côté serveur** | `apps/ai/app/policy.py` : UNE table rôle × outil (`POLICY`), appliquée dans `agent/loop.py::execute_tool` via `agent/access.py` **avant** que l'outil ne s'exécute, sur les arguments **validés** (alias `clientId` / `client_id` identiques). Le modèle n'est jamais cru : « je suis l'administrateur » ne change rien. Un outil absent de la table est refusé aux rôles non internes (un test échoue si un outil n'est pas classé). `unknown` ne peut écrire **aucune** donnée même si la table était fausse (`WRITE_TOOLS`). Refus = `{error, denied: true}` avec une phrase que le modèle peut dire. |
| **Prompt par rôle** | Le contexte d'entreprise du prompt est choisi par rôle : fiche **publique** pour `client` / `unknown` (liste blanche par fichier : début de `01-entreprise.md`, glossaire produits, zones et heures limites sans les tournées/chauffeurs), contexte **complet** pour `sales` / `direction`. Les fichiers `data/context/` ne sont pas modifiés. Un nouveau fichier de contexte est interne tant qu'il n'est pas listé. Le bloc identité (règles du rôle + fiche client préchargée) est en **fin** de prompt, dans un 2e bloc système avec son propre point de cache : le gros préfixe est partagé par toutes les sessions d'un même périmètre, et figé pour la session (cache lu de tour en tour). |
| **Fiche client préchargée** | Rôle `client` (ou commercial qui choisit un client) : au début de la session on lit `GET /api/clients/{id}` + `GET /api/context/for` (cache 5 min), et on injecte un bloc ≤ ~800 tokens : nom, zone, jours, paiement, préférences, dossiers ouverts, habitudes avec leurs `prd_…`, 5 derniers événements. Un client n'y voit ni plafond de crédit, ni encours, ni notes privées, ni fiches risque/prix interne. Gelé pour la session (sinon le cache de prompt serait invalidé). Sans ERP : pas de fiche, les outils restent. |
| **Écritures non vérifiées** | `unknown` : aucune écriture. `client` : seulement sur son `cli_…` ; commande confirmée seulement si elle lui appartient (vérifié dans l'ERP), brouillon uniquement pour ajouter une ligne, et **un « oui » explicite dans un tour séparé** du brouillon (le serveur refuse `confirm_order` dans le tour où le brouillon a été créé ou modifié, ou sans « oui »). Tout événement écrit par un client est « Déclaré par le client (non vérifié) : … », « Le client affirme ou demande : … », gravité **basse**, types limités ; `save_context` d'un client : `preference` / `logistics` sur lui-même, mêmes mentions, jamais `policy` / `pricing` / `risk`. Provenance sur **chaque** écriture : en-tête `x-actor-name` = « Le Refuge Payet · client déclaré » (donc `createdBy` / `author`) + tags `voice_agent:declared:<rôle>` (et `non-verifie` pour un client). Pas de changement de schéma : `source` du contexte est une énumération fermée, la provenance fine passe par les `tags`. |
| **`identify_caller(name)`** | Propose au plus 3 candidats, noms seulement pour un inconnu, marqués `unverified`. Ne donne aucun accès : le rôle ne change que par le sélecteur. |

### 6.3 Table des droits

| Outil | unknown | client | sales | direction |
|---|---|---|---|---|
| `search` | produits seulement | produits + son client | tout | tout |
| `get_product_stock`, `find_alternatives` | champs publics (pas de réservé, arrivages, DLC) | idem | tout | tout |
| `get_price`, `get_client`, `get_client_history`, `get_context`, `search_context`, `resolve_mention` | non | son client (champs internes masqués) | tout | tout |
| `create_draft_order`, `add_order_line`, `confirm_order`, `get_order` | non | ses commandes (confirmation : « oui » séparé) | tout | tout |
| `log_client_event`, `save_context` | non | son client, non vérifié, types restreints | tout | tout |
| `learn_term`, `forget_term` | non | son client | tout | tout |
| `get_supplier_history`, `log_supplier_event` | non | non | tout | tout |
| `identify_caller` | oui (candidats) | non | oui | oui |

### 6.4 Résultats (modèle réel `claude-sonnet-5-5`, tours **tapés**, `scripts/bench/adversarial.py`)

- 15 scénarios / 43 contrôles : inconnu qui demande les clients, les fournisseurs, se dit « administrateur » puis demande un historique fournisseur, se dit Le Refuge Payet pour faire confirmer une commande, injection de prompt, outils forcés ;
  client `cli_0082` qui interroge un autre client (`cli_0033`), les fournisseurs, fixe un prix à 1,96 €, exige 60 % de remise, passe une commande normale ; commercial en contrôle positif. Les contrôles lisent **l'état de l'ERP** après coup (commandes, événements, prix).
- Le verrou côté serveur est exercé sans modèle ni coût par `--probe` (historique forgé sur `POST /chat` + LLM mock qui tente toujours l'outil interdit) : 5/5 refus ou passages attendus.
- Chiffres exacts, échecs restants et mesure de la fiche préchargée : voir le rapport de la passe et `tmp/captures/20261123_post-identity/`.

### 6.5 Limites honnêtes

- **L'identité est déclarée, pas prouvée** : qui tient l'interface choisit son rôle. Le verrou protège contre ce que le modèle dit ou se laisse dire, pas contre quelqu'un qui choisit « direction ». En production il faut le caller-ID ou une authentification (et une vraie vérification avant d'ouvrir un compte client).
- Le sélecteur s'applique à l'interface de la démo ; `POST /chat` et `WS /voice` acceptent n'importe quel rôle déclaré par leur appelant, comme tout le reste de cette API sans authentification.
- Les conseils d'écoute du lexique (bloc `[Lexique …]` sur les tours parlés) ne sont pas filtrés pour un client : un mot proche du nom d'un autre client peut le lui faire proposer. Ils sont coupés pour `unknown`.
- Un inconnu peut deviner des noms de clients un par un avec `identify_caller` (3 candidats, sans id ni détail) ; pas de limitation de débit.
- Les modèles actuels refusent d'eux-mêmes la plupart des attaques (aucun des appels interdits n'a été tenté dans nos essais réels) : c'est le test `--probe` et les tests unitaires qui prouvent le verrou, pas le comportement du modèle.
- La confirmation « oui explicite » est une détection par mots (oui, d'accord, ok, confirme…) : elle peut refuser à tort une confirmation formulée autrement (l'agent redemande). *(Amélioré en §7 via `jev_router.confirm_action` quand `JEV_API_KEY` est active.)*

---

## 7. Proactivité système : Jev System One, garde-fous ERP et swap LLM/STT (2026-11-24)

### 7.1 Décisions rapides Jev (`apps/ai/app/services/jev_router.py`)

Plutôt que d'envoyer chaque micro-décision au gros modèle conversationnel (2–4 s), **TypeSafe Jev (`jev-latest`)** intervient en parallèle ou en garde déterministe sur 4 primitives (`100–200 ms` mesurés en live dans le conteneur `ai`) :

| Primitive | Rôle | Latence live mesurée (`ai`) |
|---|---|---|
| `route_turn` | Classe le tour (`social` / `simple_read` / `order_write`) pour éviter les outils sur les salutations/remerciements | **158,4–193,8 ms** (affiché en direct sur la puce UI **`Jev`** + **`Route Jev`**) |
| `disambiguate` | Tranche entre candidats produits/clients proches du lexique | **162,3 ms** |
| `confirm_action` | Porte booléenne `is_yes` pour confirmer une commande ou apprendre un terme | **131,0 ms** |
| `score_claim` | Évalue la plausibilité d'une affirmation orale (remise, délai, qualité) avant trace ERP | **126,2 ms** |

Chaque tour vocal ou tapé sur `/voice` collecte la latence Jev mesurée (`timings.jevMs`) et l'intention classifiée (`timings.jevRoute`, ex. `order:write`, `order:read_only`) et les affiche sur la ligne de puces du tour ainsi que dans la barre **Latence moyenne** et dans les logs `[turn]`. L'endpoint `GET /ai/jev/stats` expose en outre les centiles `p50_ms` / `p90_ms` cumulés par primitive.

### 7.2 Garde-fous de plausibilité dans le backend (`apps/backend/app/services/orders.py`)

Les règles de bon sens métier vivent dans le **backend**, jamais dans le prompt seul : à la création ou modification d'une commande (`POST /api/orders`, `POST /api/orders/{id}/lines`), le service retourne un champ `warnings[]` structuré, **affiché en bandeau ambre directement dans la carte d'outil (`ToolRow`) sur `/voice` et `Assistant`** et obligatoirement cité par l'agent avant confirmation :
- `season_closed` : détecte une date de livraison hors fenêtre saisonnière du client (ex. *Le Refuge Payet*, ouvert mi-décembre → mi-avril). Calibré sur **24 141 commandes historiques** : **0,01 %** de faux positifs. Vérifié en live sur `CMD-2026-007300` (200 kg de frites le `2026-12-01` → alerte `season_closed` renvoyée).
- `unusual_quantity` : quantité `> 2,5 × p90` historique du client sur ce produit (**0,001 %** de faux positifs sur **166 273 lignes**).
- `credit_alert` / `no_substitution` : remonte immédiatement l'état d'encours ou la préférence stricte sans bloquer l'enregistrement du brouillon.

### 7.3 Interchangeabilité LLM / STT et bascule Anthropic → NVIDIA Nemotron

- **Architecture agnostique :** `.env` pilote `LLM_PROVIDER` (`anthropic`, `nvidia`, `deepseek`, `openai`, `gemini`, `openai-compatible`, `mock`) et `STT_PROVIDER` (`soniox`, `nvidia`, `deepgram`, `gradium`, `openai`, `mock`). `apps/ai/app/clients/presets.py` et `factory.py` résolvent la clé dédiée (`NVIDIA_API_KEY` prioritaire sur une clé Anthropic résiduelle) et désactivent `keep_warm` pour les fournisseurs hors Anthropic.
- **Incident réel & résilience (2026-11-24) :** la clé Anthropic du workspace kit a atteint son plafond mensuel (`HTTP 400`, réinitialisation le `2026-12-01T00:00Z`). Grâce au preset `nvidia` (`nvidia/nemotron-3-ultra-550b-a55b`, `LLM_EFFORT=low`) activé via `docker-compose.override.yml` (non commité), toute la pile vocale et le chat ont continué sans interruption.
- **Mesure live sur `WS /voice` avec Nemotron Ultra + Jev + filler précoce (`browser-proxy`) :**
  - Requête produit (`get_product_stock prd_0028` = **8 ms**) : `LLM 1er = 2,4 s`, `TTS 1er = 131 ms`, **`Total (filler) = 21 ms` / `Perçu = 39 ms`**, `Réponse = 2,6–2,7 s`, `Cache = 26,3k`, `Coût = 0,0031 €`.
  - Suivi avec `get_product_stock prd_0031` (**5 ms**) : `Total = 3 ms`, `Perçu = 38 ms`, `Réponse = 4,3 s`, `Cache = 35,1k`, `Coût = 0,0073 €`.
  - Tour social (`"Merci beaucoup !"`) : **0 outil**, `1,2 s`, **`0,0018 €`**.
- **Benchmark STT cadencé (trames 100 ms temps réel, 20 phrases / 62 entités) :** Soniox + vocabulaire en flux cadencé atteint **225 ms p50** fin-de-parole → final (contre 2,86 s en rafale artificielle sur l'ancien banc) et **62/62 (100 %)** après le résolveur phonétique (médiane **2,2 ms** sur hôte, 0 faux positif sur 80 transcripts + 12 négatifs). Parakeet NVCF (150 ms) et Whisper NVCF (220 ms) restent optionnels derrière `--extra nvidia` ; le repo jury tourne sans extra NVIDIA.

---

## 8. Authentification par profils, sessions unifiées et Tableau de bord IA (2026-11-24)

### 8.1 De l'identité déclarée à l'authentification réelle (`apps/backend/app/services/auth.py`, `apps/ai/app/auth.py`)

La section §6 avait souligné la limite honnête d'une identité purement déclarée. Nous l'avons remplacée par une **authentification signée côté serveur** (hachage `scrypt` + jeton HMAC-SHA256 12 h) avec **5 rôles** et **connexion 1-clic de démo** sur `/login` (8 comptes fictifs dont Direction, Commerciaux, Clients et Fournisseurs) :

| Rôle | Périmètre UI & ERP | Périmètre Agent IA (`policy.py` + `auth.py`) |
|---|---|---|
| `admin` (**strictement unique**) | Accès complet + `/accounts` (CRUD comptes, réinitialisation mdp) | Tous les outils + attribution vérifiée `Direction Alpes · administrateur vérifié` |
| `manager` (Commercial) | Tout le métier ERP (commandes, clients, stock, achats, tournées), sans `/accounts` | Tous les outils métier ; `/accounts` masqué et refusé (`403`) |
| `client` (rattaché `cli_…`) | Pages filtrées sur son compte (`Mes commandes`, `Mes tarifs`, `Mes factures`, `Mes paiements`, `Mon historique`), zéro accès fournisseur/encours global | Ses commandes, habitudes, tarifs et brouillons uniquement (`403` / `0 résultat` hors périmètre) |
| `supplier` (rattaché `sup_…`) | `Produits`, `Stocks`, `Mes bons d'achat`, `Ma fiche fournisseur` | Sa fiche fournisseur et ses bons d'achat uniquement ; aucune donnée ni prix client |
| `unknown` | Redirigé vers `/login` dans l'UI | Lecture catalogue public uniquement, zéro écriture |

- **Invariant Administrateur unique :** `POST /api/accounts` avec `role="admin"` renvoie **`HTTP 409 single_admin`** (vérifié en live), et le compte `admin` ne peut ni être rétrogradé, ni désactivé, ni supprimé.

### 8.2 Tableau de bord personnalisé et aidé par l'IA (`apps/ai/app/services/suggestions.py`, `apps/web/src/pages/dashboard/index.tsx`)

Chaque profil voit un tableau de bord dédié (KPI, habitudes ou bons d'achat, factures/incidents) surmonté d'un bandeau **« Briefing IA en direct »** (`GET /suggestions?seed=…&live=1`) :
- Calcule en parallèle les faits ERP du profil (panier habituel, repli automatique sur les 3 dernières commandes livrées pour les clients saisonniers hors fenêtre 60 j, brouillons ouverts, ruptures, factures en retard, lots DLC proches, bons d'achat ouverts).
- Enrichit la synthèse d'accueil via le LLM actif (borné à 6 s, `aiGenerated: true` vérifié en live sur `client`, `supplier`, `manager` et `admin`).
- Propose **4 cartes d'action cliquables** qui rotent à chaque clic sur *Nouvelles suggestions* et ouvrent directement **Voix** (avec phrase pré-remplie et envoyée) ou **Assistant** (`⌘J`).

### 8.3 Sessions unifiées Assistant ↔ Voix (`apps/ai/app/services/sessions.py`, `SessionPicker.tsx`)

Les surfaces **Assistant** (`⌘J`) et **Voix** (`/voice`) restent distinctes dans l'interface mais partagent désormais un **store SQLite unique** (`sessions.db`, CRUD complet : lister, rechercher, créer, renommer, supprimer, reprendre) et les outils de rappel (`list_past_sessions`, `recall_session`). Vérifié en direct via `browser-proxy` : une question posée sur `/voice` (*« Il vous reste du fromage à raclette tranchée ? »* → 603 kg) est immédiatement visible dans le panneau **Assistant**, qui répond au tour suivant sur le pronom anaphorique (*« Et quel est mon tarif pour cette raclette ? »* → `get_price` 6 ms, `14,20 € HT`).

---

## 9. Synthèse des résultats vérifiés (avant soumission)

| Axe | Métrique | Résultat mesuré | Source / Vérification |
|---|---|---|---|
| **Fast** | 1er son vocal (filler précoce) | **1,23 s** médiane audio (`audio_end`), **21–39 ms** après transcript final | `scripts/bench/bench.py` (A/B) + `browser-proxy` live |
| **Fast** | Finalisation STT temps réel | **225 ms p50** (Soniox cadencé 100 ms, vs 2,86 s en rafale) | `tmp/stt-lab/` (20 phrases, 62 entités) |
| **Fast** | Micro-décisions Jev | **126–194 ms** (`route`, `disambig`, `is_yes`, `score_claim`) | Appel live conteneur `ai` (`jev-latest`) |
| **Fast** | Résolveur phonétique | **2,2 ms** médiane (9–20 ms dans Docker) | `scripts/bench/vocab_eval.py` + `GET /vocab/resolve` |
| **Smart** | Rappel entités métier | **62/62 (100 %)** avec vocab + résolveur (vs 54/62 sans) · **0** faux positif | `scripts/bench/vocab_eval.py` (80 transcripts + 12 négatifs) |
| **Smart** | Garde-fous plausibilité ERP | `season_closed` (**0,01 %** FP / 24 141 cmd) · `unusual_quantity` (**0,001 %** FP / 166 273 lignes) | `apps/backend/app/services/orders.py` + `CMD-2026-007300` live |
| **Smart** | Sécurité & 5 rôles | `409 single_admin` · blocage cross-rôle client/fournisseur/inconnu · **59 + 384** tests verts | `pytest` (59 backend + 384 AI) + E2E `browser-proxy` |
| **Natural** | Coût & continuité | **0,0018–0,0073 €** / tour Nemotron (`0,009–0,017 €` Sonnet) · session unifiée Voix ↔ Assistant | Logs `[turn]` live + `browser-proxy` |

