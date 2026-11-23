"""Entry point for the Alpes Restauration x Stockline deck."""

from __future__ import annotations

import importlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT / "figures")]

FIGURE_MODULES: tuple[str, ...] = ("charts",)


def figures() -> None:
    for name in FIGURE_MODULES:
        mod = importlib.import_module(f"figures.{name}")
        for fn in mod.ALL:
            fn()


def check() -> int:
    import deck
    import deckkit
    import slides as slidesmod

    all_slides = slidesmod.load()
    problems = deckkit.validate(
        all_slides,
        specs=deck.SPECS,
        figs_dir=ROOT.parent / "build" / "figs",
        root=ROOT.parent,
        text_layouts=frozenset({"columns", "split"}),
        max_lines_single=7,
        max_lines_per_block=6,
        max_words_per_line=14,
        max_level=1,
    )
    if problems:
        for p in problems:
            print("ERROR:", p)
        return 1
    print(f"[check] {len(all_slides)} slides validated against specs.")
    return 0


def main(argv: list[str] | None = None) -> None:
    args = argv if argv is not None else sys.argv[1:]
    cmd = args[0] if args else "all"
    if cmd == "figures":
        figures()
    elif cmd == "deck":
        import deck
        deck.build()
    elif cmd == "preview":
        import preview
        preview.main()
    elif cmd == "check":
        raise SystemExit(check())
    elif cmd == "all":
        figures()
        import deck
        import preview
        deck.build()
        preview.main()
        raise SystemExit(check())
    else:
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
