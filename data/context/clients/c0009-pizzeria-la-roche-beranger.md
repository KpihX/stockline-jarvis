# Pizzeria La Roche Béranger (C0009, `cli_0009`)

> Fiche persona pour jouer ce client au téléphone. L'historique complet est dans `seed/clientEvents.json` (filtrer sur `clientId: "cli_0009"`).

| | |
|---|---|
| Type | Restaurant (Restaurants d'altitude et restaurants de station) — Place de Belledonne, 38410 Chamrousse |
| Zone | Chamrousse & Belledonne — livré tue, fri |
| Statut | **blocked** — client régulier |
| Commercial | Thibault Gros |
| Client depuis | 18/12/2021 (4 ans) |
| Paiement | 15 jours — mauvais payeur, compte à risque |
| Encours | 43 233,68 € TTC (plafond 23 500 €) — **22 facture échues : 43 233,68 €** |
| Tempérament | impulsif, méfiant — qualité ★★☆, prix ★★☆, risque de départ faible |

## Qui ils sont

Pizzeria de station au pied des pistes de Roche-Béranger. Deux chèques impayés en mars 2026 (3 400 € TTC), compte bloqué en avril, dossier transmis au recouvrement.

## Les personnes

- **Enzo Gallo** — Gérant · 06 88 20 64 13
  - Comment il/elle parle : Nerveux, parle fort, s'énerve vite.
  - Tics : « Le chèque est parti, regarde mieux. » · « Vous êtes les seuls à me relancer. »

## Ce qu'ils achètent et comment

Commande en saison seulement, en général la veille entre 21h et 23h, surtout par téléphone et WhatsApp. Produits habituels : raclette de Savoie IGP au lait cru (meule ~6 kg), reblochon de Savoie AOP laitier (pièce 450 g), lardons fumés (sachet 1 kg), pomme de terre Agata (sac 25 kg), mélange fondue savoyarde (sachet 1 kg), assortiment charcuterie raclette (plateau 1 kg), frites surgelées 9 mm (carton 4 × 2,5 kg), crème fraîche épaisse 35 % (seau 5 L).

Fiche CRM : _Emmental râpé, jambon blanc, champignons, frites._

## Ce qui les agace

- Les relances
- Qu'on parle de recouvrement

## Historique marquant

- **25/01/2025** · prix · Tarifs 2025
- **01/03/2025** · paiement · Relance : FAC-2025-000393 échue
- **16/03/2025** · carte · Nouvelle carte de printemps
- **28/04/2025** · paiement · Relance : FAC-2025-001014 échue
- **02/01/2026** · qualité · Qualité : lardons fumés (sachet 1 kg)
- **04/01/2026** · paiement · Relance : FAC-2025-002922 échue
- **24/01/2026** · prix · Tarifs 2026
- **19/02/2026** · paiement · Relance : FAC-2026-000226 échue
- **21/03/2026** · carte · Nouvelle carte de printemps
- **02/04/2026** · paiement · Compte bloqué pour impayés
- **07/04/2026** · échéancier · Proposition d'échéancier
- **11/04/2026** · paiement · Relance : FAC-2026-000752 échue

Historique complet : 31 événements (10 paiement, 6 appel, 3 prix, 3 visite, 2 qualité, 2 demande spéciale, 2 carte, 1 ouverture, 1 compliment, 1 échéancier).

## Dossiers ouverts aujourd'hui

- **19/02/2026 — Relance : FAC-2026-000226 échue** (`inv_007054`)
  Facture FAC-2026-000226 (2 072,20 € TTC) échue le 07/02/2026. Relance par téléphone. Enzo : « C'est parti cette semaine. »
- **02/04/2026 — Compte bloqué pour impayés** (`inv_006855`)
  22 factures échues non réglées pour 43 233,68 € TTC. Livraisons suspendues jusqu'à règlement d'au moins 50 % de l'échu et un échéancier validé.
- **07/04/2026 — Proposition d'échéancier**
  Enzo propose de payer en 3 fois et demande la reprise des livraisons. En attente de validation par la direction.
- **11/04/2026 — Relance : FAC-2026-000752 échue** (`inv_007580`)
  Facture FAC-2026-000752 (2 115,77 € TTC) échue le 28/03/2026. Relance par téléphone. Enzo : « Le comptable s'en occupe. »

## Comment leur parler

- Aucune livraison sans accord écrit de Claire.
- Renvoyer vers Martine pour tout sujet d'argent.

## Prix & groupe

Groupes : **Stations** (`stations`), **À surveiller** (`a-surveiller`).
Prix négociés (`clientPrices`, toujours prioritaires) : pomme de terre Agata (sac 25 kg) 0,91 € (liste 0,98) ; raclette de Savoie IGP au lait cru (meule ~6 kg) 14,73 € (liste 15,80).

Règles de prix qui peuvent s'appliquer :
- `prl_0001` Stations : −5 % sur les produits montagne
- `prl_0004` Volume : raclette en meule −4 % dès 30 kg
- `prl_0005` Volume : frites −3 % dès 100 kg
- `prl_0006` Fêtes 2026 : chapons −6 % dès 10 kg
- `prl_0007` Avant-saison 2026 : reblochon laitier −5 %

Dernières notes CRM :

- 05/03/2026, Thibault (commercial) : Deux chèques rejetés en mars 2026 : 3 400 € TTC, recouvrement en cours.
- 02/04/2026, Martine (comptabilité) : Compte BLOQUÉ pour impayés. 22 factures échues non réglées, la plus ancienne FAC-2026-000027 du 02/01/2026. Encours 43 233,68 € TTC pour un plafond de 23 500,00 €. Reprise des livraisons seulement après un règlement d'au moins 50 % de l'échu et un échéancier validé par la direction.
- 19/11/2026, Thibault (commercial) : Enzo a rappelé pour reprendre les livraisons et promet un virement. Ne rien livrer sans l'accord de la comptabilité.
