# Prix et crédit

## Prix de vente

- Tarif général révisé chaque lundi pour le frais (fruits et légumes, viande, volailles) ; tarif annuel au 1er janvier pour la crèmerie, l'épicerie et les surgelés.
- Fromages : prix au kilo, meule entière ou morceau ; contrats de saison à prix fixe pour les stations (signés en octobre-novembre).
- Minimum de commande 120 € HT en ville, 250 € HT en station, sinon 25 € de frais de montée.
- Remises : seuls les commerciaux et Claire peuvent accorder une remise ; jamais le standard de nuit.
- Marchés publics : prix au bordereau, révision annuelle sur indice.

Ordre de résolution : prix négocié client > règle de prix (client, puis groupe) > prix liste.

## Groupes de clients

- **Stations** (`stations`) : Restaurants d'altitude, hôtels et résidences de station : saison de mi-décembre à mi-avril, contrats de saison.
- **Grenoble** (`grenoble`) : Restaurants, bistrots et brasseries de Grenoble et de l'agglomération, ouverts toute l'année.
- **Collectivités** (`collectivites`) : Cuisines centrales, cantines, EHPAD : menus planifiés, Egalim.
- **Marché public** (`marche-public`) : Prix au bordereau, mandat administratif.
- **Hôtellerie** (`hotellerie`) : Hôtels et résidences : économat, factures au mois.
- **Traiteurs** (`traiteurs`) : Traiteurs : séminaires, mariages, fêtes.
- **Détaillants** (`detaillants`) : Épiceries, fromageries et supérettes qui revendent.
- **Grands comptes** (`grands-comptes`) : Les plus gros chiffres d'affaires des 12 derniers mois, suivis par la direction.
- **À surveiller** (`a-surveiller`) : Retards de paiement, litiges ou compte bloqué : vérifier l'encours avant toute commande.
- **Clients perdus** (`perdus`) : Plus de commande depuis plusieurs mois (partis à la concurrence ou fermés) : à reconquérir.

## Règles de prix

- `prl_0001` Stations : −5 % sur les produits montagne, du 01/12/2026 au 30/04/2027 — Conditions de la saison d'hiver 2026-2027.
- `prl_0002` Collectivités : −4 % sur la crèmerie, du 01/01/2025
- `prl_0003` Détaillants : coût + 24 % sur les fromages, du 01/09/2024 — Les fromagers gardent leur marge à la coupe.
- `prl_0004` Volume : raclette en meule −4 % dès 30 kg, du 01/01/2024
- `prl_0005` Volume : frites −3 % dès 100 kg, du 01/01/2025
- `prl_0006` Fêtes 2026 : chapons −6 % dès 10 kg, du 01/12/2026 au 31/12/2026 — Opération chapons de Noël.
- `prl_0007` Avant-saison 2026 : reblochon laitier −5 %, du 01/11/2026 au 15/12/2026 — Pour remplir les chambres froides des stations avant l'ouverture.

## Crédit et relances

- Plafond d'encours par client (TTC) ; au-delà, la commande passe en validation chez Martine.
- Stations : tout le solde de la saison doit être réglé au 31 mai ; relance dès avril.
- Relance à J+5 par mail, J+15 par téléphone, J+30 courrier ; blocage à J+60 ou au premier chèque rejeté.
- Déblocage : règlement d'au moins 50 % de l'échu et échéancier validé par Claire.

## Clients à surveiller (au 24/11)

- La Bergerie des Deux Alpes (cli_0003) : mauvais payeur, compte à risque, 12 facture échues pour 68 938,77 € TTC — **bloqué**.
- Pizzeria La Roche Béranger (cli_0009) : mauvais payeur, compte à risque, 22 facture échues pour 43 233,68 € TTC — **bloqué**.
- La Bergerie d'Île Verte (cli_0022) : paie en retard (3 à 6 semaines), mais finit par payer.
- Le Café de la Place (cli_0024) : paie en retard (3 à 6 semaines), mais finit par payer, 1 facture échue pour 10 296,54 € TTC.
- Chalet-Hôtel Leïla (cli_0033) : paie en retard (3 à 6 semaines), mais finit par payer.
- Le Crêt Poirier (cli_0043) : mauvais payeur, compte à risque — **bloqué**.
- La Table de Florian (cli_0044) : paie à l'heure mais déduit ce qu'il conteste, 1 facture échue pour 152,61 € TTC.
- Le Comptoir Perrin (cli_0050) : paie en retard (3 à 6 semaines), mais finit par payer, 4 facture échues pour 1 348,36 € TTC.
- L'Ardoise d'Yann (cli_0053) : paie en retard (3 à 6 semaines), mais finit par payer, 5 facture échues pour 5 940,98 € TTC.
- La Ferme à Dédé Grenoble (cli_0054) : paie en retard (3 à 6 semaines), mais finit par payer.
- Les Réceptions de Samuel (cli_0064) : paie à l'heure mais déduit ce qu'il conteste, 2 facture échues pour 362,21 € TTC.
- Carré Traiteur (cli_0070) : paie en retard (3 à 6 semaines), mais finit par payer, 1 facture échue pour 11 679,08 € TTC.
- Le Bivouac (cli_0075) : paie en retard (3 à 6 semaines), mais finit par payer.
- Brasserie de la Gare (cli_0094) : paie en retard (3 à 6 semaines), mais finit par payer, 3 facture échues pour 7 067,53 € TTC.
