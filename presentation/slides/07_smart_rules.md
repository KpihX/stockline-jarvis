---
layout: split
figure: security_and_rules
caption: "Un modele de langage se persuade ; une table de droits et une regle backend ne se negocient pas."
---

# Sur : 5 roles verifies, Jev et alertes ERP en direct

> Remplacer la confiance aveugle dans le prompt par des verrous serveur et des warnings calibres

- Auth signee scrypt + HMAC-SHA256 et connexion 1-clic (8 comptes demo)
- 5 roles cloisonnes : admin unique (HTTP 409), manager, client, supplier, unknown
- Warnings ERP affiches et dits : season_closed (0,01 % FP) et unusual_quantity
- Jev System One : route (158-194 ms), disambig (162 ms), confirm is_yes (131 ms)
- Score Jev (126 ms) : isole toute remise orale en « non verifie »

## Notes

Un LLM seul peut se laisser convaincre par un appelant qui pretend etre un client ou reclame 60 pour cent de remise. Nous avons donc verrouille cinq roles authentifies cote serveur, avec un administrateur unique protege par HTTP 409. Avant toute confirmation de commande, Jev verifie le oui explicite en 131 millisecondes. Et lors de la creation du brouillon, le backend calcule les alertes de saison fermee et de quantite anormale, affichees en ambre et citees a voix haute.
