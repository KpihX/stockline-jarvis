"""Cross-session recall tools (`search_sessions`, `recall_session`): scoped strictly by ctx.caller."""

from pydantic import Field

from .registry import ToolContext, tool


@tool
async def search_sessions(
    ctx: ToolContext,
    query: str = Field(default="", description="Mots-clés (titre, produit, client, numéro de commande)"),
    client_id: str | None = Field(None, description="Optionnel : filtrer sur un client (cli_…)"),
) -> list[dict]:
    """
    Cherche dans les conversations passées (chat et voix) : décisions, commandes créées, questions en suspens.
    Permet de se rappeler d'un appel ou échange précédent. Scoped by caller role.
    """
    from app.services import sessions

    cid = ctx.caller.client_id if ctx.caller.role == "client" else client_id
    items = sessions.list_sessions(q=query, caller=ctx.caller, client_id=cid, limit=6)
    return [
        {
            "id": s["id"],
            "titre": s["title"],
            "date": s["updatedAt"][:10],
            "surface": s["surface"],
            "clientId": s["clientId"],
            "commandes": s["commandIds"][:4],
            "apercu": s["preview"],
            "enAttente": s["pendingQuestion"],
        }
        for s in items
    ]


@tool
async def recall_session(
    ctx: ToolContext,
    session_id: str = Field(description="Identifiant de session (ex. sess_…)"),
    client_id: str | None = Field(None, description="Optionnel : id client pour vérification de portée"),
) -> dict:
    """
    Charge le résumé détaillé et les derniers messages d'une session passée pour reprendre le contexte.
    Recall one past conversation summary and key facts.
    """
    from app.services import sessions

    d = sessions.detail(session_id, caller=ctx.caller)
    if d is None:
        raise LookupError(f"Session introuvable ou hors de portée : {session_id}")
    return {
        "id": d["id"],
        "titre": d["title"],
        "date": d["updatedAt"][:10],
        "surface": d["surface"],
        "clientId": d["clientId"],
        "faits": d["facts"],
        "messages": d["messages"][-8:],
    }
