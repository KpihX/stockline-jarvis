"""Plausibility warnings of a sales order (never blocking, same shape as the other order warnings):

- `season_closed`     the delivery date falls outside the client's opening season.
- `unusual_quantity`  a product quantity far above what this client usually orders.

Both are DATA-DRIVEN from facts the ERP already holds, and explainable (the message gives the reason):

  season   1. explicit season written by a human: a client note, `preferences` or a client context row
              saying "ouvert de mi-décembre à mi-avril" / "Fermé en mai-juin et de septembre à mi-décembre"
              (parsed by `parse_season`; the context rows make it editable at runtime, e.g. `save_context`);
           2. else the client's own order history: if no order was ever delivered around the same calendar
              day in the other years (window below), the client is closed then. No verdict (= no warning)
              when the history is too short to tell.
  quantity the client's past quantities for that product (delivered / invoiced orders only: a test or a
           draft never pollutes it); a distinct message when the client never ordered that product, then
           the reference is what all clients order of it.

Pure functions (testable without a database) are at the top, the ERP glue at the bottom.
Measure false positives on the seed history with `apps/backend/tests/measure_plausibility.py`.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from app import crud
from app.core.db import Doc
from app.core.utils import fr_num

# ═════════ Thresholds — the ONE place to tune the two warnings ═════════
# Measured on the seed history (tests/measure_plausibility.py): season by history 3 / 24 141 past orders would warn
# (0.01 %, other years only); quantity 2 / 166 273 lines (0.001 %) with every other order as reference, 0.025 % when
# only earlier orders count (first order of a product: ~1 %). A factor of 2.0 instead of 2.5 gives 0.035 % / 0.12 %;
# 1.5 gives 0.34 %. Recall of a typo-like line: ×10 → 96 % warn, ×4 → 55 %.

# season_closed (history path)
SEASON_MIN_ORDERS = 12  # fewer delivered orders in total → not enough history to claim a season
SEASON_MIN_YEARS = 2  # the same calendar window must be OBSERVED (inside the client's first→last order span) in this many years
SEASON_WINDOW_MIN_DAYS = 7  # half-width of "around the same day"; widened for clients that order rarely…
SEASON_WINDOW_MAX_DAYS = 21  # …but never beyond this
SEASON_GAP_FACTOR = 2.5  # half-width = factor × the client's p90 gap between two orders, clamped to the bounds above

# unusual_quantity
QTY_P90_FACTOR = 2.5  # warn above factor × the client's p90 for that product (or × its max while history is short)
QTY_MIN_HISTORY = 5  # past orders of that product needed to trust the p90; below that the reference is the max
QTY_NEVER_ORDERED_FACTOR = 1.5  # never ordered by this client: warn above factor × p95 of what ALL clients order of it
QTY_PEERS_MIN_LINES = 20  # …and only if at least that many past lines exist across clients for the product
QTY_FLOOR = {"kg": 25.0, "liter": 25.0, "piece": 30.0, "box": 10.0, "dozen": 10.0}  # never warn at or below this
QTY_FLOOR_DEFAULT = 25.0

# ═════════ Pure logic ═════════


def _pctl(sorted_values: list[float], p: float) -> float:
    """Percentile p (0..1) with linear interpolation of an already sorted list."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = p * (len(sorted_values) - 1)
    lo, hi = math.floor(pos), math.ceil(pos)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)


def _same_day(iso: str, year: int) -> date:
    d = date.fromisoformat(iso[:10])
    try:
        return d.replace(year=year)
    except ValueError:  # 29 February
        return d.replace(year=year, day=28)


# ── Quantity ──


@dataclass(frozen=True)
class QtyVerdict:
    never_ordered: bool  # True: reference is what all clients order; False: what this client orders
    typical: float  # client's median (or, never ordered: p95 of all clients)
    limit: float  # the line quantity is above this


def unusual_quantity(qty: float, unit: str, past: list[float], peers: list[float] | None = None) -> QtyVerdict | None:
    """`past`: this client's per-order quantities of the product; `peers`: every client's, for the never-ordered case.
    Returns a verdict when `qty` is far above the usual, else None."""
    floor = QTY_FLOOR.get(unit, QTY_FLOOR_DEFAULT)
    if qty <= floor:
        return None
    if past:
        s = sorted(past)
        base = _pctl(s, 0.9) if len(s) >= QTY_MIN_HISTORY else s[-1]
        limit = max(QTY_P90_FACTOR * base, floor)
        return QtyVerdict(False, _pctl(s, 0.5), limit) if qty > limit else None
    if not peers or len(peers) < QTY_PEERS_MIN_LINES:
        return None
    ref = _pctl(sorted(peers), 0.95)
    limit = max(QTY_NEVER_ORDERED_FACTOR * ref, floor)
    return QtyVerdict(True, ref, limit) if qty > limit else None


# ── Season ──

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
_MONTH_RE = r"(mi-)?(janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|septembre|octobre|novembre|d[ée]cembre)"
_OPEN_RE = re.compile(rf"ouverte?s?\s+((?:de|du|d')\s*{_MONTH_RE}\s+(?:à|au|jusqu'à|jusqu'au)\s+{_MONTH_RE})", re.I)
_CLOSED_RE = re.compile(r"\bferm(?:é|ée|és|ées)\s+([^.;\n]+)", re.I)
_PART_RE = re.compile(rf"^(?:en\s+|de\s+|du\s+|d')?\s*{_MONTH_RE}(?:\s*(?:-|à|au)\s*{_MONTH_RE})?$", re.I)

MonthDay = tuple[int, int]
Range = tuple[MonthDay, MonthDay]  # inclusive, may wrap over the new year


def _month_no(name: str) -> int:
    n = name.lower().replace("é", "e").replace("û", "u")
    return [m.replace("é", "e").replace("û", "u") for m in MONTHS].index(n) + 1


def _in(r: Range, md: MonthDay) -> bool:
    (s, e) = r
    return s <= md <= e if s <= e else md >= s or md <= e


@dataclass(frozen=True)
class Season:
    """Explicit opening season. `open` ranges: the client orders only inside them; `closed` ranges: it never does.
    Boundaries are tolerant (the 15th of a "mi-X" is never flagged), `phrase` is the human wording for the message."""

    open: tuple[Range, ...] = ()
    closed: tuple[Range, ...] = ()
    phrase: str = ""

    def is_closed_on(self, iso: str) -> bool:
        d = date.fromisoformat(iso[:10])
        md = (d.month, d.day)
        return any(_in(r, md) for r in self.closed) or (bool(self.open) and not any(_in(r, md) for r in self.open))


def parse_season(texts: Iterable[str]) -> Season | None:
    """Look for "ouvert de mi-décembre à mi-avril" and "Fermé en mai-juin et de septembre à mi-décembre" in free text."""
    opens: list[Range] = []
    closeds: list[Range] = []
    phrases: list[str] = []

    def rng(mi1: str | None, m1: str, mi2: str | None, m2: str, closed: bool) -> Range:
        # Open: "mi-X" boundaries are included. Closed: they are excluded (benefit of the doubt).
        d1 = (16 if closed else 15) if mi1 else 1
        d2 = (14 if closed else 15) if mi2 else 31
        return (_month_no(m1), d1), (_month_no(m2), d2)

    for text in texts:
        for m in _OPEN_RE.finditer(text):
            g = m.groups()  # phrase, mi1, m1, mi2, m2
            r = rng(g[1], g[2], g[3], g[4], closed=False)
            if r not in opens:
                opens.append(r)
                phrases.append(f"ouvert {g[0].lower()} seulement")
        for m in _CLOSED_RE.finditer(text):
            found: list[Range] = []
            for part in re.split(r"\s+et\s+|,", m.group(1).strip()):
                pm = _PART_RE.match(part.strip())
                if not pm:
                    continue
                mi1, m1, mi2, m2 = pm.groups()
                found.append(rng(mi1, m1, mi2, m2, closed=True) if m2 else rng(None, m1, None, m1, closed=True))
            new = [r for r in found if r not in closeds]
            if new:
                closeds.extend(new)
                phrases.append(f"fermé {m.group(1).strip().lower()}")
    if not opens and not closeds:
        return None
    return Season(tuple(opens), tuple(closeds), " ; ".join(phrases))


@dataclass(frozen=True)
class SeasonVerdict:
    source: str  # "fiche" (explicit text) | "historique" (orders)
    phrase: str = ""  # fiche: the wording
    years: tuple[int, ...] = ()  # historique: years observed WITHOUT an order that day · fiche: years WITH one (contradiction)


def _windows(target: str, dates: list[str]) -> tuple[list[int], list[int]] | None:
    """Around the calendar day of `target`, in each year of the client's history: (years with an order, years observed
    without any). A year whose window sticks out of the first→last order span tells nothing and is skipped.
    None when the history is too short."""
    if len(dates) < SEASON_MIN_ORDERS:
        return None
    first, last = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    ordinals = sorted({date.fromisoformat(d).toordinal() for d in dates})
    gaps = sorted(b - a for a, b in zip(ordinals, ordinals[1:]))
    half = min(SEASON_WINDOW_MAX_DAYS, max(SEASON_WINDOW_MIN_DAYS, math.ceil(SEASON_GAP_FACTOR * _pctl(gaps, 0.9))))
    ordered: list[int] = []
    empty: list[int] = []
    for year in range(first.year, last.year + 1):
        lo = _same_day(target, year).toordinal() - half
        hi = lo + 2 * half
        if any(lo <= o <= hi for o in ordinals):
            ordered.append(year)
        elif lo >= first.toordinal() and hi <= last.toordinal():
            empty.append(year)
    return ordered, empty


def season_closed(target: str, dates: list[str], explicit: Season | None) -> SeasonVerdict | None:
    """Is a delivery on `target` outside the client's season? `dates`: the client's past delivery dates, sorted.
    An explicit season wins over the history (the history then only adds the years where the client ordered
    that day anyway, so the reader sees the contradiction). None = open, or not enough evidence to say."""
    w = _windows(target, dates)
    if explicit:
        return SeasonVerdict("fiche", phrase=explicit.phrase, years=tuple(w[0]) if w else ()) if explicit.is_closed_on(target) else None
    if not w or w[0]:
        return None  # too short a history, or the client did order around that day in some year: open
    return SeasonVerdict("historique", years=tuple(w[1])) if len(w[1]) >= SEASON_MIN_YEARS else None


# ── Messages (French, short, speakable, no ids) ──


def _spoken_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{'1er' if d.day == 1 else d.day} {MONTHS[d.month - 1]}"


def _years(ys: tuple[int, ...]) -> str:
    s = [str(y) for y in ys]
    return s[0] if len(s) == 1 else ", ".join(s[:-1]) + " et " + s[-1]


def season_message(client_name: str, delivery_date: str, v: SeasonVerdict) -> str:
    if v.source == "fiche":
        also = f" (il a pourtant commandé à cette période en {_years(v.years)})" if v.years else ""
        return f"Livraison le {_spoken_date(delivery_date)} : {client_name} est {v.phrase}{also}"
    return f"Livraison le {_spoken_date(delivery_date)} : {client_name} semble fermé à cette période, aucune commande à cette date en {_years(v.years)}"


_UNIT_FR = {"kg": ("kg", "kg"), "piece": ("pièce", "pièces"), "box": ("colis", "colis"), "liter": ("litre", "litres"), "dozen": ("douzaine", "douzaines")}


def _qty_text(qty: float, unit: str) -> str:
    one, many = _UNIT_FR.get(unit, (unit, unit))
    return f"{fr_num(qty)} {one if abs(qty) <= 1 else many}"


def _spoken_name(name: str) -> str:
    """Drop the packaging in parentheses: "Frites surgelées 9 mm (carton 4 × 2,5 kg)" → "Frites surgelées 9 mm"."""
    return re.sub(r"\s*\([^)]*\)", "", name).strip()


def quantity_message(product_name: str, unit: str, qty: float, v: QtyVerdict) -> str:
    name = _spoken_name(product_name)
    if v.never_ordered:
        return (f"{name} : le client n'en a jamais commandé et la ligne en fait {_qty_text(qty, unit)}, "
                f"alors que la plupart des clients en prennent moins de {fr_num(round(v.typical, -1) if v.typical >= 50 else round(v.typical))}")  # fmt: skip
    return f"{name} : le client en commande en général {_qty_text(round(v.typical, 1), unit)}, la ligne en fait {fr_num(qty)}"


# ═════════ ERP glue ═════════


HISTORY_STATUSES = ("delivered", "invoiced")  # what counts as "the client really ordered this"


@dataclass
class History:
    dates: dict[str, list[str]]  # client → sorted delivery dates of its delivered / invoiced orders
    qty: dict[tuple[str, str], list[float]]  # (client, product) → quantity per order
    peers: dict[str, list[float]]  # product → quantity per order, every client


def build_history(orders: Iterable[Doc]) -> History:
    """Index the delivered / invoiced orders (drafts, confirmed, cancelled never count)."""
    dates: dict[str, list[str]] = defaultdict(list)
    qty: dict[tuple[str, str], list[float]] = defaultdict(list)
    for o in orders:
        if o["status"] not in HISTORY_STATUSES:
            continue
        dates[o["clientId"]].append(o["deliveryDate"])
        per_product: dict[str, float] = defaultdict(float)
        for l in o["lines"]:
            per_product[l["productId"]] += l["qty"]
        for pid, q in per_product.items():
            qty[(o["clientId"], pid)].append(q)
    peers: dict[str, list[float]] = defaultdict(list)
    for (_, pid), qs in qty.items():
        peers[pid].extend(qs)
    return History({c: sorted(d) for c, d in dates.items()}, dict(qty), dict(peers))


_cache: dict = {}


def history() -> History:
    """Rebuilt (~100 ms) only when the set of delivered / invoiced orders changes, NOT on every write: an order
    read after each line edit would otherwise pay it each time (voice latency). Those orders never mutate."""
    n = sum(1 for o in crud.orders.rows.values() if o["status"] in HISTORY_STATUSES)  # ~2 ms
    if _cache.get("n") != n:
        _cache.update(n=n, h=build_history(crud.orders.rows.values()))
    return _cache["h"]


def explicit_season(client: Doc) -> Season | None:
    """Season written in the client's preferences, notes or context rows."""
    texts = [client.get("preferences") or "", *(n["text"] for n in client.get("notes") or [])]
    texts += [e["body"] for e in crud.context_entries.rows.values() if e.get("entityType") == "client" and e.get("entityId") == client["id"]]
    return parse_season(texts)


def plausibility_warnings(order: Doc, client: Doc) -> list[Doc]:
    h = history()
    warnings: list[Doc] = []
    verdict = season_closed(order["deliveryDate"], h.dates.get(client["id"], []), explicit_season(client))
    if verdict:
        warnings.append({"code": "season_closed", "message": season_message(client["name"], order["deliveryDate"], verdict)})
    demand: dict[str, float] = defaultdict(float)
    for l in order["lines"]:
        demand[l["productId"]] += l["qty"]
    for pid, qty in demand.items():
        p = crud.products.get(pid)
        if not p:
            continue
        v = unusual_quantity(qty, p["unit"], h.qty.get((client["id"], pid), []), h.peers.get(pid))
        if v:
            warnings.append({"code": "unusual_quantity", "productId": pid, "message": quantity_message(p["name"], p["unit"], qty, v)})
    return warnings
