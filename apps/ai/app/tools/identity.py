"""
identify_caller: the caller gave a name, who could that be? It PROPOSES candidates and nothing more.

The role of a session is set by the UI selector (app/policy.py), never by this tool, never by what is said on the line: the result
is always marked "unverified" and a match changes no access. For an unknown caller only the names are returned (no id, no detail).
"""

from pydantic import Field

from .registry import ToolContext, tool

MIN_QUERY = 3
MAX_CANDIDATES = 3


@tool
async def identify_caller(ctx: ToolContext, name: str = Field(description="Le nom que l'interlocuteur donne (son établissement ou lui-même), tel qu'entendu")) -> dict:
    """
    Propose des clients qui ressemblent au nom donné par un interlocuteur NON identifié. Le résultat est NON VÉRIFIÉ : il ne donne aucun accès
    et ne change pas l'identité de l'appel (elle se règle dans l'interface, pas par la parole). À utiliser pour répéter le nom
    (« Le Refuge Payet, c'est bien ça ? ») puis dire qu'il faut s'identifier pour aller plus loin.
    Propose unverified client candidates for a name; never grants access.
    """
    query = " ".join(name.split())
    if len(query) < MIN_QUERY:
        return {"status": "unverified", "candidates": [], "note": "Nom trop court : demande à l'interlocuteur de répéter ou d'épeler."}
    hits = await ctx.erp.get("/api/search", {"q": query, "types": "client"})
    found = [h for h in hits if h.get("type") == "client"][:MAX_CANDIDATES]
    return {
        "status": "unverified",
        "candidates": [{"name": h["label"], **({"id": h["id"]} if ctx.caller.internal else {})} for h in found],
        "note": "Identité NON vérifiée : aucun accès accordé. L'interlocuteur doit s'identifier par le canal prévu pour obtenir des informations ou passer commande.",
    }
