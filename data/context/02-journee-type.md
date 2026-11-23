# Une journée chez Alpes Restauration

## Convention « maintenant » du pack

Le pack est figé au **mardi 24/11/2026 à 04h30** (heure de Paris). Les commandes du jour sont préparées, confirmées ou encore en brouillon ; les camions ne sont pas partis. Les commandes de demain arrivent encore. L'historique couvre trois ans.

## Le cycle de 24 heures

- **20:00** — Yohan prend le standard : les restaurants de ville commandent après le service, les restaurants d'altitude vers 22h-23h en saison.
- **02:30** — Pascal est au MIN de Grenoble pour les fruits et légumes ; Bernard prépare la découpe des meules.
- **03:00** — Réception des camions fournisseurs (fromages de Savoie, viande, volailles, surgelés) ; contrôle des températures.
- **03:15** — Préparation par tournée : les stations d'abord, puis Grenoble ; découpe des fromages au fil.
- **04:30** — Fin de préparation des stations, chargement des 4x4. **C'est l'heure « maintenant » du pack.**
- **04:45** — Départ de la tournée Oisans (en saison) ; 5h15 Chamrousse et Vercors ; 6h00 Grenoble et agglomération.
- **07:00** — Coralie arrive : appli, mails, WhatsApp, réclamations ; point routes et météo avec Didier.
- **10:00** — Pascal et Bernard passent les commandes fournisseurs pour le lendemain.
- **15:00** — Tarif de la semaine et promos envoyés aux clients ; les commerciaux rappellent leurs clients.

## Heures limites de commande

- Restaurants de Grenoble et de l'agglomération : commande avant 2h du matin pour le jour même, sinon le lendemain.
- Stations (Oisans, Chamrousse, Vercors) : commande la veille avant 23h ; le samedi de chassé-croisé, le jeudi avant 18h.
- Cantines, cuisines centrales, EHPAD : commande à J-2 avant 12h, avec numéro de bon.
- Meules entières, beaufort d'alpage et chapons : la veille avant 12h, selon disponibilité chez l'affineur.

## Qui appelle quand

- Les commerciaux (Thibault, Émilie, Sébastien) prennent les commandes de leur portefeuille en journée.
- Yohan Baret tient le standard de nuit (`createdBy: "yohan"`) : Prend les commandes de 20h à 4h (les restaurants d'altitude appellent après le service du soir) ; ne peut accorder aucune remise.
- Les commandes par e-mail et WhatsApp arrivent en brouillon et sont confirmées par l'ADV ou le commercial.

## Facturation

- Facture à la livraison, à la semaine (le lundi, pour la semaine écoulée) ou au mois (le 1er) selon le client.
- `overdue` n'est jamais stocké : une facture émise ou partiellement payée après son échéance est en retard.
- Les retours et refus à la livraison sont déduits de la facture (ligne préparée diminuée).
