"""Visual system for the Alpes Restauration x Stockline presentation.

Single source of truth for colours, typography and 16:9 (13.333 x 7.5 in) geometry.
Zero third-party template identity: blank canvas aligned with DESIGN.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from deckkit import Box, Level, TextStyle

# ── Canvas (16:9 widescreen) ──────────────────────────────────────────────────
SLIDE_W = 13.333
SLIDE_H = 7.5

# ── Palette (hex without # for python-pptx, with # helper for matplotlib) ─────
PAPER = "FAFDFB"       # calm off-white ground (shared by slides AND figures)
SURFACE = "F1F6F3"     # subtle tinted card/band
INK = "0F291E"         # deep forest ink (titles, strong contrast)
BODY_INK = "354940"    # secondary slate-forest (body text)
MUTED = "6A7D74"       # captions, footers, axes
BORDER = "D5E2DB"      # 1px hairline border

EMERALD = "157A4B"     # primary brand accent (Alpes Restauration / ERP)
EMERALD_SOFT = "E2F3EA"
EMERALD_DARK = "0D5433"
VIOLET = "6D28D9"      # voice / AI agent accent (matches DESIGN.md violet)
VIOLET_SOFT = "EFE9FC"
AMBER = "D97706"       # warnings / filler distinction
AMBER_SOFT = "FEF3DC"
CORAL = "C83737"       # errors / out-of-stock / risk
CORAL_SOFT = "FDEAEA"
BLUE = "1D65C1"        # neutral comparison / Jev

PALETTE = {
    "paper": f"#{PAPER}",
    "surface": f"#{SURFACE}",
    "ink": f"#{INK}",
    "body": f"#{BODY_INK}",
    "muted": f"#{MUTED}",
    "border": f"#{BORDER}",
    "emerald": f"#{EMERALD}",
    "emerald_soft": f"#{EMERALD_SOFT}",
    "emerald_dark": f"#{EMERALD_DARK}",
    "violet": f"#{VIOLET}",
    "violet_soft": f"#{VIOLET_SOFT}",
    "amber": f"#{AMBER}",
    "amber_soft": f"#{AMBER_SOFT}",
    "coral": f"#{CORAL}",
    "coral_soft": f"#{CORAL_SOFT}",
    "blue": f"#{BLUE}",
    # figkit standard aliases
    "navy": f"#{INK}",
    "slate": f"#{BODY_INK}",
    "rule": f"#{BORDER}",
    "gold": f"#{AMBER}",
}

COLOURS = {
    "emerald": EMERALD,
    "violet": VIOLET,
    "amber": AMBER,
    "coral": CORAL,
    "blue": BLUE,
    "ink": INK,
    "grey": BODY_INK,
}

# ── Typography ────────────────────────────────────────────────────────────────
HEAD_FONT = "Maven Pro"
BODY_FONT = "Roboto"

TITLE_COVER = TextStyle(size=40, colour=INK, bold=True, font=HEAD_FONT)
SUB_COVER = TextStyle(size=19, colour=EMERALD, bold=False, font=BODY_FONT)
HEAD_SLIDE = TextStyle(size=24, colour=INK, bold=True, font=HEAD_FONT)
SUB_SLIDE = TextStyle(size=13, colour=BODY_INK, italic=False, font=BODY_FONT)
COL_HEAD = TextStyle(size=15, colour=EMERALD, bold=True, font=HEAD_FONT)
CAPTION_STYLE = TextStyle(size=10.5, colour=MUTED, italic=False, font=BODY_FONT)
FOOTER_STYLE = TextStyle(size=9.5, colour=MUTED, font=BODY_FONT)
SEC_NUM = TextStyle(size=54, colour=EMERALD, bold=True, font=HEAD_FONT)
SEC_TITLE = TextStyle(size=32, colour=INK, bold=True, font=HEAD_FONT)
SEC_SUB = TextStyle(size=15, colour=BODY_INK, font=BODY_FONT)

LEVELS = [
    Level(size=15.0, indent_in=0.0, bullet="▪", colour=BODY_INK, bullet_colour=EMERALD, space_before=8),
    Level(size=13.0, indent_in=0.35, bullet="›", colour=MUTED, bullet_colour=VIOLET, space_before=4),
]

# ── Geometry (13.333 x 7.5 in, generous margins) ─────────────────────────────
MARGIN_X = 0.65
CONTENT_W = SLIDE_W - 2 * MARGIN_X  # 12.033 in

TITLE_BOX = Box(MARGIN_X, 0.42, CONTENT_W, 0.56)
SUB_BOX = Box(MARGIN_X, 1.00, CONTENT_W, 0.36)
FIG_BOX = Box(MARGIN_X, 1.48, CONTENT_W, 5.18)          # exact box for 12.0 x 5.18 in figures
FIG_BOX_CAPTIONED = Box(MARGIN_X, 1.48, CONTENT_W, 4.82)
CAPTION_BOX = Box(MARGIN_X, 6.42, CONTENT_W, 0.35)
FOOTER_LEFT = Box(MARGIN_X, 6.96, 8.5, 0.30)
FOOTER_RIGHT = Box(SLIDE_W - MARGIN_X - 1.5, 6.96, 1.5, 0.30)

FOOTER_TEXT = "Hackathon X-Forum x Stockline  |  J.A.R.V.I.S  |  Alpes Restauration"
TALK_MINUTES = 5
WORDS_PER_MINUTE = 140
