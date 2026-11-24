---
layout: figure
figure: arch_pipeline
caption: "Zero boite noire : puces STT, Jev, LLM, TTS, Cache, Cout et bascule multi-LLM (OpenCode Go -> Nemotron -> Claude)."
---

# Architecture : cascade temps reel, VoIP et repli LLM

> Chevaucher les flux (Web ou WhatsApp VoIP) pour la vitesse, verrouiller les regles en bas

## Notes

Notre architecture superpose deux lignes. En haut, le flux vocal web ou un vrai appel WhatsApp via notre pont Baileys VoIP et WebRTC Opus 48 kilohertz : Soniox biaise par 478 termes metier, repli multi-LLM OpenCode Go vers Nemotron puis Claude, et ElevenLabs avec barge-in. En bas, les quatre moteurs de controle : cinq roles authentifies, resolveur phonetique en 2,2 millisecondes, Jev System One et backend SQLite.
