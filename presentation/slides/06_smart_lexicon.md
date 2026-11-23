---
layout: figure
figure: lexicon_recall
caption: "Evaluation hors ligne sur vrais transcripts (scripts/bench/vocab_eval.py) : 0 faux positif sur 80 + 12 cas."
---

# Smart : 62/62 entites metier sans faux positif

> Un resolveur phonetique deterministe de 2,2 ms rattrape les quasi-homophones apres le STT

## Notes

Les erreurs STT les plus dangereuses sont les homophones : Refuge Paillet pour Payet, a Promont pour Apremont, Liglou pour L'Igloo. Plutot que de reecrire le transcript, un resolveur phonetique en pur Python propose les candidats avec score et marge en 2,2 millisecondes. Il fait monter Soniox de 60 a 62 sur 62, avec zero faux positif sur 80 transcripts et 12 pieges negatifs. Et l'apprentissage exige une preuve relue dans la conversation.
