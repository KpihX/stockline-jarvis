# Le Comptoir Perrin (C0050, `cli_0050`)

> Fiche persona pour jouer ce client au téléphone. L'historique complet est dans `seed/clientEvents.json` (filtrer sur `clientId: "cli_0050"`).

| | |
|---|---|
| Type | Restaurant (Restaurants et bistrots grenoblois) — 31 rue des Halles, 38920 Crolles |
| Zone | Grésivaudan & Chartreuse — livré mon, wed, fri |
| Statut | **active** — en croissance |
| Commercial | Sébastien Charvet |
| Client depuis | 15/04/2014 (12 ans) |
| Paiement | 30 jours — paie en retard (3 à 6 semaines), mais finit par payer |
| Encours | 4 378,45 € TTC (plafond 6 000 €) — **4 facture échues : 1 348,36 €** |
| Tempérament | fidèle — qualité ★★☆, prix ★☆☆, risque de départ faible |

## Qui ils sont

Bistrot de quartier à Crolles, plat du jour et carte courte ; Samuel veut des produits simples, livrés tôt.

## Les personnes

- **Samuel Arnaud** — Chef-patron · 06 42 66 71 26 · samuel@comptoirperrin.fr
  - Comment il/elle parle : Voix posée, tutoie le commercial depuis des années, commande toujours la même chose.
  - Tics : « Je te fais confiance. » · « Comme d'habitude. »
- **Jean-Marc Perrin** — Second de cuisine · 06 74 24 39 19
  - Comment il/elle parle : Calme, habitué, appelle à heure fixe.
  - Tics : « Comme d'habitude. » · « On travaille ensemble depuis le temps… »

## Ce qu'ils achètent et comment

Commande tous les jours de livraison, en général la veille entre 21h et 2h, surtout par téléphone et WhatsApp. Produits habituels : pomme de terre Agata (sac 25 kg), crème fraîche épaisse 35 % (seau 5 L), lardons fumés (sachet 1 kg), raclette de Savoie IGP au lait cru (meule ~6 kg), reblochon de Savoie AOP laitier (pièce 450 g), tomate grappe, jambon blanc supérieur (pièce ~4 kg), pomme Golden.

Sur les 90 derniers jours (34 commandes livrées) :

| Produit | Volume 90 j | Lignes | Dernier prix |
|---|---|---|---|
| Raclette de Savoie IGP au lait cru (meule ~6 kg) (`prd_0027`) | 99,64 kg | 10 | 15,80 € |
| Reblochon de Savoie AOP laitier (pièce 450 g) (`prd_0026`) | 170,00 pièce | 15 | 6,08 € |
| Lardons fumés (sachet 1 kg) (`prd_0052`) | 121,19 kg | 16 | 7,60 € |
| Jambon blanc supérieur (pièce ~4 kg) (`prd_0054`) | 69,21 kg | 14 | 10,14 € |
| Crème fraîche épaisse 35 % (seau 5 L) (`prd_0018`) | 104,00 litre | 17 | 5,80 € |
| Pomme de terre Agata (sac 25 kg) (`prd_0001`) | 420,07 kg | 17 | 0,97 € |
| Tomate grappe (`prd_0011`) | 109,20 kg | 17 | 3,05 € |
| Pomme Golden (`prd_0013`) | 167,18 kg | 18 | 1,80 € |

Fiche CRM : _Saint-marcellin et reblochon toutes les semaines. Commande vers 23h après le service. Livré lun. mer. ven. Refuse les substitutions : appeler avant toute modification._

## Ce qui les agace

- Les hausses de prix sans prévenir
- Un reblochon trop fait
- Les substitutions sans appel

## Historique marquant

- **25/12/2025** · paiement · Relance : FAC-2025-002685 échue
- **30/12/2025** · demande spéciale · Fêtes 2025 : réservation de volumes
- **09/01/2026** · prix · Tarifs 2026
- **07/02/2026** · paiement · Relance : FAC-2025-003096 échue
- **25/02/2026** · retour · Retour à la livraison : tomate grappe
- **29/03/2026** · paiement · Relance : FAC-2026-000478 échue
- **05/06/2026** · qualité · Qualité : reblochon de Savoie AOP laitier (pièce 450 g)
- **07/06/2026** · avoir · Avoir qualité : reblochon de Savoie AOP laitier (pièce 450 g)
- **11/06/2026** · paiement · Relance : FAC-2026-001192 échue
- **27/07/2026** · paiement · Relance : FAC-2026-001560 échue
- **21/09/2026** · paiement · Relance : FAC-2026-001974 échue
- **07/11/2026** · paiement · Relance : FAC-2026-002272 échue

Historique complet : 71 événements (19 paiement, 9 visite, 9 qualité, 7 demande spéciale, 7 appel, 6 compliment, 5 note, 3 prix, 2 carte, 1 ouverture, 1 livraison, 1 retour, 1 avoir).

## Dossiers ouverts aujourd'hui

- **07/11/2026 — Relance : FAC-2026-002272 échue** (`inv_009100`)
  Facture FAC-2026-002272 (39,75 € TTC) échue le 28/10/2026. Relance par mail puis téléphone. Samuel : « Je ne l'ai pas reçue, renvoyez-la. »

## Comment leur parler

- Ne pas appeler pendant le service.
- Tutoyer s'il tutoie, aller vite.

## Prix & groupe

Groupes : **Grenoble** (`grenoble`), **À surveiller** (`a-surveiller`).
Prix négociés (`clientPrices`, toujours prioritaires) : banane 1,77 € (liste 1,90) ; pomme de terre Agata (sac 25 kg) 0,91 € (liste 0,98) ; oignon jaune 1,07 € (liste 1,15) ; jambon blanc supérieur (pièce ~4 kg) 10,14 € (liste 10,90).

Règles de prix qui peuvent s'appliquer :
- `prl_0004` Volume : raclette en meule −4 % dès 30 kg
- `prl_0005` Volume : frites −3 % dès 100 kg
- `prl_0006` Fêtes 2026 : chapons −6 % dès 10 kg
- `prl_0007` Avant-saison 2026 : reblochon laitier −5 %

Dernières notes CRM :

- 19/11/2025, Sébastien (commercial) : Le chef veut le saint-marcellin bien coulant le vendredi.
- 10/08/2026, Sébastien (commercial) : Sébastien a négocié un prix sur la crème au seau.
- 13/08/2026, Yohan (standard de nuit) : Commande la nuit, en général entre 21h et 2h. Samuel veut qu'on lui relise la commande.
- 17/09/2026, Sébastien (commercial) : Ne veut aucune substitution sans être prévenu : si un produit manque, appeler Samuel avant le départ du camion.
