---
layout: figure
figure: latency_gains
caption: "Honnetete des chiffres : Total mesure le 1er son (filler compris), Reponse mesure la vraie phrase synthétisee."
---

# Fast : 1,23 s au premier son, 225 ms STT, 158 ms Jev

> Couper le silence genant tout de suite pendant que Jev et les outils travaillent en parallele

## Notes

Sur l'axe Fast, chaque milliseconde est instrumentee et visible dans l'interface. Notre test A/B prouve que le filler precoce au transcript final abaisse la mediane du premier son de 4,68 secondes a 1,23 seconde. En flux temps reel cadence a 100 millisecondes, Soniox finalise en 225 millisecondes. Et en parallele, Jev System One execute ses quatre primitives entre 126 et 194 millisecondes, affichees en direct sur la puce Jev de chaque tour.
