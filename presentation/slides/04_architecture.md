---
layout: figure
figure: arch_pipeline
caption: "Cascade chevauchee : chaque brique STT, LLM et TTS reste swappable via .env sans toucher au code metier."
---

# Architecture temps reel et garde-fous serveur

> Chevauchement vocal en haut, intelligence metier et securite deterministe en bas

## Notes

Voici le pipeline complet. En haut, le flux temps reel chevauche les etapes : micro 100 ms pre-chauffe, Soniox avec vocabulaire client en tete, LLM avec cache de prompt de 27 mille tokens, ElevenLabs coupe a la premiere virgule et barge-in. En bas, quatre gardes serveur : identite verifiee a cinq roles, resolveur phonetique en deux millisecondes, Jev pour les micro-decisions, et backend SQLite qui porte toutes les regles.
