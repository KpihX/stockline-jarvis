# Rules that bind — Hackathon X-Forum x Stockline (J.A.R.V.I.S)

Quoted from `../BRIEF.md` (§3 & §8) and `../refs/2211_-_Amphi_de_lancement_Hackathon_X-Forum.pdf`:

1. **5 minutes maximum** (`BRIEF.md` §8: "Les slides : 5 minutes maximum").
   - Budget enforced in `render.py`: `TALK_MINUTES = 5`, `WORDS_PER_MINUTE = 140` (max ~700 spoken words across non-annex slides).
2. **Three judging criteria + use case justification** (`BRIEF.md` §3, deck p. 9 & 13):
   - Use case: **For whom? What's the payoff? Why voice?**
   - **Smart**: right order, right customer, right product, alternatives, business rules, never invents.
   - **Fast**: time to first sound (`totalMs` / `perceivedMs`) and real answer (`answerMs`), tool round-trips, cost per call.
   - **Natural**: short turns, barge-in, spoken numbers/units, order read-back, noise/accents/changes of mind.
3. **Truthfulness & measured numbers** (`GUIDE-VOIX.md` §2 & §8):
   - Every latency / accuracy / cost figure on a slide comes from a script or UI run on this repo, states what `t0` means, and distinguishes a canned filler from the real answer (`firstSoundKind`).
4. **No "Merci / Questions" closing slide** (`k-presentation` rule):
   - End on the synthesis + live demo call-to-action.
5. **No AI-style em-dashes (`---`, `—`, `–`, ` -- `, `~`)** in `slides/*.md`:
   - Enforced by `scripts/check-dashes.sh`.
6. **Zero third-party branding** (team directive 2026-11-23):
   - Blank 16:9 canvas with Alpes Restauration x Stockline palette (never reuse DxO template/assets).
