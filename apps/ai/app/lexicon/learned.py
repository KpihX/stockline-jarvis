"""
Learned entries: "what this client says → the entity it means", stored as rows of the ERP context table.

Convention (no new table, no new backend route; `/api/context` already has create / patch / delete and the x-actor header):

    entityType / entityId   the owner of the entry: the client whose habit it is ("client", cli_…);
                            "company" (no id) for the global lexicon; for an entry that designates a CLIENT it is
                            anchored on that client and flagged scope="global" (the caller says their own name BEFORE
                            being identified, so it must be usable without knowing who is calling)
    kind                    "fact"
    tags                    ["vocab", "vocab:<etype>"]
    title                   Vocabulaire : « paillet » → Le Refuge Payet          (what the UI shows)
    body                    a readable line, then ONE line of JSON with the machine fields (this module's Learned)
    source                  voice_agent (set by the backend from x-actor) · user (edited by hand)

Pure functions only (encode / decode / merge / expiry / promotion): the ERP calls are in store.py.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import date

from . import config as cfg
from .phonetic import squash, words


def squash_form(s: str) -> str:
    """The identity of a spoken form: folded, spaces and plural marks dropped."""
    return squash(words(s))


EVIDENCE_BASE = {"spelled": 0.95, "order": 0.90, "confirmed": 0.85}  # how much each kind of proof is worth
EVIDENCE_RANK = {"spelled": 3, "order": 2, "confirmed": 1}
ETYPES = ("client", "product", "contact", "place")


class LearnRefused(ValueError):
    """The agent asked to learn something that does not meet the rules (message in French, shown to the model)."""


@dataclass
class Learned:
    heard: str  # as said, e.g. "paillet"
    etype: str  # client | product | contact | place
    eid: str | None
    label: str  # canonical name of the entity
    scope: str  # "global" or a client id
    count: int = 1
    first_seen: str = ""  # ISO dates (business date)
    last_seen: str = ""
    source: str = "confirmed"  # spelled | confirmed | order: the strongest proof seen
    clients: list[str] = field(default_factory=list)  # distinct clients that confirmed it (promotion counts these)
    row_id: str | None = None  # ctx_… once stored

    @property
    def norm(self) -> str:
        return squash_form(self.heard)

    @property
    def pair(self) -> tuple[str, str, str | None]:
        """What identifies "the same lesson": the folded heard form and the entity (the scope is separate)."""
        return (self.norm, self.etype, self.eid)

    @property
    def confidence(self) -> float:
        return min(0.99, EVIDENCE_BASE.get(self.source, 0.85) + 0.03 * (self.count - 1))

    @property
    def anchor(self) -> tuple[str, str | None]:
        """(entityType, entityId) of the context row that stores this entry."""
        if self.scope != "global":
            return ("client", self.scope)
        if self.etype == "client":
            return ("client", self.eid)
        return ("company", None)


def validate(heard: str, etype: str, eid: str | None, label: str) -> str:
    """The cleaned heard form, or LearnRefused. Nothing to learn when the words already ARE the entity's name."""
    heard = " ".join((heard or "").split())
    w = words(heard)
    if etype not in ETYPES:
        raise LearnRefused(f"Type d'entité non appris : {etype}")
    if not w or len(w) > 6 or len(heard) > 60 or all(x.isdigit() for x in w):
        raise LearnRefused("La forme entendue doit être 1 à 6 mots (ce que l'appelant a réellement dit).")
    if not eid and etype in ("client", "product", "contact"):
        raise LearnRefused("entityId requis (id issu de search ou get_client).")
    if squash(w) == squash_form(label):
        raise LearnRefused("Rien à apprendre : c'est déjà exactement le nom de l'entité.")
    return heard


def merge(existing: Learned | None, new: Learned, today: str) -> Learned:
    """Another confirmation of a known lesson (count+1, last_seen, strongest proof, distinct clients) or the first one."""
    if existing is None:
        new.first_seen = new.first_seen or today
        new.last_seen = today
        return new
    source = max(existing.source, new.source, key=lambda s: EVIDENCE_RANK.get(s, 0))
    clients = sorted({*existing.clients, *new.clients})
    return Learned(**{**asdict(existing), "count": existing.count + 1, "last_seen": today, "source": source, "clients": clients})


def expired(entry: Learned, today: str) -> bool:
    """Never reused for too long: ignored by the lexicon and removed by prune. A lesson confirmed twice or more lives longer."""
    try:
        age = (date.fromisoformat(today[:10]) - date.fromisoformat((entry.last_seen or entry.first_seen)[:10])).days
    except ValueError:
        return False  # undated (edited by hand): keep
    return age > (cfg.EXPIRE_USED_DAYS if entry.count >= 2 else cfg.EXPIRE_UNUSED_DAYS)


def promotions(rows: list[Learned], today: str) -> list[Learned]:
    """Global entries to create: pairs confirmed for >= PROMOTE_MIN_CLIENTS distinct clients, not yet global.
    Client designations are never promoted (they are global from the start)."""
    by_pair: dict[tuple, list[Learned]] = {}
    for r in rows:
        if r.scope != "global" and not expired(r, today):
            by_pair.setdefault(r.pair, []).append(r)
    global_pairs = {r.pair for r in rows if r.scope == "global"}
    out = []
    for pair, group in by_pair.items():
        clients = sorted({r.scope for r in group})
        if pair in global_pairs or len(clients) < cfg.PROMOTE_MIN_CLIENTS or group[0].etype == "client":
            continue
        g = group[0]
        out.append(
            Learned(
                heard=g.heard, etype=g.etype, eid=g.eid, label=g.label, scope="global",
                count=sum(r.count for r in group), first_seen=min(r.first_seen for r in group), last_seen=max(r.last_seen for r in group),
                source=max((r.source for r in group), key=lambda s: EVIDENCE_RANK.get(s, 0)), clients=clients,
            )
        )  # fmt: skip
    return out


# ── context-table rows ──

SOURCE_FR = {"spelled": "épelé", "confirmed": "confirmé", "order": "commande confirmée"}


def encode(entry: Learned) -> dict:
    """The body to POST / PATCH on /api/context."""
    kind = {"client": "client", "product": "produit", "contact": "contact", "place": "lieu"}.get(entry.etype, entry.etype)
    data = {"v": 1, **{k: v for k, v in asdict(entry).items() if k != "row_id"}}
    where = "pour tous les clients" if entry.scope == "global" else f"pour {entry.scope}"
    human = (
        f"Entendu « {entry.heard} » → {entry.label} ({kind}{f' {entry.eid}' if entry.eid else ''}), {where}. "
        f"{SOURCE_FR.get(entry.source, entry.source)} {entry.count}×, dernière fois {entry.last_seen}. "
        "Appris par l'agent vocal ; à supprimer si c'est faux."
    )
    anchor_type, anchor_id = entry.anchor
    return {
        "entityType": anchor_type,
        **({"entityId": anchor_id} if anchor_id else {}),
        "kind": "fact",
        "title": f"Vocabulaire : « {entry.heard} » → {entry.label}",
        "body": human + "\n" + json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        "tags": [cfg.VOCAB_TAG, f"{cfg.VOCAB_TAG}:{entry.etype}"],
    }


def decode(row: dict) -> Learned | None:
    """A context row → Learned, or None when it is not a (valid) vocabulary row."""
    if cfg.VOCAB_TAG not in (row.get("tags") or []):
        return None
    for line in reversed((row.get("body") or "").splitlines()):
        if line.startswith("{"):
            try:
                d = json.loads(line)
                return Learned(
                    heard=str(d["heard"]), etype=str(d["etype"]), eid=d.get("eid"), label=str(d["label"]), scope=str(d.get("scope") or "global"),
                    count=int(d.get("count") or 1), first_seen=str(d.get("first_seen") or ""), last_seen=str(d.get("last_seen") or ""),
                    source=str(d.get("source") or "confirmed"), clients=list(d.get("clients") or []), row_id=row.get("id"),
                )  # fmt: skip
            except (ValueError, KeyError, TypeError):
                return None
    return None


def public(entry: Learned, today: str | None = None) -> dict:
    """What the admin API shows."""
    return {
        "id": entry.row_id,
        "heard": entry.heard,
        "etype": entry.etype,
        "eid": entry.eid,
        "label": entry.label,
        "scope": entry.scope,
        "count": entry.count,
        "firstSeen": entry.first_seen,
        "lastSeen": entry.last_seen,
        "source": entry.source,
        "clients": entry.clients,
        "confidence": round(entry.confidence, 2),
        **({"expired": expired(entry, today)} if today else {}),
    }
