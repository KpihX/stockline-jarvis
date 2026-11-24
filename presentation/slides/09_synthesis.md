---
layout: columns
outcome: "Une commande lance tout (make setup) : passons maintenant a vos scenarios en direct."
---

# Bilan transparent et passage au test live jury

> Ce qui est prouve, ce qui reste a mesurer au micro reel, et ce que vous allez tester maintenant

## Livrables et resilience {emerald}

- Repo autonome (data/seed inclus, make setup, DECISIONS.md, video 91 s)
- Plafond Anthropic atteint : bascule instantanee sur NVIDIA Nemotron Ultra + retry 429
- 59 tests backend + 384 tests IA + typecheck + E2E browser-proxy verts

## Limites assumees {amber}

- Banc STT sur voix de synthese : bruit reel et accents a completer
- Filler precoce ameliore le 1er son (1,23 s), pas le calcul LLM (2,7-4,7 s)
- Cache de prompt long terme reste specifique a l'adaptateur Anthropic

## Votre test live en 3 clics {violet}

- 1 clic sur /login : Client (Payet), Fournisseur (Chambaran) ou Admin
- Cliquer une suggestion IA ou commander avec alerte season_closed en direct
- Observer la puce Jev (158 ms), l'ERP en direct et l'Assistant synchronise

## Notes

En conclusion, nous distinguons strictement ce qui est prouve de nos limites : le bruit micro reel reste a completer et le gain a 1,23 seconde porte sur le premier son via filler precoce. Quand la cle Anthropic du kit a atteint son plafond cette nuit, notre architecture a bascule sans friction sur NVIDIA Nemotron Ultra avec retry automatique. Tout est pret sur localhost 5173 : place a vos scenarios en direct.
