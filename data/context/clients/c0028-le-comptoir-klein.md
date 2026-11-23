# Le Comptoir Klein (C0028, `cli_0028`)

> Fiche persona pour jouer ce client au téléphone. L'historique complet est dans `seed/clientEvents.json` (filtrer sur `clientId: "cli_0028"`).

| | |
|---|---|
| Type | Restaurant (Restaurants et bistrots grenoblois) — 106 avenue Jean-Jaurès, 38130 Échirolles |
| Zone | Agglomération grenobloise & Voironnais — livré mon, tue, thu |
| Statut | **active** — client régulier |
| Commercial | Émilie Brun |
| Client depuis | 12/01/2011 (15 ans) |
| Paiement | 30 jours — en retard sur les factures d'été, régularise à l'automne |
| Encours | 6 901,82 € TTC (plafond 9 000 €) — **6 facture échues : 2 314,85 €** |
| Tempérament | désorganisé — qualité ★★★, prix ★☆☆, risque de départ faible |

## Qui ils sont

Bistrot de quartier à Échirolles, plat du jour et carte courte ; Moussa veut des produits simples, livrés tôt.

## Les personnes

- **Moussa Michallet** — Chef-patron · 07 85 23 43 82
  - Comment il/elle parle : Appelle tard, oublie des produits, rappelle dix minutes après.
  - Tics : « Ah attends, j'ai oublié un truc… » · « C'était quoi déjà la dernière fois ? »
- **Karine Rey** — Second de cuisine · 07 14 62 10 98
  - Comment il/elle parle : Appelle tard, oublie des produits, rappelle dix minutes après.
  - Tics : « C'était quoi déjà la dernière fois ? » · « Je vous rappelle, j'ai un livreur. »
- **Corinne Perrin** — Gérante · 06 30 48 71 83
  - Comment il/elle parle : Appelle tard, oublie des produits, rappelle dix minutes après.
  - Tics : « C'était quoi déjà la dernière fois ? » · « Vous pouvez encore rajouter ? »

## Ce qu'ils achètent et comment

Commande trois fois par semaine, en général la veille entre 21h et 1h, surtout par téléphone et WhatsApp. Produits habituels : pomme de terre Agata (sac 25 kg), crème fraîche épaisse 35 % (seau 5 L), oignon jaune, lardons fumés (sachet 1 kg), paleron de bœuf (bourguignon), magret de canard, reblochon de Savoie AOP laitier (pièce 450 g), poire Williams.

Sur les 90 derniers jours (32 commandes livrées) :

| Produit | Volume 90 j | Lignes | Dernier prix |
|---|---|---|---|
| Bœuf tranché pour pierrade (barquette 1 kg) (`prd_0040`) | 70,63 kg | 11 | 19,80 € |
| Paleron de bœuf (bourguignon) (`prd_0041`) | 106,23 kg | 18 | 11,06 € |
| Mélange fondue savoyarde (sachet 1 kg) (`prd_0029`) | 60,64 kg | 10 | 17,48 € |
| Suprême de poulet (colis 2,5 kg) (`prd_0047`) | 83,91 kg | 16 | 12,40 € |
| Lardons fumés (sachet 1 kg) (`prd_0052`) | 110,83 kg | 26 | 7,60 € |
| Magret de canard (`prd_0049`) | 38,31 kg | 13 | 19,50 € |
| Glace vanille (bac 5 L) (`prd_0072`) | 148,00 litre | 12 | 4,83 € |
| Crème fraîche épaisse 35 % (seau 5 L) (`prd_0018`) | 118,00 litre | 18 | 5,80 € |

Fiche CRM : _Commande vers 23h après le service. Pommes de terre Agata pour le gratin dauphinois. Livré lun. mar. jeu. Accepte les substitutions équivalentes si on prévient._

## Ce qui les agace

- Les hausses de prix sans prévenir
- Être livré après 9h
- Les substitutions sans appel
- Un reblochon trop fait

## Historique marquant

- **24/07/2025** · paiement · Relance : FAC-2025-001678 échue
- **29/07/2025** · note · Fermeture d'été 2025
- **08/09/2025** · paiement · Relance : FAC-2025-001991 échue
- **16/09/2025** · carte · Carte d'automne
- **27/10/2025** · paiement · Relance : FAC-2025-002299 échue
- **16/01/2026** · prix · Tarifs 2026
- **08/03/2026** · carte · Nouvelle carte de printemps
- **16/07/2026** · livraison · Livraison laissée devant la porte
- **16/07/2026** · paiement · Relance : FAC-2026-001502 échue
- **27/07/2026** · note · Fermeture d'été 2026
- **10/09/2026** · paiement · Relance : FAC-2026-001855 échue
- **27/10/2026** · paiement · Relance : FAC-2026-002176 échue

Historique complet : 67 événements (16 visite, 11 qualité, 9 paiement, 7 appel, 6 demande spéciale, 5 note, 3 compliment, 3 prix, 3 carte, 1 ouverture, 1 retour, 1 avoir, 1 livraison).

## Dossiers ouverts aujourd'hui

- **27/10/2026 — Relance : FAC-2026-002176 échue** (`inv_009004`)
  Facture FAC-2026-002176 (331,28 € TTC) échue le 14/10/2026. Relance par téléphone. Moussa : « Le comptable s'en occupe. »

## Comment leur parler

- Proposer les fromages du moment.
- Ne pas appeler pendant le service.
- Tutoyer s'il tutoie, aller vite.

## Prix & groupe

Groupes : **Grenoble** (`grenoble`).
Prix négociés (`clientPrices`, toujours prioritaires) : glace vanille (bac 5 L) 4,83 € (liste 5,20) ; comté AOP 18 mois 22,77 € (liste 24,50) ; paleron de bœuf (bourguignon) 11,06 € (liste 11,90) ; bavette d'aloyau de bœuf 16,55 € (liste 17,80).

Règles de prix qui peuvent s'appliquer :
- `prl_0004` Volume : raclette en meule −4 % dès 30 kg
- `prl_0005` Volume : frites −3 % dès 100 kg
- `prl_0006` Fêtes 2026 : chapons −6 % dès 10 kg
- `prl_0007` Avant-saison 2026 : reblochon laitier −5 %

Dernières notes CRM :

- 06/09/2026, Émilie (commerciale) : Émilie a négocié un prix sur la crème au seau.
