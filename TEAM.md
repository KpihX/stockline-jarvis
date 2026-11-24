# J.A.R.V.I.S — Alpes Restauration

> **J.A.R.V.I.S — *Juste un Agent Rapide pour la Voix et l'Inventaire Stockline***

Votre entreprise : **Alpes Restauration** (grossiste généraliste CHR montagne — Grenoble, Oisans, Vercors). Ses données (`./data/seed` et `./data/context`) sont incluses dans le dépôt.
Vos clés sont dans `.env` : privé, ne le partagez pas et ne le committez pas (`.env.example` est copié automatiquement par `make setup` si `.env` est absent).

1. **Lancer en 1 commande** : `make setup` (Docker : 4 services `backend`, `ai`, `web`, `wa`) ou `make local` (sans Docker) → **http://localhost:5173**
2. **Livrables J.A.R.V.I.S** :
   - Décisions & mesures : **[`DECISIONS.md`](DECISIONS.md)** (inclut les 2 appels WhatsApp VoIP réels + repli multi-LLM `opencode-go → nvidia → anthropic`)
   - Vidéo de démo (1 min 33 s ≤ 2 min) : **[`demo/stockline-jarvis-demo.mp4`](demo/stockline-jarvis-demo.mp4)**
   - Slides (9 slides, ~4,5 min ≤ 5 min) : **[`presentation/build/Stockline-JARVIS-Alpes-Restauration.pdf`](presentation/build/Stockline-JARVIS-Alpes-Restauration.pdf)** & **[`.pptx`](presentation/build/Stockline-JARVIS-Alpes-Restauration.pptx)**
   - Script de test appel WhatsApp réel : **[`TEST_WHATSAPP_CALL.md`](TEST_WHATSAPP_CALL.md)**
   - Guide complet, architecture & comptes de démo 1-clic : **[`README.md`](README.md)** (`make check` + `59` tests backend + `391` tests AI verts)
3. Références du kit : **[`BRIEF.md`](BRIEF.md)** · **[`SETUP.md`](SETUP.md)** · **[`METIER.md`](METIER.md)** · **[`ERP.md`](ERP.md)** · **[`GLOSSAIRE.md`](GLOSSAIRE.md)** · **[`FAQ.md`](FAQ.md)**
