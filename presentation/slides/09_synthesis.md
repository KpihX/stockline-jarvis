---
layout: columns
outcome: "Pret pour le test en direct : make setup lance tout, passons maintenant a la demo live."
---

# Bilan honnete et passage a la demo live

> Tout est mesure, reproductible avec make setup, et pret pour vos scenarios jury

## Livrables et architecture {emerald}

- Repo autonome avec data/seed, make setup, DECISIONS.md et video 2 min
- Plafond Anthropic atteint en fin de nuit : bascule fluide sur NVIDIA Nemotron Ultra
- 59 tests backend + 384 tests IA + typecheck + E2E browser-proxy verts

## Limites assumees {amber}

- Corpus STT sur voix de synthese propre : bruit reel et accents a mesurer
- Filler precoce ameliore le ressenti (1,23 s), pas le calcul LLM (2,7-4,8 s)
- Cache de prompt et keep-alive restent specifiques a Anthropic

## En direct devant le jury {violet}

- Connexion 1-clic par profil (Client Payet, Fournisseur Chambaran, Admin)
- Commande vocale avec alerte season_closed + suite dans l'Assistant
- Verification en direct de la mise a jour ERP et du cout par tour

## Notes

Pour conclure honnetement : nos tests de bruit reel micro restent a completer, le gain a 1,23 seconde porte sur le premier son grace au filler precoce, et suite au plafond de la cle Anthropic du kit, le systeme tourne en direct sur NVIDIA Nemotron Ultra par simple variable d'environnement. Tout est vert, reproductible par make setup, et nous sommes prets pour vos appels de test en direct.
