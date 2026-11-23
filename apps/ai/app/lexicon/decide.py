"""
Settling the ambiguous mentions with Jev (the decision model, clients/jev.py), optional and failure tolerant.

For each "ambiguous" mention Jev is asked ONE typed question: which of the candidates did the caller mean, or none of them?
    confident (>= JEV_MIN_CONFIDENCE) on a candidate  → the mention becomes "resolved" (decidedBy="jev"): still repeated back to the caller
    confident on "none of these"                       → the mention is dropped (a look-alike word, not a mention)
    anything else (unsure, no key, error, timeout)     → it stays "ambiguous": the agent ASKS (and offers to spell), it never guesses
Without JEV_API_KEY nothing changes: the LLM path decides, with the candidates in front of it.
"""

import asyncio
from collections.abc import Awaitable, Callable

from app.clients.jev import JevClient

from . import config as cfg
from .resolver import Mention

NONE_OF_THESE = "aucun"


def _key(c) -> str:
    return f"{c.entry.etype}:{c.entry.eid or c.entry.label}"


async def settle(jev: JevClient | None, text: str, mentions: list[Mention]) -> list[Mention]:
    """The mentions, with Jev's decision applied to the ambiguous ones (in parallel, each bounded by JEV_TIMEOUT_S)."""
    if jev is None or not any(m.status == "ambiguous" for m in mentions):
        return mentions
    decided = await asyncio.gather(*(_settle_one(jev, text, m) if m.status == "ambiguous" else _same(m) for m in mentions))
    return [m for m in decided if m is not None]


async def _same(m: Mention) -> Mention:
    return m


async def _settle_one(jev: JevClient, text: str, m: Mention) -> Mention | None:
    options: dict[str, str | None] = {_key(c): f"{c.entry.label} ({c.entry.etype})" for c in m.candidates}
    exact = all(c.exact for c in m.candidates)
    if not exact:
        options[NONE_OF_THESE] = "Aucun de ces éléments : le passage désigne autre chose, ce ne sont pas des mots du catalogue."
    try:
        d = await asyncio.wait_for(
            jev.choose(
                {"phrase_de_l_appelant": text, "passage_a_comprendre": m.surface},
                "Dans cette phrase d'un client qui commande par téléphone, que désigne le passage ? (la transcription peut être approximative)",
                options,
            ),
            cfg.JEV_TIMEOUT_S,
        )
    except Exception:  # no network, Jev error, timeout: the agent asks
        return m
    if d.confidence < cfg.JEV_MIN_CONFIDENCE or d.choice not in options:
        return m
    if d.choice == NONE_OF_THESE:
        return None
    pick = next(c for c in m.candidates if _key(c) == d.choice)
    rest = sorted((p for k, p in d.probabilities.items() if k != d.choice), reverse=True)
    return Mention(m.surface, m.start, m.end, "resolved", [pick, *(c for c in m.candidates if c is not pick)], d.probabilities.get(d.choice, d.confidence) - (rest[0] if rest else 0), "jev")


def yes_asker(jev: JevClient | None) -> Callable[[str, str], Awaitable[bool | None]] | None:
    """`ask_yes(question, answer)` for the guard: Jev's is_yes, or None when there is no Jev."""
    if jev is None:
        return None
    from app.agent.jev_examples import is_yes  # here, not at the top: app.agent imports the tools, which import this package

    return lambda question, answer: asyncio.wait_for(is_yes(jev, question, answer), cfg.JEV_TIMEOUT_S * 2)
