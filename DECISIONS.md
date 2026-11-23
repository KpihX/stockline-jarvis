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
