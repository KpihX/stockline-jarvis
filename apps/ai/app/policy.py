"""
Access policy of the voice / chat agent: WHO is on the line and WHAT that role may do. One table, enforced by the harness.

    caller = Caller(role, client_id, actor_name)      DECLARED by the UI selector (the demo has no caller-ID, no telephony)
    authorize(caller, tool, args)                     raises AccessDenied (a French sentence the model can say) before the tool runs
    redact(caller, tool, result)                      strips what the role may not read from an allowed tool's result
    context_scope(caller)                             "public" | "full": which company context files go in the system prompt

The server never trusts the model: a prompt rule is a hint, this module is the lock. Pure functions, no I/O (the one check that
needs the ERP, "does this order belong to the caller", lives in app/agent/access.py and calls `order_owner_ok` here).

Roles
    unknown    not identified (default): catalogue, product info and catalogue prices only, NO write, nothing about any client or supplier.
    client     bound to ONE client id: reads and writes only about it. No suppliers, no other clients, no internal policy / risk notes.
    supplier   bound to ONE supplier id: reads/writes only its own supplier record, events and public catalogue. No clients, no sales prices, no client orders.
    manager    commercial (legacy alias: sales): all business tools.
    admin      management (legacy alias: direction): everything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.schemas.chat import CallerRole

Role = Literal["unknown", "client", "supplier", "manager", "admin"]
ROLES: tuple[Role, ...] = ("unknown", "client", "supplier", "manager", "admin")
ROLE_ALIAS: dict[str, Role] = {"sales": "manager", "direction": "admin"}
INTERNAL: tuple[str, ...] = ("manager", "admin", "sales", "direction")

CLIENT_ID = re.compile(r"^cli_\d{1,9}$")
SUPPLIER_ID = re.compile(r"^sup_\d{1,9}$")
ROLE_LABEL = {
    "unknown": "non identifié",
    "client": "client déclaré",
    "supplier": "fournisseur déclaré",
    "manager": "commercial déclaré",
    "sales": "commercial déclaré",
    "admin": "direction déclarée",
    "direction": "direction déclarée",
}
VERIFIED_LABEL = {
    "unknown": "non identifié",
    "client": "client vérifié",
    "supplier": "fournisseur vérifié",
    "manager": "manager vérifié",
    "sales": "commercial vérifié",
    "admin": "administrateur vérifié",
    "direction": "administrateur vérifié",
}
NAME_MAX = 80


class AccessDenied(Exception):
    """The role may not do this. The message is spoken to the caller by the model: short, French, never reveals what it protects."""


def clean_name(name: str | None) -> str | None:
    """A declared name: one line, no control characters, bounded (it ends up in an HTTP header and in ERP author fields)."""
    n = re.sub(r"[\x00-\x1f\x7f]+", " ", name or "").strip()
    return n[:NAME_MAX] or None


def _norm_role(role: str | None) -> Role:
    if not role:
        return "unknown"
    r = ROLE_ALIAS.get(role, role)
    return r if r in ROLES else "unknown"  # type: ignore[return-value]


@dataclass(frozen=True)
class Caller:
    """The identity of a session (verified via token, or declared when ALLOW_DECLARED_IDENTITY=1). Build with `Caller.verified_account` or `Caller.declare`."""

    role: Role = "unknown"
    client_id: str | None = None  # client role: the ONE client they are; manager/admin: optional working client
    actor_name: str | None = None
    supplier_id: str | None = None  # supplier role: the ONE supplier they are
    verified: bool = False
    account_id: str | None = None

    @classmethod
    def declare(
        cls,
        role: str | None = None,
        client_id: str | None = None,
        actor_name: str | None = None,
        supplier_id: str | None = None,
    ) -> Caller:
        """Normalise a declared identity: an unknown role or a client/supplier without a valid id is `unknown`, never a guess."""
        name = clean_name(actor_name)
        cid_raw = (client_id or "").strip()
        sid_raw = (supplier_id or "").strip()
        r = _norm_role(role)
        if r == "supplier" and not sid_raw and SUPPLIER_ID.match(cid_raw):
            sid_raw, cid_raw = cid_raw, ""
        cid = cid_raw if CLIENT_ID.match(cid_raw) else None
        sid = sid_raw if SUPPLIER_ID.match(sid_raw) else None
        if r == "client" and not cid:
            r = "unknown"
        if r == "supplier" and not sid:
            r = "unknown"
        return cls(
            role=r,
            client_id=cid if r in ("client", "manager", "admin") else None,
            actor_name=name,
            supplier_id=sid if r == "supplier" else None,
            verified=False,
        )

    @classmethod
    def verified_account(cls, acc: dict[str, Any]) -> Caller:
        """Build a verified Caller from GET /api/auth/me payload."""
        r = _norm_role(acc.get("role"))
        eid = acc.get("entityId")
        cid = eid if r == "client" and eid and CLIENT_ID.match(str(eid)) else None
        sid = eid if r == "supplier" and eid and SUPPLIER_ID.match(str(eid)) else None
        if r == "client" and not cid:
            return UNKNOWN
        if r == "supplier" and not sid:
            return UNKNOWN
        return cls(
            role=r,
            client_id=cid,
            actor_name=clean_name(acc.get("displayName") or acc.get("username")),
            supplier_id=sid,
            verified=True,
            account_id=acc.get("id"),
        )

    @property
    def internal(self) -> bool:
        return self.role in INTERNAL

    @property
    def scope(self) -> Literal["public", "full"]:
        return context_scope(self)

    @property
    def erp_name(self) -> str:
        """`x-actor-name` of every ERP write: who the agent was talking to + verified/declared tag."""
        labels = VERIFIED_LABEL if self.verified else ROLE_LABEL
        label = labels[self.role]
        return f"{self.actor_name} · {label}" if self.actor_name else label.capitalize()

    @property
    def provenance(self) -> str:
        """Tag on every record the agent writes: `voice_agent:verified:client` or `voice_agent:declared:client`."""
        kind = "verified" if self.verified else "declared"
        return f"voice_agent:{kind}:{self.role}"


UNKNOWN = Caller()


def context_scope(caller: Caller) -> Literal["public", "full"]:
    """Which company context goes in the system prompt. Chosen once per identity, so it is stable within a session (prompt cache)."""
    return "full" if caller.internal else "public"


# ── The table ─────────────────────────────────────────────────────────────────────────────────────────────────────────
# NO: refused · ALL: allowed · OWN: only about the caller's own client/supplier (arguments checked, results filtered)
# CATALOGUE: product-level information only (arguments / results restricted to the public catalogue)
NO, ALL, OWN, CATALOGUE = "no", "all", "own", "catalogue"

#                          unknown    client     supplier   manager  admin
POLICY: dict[str, tuple[str, str, str, str, str]] = {
    "search":               (CATALOGUE, OWN,       CATALOGUE, ALL, ALL),  # supplier: products + own supplier record in redact()
    "get_product_stock":    (CATALOGUE, CATALOGUE, CATALOGUE, ALL, ALL),  # stock level, list price only
    "find_alternatives":    (CATALOGUE, CATALOGUE, CATALOGUE, ALL, ALL),
    "get_price":            (NO,        OWN,       NO,        ALL, ALL),  # sales price is client-specific; supplier must NOT see sales pricing
    "get_client":           (NO,        OWN,       NO,        ALL, ALL),
    "get_client_history":   (NO,        OWN,       NO,        ALL, ALL),
    "log_client_event":     (NO,        OWN,       NO,        ALL, ALL),
    "get_context":          (NO,        OWN,       OWN,       ALL, ALL),  # client: own cli_; supplier: own sup_ + product/category
    "search_context":       (NO,        OWN,       OWN,       ALL, ALL),
    "save_context":         (NO,        OWN,       OWN,       ALL, ALL),  # client/supplier: restricted kinds about own entity
    "get_supplier_history": (NO,        NO,        OWN,       ALL, ALL),  # supplier: own sup_ ONLY
    "log_supplier_event":   (NO,        NO,        OWN,       ALL, ALL),  # supplier: own sup_ ONLY
    "create_draft_order":   (NO,        OWN,       NO,        ALL, ALL),
    "add_order_line":       (NO,        OWN,       NO,        ALL, ALL),
    "confirm_order":        (NO,        OWN,       NO,        ALL, ALL),
    "get_order":            (NO,        OWN,       NO,        ALL, ALL),
    "resolve_mention":      (NO,        OWN,       CATALOGUE, ALL, ALL),  # supplier: products only
    "learn_term":           (NO,        OWN,       NO,        ALL, ALL),
    "forget_term":          (NO,        OWN,       NO,        ALL, ALL),
    "identify_caller":      (ALL,       NO,        NO,        ALL, ALL),
    "search_sessions":      (NO,        OWN,       NO,        ALL, ALL),
    "recall_session":       (NO,        OWN,       NO,        ALL, ALL),
}

# Tools that change data: refused to `unknown` whatever the table says (belt and braces: a typo in the table cannot open a write).
WRITE_TOOLS = frozenset({"log_client_event", "save_context", "log_supplier_event", "create_draft_order", "add_order_line", "confirm_order", "learn_term", "forget_term"})  # fmt: skip

CLIENT_EVENT_TYPES = frozenset({"complaint", "quality_issue", "delivery_issue", "special_request", "price_negotiation", "menu_change", "compliment", "call", "note"})  # fmt: skip
SUPPLIER_EVENT_TYPES = frozenset({"quality_issue", "delivery_issue", "shortage", "return", "price_change", "invoice_issue", "call", "note"})  # fmt: skip
CLIENT_CONTEXT_KINDS = frozenset({"preference", "logistics"})  # what a client may add to its own sheet
SUPPLIER_CONTEXT_KINDS = frozenset({"preference", "logistics", "fact"})  # what a supplier may add to its own sheet
CLIENT_HIDDEN_KINDS = frozenset({"risk", "policy"})  # internal assessments and rules: not read back to external roles
PUBLIC_PRODUCT_FIELDS = ("id", "name", "unit", "price", "origin", "caliber", "available")
CLIENT_HIDDEN_FIELDS = ("creditLimit", "outstanding", "overdue", "notes")  # of get_client: finances and the reps' private notes

DENIED_UNKNOWN = "Je ne peux pas vous donner cette information ni faire cette opération sans identification."
DENIED_OTHER_CLIENT = "Je ne peux parler que de votre compte, pas de celui d'un autre client."
DENIED_OTHER_SUPPLIER = "Je ne peux consulter ou modifier que votre propre fiche fournisseur."
DENIED_RESERVED = "Cette information est réservée à l'équipe interne."


def rule(caller: Caller, tool: str) -> str:
    """The table entry for (role, tool). A tool missing from the table: refused to everyone but the internal roles."""
    r_name = _norm_role(caller.role)
    entry = POLICY.get(tool)
    if entry is None:
        return ALL if caller.internal else NO
    r = entry[ROLES.index(r_name)]
    return NO if tool in WRITE_TOOLS and r_name == "unknown" else r


def denied(caller: Caller) -> AccessDenied:
    return AccessDenied(DENIED_UNKNOWN if caller.role == "unknown" else DENIED_RESERVED)


def authorize(caller: Caller, tool: str, args: dict[str, Any]) -> None:
    """Raise AccessDenied unless `caller` may run `tool` with `args` (the VALIDATED, snake_case arguments).
    Order ownership and the confirmation turn need the conversation / the ERP: see app/agent/access.py."""
    r = rule(caller, tool)
    if r == NO:
        raise denied(caller)
    if r in (ALL, CATALOGUE):
        return

    if caller.role == "supplier":
        own_sup = caller.supplier_id
        if not own_sup:
            raise denied(caller)
        match tool:
            case "get_supplier_history":
                if args.get("supplier_id") != own_sup:
                    raise AccessDenied(DENIED_OTHER_SUPPLIER)
            case "log_supplier_event":
                if args.get("supplier_id") != own_sup:
                    raise AccessDenied(DENIED_OTHER_SUPPLIER)
                if args.get("type") not in SUPPLIER_EVENT_TYPES:
                    raise AccessDenied("Ce type d'événement fournisseur n'est pas autorisé ici.")
            case "get_context":
                if args.get("entity_type") == "supplier":
                    if args.get("id") != own_sup:
                        raise AccessDenied(DENIED_OTHER_SUPPLIER)
                elif args.get("entity_type") not in ("product", "category"):
                    raise AccessDenied(DENIED_RESERVED)
            case "search_context":
                etype = args.get("entity_type")
                if etype == "supplier":
                    if args.get("entity_id") != own_sup:
                        raise AccessDenied(DENIED_OTHER_SUPPLIER)
                elif etype not in ("product", "category"):
                    raise AccessDenied("Précisez entityType : supplier (le vôtre), product ou category.")
            case "save_context":
                if args.get("entity_type") != "supplier" or args.get("entity_id") != own_sup or args.get("kind") not in SUPPLIER_CONTEXT_KINDS:
                    raise AccessDenied("Je ne peux mémoriser ici que des informations pratiques sur votre fiche fournisseur.")
            case _:
                raise denied(caller)
        return

    own = caller.client_id
    if not own:  # a client role always has one; defensive
        raise denied(caller)

    def mine(client_id: Any) -> None:
        if client_id != own:
            raise AccessDenied(DENIED_OTHER_CLIENT)

    match tool:
        case "get_price" | "get_client" | "get_client_history" | "create_draft_order":
            mine(args.get("client_id"))
        case "log_client_event":
            mine(args.get("client_id"))
            if args.get("type") not in CLIENT_EVENT_TYPES:
                raise AccessDenied("Ce type d'événement n'est pas enregistrable depuis cet appel.")
        case "get_context":
            if args.get("entity_type") == "client":
                mine(args.get("id"))
            elif args.get("entity_type") not in ("product", "category"):
                raise AccessDenied(DENIED_RESERVED)
        case "search_context":
            etype = args.get("entity_type")
            if etype == "client":
                mine(args.get("entity_id"))
            elif etype not in ("product", "category"):
                raise AccessDenied("Précisez entityType : client (le vôtre), product ou category.")
        case "save_context":
            mine(args.get("entity_id"))
            if args.get("entity_type") != "client" or args.get("kind") not in CLIENT_CONTEXT_KINDS:
                raise AccessDenied("Je ne peux mémoriser ici que vos préférences et contraintes de livraison.")
        case "resolve_mention":
            if args.get("client_id") not in (None, own):
                raise AccessDenied(DENIED_OTHER_CLIENT)
        case "learn_term":
            mine(args.get("client_id"))
            if args.get("entity_type") == "client":
                mine(args.get("entity_id"))
        case "forget_term":
            mine(args.get("client_id"))
        case "search_sessions" | "recall_session":
            if args.get("client_id") not in (None, own):
                raise AccessDenied(DENIED_OTHER_CLIENT)
        case _:  # search, add_order_line, confirm_order, get_order: results filtered / ERP ownership check (app/agent/access.py)
            pass


def order_owner_ok(caller: Caller, order_client_id: str | None) -> bool:
    return caller.internal or (caller.role == "client" and order_client_id == caller.client_id)


# ── Results ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def redact(caller: Caller, tool: str, result: Any) -> Any:
    """What an ALLOWED tool may still show this role. Internal roles see everything."""
    if caller.internal:
        return result
    match tool:
        case "search" if isinstance(result, list):
            return [
                r for r in result
                if r.get("type") == "product"
                or (caller.role == "client" and r.get("type") == "client" and r.get("id") == caller.client_id)
                or (caller.role == "supplier" and r.get("type") == "supplier" and r.get("id") == caller.supplier_id)
            ]
        case "get_product_stock" if isinstance(result, dict):
            return {k: result[k] for k in PUBLIC_PRODUCT_FIELDS if k in result}
        case "get_client" if isinstance(result, dict):
            return {k: v for k, v in result.items() if k not in CLIENT_HIDDEN_FIELDS}
        case "search_context" if isinstance(result, list):
            return [e for e in result if e.get("kind") not in CLIENT_HIDDEN_KINDS]
        case "get_context" if isinstance(result, dict):
            return {**result, "entries": [e for e in result.get("entries", []) if e.get("kind") not in CLIENT_HIDDEN_KINDS], "related": []}
        case "resolve_mention" if isinstance(result, list):
            out = []
            for m in result:
                keep = [
                    c for c in m.get("candidates", [])
                    if c.get("type") in ("product", "place") or (caller.role == "client" and c.get("id") == caller.client_id)
                ]
                if keep or "candidates" not in m:
                    out.append({**m, **({"candidates": keep} if "candidates" in m else {})})
            return out
        case _:
            return result


# ── System prompt: the public company card ───────────────────────────────────────────────────────────────────────────
# Allow-list by file (a new context file is internal until listed here). value: sections to DROP (by heading), or None = whole file,
# or PREAMBLE = only what comes before the first "## " heading.
PREAMBLE = "preamble"
PUBLIC_CONTEXT: dict[str, Any] = {
    "01-entreprise.md": PREAMBLE,  # who we are, what we sell, address: NOT the key figures, top clients, team portfolios, suppliers
    "03-glossaire-produits.md": None,  # how customers name the products + list prices (public tariff)
    "06-livraisons-zones.md": {"Tournées"},  # zones, days, order cut-offs: NOT drivers and plates
}


def public_context(name: str, text: str) -> str:
    """The part of one context file a client or an unknown caller may see in the prompt ("" = none)."""
    if name not in PUBLIC_CONTEXT:
        return ""
    spec = PUBLIC_CONTEXT[name]
    if spec is None:
        return text
    parts = re.split(r"(?m)^(?=## )", text)
    if spec == PREAMBLE:
        return parts[0].strip()
    return "".join(p for p in parts if not any(p.startswith(f"## {h}") for h in spec)).strip()
