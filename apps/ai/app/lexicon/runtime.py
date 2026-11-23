"""
The two runtime entry points of the lexicon (everything else is pure or in store.py):

    annotate(heard, client_id)   voice session, once per spoken turn: "" or a short French block for the END of the user turn
    analyse(text, client_id)     the resolve_mention tool: the mentions themselves

Never raises, never stalls a turn: no ERP / catalogue not loaded yet / a slow client sheet → the resolver is skipped or runs on the
global lexicon only; Jev only runs for ambiguous mentions and is cut at JEV_TIMEOUT_S.
"""

import time

from app.clients import get_jev_client

from . import config as cfg
from .decide import settle
from .resolver import Mention, Usual, format_hints, resolve
from .store import store

READY_WAIT_S = 0.25  # at turn start: a lexicon that is not loaded yet is skipped, not awaited


async def analyse(text: str, client_id: str | None = None, *, wait: float | None = None, use_jev: bool = True) -> tuple[list[Mention], dict[str, Usual], float]:
    """(mentions, the caller's usual products, resolver milliseconds). Empty when the lexicon is not available."""
    ix = await store.indexes(client_id, wait)
    if ix is None:
        return [], {}, 0.0
    t0 = time.perf_counter()
    mentions = resolve(text, ix.indexes, usual=ix.usual, scope=ix.scope)
    ms = (time.perf_counter() - t0) * 1000
    if use_jev:
        mentions = await settle(get_jev_client(), text, mentions)
    return mentions, ix.usual, ms


async def annotate(heard: str, client_id: str | None = None) -> str:
    """The lexicon block for a spoken turn ("" when there is nothing worth the model's attention)."""
    try:
        if not await store.ready(READY_WAIT_S):
            return ""
        mentions, usual, _ = await analyse(heard, client_id, wait=cfg.HINT_CLIENT_WAIT_S)
        return format_hints(mentions, usual)
    except Exception as e:  # the lexicon is an aid: never a reason to lose a turn
        print(f"[lexicon] annotate failed ({type(e).__name__}: {e})", flush=True)
        return ""


CALLER_TOOLS = ("get_client", "get_client_history", "create_draft_order", "get_price")  # tools whose clientId argument is the caller


def caller_of(tool_name: str, arguments: dict) -> str | None:
    """The client id the agent is working on, from a tool call (the voice session uses it as 'the caller is identified')."""
    cid = (arguments or {}).get("clientId")
    return cid if tool_name in CALLER_TOOLS and isinstance(cid, str) and cid.startswith("cli_") else None


def mention_json(m: Mention) -> dict:
    """A mention for the model / the API: small, camelCase."""
    return {
        "heard": m.surface,
        "status": m.status,
        "margin": round(m.margin, 2),
        **({"decidedBy": m.decided_by} if m.decided_by else {}),
        "candidates": [
            {
                "type": c.entry.etype,
                **({"id": c.entry.eid} if c.entry.eid else {}),
                "name": c.entry.label,
                "score": round(c.score, 2),
                **({"learned": True} if c.entry.source == "learned" else {}),
            }
            for c in m.candidates[:4]
        ],
        "action": {
            "exact": "entendu tel quel",
            "resolved": "proposition claire : répète ce nom à l'appelant pour confirmer",
            "ambiguous": "trop proche pour trancher : demande lequel, ou de l'épeler",
        }[m.status],
    }
