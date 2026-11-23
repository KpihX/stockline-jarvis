"""
Vocabulary tools: what the caller says vs. what the ERP knows. The lexicon (lexicon/) is evolving and per client; the agent
looks words up, and records a lesson ONLY after the caller confirmed it. Business knowledge stays in the ERP context table.

The lexicon modules are imported inside the tools: lexicon/store.py imports app.tools (the ERP client), so a top-level import here would be circular.
"""

from typing import Literal

from pydantic import Field

from app.clients import get_jev_client
from app.lexicon.learned import LearnRefused

from .erp import enc
from .registry import ToolContext, tool


@tool
async def resolve_mention(
    ctx: ToolContext,
    text: str = Field(description="Ce que l'appelant a dit (ou le passage douteux), tel que transcrit, ex. « le refuge Paillet »"),
    client_id: str | None = Field(None, description="Optionnel : l'appelant, une fois identifié (son vocabulaire passe en premier)"),
) -> list[dict]:
    """
    Cherche, dans le lexique (catalogue, surnoms, vocabulaire de CE client et appris), à quoi ressemblent les mots entendus : clients, produits,
    contacts, lieux. Rend, pour chaque passage, des candidats avec un score et une marge. À utiliser quand un nom ressemble sans être exact :
    status resolved = répète le nom à l'appelant pour confirmer ; status ambiguous = demande lequel ou de l'épeler. Ne devine jamais.
    Phonetic/fuzzy lookup of heard words against the lexicon.
    """
    from app.lexicon.runtime import analyse, mention_json

    mentions, _, _ = await analyse(text, client_id)
    worth = [m for m in mentions if m.status != "exact" or m.best.entry.etype == "client" or m.best.entry.source == "learned"]
    return [mention_json(m) for m in worth] or [{"status": "no_match", "action": "aucun terme proche : demande à l'appelant de répéter ou d'épeler"}]


@tool
async def learn_term(
    ctx: ToolContext,
    client_id: str = Field(description="L'appelant : cli_…"),
    heard: str = Field(description="Les mots EXACTS dits par l'appelant et mal compris, ex. « Paillet »"),
    entity_type: Literal["client", "product", "contact", "place"] = Field(description="Ce que ces mots désignent"),
    entity_id: str | None = Field(None, description="cli_… ou prd_… (obligatoire pour client et product)"),
    evidence: Literal["spelled", "confirmed", "order"] = Field(
        description="La preuve : spelled = l'appelant a épelé ; confirmed = tu as répété le nom et l'appelant a dit oui ; order = la commande est confirmée dans l'ERP"
    ),
    order_id: str | None = Field(None, description="ord_… si evidence = order"),
) -> dict:
    """
    Mémorise « ce que CE client dit → ce que ça désigne » pour que les prochains appels l'entendent mieux. UNIQUEMENT après une confirmation réelle :
    l'appelant a épelé, ou a répondu oui quand tu as répété le nom, ou la commande est confirmée. Jamais sur une supposition. L'outil relit la
    conversation et refuse sans preuve. Un nom de client appris vaut pour tous les appels ; le reste, pour ce client (et tous si 3 clients le confirment).
    Record a confirmed heard-form → entity lesson.
    """
    from app.lexicon import guard
    from app.lexicon.decide import yes_asker
    from app.lexicon.store import store

    label = entity_id or heard
    order = None
    if evidence == "order":
        if not order_id:
            raise LearnRefused("evidence=order demande orderId.")
        order = await ctx.erp.get(f"/api/orders/{enc(order_id)}")
    cat = await store.catalogue()
    if cat:  # the canonical name, from the ERP (the model's label is not trusted)
        label = {"client": cat.clients, "product": cat.products}.get(entity_type, {}).get(entity_id or "", {}).get("name") or label
    await guard.check_evidence(
        evidence, heard, label, ctx.messages or [], ask_yes=yes_asker(get_jev_client()), order=order, client_id=client_id, etype=entity_type, eid=entity_id
    )
    result = await store.learn(ctx.erp, client_id, heard, entity_type, entity_id, label, evidence)
    return {**result, "learned": True, "heard": heard}


@tool
async def forget_term(
    ctx: ToolContext,
    heard: str = Field(description="Les mots appris à oublier, ex. « Paillet »"),
    client_id: str | None = Field(None, description="Optionnel : n'oublier que pour ce client (et les entrées globales)"),
) -> dict:
    """
    Oublie une correspondance de vocabulaire apprise (à utiliser quand l'appelant dit que tu t'es trompé de nom, ou qu'une entrée est fausse).
    Ne touche ni au catalogue ni aux fiches. Forget a learned vocabulary entry.
    """
    from app.lexicon.store import store

    gone = await store.forget_heard(ctx.erp, heard, client_id)
    if not gone:
        raise LookupError(f"Aucune entrée apprise pour « {heard} »")
    return {"forgot": gone}
