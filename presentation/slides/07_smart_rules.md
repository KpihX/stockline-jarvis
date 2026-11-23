---
layout: split
figure: security_and_rules
caption: "Chaque regle est prouvee par tests unitaires (59 + 384) et verification navigateur live."
---

# Sur : regles deterministes et 5 roles authentifies

> Audit initial : un inconnu pouvait creer une commande ou usurper un client

- Auth reelle scrypt + HMAC-SHA256 et connexion 1-clic de demo
- 5 roles verrouilles cote serveur : admin, manager, client, supplier, unknown
- Invariant 1 seul administrateur garanti par code (HTTP 409)
- Warnings backend : season_closed (0,01 % FP) et unusual_quantity (0,001 % FP)
- Jev System One : route 194 ms, desambiguise 162 ms, confirme 131 ms

## Notes

Lors de notre premier audit en direct, un appelant anonyme pouvait obtenir le top clients ou se faire passer pour Le Refuge Payet. Nous avons donc remplace l'identite declaree par une vraie authentification a cinq roles, avec connexion demo en un clic et un administrateur unique protege par HTTP 409. Cote metier, le backend remonte automatiquement les alertes de saison fermee et de quantite hors norme, calibrees sur 24 mille commandes.
