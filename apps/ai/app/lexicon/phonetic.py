"""
Light French phonetics, pure Python, a few microseconds per word. No dependency.

    fold("Hôtel Le Sérac Bleu")  → "hotel le serac bleu"      accents, œ, ’ and case removed
    words("L'Igloo")             → ["l", "igloo"]
    key("Paillet") == key("Payet") == "pAjE"                   sound-alike words share a key
    similarity("tombe de savoie", "tomme de savoie")           0..1, 1.0 only for the same spelling

The key is a rough phonetic transcription (vowels UPPERCASE, nasals 1 2 3, consonants lowercase), NOT a dictionary
pronunciation: enough to see that "Paillet" ≈ "Payet", "ma graie" ≈ "magret", "Liglou" ≈ "L'Igloo".
Comparison = weighted Levenshtein on keys (a missing vowel or a vowel for another vowel is cheap, a different
consonant costs 1, voiced/unvoiced pairs b/p d/t g/k v/f cost less) blended with the plain spelling similarity.
"""

import re
import unicodedata
from functools import lru_cache

_ACCENT_E = str.maketrans({"é": "E", "è": "E", "ê": "E", "ë": "E"})  # kept apart: an accented e is never mute


def fold(s: str) -> str:
    """Lower case, no accents, œ→oe, ’→'. Keeps letters, digits and spaces/apostrophes for `words`."""
    s = s.lower().replace("œ", "oe").replace("æ", "ae").replace("’", "'").replace("ç", "ss")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def words(s: str) -> list[str]:
    """Folded alphanumeric tokens: "Saint-Marcellin d'Isère" → ["saint", "marcellin", "d", "isere"]."""
    return re.findall(r"[a-z0-9]+", fold(s))


# Ordered rewrite rules, applied on the folded word (accented é/è/ê already marked as "E").
_RULES: list[tuple[str, str]] = [
    (r"eau", "O"), (r"au", "O"), (r"oeu", "E"), (r"eu", "E"),
    (r"ou", "U"), (r"oi", "WA"), (r"oy(?=[aeiou])", "WAj"),
    (r"(?:a|ai)ill", "Aj"), (r"(?:e|ei)ill", "Ej"),
    (r"(?<=[aeiouyEU])ill", "j"), (r"(?<=[aeiouyEU])y(?=[aeiouE])", "j"),
    (r"ph", "f"), (r"gn", "N"), (r"sch", "S"), (r"ch", "S"),
    (r"qu", "k"), (r"cq", "k"), (r"ck", "k"), (r"kh", "k"),
    (r"gu(?=[eiy])", "g"), (r"g(?=[eiy])", "J"), (r"j", "J"), (r"c(?=[eiy])", "s"), (r"c", "k"),
    (r"x", "ks"), (r"w", "v"), (r"h", ""),
    (r"(?:ain|aim|ein|eim|yn|ym)(?![aeiouynm])", "1"), (r"ien(?![aeiouynm])", "j1"),
    (r"(?:in|im|un|um)(?![aeiouynm])", "1"),
    (r"(?:an|am|en|em)(?![aeiouynm])", "2"), (r"(?:on|om)(?![aeiouynm])", "3"),
    (r"ai", "E"), (r"ei", "E"), (r"oo", "O"), (r"ee", "E"),
    (r"y(?=[aeiouEU])", "j"), (r"y", "I"),
    (r"(?<=[aeiouEUAIOY])s(?=[aeiouEUAIOY])", "z"),
    (r"z", "s"),
]
_COMPILED = [(re.compile(p), r) for p, r in _RULES]


@lru_cache(maxsize=20000)
def word_key(word: str) -> str:
    """Phonetic key of one word ("payet" → "pAjE")."""
    w = "".join(c if c == "E" else fold(c) for c in word.lower().translate(_ACCENT_E))  # É è ê → "E" (kept), other accents folded
    w = re.sub(r"[^a-zE0-9]", "", w)
    # endings that sound like a closing "é" ("-et" Payet/magret, "-er", "-ez", "-aie")
    if len(w) > 3:
        w = re.sub(r"(?:ets?|ers?|ez|aie)$", "E", w)
    while len(w) > 3 and w[-1] in "sxz":  # plural marks are silent
        w = w[:-1]
    for pattern, repl in _COMPILED:
        w = pattern.sub(repl, w)
    # silent final t/d/p and mute e (after the rules, which still need to see the final "e": "refuge" → g = ʒ)
    for _ in range(3):
        if len(w) > 3 and w[-1] in "tdp":
            w = w[:-1]
        elif len(w) > 3 and w[-1] == "e" and w[-2] not in "aeiouyEUAIO":
            w = w[:-1]
        else:
            break
    w = re.sub(r"(.)\1+", r"\1", w)  # double letters
    return "".join(_VOWEL_KEY.get(c, c) for c in w)


def squash(tokens: list[str]) -> str:
    """The folded tokens glued together, plural marks dropped ("reblochons fermiers" == "reblochon fermier"): the exact-spelling identity."""
    return "".join(t[:-1] if len(t) > 3 and t[-1] in "sx" else t for t in tokens)


def key(text: str) -> str:
    """Phonetic key of a phrase, spaces removed ("Le Refuge Payet" → "lErEfYJpAJE"). Accents are read here (a final é is never mute)."""
    return "".join(word_key(w) for w in re.findall(r"[^\W_]+", text.lower()))


_VOWEL_KEY = {"a": "A", "e": "E", "i": "I", "o": "O", "u": "Y", "y": "I"}  # what is left of the plain vowels after the rules
_VOWELS = set("AEIOUY123")
_CLOSE = {frozenset(p) for p in ("OU", "EI", "AE", "EY", "IY", "OY", "bp", "dt", "gk", "vf", "JS", "mn", "12", "13", "23")}  # similar sounds


@lru_cache(maxsize=None)
def _sub(a: str, b: str) -> float:
    if a == b:
        return 0.0
    if frozenset((a, b)) in _CLOSE:
        return 0.4
    if a in _VOWELS and b in _VOWELS:
        return 0.55
    return 1.0


@lru_cache(maxsize=None)
def _ins(c: str) -> float:
    return 0.6 if c in _VOWELS else 1.0


def distance(a: str, b: str, limit: float = float("inf")) -> float:
    """Weighted Levenshtein between two phonetic keys. Gives up (returns > limit) as soon as every path costs more than `limit`."""
    if a == b:
        return 0.0
    prev = [0.0]
    for cb in b:
        prev.append(prev[-1] + _ins(cb))
    for ca in a:
        ia = _ins(ca)
        cur = [prev[0] + ia]
        for j, cb in enumerate(b):
            cur.append(min(prev[j + 1] + ia, cur[j] + _ins(cb), prev[j] + _sub(ca, cb)))
        if min(cur) > limit:
            return limit + 1.0
        prev = cur
    return prev[-1]


def phonetic_similarity(ka: str, kb: str, floor: float = 0.0) -> float:
    """1.0 = same sound; 0.0 = nothing in common (keys, not words). Below `floor` the exact value is not computed (returns 0)."""
    n = max(len(ka), len(kb))
    if n == 0:
        return 1.0
    d = distance(ka, kb, (1.0 - floor) * n)
    return max(0.0, 1.0 - d / n)


def spelling_similarity(a: str, b: str) -> float:
    """Plain Levenshtein ratio on folded, space-less text."""
    return folded_ratio("".join(words(a)), "".join(words(b)))


def folded_ratio(a: str, b: str) -> float:
    """Levenshtein ratio of two strings that are already folded (the resolver's hot path: no re-folding)."""
    n = max(len(a), len(b))
    if n == 0:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1.0 - prev[-1] / n


def similarity(a: str, b: str) -> float:
    """How alike two phrases sound AND look, 0..1. 1.0 only when their folded spellings are identical;
    two different spellings with the same sound ("Paillet" / "Payet") stay below 0.95."""
    if squash(words(a)) == squash(words(b)):
        return 1.0
    sound = phonetic_similarity(key(a), key(b))
    return min(0.95, 0.75 * sound + 0.25 * spelling_similarity(a, b))
