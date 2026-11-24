---
layout: figure
figure: lexicon_recall
caption: "Apprendre sans jamais deviner : une entree n'est ecrite que si la conversation prouve un oui ou une epellation."
---

# Smart : 62/62 entites metier et 0 faux positif

> Rattraper « Refuge Paillet » et « vin blanc a Promont » en 2,2 ms avant meme d'appeler le LLM

## Notes

Au telephone, un chef dit Refuge Paillet pour Payet, ou vin blanc a Promont pour Apremont. Notre resolveur phonetique francais, en pur Python et sans dependance, inspecte les groupes de mots en 2,2 millisecondes. Sans jamais reecrire le transcript brut, il injecte les candidats avec leur score et fait passer Soniox de 60 a 62 sur 62, avec zero faux positif sur 80 transcripts. Si une mention reste ambigue, Jev tranche en 162 millisecondes.
