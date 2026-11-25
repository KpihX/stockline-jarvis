---
layout: columns
outcome: "Une commande lance tout (make setup) : passons maintenant a vos scenarios en direct."
---

# Bilan transparent et passage au test live jury

> Ce qui est prouve, ce qui reste a mesurer au micro reel, et ce que vous allez tester maintenant

## Livrables et resilience {emerald}

- Repo autonome (data/seed, make setup, DECISIONS.md, video 115 s)
- Repli LLM agnostique : OpenCode Go -> NVIDIA Nemotron -> Claude
- 59 tests backend + 391 tests IA + typecheck + 2 appels WhatsApp reels

## Limites assumees {amber}

- Banc STT sur voix de synthese ; hesitations numeriques courtes sensibles
- Confirmation vocale post-appel env. 16-23 s sur modele thinking (coalescee)
- Cache de prompt long terme specifique a Anthropic ; .env reste hors Git

## Votre test live en 3 clics {violet}

- 1 clic sur /login : Client (Payet), Fournisseur ou Commercial/Admin
- Ouvrir /voix ou appeler le numero WhatsApp connecte sur /calls
- Observer Jev (138-184 ms), season_closed, confirmation et Assistant

## Notes

En conclusion, tout est mesure et transparent. Face au plafond Anthropic, notre repli agnostique OpenCode Go puis Nemotron prend le relais sans coupure. Sur deux vrais appels WhatsApp, zero paquet WebRTC perdu, Jev repond entre 138 et 184 millisecondes, et l'agent confirme la commande et memorise l'ouverture anticipee dans l'ERP. Place a vos scenarios en direct sur localhost 5173 ou sur /calls.
