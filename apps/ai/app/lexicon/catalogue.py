"""
Seeding the lexicon from the ERP (pure functions: the ERP calls are in store.py).

    global lexicon   client names, product names + the aliases people say, CHR / Savoie jargon
    client lexicon   what THIS caller says: their contacts' names, delivery place names, the products they usually
                     order (with their usual quantity and unit), plus what the agent learned for them (learned.py)
"""

import re
from dataclasses import dataclass, field

from . import config as cfg
from .learned import Learned
from .phonetic import words
from .resolver import Entry, Index, Usual

# CHR / Savoie words people say; sent to the STT, and protected from "corrections". Only those not already a product alias.
JARGON = (
    "comme d'hab", "d'hab", "comme d'habitude", "la même chose", "pareil que d'habitude", "meule", "colis", "carton", "caisse",
    "plateau", "seau", "barquette", "bidon", "pastille verte", "tartiflette", "pierrade", "raclette", "diots", "crozets",
    "farçon", "pormonier", "matafan", "gratin dauphinois", "ravioles du Royans", "noix de Grenoble", "DLC", "label rouge", "AOP", "IGP",
    "précuit", "surgelé", "sous vide", "demi-gros", "chez", "livraison tournée",
)  # fmt: skip

_ARTICLE = re.compile(r"^(?:le|la|les|l')\s*", re.IGNORECASE)
_PAREN = re.compile(r"\s*\([^)]*\)\s*")


def short_name(name: str) -> str:
    """"Pomme de terre Agata (sac 25 kg)" → "Pomme de terre Agata"."""
    return _PAREN.sub(" ", name).strip()


@dataclass
class Catalogue:
    """The global lexicon + what the client lexicons are built from."""

    index: Index
    terms: list[str]  # STT terms: client names, then product names, then aliases (the most misheard first)
    products: dict[str, dict] = field(default_factory=dict)  # id → ERP product
    clients: dict[str, dict] = field(default_factory=dict)  # id → ERP client (list view)


def build_catalogue(products: list[dict], clients: list[dict]) -> Catalogue:
    entries: list[Entry] = []
    seen_forms: set[str] = set()
    names, aliases = [], []
    for c in clients:
        label = c["name"]
        forms = [label, _ARTICLE.sub("", label)]
        for f in dict.fromkeys(forms):
            if f:
                entries.append(Entry(f, "client", c["id"], label, "catalogue"))
                seen_forms.add("".join(words(f)))
        names.append(label)
    product_names = []
    for p in products:
        label = short_name(p["name"])
        lead = " ".join(label.split()[:3]) if len(label.split()) >= 4 else label  # "Diots de Savoie nature" is said "diots de Savoie"
        for f in dict.fromkeys([p["name"], label, lead]):
            entries.append(Entry(f, "product", p["id"], label, "catalogue"))
            seen_forms.add("".join(words(f)))
        product_names.append(p["name"])
        for a in p.get("aliases") or []:
            entries.append(Entry(a, "product", p["id"], label, "alias"))
            seen_forms.add("".join(words(a)))
            aliases.append(a)
    for j in JARGON:
        if "".join(words(j)) not in seen_forms:
            entries.append(Entry(j, "jargon", None, j, "jargon"))
    terms = dedupe([*names, *product_names, *aliases, *JARGON])
    return Catalogue(Index(entries), terms, {p["id"]: p for p in products}, {c["id"]: c for c in clients})


def dedupe(names: list) -> list[str]:
    seen, out = set(), []
    for n in names:
        n = " ".join(str(n or "").replace(",", " ").split())  # the STT hint is a comma-separated list
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


@dataclass
class ClientLexicon:
    client_id: str
    name: str
    index: Index  # entries of this client only (contacts, places, learned)
    usual: dict[str, Usual]  # productId → usual quantity (client sheet)
    terms: list[str]  # STT terms for this caller, best first


def build_client(client: dict, catalogue: Catalogue | None, learned: list[Learned]) -> ClientLexicon:
    """`client`: GET /api/clients/{id}. `learned`: the rows that apply to this client (its own + global client designations
    are already in the global index, only its private ones matter here)."""
    cid = client["id"]
    entries: list[Entry] = []
    contact_terms: list[str] = []
    for ct in client.get("contacts") or []:
        full = (ct.get("name") or "").strip()
        if not full:
            continue
        entries.append(Entry(full, "contact", cid, full, "sheet", cid))
        first = full.split()[0]
        if len(first) > 2:
            entries.append(Entry(first, "contact", cid, full, "sheet", cid))
        contact_terms += [full, first]
    place_terms = []
    for place in (client.get("city"), client.get("zone")):
        if place:
            entries.append(Entry(place, "place", None, place, "sheet", cid))
            place_terms.append(place)
    usual: dict[str, Usual] = {}
    for u in client.get("usual") or []:
        usual[u["productId"]] = Usual(u["productId"], short_name(u.get("productName") or ""), u.get("unit"), u.get("avgQty"), u.get("frequency"))
    for lr in learned:
        entries.append(Entry(lr.heard, lr.etype, lr.eid, lr.label, "learned", cid if lr.scope != "global" else "global", lr.confidence, lr.row_id))
    usual_terms: list[str] = []
    for pid, u in sorted(usual.items(), key=lambda kv: -(kv[1].frequency or 0)):
        p = (catalogue.products.get(pid) if catalogue else None) or {}
        usual_terms += [p.get("name") or u.label, *(p.get("aliases") or [])]
    learned_terms = [lr.label for lr in sorted(learned, key=lambda x: -x.count)]
    terms = dedupe([client["name"], *learned_terms, *usual_terms, *contact_terms, *place_terms])
    return ClientLexicon(cid, client["name"], Index(entries), usual, terms[: cfg.MAX_CLIENT_TERMS])
