"""Data-driven figures for the Alpes Restauration x Stockline deck.

Every figure is authored at the exact size (in inches) of its target box in theme.py
on the shared PAPER ground (#FAFDFB), so typography projects 1:1 with slide text.
No bbox_inches='tight': figkit.save preserves exact canvas dimensions.
"""

from __future__ import annotations

import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import figkit  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import theme  # noqa: E402

FIGS_DIR = SCRIPTS.parent / "build" / "figs"
figkit.use(
    palette=theme.PALETTE,
    serif=[theme.HEAD_FONT, "DejaVu Sans"],
    geometric=[theme.BODY_FONT, "DejaVu Sans"],
    figs_dir=str(FIGS_DIR),
    dpi=200,
)

# Exact box sizes matching theme.py
W_FULL, H_FULL = 12.0, 4.82
W_SPLIT, H_SPLIT = 7.3, 4.75


def _finish(ax, fig, key: str) -> None:
    fig.patch.set_facecolor(theme.PALETTE["paper"])
    ax.set_facecolor(theme.PALETTE["paper"])
    figkit.save(fig, key)


def fig_architecture() -> None:
    key = "arch_pipeline"
    fig, ax = figkit.canvas(W_FULL, H_FULL)
    # Two horizontal lanes: top = real-time voice loop, bottom = intelligence + ERP safety
    y_top, y_bot = 3.15, 1.15
    h = 1.15

    # Lane labels
    ax.text(0.10, 4.52, "FLUX TEMPS REEL (CHEVAUCHE)", fontsize=10, fontweight="bold", color=theme.PALETTE["violet"])
    ax.text(0.10, 2.52, "DECISION, SECURITE ET METIER (COTE SERVEUR)", fontsize=10, fontweight="bold", color=theme.PALETTE["emerald"])

    top_boxes = [
        (0.15, 2.05, "Micro 100 ms", "MediaRecorder opus\npre-chauffe, anti-clip", "surface", "border"),
        (2.55, 2.25, "Soniox STT flux", "225 ms finalisation\nlexique client en tete", "violet_soft", "violet"),
        (5.15, 2.30, "LLM + Cache 27k", "Claude / Nemotron\nfiller au transcript final", "violet_soft", "violet"),
        (7.80, 2.10, "ElevenLabs TTS", "136 ms 1er octet\ncoupe virgule + phrase", "surface", "border"),
        (10.20, 1.65, "Haut-parleur", "MediaSource\nbarge-in < 100 ms", "emerald_soft", "emerald"),
    ]
    for x, w, title, sub, fill, edge in top_boxes:
        figkit.box(ax, x, y_top, w, h, f"{title}\n{sub}", fill=theme.PALETTE[fill], edge=theme.PALETTE[edge],
                   size=10.5, bold=True, colour=theme.PALETTE["ink"])

    for (x1, w1, *_), (x2, *_) in zip(top_boxes, top_boxes[1:]):
        figkit.arrow(ax, (x1 + w1 + 0.04, y_top + h / 2), (x2 - 0.04, y_top + h / 2), colour=theme.PALETTE["ink"], lw=1.6)

    bot_boxes = [
        (0.15, 2.75, "Identite verifiee", "5 roles (client, supplier,\nmanager, admin) + preload", "emerald_soft", "emerald"),
        (3.20, 2.75, "Resolveur phonetique", "2,5 ms · n-grams FR\napprend si confirme", "emerald_soft", "emerald"),
        (6.25, 2.65, "Jev System One", "Routage, disambig,\nporte confirm is_yes", "amber_soft", "amber"),
        (9.20, 2.65, "Backend ERP SQLite", "Regles metier, warnings\nmemoire de sessions", "surface", "emerald"),
    ]
    for x, w, title, sub, fill, edge in bot_boxes:
        figkit.box(ax, x, y_bot, w, h, f"{title}\n{sub}", fill=theme.PALETTE[fill], edge=theme.PALETTE[edge],
                   size=10.5, bold=True, colour=theme.PALETTE["ink"])

    # Vertical connections from bottom intelligence into top real-time path
    for bx, bw, tx in [(1.52, 0, 3.65), (4.57, 0, 3.85), (7.57, 0, 6.20), (10.52, 0, 6.55)]:
        figkit.arrow(ax, (bx, y_bot + h + 0.04), (tx, y_top - 0.04), colour=theme.PALETTE["emerald"], lw=1.3)

    ax.text(6.0, 0.35, "Cascade chevauchee : chaque brique est interchangeable via .env (Soniox/NVIDIA, Anthropic/OpenAI-compatible).",
            ha="center", va="center", fontsize=10.5, color=theme.PALETTE["muted"], style="italic")
    _finish(ax, fig, key)


def fig_latency() -> None:
    key = "latency_gains"
    fig, ax = figkit.canvas(W_FULL, H_FULL)
    ax.axis("on")

    # Left panel: breakdown of first sound vs real answer; Right panel: live 35 turns + paced STT
    gs = fig.add_gridspec(1, 2, width_ratios=[1.25, 1.0], wspace=0.28, left=0.07, right=0.97, top=0.86, bottom=0.16)
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])

    # Panel 1: Kit baseline -> V0 (filler on tool) -> V0+ (filler at final transcript)
    stages = ["Kit d'origine\n(reponse)", "V0 filler outil\n(1er son)", "V0+ filler precoce\n(1er son)", "V0+ vraie reponse\n(answerMs)"]
    medians = [4.68, 3.34, 1.23, 4.83]
    colors = [theme.PALETTE["muted"], theme.PALETTE["amber"], theme.PALETTE["emerald"], theme.PALETTE["violet"]]
    bars = ax1.barh(stages[::-1], medians[::-1], color=colors[::-1], height=0.52, edgecolor="none")
    ax1.axvline(1.5, color=theme.PALETTE["coral"], linestyle="--", linewidth=1.4)
    ax1.text(1.56, 3.35, "Cible 1,5 s", color=theme.PALETTE["coral"], fontsize=9.5, fontweight="bold")
    for b, val in zip(bars, medians[::-1]):
        ax1.text(val + 0.10, b.get_y() + b.get_height() / 2, f"{val:.2f} s", va="center", fontsize=11,
                 fontweight="bold", color=theme.PALETTE["ink"])
    ax1.set_xlim(0, 6.1)
    ax1.set_xlabel("Secondes depuis audio_end (mediane, audio synthetise)", fontsize=10, color=theme.PALETTE["body"])
    ax1.set_title("1er son : 4,7 s -> 1,2 s (-74 %), filler explicite", fontsize=12, fontweight="bold",
                  color=theme.PALETTE["ink"], loc="left", pad=10)
    ax1.spines[["top", "right"]].set_visible(False)
    ax1.set_facecolor(theme.PALETTE["paper"])

    # Panel 2: STT paced latency vs burst artifact
    cats = ["Soniox rafale\n(ancien banc)", "Whisper NVCF\n(offline)", "Soniox cadence\n(temps reel 100 ms)", "Parakeet NVCF\n(streaming)"]
    p50 = [2.86, 0.22, 0.23, 0.15]
    c2 = [theme.PALETTE["coral"], theme.PALETTE["blue"], theme.PALETTE["emerald"], theme.PALETTE["muted"]]
    b2 = ax2.bar(range(len(cats)), p50, color=c2, width=0.55)
    for rect, val in zip(b2, p50):
        ax2.text(rect.get_x() + rect.get_width() / 2, val + 0.08, f"{int(val*1000)} ms", ha="center",
                 fontsize=10.5, fontweight="bold", color=theme.PALETTE["ink"])
    ax2.set_xticks(range(len(cats)))
    ax2.set_xticklabels(cats, fontsize=9.2, color=theme.PALETTE["body"])
    ax2.set_ylim(0, 3.35)
    ax2.set_ylabel("Mediane fin parole -> final (s)", fontsize=10, color=theme.PALETTE["body"])
    ax2.set_title("Cout reel de finalisation STT (p50, 20 phrases)", fontsize=12, fontweight="bold",
                  color=theme.PALETTE["ink"], loc="left", pad=10)
    ax2.spines[["top", "right"]].set_visible(False)
    ax2.set_facecolor(theme.PALETTE["paper"])

    ax.axis("off")
    fig.patch.set_facecolor(theme.PALETTE["paper"])
    figkit.save(fig, key)


def fig_lexicon() -> None:
    key = "lexicon_recall"
    fig, ax = figkit.canvas(W_FULL, H_FULL)
    ax.axis("off")
    gs = fig.add_gridspec(1, 2, width_ratios=[1.3, 1.0], wspace=0.25, left=0.06, right=0.97, top=0.86, bottom=0.16)
    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])

    engines = ["Soniox\n+ vocab", "Soniox\nsans vocab", "Whisper\nlarge-v3", "Parakeet\n1.1B"]
    raw_pct = [60 / 62 * 100, 54 / 62 * 100, 52 / 62 * 100, 38 / 62 * 100]
    res_pct = [62 / 62 * 100, 61 / 62 * 100, 62 / 62 * 100, 60 / 62 * 100]
    x = list(range(len(engines)))
    w = 0.34
    b1 = ax1.bar([i - w / 2 for i in x], raw_pct, width=w, label="STT brut", color=theme.PALETTE["muted"])
    b2 = ax1.bar([i + w / 2 for i in x], res_pct, width=w, label="+ Resolveur (2,5 ms)", color=theme.PALETTE["emerald"])
    for b, n_ok in zip(b1, [60, 54, 52, 38]):
        ax1.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.2, f"{n_ok}/62", ha="center", fontsize=9.5, color=theme.PALETTE["body"])
    for b, n_ok in zip(b2, [62, 61, 62, 60]):
        ax1.text(b.get_x() + b.get_width() / 2, b.get_height() + 1.2, f"{n_ok}/62", ha="center", fontsize=9.5, fontweight="bold", color=theme.PALETTE["emerald_dark"])
    ax1.set_xticks(x)
    ax1.set_xticklabels(engines, fontsize=10, color=theme.PALETTE["ink"])
    ax1.set_ylim(0, 114)
    ax1.set_ylabel("Rappel des entites metier (%)", fontsize=10, color=theme.PALETTE["body"])
    ax1.set_title("62 entites clients & produits : 0 faux positif (80 transcripts)", fontsize=11.5, fontweight="bold",
                  color=theme.PALETTE["ink"], loc="left", pad=10)
    ax1.legend(frameon=False, loc="lower right", fontsize=9.5)
    ax1.spines[["top", "right"]].set_visible(False)
    ax1.set_facecolor(theme.PALETTE["paper"])

    # Right panel: concrete before -> after examples + learning loop
    ax2.axis("off")
    ax2.set_xlim(0, 10)
    ax2.set_ylim(0, 10)
    ax2.text(0.2, 9.2, "Exemples rattrapes en direct", fontsize=12, fontweight="bold", color=theme.PALETTE["ink"])
    cases = [
        ("\"Refuge Paillet\"", "Le Refuge Payet (score 0,94)", "emerald"),
        ("\"vin blanc a Promont\"", "Vin blanc Apremont (score 0,88)", "emerald"),
        ("\"Liglou\"", "L'Igloo (score 0,90)", "emerald"),
        ("\"ma graie\" / \"Tombe\"", "Magret / Tomme de Savoie", "emerald"),
        ("\"le magnet de Remi\"", "0 proposition (aucun bruit)", "muted"),
    ]
    y = 7.7
    for heard, fixed, col in cases:
        ax2.text(0.2, y, heard, fontsize=10.5, fontweight="bold", color=theme.PALETTE["coral"] if col != "muted" else theme.PALETTE["muted"])
        ax2.text(4.2, y, "->", fontsize=10.5, color=theme.PALETTE["muted"])
        ax2.text(4.8, y, fixed, fontsize=10.5, fontweight="bold", color=theme.PALETTE[col])
        y -= 1.25
    ax2.add_patch(plt.Rectangle((0.2, 0.35), 9.6, 1.55, facecolor=theme.PALETTE["violet_soft"], edgecolor=theme.PALETTE["violet"], linewidth=1.2))
    ax2.text(5.0, 1.12, "Regle d'apprentissage : ecriture en base ONLY si confirme\n(oui explicite, epellation client, ou commande validee)\nPromotion globale apres confirmation par 3 clients.",
             ha="center", va="center", fontsize=9.5, color=theme.PALETTE["ink"])

    fig.patch.set_facecolor(theme.PALETTE["paper"])
    figkit.save(fig, key)


def fig_security_rules() -> None:
    key = "security_and_rules"
    fig, ax = figkit.canvas(W_SPLIT, H_SPLIT)
    ax.axis("off")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)

    # Top: Audit problem vs Code enforcement
    ax.text(0.1, 9.4, "Audit reel : ce qui passait vs ce que le code bloque", fontsize=12, fontweight="bold", color=theme.PALETTE["ink"])
    rows = [
        ("Inconnu demande le top 5 clients", "Retire du prompt public + refuse par code", theme.PALETTE["coral_soft"], theme.PALETTE["emerald_soft"]),
        ("\"Je suis Le Refuge Payet\"", "Identite verifiee + token + portee client", theme.PALETTE["coral_soft"], theme.PALETTE["emerald_soft"]),
        ("200 kg frites le 1er decembre", "Warning season_closed (mi-dec. -> mi-avr.)", theme.PALETTE["amber_soft"], theme.PALETTE["emerald_soft"]),
        ("900 kg (habituel 108 kg)", "Warning unusual_quantity (> 2,5 x p90)", theme.PALETTE["amber_soft"], theme.PALETTE["emerald_soft"]),
        ("Remise orale 1,47 EUR / 60 %", "Bloque + trace 'Declare (non verifie)'", theme.PALETTE["amber_soft"], theme.PALETTE["emerald_soft"]),
    ]
    y = 7.7
    for ask, fix, bg1, bg2 in rows:
        ax.add_patch(plt.Rectangle((0.1, y), 4.4, 1.15, facecolor=bg1, edgecolor=theme.PALETTE["border"], linewidth=0.9))
        ax.text(2.3, y + 0.57, ask, ha="center", va="center", fontsize=9.5, fontweight="bold", color=theme.PALETTE["ink"])
        ax.annotate("", xy=(5.05, y + 0.57), xytext=(4.55, y + 0.57), arrowprops=dict(arrowstyle="->", color=theme.PALETTE["emerald"], lw=1.6))
        ax.add_patch(plt.Rectangle((5.1, y), 4.8, 1.15, facecolor=bg2, edgecolor=theme.PALETTE["emerald"], linewidth=1.0))
        ax.text(7.5, y + 0.57, fix, ha="center", va="center", fontsize=9.5, fontweight="bold", color=theme.PALETTE["ink"])
        y -= 1.45

    ax.text(5.0, 0.38, "Mesure sur 24 141 commandes historiques : 0,01 % de faux positifs saison · 0,001 % sur 166 273 lignes quantite.",
            ha="center", va="center", fontsize=9.8, color=theme.PALETTE["muted"], style="italic")
    _finish(ax, fig, key)


ALL = [fig_architecture, fig_latency, fig_lexicon, fig_security_rules]
