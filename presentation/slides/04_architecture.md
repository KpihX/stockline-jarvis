---
layout: figure
figure: arch_pipeline
caption: "Zero boite noire : chaque tour affiche en direct ses puces STT, Jev, LLM, TTS, Cache et Cout."
---

# Architecture : cascade temps reel et gardes serveur

> Chevaucher les flux en haut pour la vitesse, verrouiller les decisions en bas par Jev et le code

## Notes

Notre architecture superpose deux lignes. En haut, la cascade vocale chevauchee : micro cadence a 100 millisecondes, Soniox biaise par le lexique du client, LLM avec cache de prompt, et ElevenLabs coupe dès la premiere virgule avec barge-in. En bas, les quatre moteurs de controle : authentification a cinq roles, resolveur phonetique en 2,2 millisecondes, Jev System One mesure sur chaque tour, et backend SQLite garant des regles metier.
