# Marché Frais Chamrousse (C0065, `cli_0065`)

> Fiche persona pour jouer ce client au téléphone. L'historique complet est dans `seed/clientEvents.json` (filtrer sur `clientId: "cli_0065"`).

| | |
|---|---|
| Type | Grande surface (Épiceries, fromageries et supérettes) — 3 cours de la Liberté, 38410 Chamrousse |
| Zone | Chamrousse & Belledonne — livré mon, thu |
| Statut | **active** — client régulier |
| Commercial | Sébastien Charvet |
| Client depuis | 16/06/2008 (18 ans) |
| Paiement | 30 jours — prélèvement SEPA, aucun retard |
| Encours | 7 177,19 € TTC (plafond 10 000 €) |
| Tempérament | négociateur, bavard, économe — qualité ★☆☆, prix ★★★, risque de départ moyen |

## Qui ils sont

Épicerie ou supérette de Chamrousse, rayon fromages de Savoie et charcuterie à la coupe ; double ses volumes l'hiver avec les touristes.

## Les personnes

- **Hervé Lebrun** — Gérant · 07 20 22 71 46 · herve@marchefraischamrousse.fr
  - Comment il/elle parle : Joue la surprise sur chaque tarif, finit par commander.
  - Tics : « À ce prix-là, je prends ailleurs. » · « Vous êtes plus cher que votre voisin, là. »
- **Philippe Philippe** — Responsable rayon frais · 06 75 66 65 21
  - Comment il/elle parle : Raconte sa vie, parle des clients, du temps, du foot.
  - Tics : « Et ta famille, ça va ? » · « Tu sais pas ce qui m'est arrivé… »
- **Service comptabilité** — Factures · factures@marchefraischamrousse.fr

## Ce qu'ils achètent et comment

Commande deux fois par semaine, en général la veille entre 15h et 20h, surtout par téléphone et portail web. Produits habituels : reblochon de Savoie AOP laitier (pièce 450 g), raclette tranchée (barquette 1 kg), saint-Marcellin IGP (pièce 80 g), jambon cru de Savoie IGP tranché (500 g), mélange fondue savoyarde (sachet 1 kg), oignon jaune, tomate grappe, champignon de Paris blanc.

Sur les 90 derniers jours (21 commandes livrées) :

| Produit | Volume 90 j | Lignes | Dernier prix |
|---|---|---|---|
| Mélange fondue savoyarde (sachet 1 kg) (`prd_0029`) | 184,81 kg | 13 | 16,22 € |
| Reblochon de Savoie AOP fermier (pièce 450 g) (`prd_0025`) | 382,00 pièce | 10 | 7,33 € |
| Reblochon de Savoie AOP laitier (pièce 450 g) (`prd_0026`) | 444,00 pièce | 13 | 5,96 € |
| Raclette tranchée (barquette 1 kg) (`prd_0028`) | 167,53 kg | 8 | 13,18 € |
| Huile de tournesol (bidon 10 L) (`prd_0061`) | 746,00 litre | 7 | 2,60 € |
| Emmental râpé (sachet 1 kg) (`prd_0037`) | 230,83 kg | 16 | 7,27 € |
| Jambon cru de Savoie IGP tranché (500 g) (`prd_0053`) | 127,00 pièce | 11 | 12,60 € |
| Crème liquide UHT 35 % (brique 1 L) (`prd_0019`) | 297,00 litre | 13 | 4,60 € |

Fiche CRM : _Raclette tranchée pour la clientèle de location. Fins de lot et promos en avant-saison. Livré lun. jeu. Accepte les substitutions équivalentes si on prévient._

## Ce qui les agace

- Colis incomplets
- Prix plus chers que la GMS

## Historique marquant

- **17/02/2022** · qualité · Qualité : jambon cru de Savoie IGP tranché (500 g)
- **14/04/2022** · prix · Hausse tarifaire (gazole, énergie)
- **11/04/2023** · qualité · Qualité : saint-Marcellin IGP (pièce 80 g)
- **13/01/2024** · prix · Tarifs 2024
- **18/09/2025** · retour · Retour à la livraison : poireau
- **01/11/2025** · demande spéciale · Fêtes 2025 : réservation de volumes
- **14/01/2026** · prix · Tarifs 2026
- **02/08/2026** · contact · Nouveau contact : Philippe Philippe
- **01/10/2026** · qualité · Qualité : huile de tournesol (bidon 10 L)
- **02/10/2026** · avoir · Avoir qualité : huile de tournesol (bidon 10 L)
- **02/11/2026** · livraison · Bon de livraison erroné
- **20/11/2026** · demande spéciale · Fêtes 2026 : réservation de volumes

Historique complet : 52 événements (19 visite, 8 appel, 7 qualité, 6 demande spéciale, 4 compliment, 3 prix, 1 ouverture, 1 retour, 1 contact, 1 avoir, 1 livraison).

## Dossiers ouverts aujourd'hui

- **02/11/2026 — Bon de livraison erroné** (`ord_023929`)
  BL avec les quantités d'une autre commande. Rectifié par l'ADV.
- **20/11/2026 — Fêtes 2026 : réservation de volumes**
  Hervé veut réserver pour les fêtes : reblochon de Savoie AOP laitier (pièce 450 g) et emmental râpé (sachet 1 kg) en volume pour les 23-24 et 30-31/12. Philippe : « Tu sais pas ce qui m'est arrivé… »

## Comment leur parler

- Rester simple.
- Proposer les promos.

## Prix & groupe

Groupes : **Détaillants** (`detaillants`).
Pas de prix négocié.

Règles de prix qui peuvent s'appliquer :
- `prl_0003` Détaillants : coût + 24 % sur les fromages
- `prl_0004` Volume : raclette en meule −4 % dès 30 kg
- `prl_0005` Volume : frites −3 % dès 100 kg
- `prl_0006` Fêtes 2026 : chapons −6 % dès 10 kg
- `prl_0007` Avant-saison 2026 : reblochon laitier −5 %

Dernières notes CRM :

- 02/03/2026, Sébastien (commercial) : Hervé commande plus dès les vacances de Noël.
