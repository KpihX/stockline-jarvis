"""
Deterministic mention resolver: transcript → candidate entities from the lexicon. Pure Python, no I/O, a few ms.

    mentions = resolve("Ici le refuge Paillet, du vin blanc à Promont", [catalogue_index, client_index])
    mentions[0]  → Mention("refuge Paillet", status="resolved", best=Le Refuge Payet (client cli_0006), score 0.93, margin 0.4)
    mentions[1]  → Mention("à Promont",      status="resolved", best=Apremont (product prd_0090))

It NEVER rewrites the transcript: it returns candidates with a score and a margin; the caller (voice session, tool)
decides. Statuses:
    exact      the words are exactly a known form (a name, an alias, a learned form)
    resolved   a near-miss with ONE clearly best entity (score >= ACCEPT, margin >= MIN_MARGIN): propose it, confirm it
    ambiguous  plausible but close or weak: ask the caller (and offer to spell), do not guess

How: every 1..5-word span of the transcript is compared with the lexicon's forms. Exact spelling is a dict lookup;
near-misses go through a bigram index on the phonetic keys (lexicon/phonetic.py) to shortlist forms, then a weighted
edit distance. Client entries and the products a client usually orders get a small prior.
"""

import re
from collections import Counter
from dataclasses import dataclass, field

from . import config as cfg
from .phonetic import folded_ratio, key, phonetic_similarity, squash, words

# ── what a lexicon is made of ──


@dataclass(frozen=True)
class Entry:
    """One way of saying something: `form` designates the entity (etype, eid)."""

    form: str
    etype: str  # client | product | contact | place | jargon
    eid: str | None  # cli_…, prd_… ; None for jargon / places
    label: str  # the canonical name to repeat to the caller
    source: str = "catalogue"  # catalogue | alias | jargon | sheet | learned
    scope: str = "global"  # "global" or a client id (entries of that client only)
    confidence: float = 1.0  # learned entries: how sure we are
    row_id: str | None = None  # context-table row of a learned entry (to forget it)

    @property
    def entity(self) -> tuple[str, str]:
        return (self.etype, self.eid or self.label)


@dataclass(frozen=True)
class Usual:
    """A product the client usually orders (client sheet): used as a prior and shown as 'd'habitude 10 kg'."""

    product_id: str
    label: str
    unit: str | None = None
    avg_qty: float | None = None
    frequency: float | None = None


@dataclass(frozen=True)
class Candidate:
    entry: Entry
    score: float
    exact: bool = False


@dataclass
class Mention:
    surface: str  # the words as transcribed
    start: int  # token indexes [start, end)
    end: int
    status: str  # exact | resolved | ambiguous
    candidates: list[Candidate] = field(default_factory=list)  # best first, one per entity
    margin: float = 1.0  # best score minus second best (1.0 when alone)
    decided_by: str | None = None  # "jev" when the decision model settled an ambiguity

    @property
    def best(self) -> Candidate:
        return self.candidates[0]


# ── words that are never worth a fuzzy match ──

STOP = frozenset(
    "le la les l un une des du de d au aux a à et ou en pour sur sous avec sans chez par dans ce cet cette ces mon ma mes ton ta tes son sa ses "
    "notre nos votre vos leur leurs je j tu il elle on nous vous ils elles me m te t se s moi toi lui y qui que qu quoi dont où ne n pas plus "
    "si ça ca c est es suis sont etait ete fait fais faire avoir ai as avez avons ont aurait voudrais voudrait veux veut peux peut pouvez "
    "mets mettez mettre met rajoute rajouter ajoute ajouter ajoutez donne donnez prends prenez bon bien tres trop aussi encore deja "
    "oui non ok merci svp plait bonjour salut allo bonsoir ici voila alors donc mais ou ni car comme finalement faut faudrait besoin il y".split()
)
COMMON = frozenset(
    "kilo kilos kg gramme grammes litre litres piece pieces carton cartons caisse caisses colis plateau plateaux seau seaux bidon bidons "
    "sachet sachets barquette barquettes boite boites sac sacs pot pots botte bottes douzaine douzaines paquet paquets unite unites "
    "commande commandes livraison livrer livre demain aujourd hui lundi mardi mercredi jeudi vendredi samedi dimanche semaine matin soir "
    "prix stock produit produits client clients facture factures appareil appel numero fois chose choses autre autres meme "
    "petit petite petits grand grande gros grosse bon bonne frais fraiche fraiches surgele surgeles surgelee surgelees "
    "cuisine restaurant hotel brasserie pizzeria resident residence village vacances chalet maison cantine traiteur "
    "un deux trois quatre cinq six sept huit neuf dix onze douze treize quinze vingt trente quarante cinquante cent mille pourcent pour cent "
    "habitude habitudes annulez annule annuler derniere dernier ancien nouvelle nouveau prochaine prochain disponible dispo vendre vendez "
    "vous avez avoir voulez voudrez voulais comme dit dire dites parle parler passer passe passez envoyer envoyez bien tout toute tous toutes".split()
)

MAX_SPAN_WORDS = 5
_TOKEN = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿŒœ]+")


@dataclass(frozen=True)
class Token:
    folded: str  # "kevin"
    raw: str  # "Kévin": accents are read by the phonetic key
    start: int  # char offsets in the original text, so a span can be shown as said
    end: int
    seg: int  # clause number: a span never crosses a comma, full stop, "?" …


def tokenize(text: str) -> list[Token]:
    out: list[Token] = []
    seg, prev_end = 0, 0
    for m in _TOKEN.finditer(text):
        folded = "".join(words(m.group()))
        if not folded:
            continue
        if out and re.search(r"[,.;:!?…()]", text[prev_end : m.start()]):
            seg += 1
        out.append(Token(folded, m.group(), m.start(), m.end(), seg))
        prev_end = m.end()
    return out


# ── the index ──


def _bigrams(k: str) -> set[str]:
    return {k[i : i + 2] for i in range(len(k) - 1)} or {k}


class Index:
    """A set of entries searchable by exact folded spelling and by approximate phonetics."""

    def __init__(self, entries: list[Entry] | tuple[Entry, ...] = ()):
        self.entries = list(entries)
        self.norms = [squash(words(e.form)) for e in self.entries]
        self.keys = [key(e.form) for e in self.entries]
        self.exact: dict[str, list[int]] = {}
        self.grams: dict[str, list[int]] = {}
        self.max_words = 1
        for i, (n, k) in enumerate(zip(self.norms, self.keys)):
            if not n:
                continue
            self.exact.setdefault(n, []).append(i)
            self.max_words = max(self.max_words, len(words(self.entries[i].form)))
            if len(k) >= 3:
                for g in _bigrams(k):
                    self.grams.setdefault(g, []).append(i)

    def __len__(self) -> int:
        return len(self.entries)

    def exact_hits(self, norm: str) -> list[Entry]:
        return [self.entries[i] for i in self.exact.get(norm, ())]

    def near(self, norm: str, k: str, floor: float) -> list[tuple[Entry, float]]:
        """Entries whose form sounds like (norm, k), with their score (>= floor, below 1.0: exact spellings excluded)."""
        grams = _bigrams(k)
        hits = Counter(i for g in grams for i in self.grams.get(g, ()))
        need = max(1, -(-len(grams) * 3 // 5))  # shortlist: at least 60 % of the span's sound pairs are in the form
        phon_floor = max(0.0, (floor - 0.25) / 0.75)  # the spelling part adds at most 0.25
        out = []
        for i, n in hits.items():
            if n < need or self.norms[i] == norm or self.entries[i].source == "jargon":  # jargon is protected, never a correction target
                continue
            kf = self.keys[i]
            if abs(len(kf) - len(k)) > max(2, int(0.4 * max(len(kf), len(k)))):
                continue
            p = phonetic_similarity(k, kf, phon_floor)
            if p < phon_floor:
                continue
            s = min(0.95, 0.75 * p + 0.25 * folded_ratio(norm, self.norms[i]))
            if s >= floor:
                out.append((self.entries[i], s))
        return out


# ── resolving ──


def resolve(
    text: str,
    indexes: list[Index],
    *,
    usual: dict[str, Usual] | None = None,
    scope: str | None = None,
) -> list[Mention]:
    """Mentions found in `text`, left to right, non-overlapping. `usual`: the caller's habitual products (prior).
    Entries whose scope is another client are ignored."""
    toks = tokenize(text)
    if not toks or not any(len(ix) for ix in indexes):
        return []
    max_n = min(MAX_SPAN_WORDS, max(ix.max_words for ix in indexes))
    usual = usual or {}
    found: list[Mention] = []
    for i in range(len(toks)):
        for n in range(1, min(max_n, len(toks) - i) + 1):
            span = toks[i : i + n]
            if span[0].seg != span[-1].seg:
                break  # longer spans cross the same clause break
            sw = [t.folded for t in span]
            if any(w.isdigit() for w in sw) or all(w in STOP for w in sw):
                continue
            m = _span_mention(sw, " ".join(t.raw for t in span), indexes, usual, scope)
            if m:
                m.start, m.end = i, i + n
                m.surface = text[span[0].start : span[-1].end]
                found.append(m)
    return _non_overlapping(found)


def _span_mention(sw: list[str], raw: str, indexes: list[Index], usual: dict[str, Usual], scope: str | None) -> Mention | None:
    norm = squash(sw)
    n = len(sw)
    best: dict[tuple[str, str], Candidate] = {}

    def offer(entry: Entry, score: float, exact: bool) -> None:
        if entry.scope not in ("global", scope):
            return
        if not exact:
            if entry.scope != "global":
                score += cfg.CLIENT_BONUS
            if entry.etype == "product" and entry.eid in usual:
                score += cfg.USUAL_BONUS
            score = min(score, 0.98)
        cur = best.get(entry.entity)
        if cur is None or score > cur.score:
            best[entry.entity] = Candidate(entry, score, exact)

    for ix in indexes:
        for e in ix.exact_hits(norm):
            offer(e, 1.0, True)
    k = key(raw)
    # a mention does not end on a function word; 3-sound words ("diots") are matched only alone and more strictly
    fuzzy_ok = len(k) >= (3 if n == 1 else 4) and sw[-1] not in STOP and not (n == 1 and sw[0] in COMMON)
    if fuzzy_ok:
        edge_penalty = 0.02 * ((sw[0] in STOP) + (sw[-1] in STOP))
        for ix in indexes:
            for e, s in ix.near(norm, k, cfg.AMBIGUOUS_SCORE):
                offer(e, s - edge_penalty, False)
    if not best:
        return None
    cands = sorted(best.values(), key=lambda c: (-c.score, c.entry.label))
    top = cands[0]
    margin = top.score - cands[1].score if len(cands) > 1 else 1.0
    if top.exact:
        exact_n = sum(1 for c in cands if c.exact)
        if exact_n > 1:  # several entities answer to the same words: the agent has to ask which
            return Mention("", 0, 0, "ambiguous", [c for c in cands if c.exact][:4], 0.0)
        return Mention("", 0, 0, "exact", cands[:1], margin)
    accept = cfg.ACCEPT_SCORE if n > 1 else cfg.SHORT_WORD_ACCEPT if len(k) <= 3 else cfg.SINGLE_WORD_ACCEPT
    if top.score >= accept and margin >= cfg.MIN_MARGIN:
        return Mention("", 0, 0, "resolved", cands[:3], margin)
    floor = cfg.AMBIGUOUS_SCORE if n > 1 else cfg.SHORT_WORD_ACCEPT if len(k) <= 3 else cfg.SINGLE_AMBIGUOUS_SCORE
    if top.score >= floor:
        close = [c for c in cands if top.score - c.score <= 0.12 and c.score >= floor]
        return Mention("", 0, 0, "ambiguous", close[:4], margin)
    return None


def _non_overlapping(found: list[Mention]) -> list[Mention]:
    """Greedy, no overlap. Exact spellings first (what was heard right is not corrected), then the rest by score, then the longer span.
    One exception: a lone generic word heard exactly ("fondue") does not hide a longer near-miss around it that names ANOTHER
    entity ("La Fondue de Taillefère" = a client); a near-miss of the same entity ("du paleron") never overrides it."""
    singles = [m for m in found if m.status == "exact" and m.end - m.start == 1]

    def overrides(m: Mention) -> bool:
        if m.status != "resolved" or m.end - m.start < 2:
            return False
        inside = [e for e in singles if m.start <= e.start < m.end]
        return bool(inside) and all(e.best.entry.entity != m.best.entry.entity for e in inside)

    def rank(m: Mention) -> tuple:
        first = m.status == "exact" and m.end - m.start > 1
        return (0 if first else 1 if overrides(m) else 2, m.status != "exact", -m.best.score, -(m.end - m.start), m.start)

    order = sorted(found, key=rank)
    taken: list[Mention] = []
    used: set[int] = set()
    for m in order:
        span = set(range(m.start, m.end))
        if used & span:
            continue
        taken.append(m)
        used |= span
    return sorted(taken, key=lambda m: m.start)


# ── what the LLM reads ──


def describe(c: Candidate) -> str:
    e = c.entry
    kind = {"client": "client", "product": "produit", "contact": "contact", "place": "lieu", "jargon": "terme"}.get(e.etype, e.etype)
    return f"{e.label} ({kind}{f' {e.eid}' if e.eid else ''})"


def format_hints(mentions: list[Mention], usual: dict[str, Usual] | None = None) -> str:
    """Short French block appended at the END of the user turn (the cached prefix stays untouched).
    Only what is worth the agent's attention: near-misses, ambiguities, and clients heard exactly (their id saves a search)."""
    usual = usual or {}
    lines = []
    for m in mentions:
        c = m.best
        if m.status == "exact" or (m.status == "ambiguous" and all(x.exact for x in m.candidates)):
            if m.status == "exact" and (c.entry.etype == "client" or c.entry.source == "learned"):
                lines.append(f"- « {m.surface} » = {describe(c)}.")
            elif m.status == "ambiguous" and all(x.entry.etype == "client" for x in m.candidates):
                lines.append(f"- « {m.surface} » : plusieurs clients portent ce nom ({' ou '.join(describe(x) for x in m.candidates[:3])}) : demande lequel.")
        elif m.status == "resolved":
            lines.append(f"- « {m.surface} » ressemble à {describe(c)} (proche, score {c.score:.2f}): répète ce nom à l'appelant pour confirmer{extra_usual(c, usual)}.")
        elif m.status == "ambiguous":
            options = " ou ".join(describe(x) for x in m.candidates[:3])
            what = f"hésitation entre {options}" if len(m.candidates) > 1 else f"ressemble vaguement à {options}, pas assez pour trancher"
            lines.append(f"- « {m.surface} » : {what}. Demande de préciser ou d'épeler : ne devine pas.")
    if not lines:
        return ""
    return "[Lexique : aide à l'écoute, ce n'est pas ce que l'appelant a dit]\n" + "\n".join(lines)


def extra_usual(c: Candidate, usual: dict[str, Usual]) -> str:
    u = usual.get(c.entry.eid or "")
    if not u or u.avg_qty is None:
        return ""
    return f"; commande habituelle ≈ {u.avg_qty:g} {u.unit or ''}".rstrip()


__all__ = ["Candidate", "Entry", "Index", "Mention", "Usual", "describe", "format_hints", "resolve", "tokenize"]
