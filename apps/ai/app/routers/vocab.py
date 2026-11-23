"""
/vocab: see, test and remove what the voice agent learned (the evolving per-client lexicon, app/lexicon/).

    GET    /vocab?clientId=cli_0006&expired=1     learned entries (all clients when no clientId; expired=1 also lists the expired ones)
    GET    /vocab/resolve?q=le refuge Paillet&clientId=cli_0006    what the resolver makes of a phrase (debug, no LLM, no Jev)
    DELETE /vocab/{id}                            forget one entry (id = the context row, ctx_…): the unlearn path
    POST   /vocab/prune                           delete the entries never reused for too long (config.py EXPIRE_*)
    POST   /vocab/refresh                         drop the caches (after `make reset`, or an edit made straight in the ERP)

The same rows are visible and editable in the ERP: GET /api/context?tag=vocab (and the client's Contexte tab).
"""

from fastapi import APIRouter, HTTPException, Query

from app.lexicon import learned as L
from app.lexicon.runtime import analyse, mention_json
from app.lexicon.store import store
from app.tools.erp import ErpClient, ErpError

router = APIRouter(prefix="/vocab", tags=["vocabulary"])


@router.get("")
async def list_vocab(client_id: str | None = Query(None, alias="clientId"), expired: bool = False) -> list[dict]:
    """Learned entries, strongest first. camelCase query: ?clientId=…"""
    store.invalidate()
    today = await store.today()
    rows = await store.learned(include_expired=expired)
    if client_id:
        rows = [r for r in rows if r.scope in (client_id, "global")]
    return [L.public(r, today) for r in sorted(rows, key=lambda r: (-r.count, r.heard))]


@router.get("/resolve")
async def resolve_vocab(q: str, client_id: str | None = Query(None, alias="clientId")) -> dict:
    mentions, _, ms = await analyse(q, client_id, use_jev=False)
    return {"ms": round(ms, 2), "mentions": [mention_json(m) for m in mentions]}


@router.delete("/{row_id}")
async def forget_vocab(row_id: str) -> dict:
    try:
        return await store.forget(ErpClient("user"), row_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except ErpError as e:
        raise HTTPException(502, str(e)) from None


@router.post("/prune")
async def prune_vocab() -> dict:
    return {"deleted": await store.prune(ErpClient("user"))}


@router.post("/refresh")
async def refresh_vocab() -> dict:
    store.invalidate()
    return {"ok": True}
