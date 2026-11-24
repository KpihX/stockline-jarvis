# Script de test réel : Appel WhatsApp VoIP à deux (Client `337` ↔ Manager PC)

Ce guide est calibré pour maximiser la précision STT (Soniox + lexique phonétique J.A.R.V.I.S), déclencher **Jev System One** (`order:read_only` puis `order:write`), vérifier l'alerte backend **`season_closed`** et éviter tout écho micro entre les deux téléphones.

---

## 0. Pré-requis (déjà prêts sur ta machine)

- **Ligne WhatsApp connectée (Pont Baileys VoIP)** : `33605957785` (`status: connected`)
- **Client `337` pré-associé en base** : `33745717350` → **Le Refuge Payet (`cli_0082`)**
- **Page à ouvrir sur le PC (Manager / Admin)** : **[http://localhost:5173/calls](http://localhost:5173/calls)**
- **Règle acoustique importante** : ton camarade avec le téléphone **`337`** doit s'éloigner dans une autre pièce (ou mettre un casque côté PC) afin que le micro du PC ne capte que la voix du **Gestionnaire** et WhatsApp que la voix du **Client**.
- **Pour recommencer le test autant de fois que voulu** : clique simplement sur **`Réinit tests (ERP + Appels)`** en haut à droite de `/calls` (remet l'ERP et l'historique d'appels à zéro **tout en gardant le QR Code WhatsApp et l'association `337` intacts**).

---

## 1. Déroulé du dialogue (≈ 45 secondes)

### Étape 1 — Sonnerie & Identification automatique

- **Client (`337`)** : appelle le numéro **`33605957785`** sur WhatsApp.
- **Sur `/calls` (PC)** : le bandeau vert apparaît automatiquement avec **Le Refuge Payet (`33745717350` · `cli_0082`)**.
- **Gestionnaire (PC)** : clique sur **`Décrocher`** (le statut passe à `WebRTC Opus 48 kHz (connected)`).

### Étape 2 — Ouverture & Question ambiguë (vérifie l'abstention ERP + Jev `read_only`)

- **Gestionnaire (PC)** :
  > _« Allô bonjour, Alpes Restauration à l'appareil, c'est Le Refuge Payet ? »_
- **Client (`337`, articulé, courte pause après la phrase)** :
  > _« Bonjour, oui c'est Le Refuge Payet. Je voudrais savoir ce que vous avez comme fromage à raclette ou comme crème. »_
- **Ce que vous devez observer à l'écran** :
  - Puce **`Jev <ms> ms`** sur la bulle client (`info:read_only` ou `order:read_only`).
  - **Aucune commande créée** dans l'ERP (règle d'abstention respectée) : le Copilote J.A.R.V.I.S propose les références exactes et demande la quantité.

### Étape 3 — Commande hors saison (vérifie `create_draft_order` + alerte `season_closed`)

- **Gestionnaire (PC)** :
  > _« Nous avons de la raclette en meule au lait cru et de la raclette tranchée en barquette d'un kilo. Qu'est-ce que je vous note et pour quelle date ? »_
- **Client (`337`)** :
  > _« Mets-moi cinquante kilos de frites surgelées et vingt kilos de raclette tranchée pour le premier décembre. »_
- **Ce que vous devez observer à l'écran** :
  - Puce **`Jev <ms> ms · order:write`**.
  - Le Copilote J.A.R.V.I.S crée **une pré-commande brouillon (`CMD-2026-…`)** en direct avec le tarif négocié (`2,10 €/kg` sur 50 kg de frites, `2,04 €/kg` à partir de 200 kg).
  - Un **bandeau ambre `⚠ season_closed`** apparaît immédiatement (_Le Refuge Payet est habituellement ouvert de mi-décembre à mi-avril_) et la carte du brouillon affiche le total HT et un bouton **`Confirmer`** 1-clic.

### Étape 4 — Prévention & Confirmation (optionnel, ajout de ligne sur la même commande)

- **Gestionnaire (PC)** :
  > _« Je vous préviens juste : sur l'ERP vous êtes notés fermés jusqu'à mi-décembre, on maintient bien le mardi premier décembre ? »_
- **Client (`337`)** :
  > _« Oui c'est bon, on ouvre plus tôt cette année, confirme la commande s'il te plaît. »_
- **Gestionnaire (PC)** : attends que la carte passe à **`Confirmée`** (≈ 5–15 s) avant de cliquer sur **`Raccrocher`**, puis vérifie **`Accueil`** (Dashboard) ou **`Commandes`** (`/orders`) : la commande et l'alerte `season_closed` sont enregistrées dans l'ERP sous l'acteur `J.A.R.V.I.S · Appel Le Refuge Payet`.

---

## 2. Variantes faciles à prononcer pour un 2e essai

Après avoir cliqué sur **`Réinit tests (ERP + Appels)`**, vous pouvez aussi tester ces phrases très nettes pour le STT :

- _« Bonjour, c'est Le Refuge Payet, je veux commander cinquante kilos de carottes des sables et dix litres de crème liquide pour jeudi. »_
- _« Bonjour, c'est Le Refuge Payet, mets-moi comme d'habitude pour ma prochaine tournée. »_ _(déclenche le panier habituel préchargé depuis l'historique saisonnier)_
