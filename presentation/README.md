# Presentation — Alpes Restauration x Stockline (J.A.R.V.I.S)

Deck as code (`k-presentation` doctrine).
- Markdown in `slides/*.md` owns every word and timed speaker notes (5 min max).
- Python (`scripts/theme.py`, `scripts/figures/*.py`, `scripts/deck.py`) only places and draws on a blank 16:9 canvas (`13.333 x 7.5 in`).

## Commands
```bash
make check   # check-dashes + contract validation (slides <-> figures)
make build   # build figures + assemble .pptx + export PDF + PNG previews
```
