"""Assemble presentation/build/Stockline-Team01-Alpes-Restauration.pptx from slides/*.md and build/figs/*.png."""

from __future__ import annotations

import pathlib
import sys

from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import deckkit as kit  # noqa: E402
import slides as slidesmod  # noqa: E402
import theme  # noqa: E402

ROOT = HERE.parent
FIGS = ROOT / "build" / "figs"
TARGET = ROOT / "build" / "Stockline-Team01-Alpes-Restauration.pptx"


def _chrome_slide(prs, slide: slidesmod.Slide, *, show_footer: bool = True):
    page = prs.slides.add_slide(kit.blank_layout(prs))
    kit.set_background(page, theme.PAPER)
    # Thin emerald top bar (clean architectural signature, zero third-party logo)
    bar = page.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(theme.SLIDE_W), Inches(0.06))
    bar.fill.solid()
    bar.fill.fore_color.rgb = RGBColor.from_string(theme.EMERALD)
    bar.line.fill.background()
    bar.shadow.inherit = False
    if show_footer:
        kit.separator_h(page, y=6.88, left=theme.MARGIN_X, right=theme.SLIDE_W - theme.MARGIN_X, colour=theme.BORDER, width_pt=0.75)
        kit.textbox(page, theme.FOOTER_LEFT, theme.FOOTER_TEXT, theme.FOOTER_STYLE, align=PP_ALIGN.LEFT)
        kit.textbox(page, theme.FOOTER_RIGHT, slide.label, theme.FOOTER_STYLE, align=PP_ALIGN.RIGHT)
    return page


def fill_title(prs, slide: slidesmod.Slide):
    page = _chrome_slide(prs, slide, show_footer=False)
    # Subtle left vertical accent pillar
    pillar = page.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.65), Inches(1.55), Inches(0.09), Inches(3.85))
    pillar.fill.solid()
    pillar.fill.fore_color.rgb = RGBColor.from_string(theme.EMERALD)
    pillar.line.fill.background()
    pillar.shadow.inherit = False

    kicker = slide.meta.get("kicker", "HACKATHON X-FORUM x STOCKLINE  ·  TEAM 01")
    kit.textbox(page, kit.Box(0.95, 1.55, 11.5, 0.35), kicker,
                kit.TextStyle(size=12, colour=theme.EMERALD, bold=True, font=theme.BODY_FONT))
    kit.textbox(page, kit.Box(0.95, 2.02, 11.6, 1.45), slide.head, theme.TITLE_COVER, anchor=MSO_ANCHOR.TOP)
    if slide.sub:
        kit.textbox(page, kit.Box(0.95, 3.55, 11.2, 0.70), slide.sub, theme.SUB_COVER, anchor=MSO_ANCHOR.TOP)

    # KPI pills strip on the cover if figure or columns exist
    if slide.columns:
        n = len(slide.columns)
        gap = 0.25
        card_w = (11.6 - gap * (n - 1)) / n
        for idx, col in enumerate(slide.columns):
            x = 0.95 + idx * (card_w + gap)
            card = page.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(4.55), Inches(card_w), Inches(1.20))
            card.fill.solid()
            card.fill.fore_color.rgb = RGBColor.from_string(theme.SURFACE)
            card.line.color.rgb = RGBColor.from_string(theme.BORDER)
            card.line.width = Pt(1.0)
            card.shadow.inherit = False
            col_c = theme.COLOURS.get(col.colour, theme.EMERALD)
            kit.textbox(page, kit.Box(x + 0.18, 4.68, card_w - 0.36, 0.42), col.name,
                        kit.TextStyle(size=22, colour=col_c, bold=True, font=theme.HEAD_FONT))
            body = col.body or (col.bullets[0].text if col.bullets else "")
            kit.textbox(page, kit.Box(x + 0.18, 5.14, card_w - 0.36, 0.48), body,
                        kit.TextStyle(size=11.5, colour=theme.BODY_INK, font=theme.BODY_FONT))

    meta_line = slide.meta.get("footer", "Alpes Restauration (Grenoble / Oisans / Vercors)  ·  24 novembre 2026")
    kit.textbox(page, kit.Box(0.95, 6.45, 11.6, 0.35), meta_line,
                kit.TextStyle(size=11, colour=theme.MUTED, font=theme.BODY_FONT))
    return page


def fill_figure(prs, slide: slidesmod.Slide):
    page = _chrome_slide(prs, slide)
    kit.textbox(page, theme.TITLE_BOX, slide.head, theme.HEAD_SLIDE)
    if slide.sub:
        kit.textbox(page, theme.SUB_BOX, slide.sub, theme.SUB_SLIDE)
    box = theme.FIG_BOX_CAPTIONED if slide.caption else theme.FIG_BOX
    fig_path = (ROOT / slide.image) if slide.image else (FIGS / f"{slide.figure}.png")
    kit.fit_picture(page, box, fig_path, anchor="top")
    if slide.caption:
        kit.textbox(page, theme.CAPTION_BOX, slide.caption, theme.CAPTION_STYLE)
    return page


def fill_columns(prs, slide: slidesmod.Slide):
    page = _chrome_slide(prs, slide)
    kit.textbox(page, theme.TITLE_BOX, slide.head, theme.HEAD_SLIDE)
    if slide.sub:
        kit.textbox(page, theme.SUB_BOX, slide.sub, theme.SUB_SLIDE)

    outcome = slide.meta.get("outcome", "").strip()
    n = max(1, len(slide.columns))
    gap = 0.30
    col_w = (theme.CONTENT_W - gap * (n - 1)) / n
    top_y = 1.55
    card_h = 4.15 if outcome else 5.00

    for i, col in enumerate(slide.columns):
        x = theme.MARGIN_X + i * (col_w + gap)
        card = page.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(top_y), Inches(col_w), Inches(card_h))
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor.from_string(theme.SURFACE)
        card.line.color.rgb = RGBColor.from_string(theme.BORDER)
        card.line.width = Pt(1.0)
        card.shadow.inherit = False

        c_hex = theme.COLOURS.get(col.colour, theme.EMERALD)
        # Top accent strip flush with crisp rectangle card
        strip = page.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(top_y), Inches(col_w), Inches(0.06))
        strip.fill.solid()
        strip.fill.fore_color.rgb = RGBColor.from_string(c_hex)
        strip.line.fill.background()
        strip.shadow.inherit = False

        kit.textbox(page, kit.Box(x + 0.22, top_y + 0.18, col_w - 0.44, 0.44), col.name,
                    kit.TextStyle(size=16, colour=c_hex, bold=True, font=theme.HEAD_FONT))

        body_box = page.shapes.add_textbox(Inches(x + 0.22), Inches(top_y + 0.72), Inches(col_w - 0.44), Inches(card_h - 0.90))
        if col.bullets:
            kit.set_bullets(body_box, col.bullets, levels=theme.LEVELS, anchor=MSO_ANCHOR.TOP,
                            hang_in=0.28, line_pct=115, accent=c_hex)
        else:
            kit.set_text(body_box, col.body, kit.TextStyle(size=13.5, colour=theme.BODY_INK, font=theme.BODY_FONT),
                         anchor=MSO_ANCHOR.TOP)

    if outcome:
        band = page.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(theme.MARGIN_X), Inches(5.90), Inches(theme.CONTENT_W), Inches(0.76))
        band.fill.solid()
        band.fill.fore_color.rgb = RGBColor.from_string(theme.EMERALD_SOFT)
        band.line.color.rgb = RGBColor.from_string(theme.EMERALD)
        band.line.width = Pt(1.0)
        band.shadow.inherit = False
        kit.textbox(page, kit.Box(theme.MARGIN_X + 0.25, 5.95, theme.CONTENT_W - 0.50, 0.66), outcome,
                    kit.TextStyle(size=15, colour=theme.INK, bold=True, font=theme.HEAD_FONT),
                    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    return page


def fill_split(prs, slide: slidesmod.Slide):
    """Left key bullets / narrative, right figure (exact ratio box)."""
    page = _chrome_slide(prs, slide)
    kit.textbox(page, theme.TITLE_BOX, slide.head, theme.HEAD_SLIDE)
    if slide.sub:
        kit.textbox(page, theme.SUB_BOX, slide.sub, theme.SUB_SLIDE)

    left_w = 4.35
    right_x = theme.MARGIN_X + left_w + 0.35
    right_w = theme.CONTENT_W - left_w - 0.35

    card = page.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(theme.MARGIN_X), Inches(1.52), Inches(left_w), Inches(5.05))
    card.fill.solid()
    card.fill.fore_color.rgb = RGBColor.from_string(theme.SURFACE)
    card.line.color.rgb = RGBColor.from_string(theme.BORDER)
    card.line.width = Pt(1.0)
    card.shadow.inherit = False

    tb = page.shapes.add_textbox(Inches(theme.MARGIN_X + 0.22), Inches(1.70), Inches(left_w - 0.44), Inches(4.70))
    bullets = slide.bullets or (slide.columns[0].bullets if slide.columns else [])
    kit.set_bullets(tb, bullets, levels=theme.LEVELS, anchor=MSO_ANCHOR.MIDDLE, hang_in=0.28, line_pct=115, accent=theme.EMERALD)

    fig_path = (ROOT / slide.image) if slide.image else (FIGS / f"{slide.figure}.png")
    fig_box = kit.Box(right_x, 1.52, right_w, 4.75 if slide.caption else 5.05)
    kit.fit_picture(page, fig_box, fig_path, anchor="top")
    if slide.caption:
        kit.textbox(page, kit.Box(right_x, 6.36, right_w, 0.35), slide.caption, theme.CAPTION_STYLE)
    return page


SPECS = {
    "title": (fill_title, (), None),
    "figure": (fill_figure, ("figure",), 0),
    "columns": (fill_columns, (), None),
    "split": (fill_split, ("figure",), None),
}


def build() -> pathlib.Path:
    prs, _ = kit.open_deck(size_in=(theme.SLIDE_W, theme.SLIDE_H))
    prs.core_properties.title = "Alpes Restauration — Agent vocal ERP"
    prs.core_properties.subject = "Hackathon X-Forum x Stockline (Team 01)"
    prs.core_properties.author = "Team 01 (KpihX)"
    prs.core_properties.last_modified_by = "Team 01"

    all_slides = slidesmod.load()
    for s in all_slides:
        if s.layout not in SPECS:
            raise SystemExit(f"{s.path.name}: unknown layout {s.layout!r}")
        filler = SPECS[s.layout][0]
        page = filler(prs, s)
        if s.notes:
            page.notes_slide.notes_text_frame.text = s.notes

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    tmp = TARGET.with_suffix(".tmp.pptx")
    prs.save(str(tmp))
    tmp.replace(TARGET)
    print(f"[deck] {len(all_slides)} slides -> {TARGET}")
    kit.budget(all_slides, words_per_minute=theme.WORDS_PER_MINUTE, talk_minutes=theme.TALK_MINUTES)
    return TARGET


if __name__ == "__main__":
    build()
