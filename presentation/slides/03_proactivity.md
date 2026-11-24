---
layout: columns
outcome: "Separer le reflexe instantane (code + Jev 158 ms) du raisonnement conversationnel (LLM)."
---

# Cinq couches de proactivite : du reflexe a la preuve

> Un copilote qui prepare le terrain avant l'appel, agit pendant l'ecoute et verifie avant d'ecrire

## 1-2. Precharger et Anticiper {emerald}

- Identite verifiee charge fiche, habitudes et panier saisonnier a l'ouverture
- Filler precoce des le transcript final + annonce outil anticipee
- Jev System One route, desambiguise et valide oui/non en 126-194 ms

## 3-4. Alerter et Apprendre {violet}

- Regles metier deterministes cote backend (champ warnings structure)
- Resolveur phonetique 2,2 ms rattrape les homophones sans couter un tour LLM
- Apprentissage vocabulaire verrouille sur preuve reelle (oui, epellation, commande)

## 5. Unifier l'experience {blue}

- Tableau de bord aide par l'IA et adapte a chacun des 5 profils
- Cartes d'actions rotatives qui lancent directement Voix ou Assistant
- Memoire SQLite unique : commencer a la voix, finir par ecrit sans rupture

## Notes

Pour rendre l'agent réellement proactif, nous avons separe le reflexe du raisonnement sur cinq couches. Avant le premier mot, la fiche client et ses habitudes saisonnieres sont prechargees. Des la fin de parole, le filler precoce et Jev System One partent en parallele. Cote serveur, le resolveur phonetique et les warnings backend verrouillent la justesse. Enfin, Dashboard, Voix et Assistant partagent la meme memoire SQLite.
