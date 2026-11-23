"""
Access policy of the voice / chat agent: WHO is on the line and WHAT that role may do. One table, enforced by the harness.

    caller = Caller(role, client_id, actor_name)      DECLARED by the UI selector (the demo has no caller-ID, no telephony)
    authorize(caller, tool, args)                     raises AccessDenied (a French sentence the model can say) before the tool runs
    redact(caller, tool, result)                      strips what the role may not read from an allowed tool's result
    context_scope(caller)                             "public" | "full": which company context files go in the system prompt

The server never trusts the model: a prompt rule is a hint, this module is the lock. Pure functions, no I/O (the one check that
needs the ERP, "does this order belong to the caller", lives in app/agent/access.py and calls `order_owner_ok` here).

Roles
    unknown    not identified (default): catalogue, product info and catalogue prices only, NO write, nothing about any client.
    client     bound to ONE client id: reads and writes only about it. No suppliers, no other clients, no internal policy / risk notes.
    sales      commercial: everything.
    direction  management: everything (own column so the two can diverge).

Production would replace the declared identity by caller-ID / authentication; this table would not change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from app.schemas.chat import CallerRole

Role = CallerRole
ROLES: tuple[Role, ...] = ("unknown", "client", "sales", "direction")
INTERNAL: tuple[Role, ...] = ("sales", "direction")

CLIENT_ID = re.compile(r"^cli_\d{1,9}$")
ROLE_LABEL = {"unknown": "non identifié", "client": "client déclaré", "sales": "commercial déclaré", "direction": "direction déclarée"}
NAME_MAX = 80


class AccessDenied(Exception):
    """The role may not do this. The message is spoken to the caller by the model: short, French, never reveals what it protects."""


def clean_name(name: str | None) -> str | None:
    """A declared name: one line, no control characters, bounded (it ends up in an HTTP header and in ERP author fields)."""
    n = re.sub(r"[\x00-\x1f\x7f]+", " ", name or "").strip()
    return n[:NAME_MAX] or None


@dataclass(frozen=True)
class Caller:
    """The declared identity of a session. Build it with `Caller.declare` (it normalises); the default is the safest one."""

    role: Role = "unknown"
    client_id: str | None = None  # client role: the ONE client they are; sales / direction: the client they are working on (optional)
    actor_name: str | None = None

    @classmethod
    def declare(cls, role: str | None = None, client_id: str | None = None, actor_name: str | None = None) -> Caller:
        """Normalise what the UI sent: an unknown role or a client without a valid cli_… id is `unknown`, never a guess."""
        name = clean_name(actor_name)
        cid = client_id.strip() if client_id and CLIENT_ID.match(client_id.strip()) else None
        r: Role = role if role in ROLES else "unknown"  # type: ignore[assignment]
        if r == "client" and not cid:
            r = "unknown"
        return cls(r, cid if r != "unknown" else None, name)

    @property
    def internal(self) -> bool:
        return self.role in INTERNAL

    @property
    def scope(self) -> Literal["public", "full"]:
        return context_scope(self)

    @property
    def erp_name(self) -> str:
        """`x-actor-name` of every ERP write: who the agent was talking to AND that this is a declaration, not a proof."""
        label = ROLE_LABEL[self.role]
        return f"{self.actor_name} · {label}" if self.actor_name else label.capitalize()

    @property
    def provenance(self) -> str:
        """Tag on every record the agent writes (events, context rows): `voice_agent:declared:client`."""
        return f"voice_agent:declared:{self.role}"


UNKNOWN = Caller()


def context_scope(caller: Caller) -> Literal["public", "full"]:
    """Which company context goes in the system prompt. Chosen once per identity, so it is stable within a session (prompt cache)."""
    return "full" if caller.internal else "public"


# ── The table ─────────────────────────────────────────────────────────────────────────────────────────────────────────
# NO: refused · ALL: allowed · OWN: only about the caller's own client (arguments checked, results filtered)
# CATALOGUE: product-level information only (arguments / results restricted to the public catalogue)
NO, ALL, OWN, CATALOGUE = "no", "all", "own", "catalogue"

#                          unknown    client   sales  direction
POLICY: dict[str, tuple[str, str, str, str]] = {
    "search":              (CATALOGUE, OWN,       ALL, ALL),  # unknown: products only. client: products + its own client record
    "get_product_stock":   (CATALOGUE, CATALOGUE, ALL, ALL),  # stock level, list price: no reservations, arrivals, expiry
    "find_alternatives":   (CATALOGUE, CATALOGUE, ALL, ALL),
    "get_price":           (NO,        OWN,       ALL, ALL),  # a negotiated price is client-specific
    "get_client":          (NO,        OWN,       ALL, ALL),
    "get_client_history":  (NO,        OWN,       ALL, ALL),
    "log_client_event":    (NO,        OWN,       ALL, ALL),  # client: always recorded as an unverified claim
    "get_context":         (NO,        OWN,       ALL, ALL),
    "search_context":      (NO,        OWN,       ALL, ALL),
    "save_context":        (NO,        OWN,       ALL, ALL),  # client: preference / logistics facts about itself, flagged unverified
    "get_supplier_history": (NO,       NO,        ALL, ALL),
    "log_supplier_event":  (NO,        NO,        ALL, ALL),
    "create_draft_order":  (NO,        OWN,       ALL, ALL),
    "add_order_line":      (NO,        OWN,       ALL, ALL),  # order ownership checked against the ERP
    "confirm_order":       (NO,        OWN,       ALL, ALL),  # + explicit confirmation turn for the client
    "get_order":           (NO,        OWN,       ALL, ALL),
    "resolve_mention":     (NO,        OWN,       ALL, ALL),  # client: products and itself only
    "learn_term":          (NO,        OWN,       ALL, ALL),
    "forget_term":         (NO,        OWN,       ALL, ALL),
    "identify_caller":     (ALL,       NO,        ALL, ALL),  # proposes candidates, NEVER upgrades the role (the UI selector does)
}

# Tools that change data: refused to `unknown` whatever the table says (belt and braces: a typo in the table cannot open a write).
WRITE_TOOLS = frozenset({"log_client_event", "save_context", "log_supplier_event", "create_draft_order", "add_order_line", "confirm_order", "learn_term", "forget_term"})  # fmt: skip

CLIENT_EVENT_TYPES = frozenset({"complaint", "quality_issue", "delivery_issue", "special_request", "price_negotiation", "menu_change", "compliment", "call", "note"})  # fmt: skip
CLIENT_CONTEXT_KINDS = frozenset({"preference", "logistics"})  # what a declared client may add to its own sheet
CLIENT_HIDDEN_KINDS = frozenset({"risk", "policy"})  # internal assessments and rules: not read back to a client
PUBLIC_PRODUCT_FIELDS = ("id", "name", "unit", "price", "origin", "caliber", "available")
CLIENT_HIDDEN_FIELDS = ("creditLimit", "outstanding", "overdue", "notes")  # of get_client: finances and the reps' private notes

DENIED_UNKNOWN = "Je ne peux pas vous donner cette information ni faire cette opération sans identification."
DENIED_OTHER_CLIENT = "Je ne peux parler que de votre compte, pas de celui d'un autre client."
DENIED_RESERVED = "Cette information est réservée à l'équipe interne."


def rule(caller: Caller, tool: str) -> str:
    """The table entry for (role, tool). A tool missing from the table: refused to everyone but the internal roles."""
    entry = POLICY.get(tool)
    if entry is None:
        return ALL if caller.internal else NO
    r = entry[ROLES.index(caller.role)]
    return NO if tool in WRITE_TOOLS and caller.role == "unknown" else r


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
    own = caller.client_id
    if not own:  # a client role always has one (Caller.declare); defensive
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
            return [r for r in result if r.get("type") == "product" or (caller.role == "client" and r.get("type") == "client" and r.get("id") == caller.client_id)]  # fmt: skip
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
                keep = [c for c in m.get("candidates", []) if c.get("type") in ("product", "place") or c.get("id") == caller.client_id]
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
