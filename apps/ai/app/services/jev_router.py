"""
Jev routing around a voice turn — optional, opportunistic, bounded, additive.

Jev (TypeSafe's decision model) answers typed questions in 168-752 ms measured by this kit
(clients/jev.py): a 150 ms timeout would mean ALWAYS falling back. Every call here is cut at
JEV_TIMEOUT_S = 0.9 s and timed (latency_stats() → measured p50/p90, never guessed).

    route_turn         4 questions in ONE request; started at the final transcript in a background
                       task. Its result is only used if it is already there when it is needed:
                       it never delays the model, it only arms an opportunistic read-only preload.
    disambiguate       ambiguous resolver mentions → resolved (>= 0.6, decidedBy="jev") or
                       needs_clarification (the agent asks / offers to spell, never guesses).
    confirm_action     the ONE awaited call: a security gate before confirm_order. No Jev answer
                       (no key, error, timeout) → the existing word-for-word check (access.explicit_yes):
                       the gate is never opened by a missing decision.
    score_claim        noul probability that an utterance is a claim (discount, payment, legal),
                       used to tag writes 'unverified' — or to ask again when unsure.

No JEV_API_KEY → get_jev_client() is None → deterministic fallbacks, no preload, no gate change,
no added latency, no error. No shared module is modified: the wrappers installed by
on_final_transcript() live only in this file and decorate the Tool objects in place.
"""

from __future__ import annotations

import asyncio
import functools
import time
from dataclasses import dataclass, field
from typing import Any

from app.clients import get_jev_client
from app.clients.jev import choice_question, yes_no_question

# The kit measured 168-752 ms (clients/jev.py). 0.9 s keeps the slow tail without stalling a turn.
JEV_TIMEOUT_S = 0.9
MIN_CONFIDENCE = 0.6  # choose / claim: below this, ask instead of guessing
YES_THRESHOLD = 0.8  # is_yes: only a clear yes opens the write gate
CLAIM_THRESHOLD = 0.6
PRELOAD_TIMEOUT_S = 1.5
CACHE_TTL_S = 30.0

INTENTS = {
    "stock": "disponibilité, stock, rupture d'un produit",
    "price": "prix, tarif, remise, coût",
    "order": "passer, modifier ou confirmer une commande",
    "client": "chercher ou consulter un client",
    "info": "question générale sur l'entreprise, ses règles ou ses procédures",
    "trivial": "salutation, remerciement, oui/non, au revoir",
}
TOOL_MODES = {
    "none": "aucun outil : réponse immédiate (salutation, merci, oui, au revoir)",
    "read_only": "lecture seule dans l'ERP (recherche, stock, prix, fiche client, contexte)",
    "write": "écriture dans l'ERP (commande, événement, mémoire)",
}
URGENCY = {"low": "peut attendre", "normal": "normal", "high": "tout de suite / urgent"}
CACHEABLE = ("search", "get_product_stock", "get_price", "get_client", "get_context", "search_context")


# ── types (kept small, JSON-friendly) ──


@dataclass(frozen=True)
class ResolvedMention:
    heard: str
    candidates: list[dict[str, Any]] = field(default_factory=list)  # [{id, label, type, score}]
    status: str = "ambiguous"  # ambiguous | resolved | needs_clarification
    decided_by: str | None = None


@dataclass(frozen=True)
class TurnRoute:
    intent: str = "info"
    tools_needed: str = "read_only"  # none | read_only | write
    urgency: str = "normal"
    requires_confirmation: bool = False
    decided_by: str = "fallback"  # jev | hint | fallback


@dataclass
class TurnState:
    transcript: str
    final: bool = True
    client_id: str | None = None
    role: str = "unknown"
    last_assistant_text: str = ""


# ── measured latency (no number is reported unless measured here) ──

_KINDS = ("route_turn", "disambiguate", "confirm_action", "score_claim")
_samples: dict[str, list[float]] = {k: [] for k in _KINDS}
_errors: dict[str, int] = {k: 0 for k in _KINDS}


def _record(kind: str, ms: float, failed: bool = False) -> None:
    samples = _samples[kind]
    if len(samples) >= 500:
        samples.pop(0)
    samples.append(round(ms, 1))
    if failed:
        _errors[kind] += 1


def latency_stats() -> dict[str, dict[str, Any]]:
    """p50 / p90 in ms over the real Jev calls made in this process (timeouts included)."""
    out: dict[str, dict[str, Any]] = {}
    for kind, xs in _samples.items():
        s = sorted(xs)
        out[kind] = {
            "n": len(s),
            "p50_ms": s[len(s) // 2] if s else None,
            "p90_ms": s[min(len(s) - 1, -(-len(s) * 9 // 10))] if s else None,
            "errors": _errors[kind],
        }
    return out


def reset_latency() -> None:
    for kind in _KINDS:
        _samples[kind].clear()
        _errors[kind] = 0


def _client():
    """Lazy: no key → None, no import-time client, no error."""
    try:
        return get_jev_client()
    except Exception:
        return None


async def _ask(jev, state: Any, questions: dict, kind: str) -> dict | None:
    """One bounded Jev request. Never raises; timeouts are recorded as latency too."""
    t0 = time.perf_counter()
    try:
        return await asyncio.wait_for(jev.ask(state, questions), JEV_TIMEOUT_S)
    except Exception:  # no network, bad key, malformed answer, timeout: the caller falls back
        _record(kind, (time.perf_counter() - t0) * 1000, failed=True)
        return None
    else:
        _record(kind, (time.perf_counter() - t0) * 1000)


def _answers(res: dict | None, name: str) -> dict:
    if not res:
        return {}
    a = (res.get("answers") or {}).get(name)
    return a if isinstance(a, dict) else {}


def _prob(value: Any, default: float = 0.0) -> float:
    try:
        p = float(value)
        return p if 0.0 <= p <= 1.0 else default
    except (TypeError, ValueError):
        return default


def _last_assistant_text(messages: list | None) -> str:
    """The recap the agent gave before the caller's answer (lexicon hints stripped)."""
    for m in reversed(messages or []):
        if getattr(m, "role", None) == "assistant" and getattr(m, "content", ""):
            return str(m.content).split("\n\n[", 1)[0][:600]
    return ""


def _last_user_text(messages: list | None) -> str:
    for m in reversed(messages or []):
        if getattr(m, "role", None) == "user":
            return str(getattr(m, "content", "")).split("\n\n[", 1)[0]
    return ""


# ── the four decisions ──


def default_route(transcript: str = "") -> TurnRoute:
    """Deterministic fallback. A trivially short turn still gets 'none' (no tool for 'merci')."""
    try:
        from .turn_hints import is_trivial

        if is_trivial(transcript):
            return TurnRoute(intent="trivial", tools_needed="none", decided_by="hint")
    except Exception:
        pass
    return TurnRoute()


async def route_turn(transcript: str, state: TurnState) -> TurnRoute:
    """Four typed questions about one state, in ONE Jev request. Never awaited on the critical path."""
    jev = _client()
    if jev is None:
        return default_route(transcript)
    payload = {
        "transcription": transcript[:1200],
        "role_declare": state.role,
        "client": state.client_id or "",
        "reponse_precedente": state.last_assistant_text[:400],
    }
    questions = {
        "intent": choice_question("Que veut faire l'appelant dans cette phrase ?", INTENTS),
        "tools_needed": choice_question("Que faut-il pour répondre ? (les outils coûtent un tour au modèle)", TOOL_MODES),
        "urgency": choice_question("Faut-il répondre immédiatement ?", URGENCY),
        "requires_confirmation": yes_no_question(
            "La phrase demande-t-elle une écriture dans l'ERP (commande, confirmation) qui exige un accord explicite ?"
        ),
    }
    res = await _ask(jev, payload, questions, "route_turn")
    if res is None:
        return default_route(transcript)
    intent = str(_answers(res, "intent").get("choice", "")).lower()
    mode = str(_answers(res, "tools_needed").get("choice", "")).lower()
    urgency = str(_answers(res, "urgency").get("choice", "")).lower()
    confirm = _prob(_answers(res, "requires_confirmation").get("noul"))
    return TurnRoute(
        intent=intent if intent in INTENTS else "info",
        tools_needed=mode if mode in TOOL_MODES else "read_only",
        urgency=urgency if urgency in URGENCY else "normal",
        requires_confirmation=confirm >= MIN_CONFIDENCE,
        decided_by="jev",
    )


async def disambiguate_entities(mentions: list[ResolvedMention]) -> list[ResolvedMention]:
    """Jev chooses between candidates of each ambiguous mention, in parallel. Threshold 0.6."""
    if not any(m.status == "ambiguous" for m in mentions):
        return list(mentions)
    jev = _client()
    if jev is None:
        return [
            ResolvedMention(m.heard, m.candidates, "needs_clarification", m.decided_by)
            if m.status == "ambiguous"
            else m
            for m in mentions
        ]

    async def settle(m: ResolvedMention) -> ResolvedMention:
        options: dict[str, str] = {}
        for c in m.candidates[:4]:
            key = str(c.get("id") or c.get("label"))
            options[key] = f"{c.get('label', key)} ({c.get('type', '?')})"
        if not options:
            return ResolvedMention(m.heard, m.candidates, "needs_clarification")
        res = await _ask(
            jev,
            {"passage_entendu": m.heard, "candidats": [c.get("label") for c in m.candidates[:4]]},
            {"q": choice_question("Lequel de ces éléments le client a-t-il dit ?", options)},
            "disambiguate",
        )
        d = _answers(res, "q")
        choice = str(d.get("choice", ""))
        confidence = _prob(d.get("confidence"))
        if res is not None and confidence >= MIN_CONFIDENCE and choice in options:
            picked = [c for c in m.candidates if str(c.get("id") or c.get("label")) == choice]
            others = [c for c in m.candidates if c not in picked]
            label = options[choice].split(" (")[0]
            return ResolvedMention(m.heard, picked + others, "resolved", "jev")
        return ResolvedMention(m.heard, m.candidates, "needs_clarification")

    return list(await asyncio.gather(*(settle(m) if m.status == "ambiguous" else _same(m) for m in mentions)))


async def _same(m: ResolvedMention) -> ResolvedMention:
    return m


async def confirm_action(question: str, answer: str) -> bool:
    """Awaited security gate. Jev is_yes >= 0.8; no Jev answer → the existing word-for-word check."""
    from .turn_hints import fold  # lazy: this module is imported by voice_session

    jev = _client()
    if jev is None or not answer.strip():
        return _word_for_word(answer)
    res = await _ask(
        jev,
        {"question_posee": question[:600], "reponse_du_client": answer[:600]},
        {"q": yes_no_question("Le client confirme-t-il explicitement ce qui lui a été proposé ?")},
        "confirm_action",
    )
    if res is None:  # no decision → do NOT open the gate any wider than the existing check
        return _word_for_word(answer)
    return _prob(_answers(res, "q").get("noul")) >= YES_THRESHOLD


def _word_for_word(answer: str) -> bool:
    from app.agent.access import explicit_yes

    return explicit_yes(answer)


async def _claim_probability(claim: str, context: dict | None = None) -> float | None:
    """None = no decision (no key / error / timeout): the existing write path continues."""
    jev = _client()
    if jev is None or not claim.strip():
        return None
    res = await _ask(
        jev,
        {"paroles_du_client": claim[:1200], "contexte": context or {}},
        {
            "q": yes_no_question(
                "Ces paroles contiennent-elles une revendication (remise, prix convenu, paiement, engagement juridique) "
                "qu'il faut enregistrer comme NON vérifiée ?"
            )
        },
        "score_claim",
    )
    if res is None:
        return None
    return _prob(_answers(res, "q").get("noul"), default=0.0)


async def score_claim(claim: str, context: dict | None = None) -> float:
    """Probability (0..1) that `claim` is an unverified claim. No Jev → 0.0 (no signal)."""
    p = await _claim_probability(claim, context)
    return p if p is not None else 0.0


# ── opportunistic read-only preload (30 s cache, shared with the tool wrappers) ──

_cache: dict[tuple, tuple[float, Any]] = {}


def _freeze(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return tuple(_freeze(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((str(k), _freeze(x)) for k, x in v.items()))
    return v


def _cache_key(name: str, args: dict) -> tuple:
    return (name, tuple(sorted((k, _freeze(v)) for k, v in (args or {}).items() if v is not None)))


def cache_get(name: str, args: dict) -> Any:
    hit = _cache.get(_cache_key(name, args))
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]
    return None


def cache_put(name: str, args: dict, result: Any) -> None:
    _cache[_cache_key(name, args)] = (time.monotonic(), result)


def clear_cache() -> None:
    _cache.clear()


async def preload_for_route(route: TurnRoute, state: TurnState, caller=None) -> int:
    """Fill the 30 s cache with the reads the next model turn is likely to make. Never raises."""
    if route.tools_needed != "read_only" or route.decided_by != "jev":
        return 0  # no Jev decision → no preload at all
    from app.policy import UNKNOWN
    from app.tools.catalog import get_client, get_price, get_product_stock, search
    from app.tools.context import get_context, search_context
    from app.tools.erp import ErpClient
    from app.tools.registry import ToolContext

    ctx = ToolContext(
        erp=ErpClient("voice_agent", caller.erp_name if caller and caller != UNKNOWN else None),
        actor="voice_agent",
        caller=caller or UNKNOWN,
    )
    query = " ".join(state.transcript.split())[:100]

    async def read(name: str, t, args: dict):
        try:
            result = await asyncio.wait_for(t.fn(ctx, **args), PRELOAD_TIMEOUT_S)
            cache_put(name, args, result)
            return result
        except Exception:
            return None

    filled = 0
    try:
        if route.intent in ("stock", "price", "order"):
            args = {"query": query, "types": ["product"]}
            hits = await read("search", search, args)
            if hits:
                filled += 1
                pid = next((h.get("id") for h in hits if str(h.get("id", "")).startswith("prd_")), None)
                if pid:
                    if await read("get_product_stock", get_product_stock, {"product_id": pid}) is not None:
                        filled += 1
                    cid = state.client_id
                    if cid and cid.startswith("cli_") and await read("get_price", get_price, {"client_id": cid, "product_id": pid}) is not None:
                        filled += 1
        elif route.intent in ("client", "order"):
            args = {"query": query, "types": ["client"]}
            hits = await read("search", search, args)
            if hits:
                filled += 1
                cid = state.client_id or next((h.get("id") for h in hits if str(h.get("id", "")).startswith("cli_")), None)
                if cid and cid.startswith("cli_"):
                    if await read("get_client", get_client, {"client_id": cid}) is not None:
                        filled += 1
                    if await read("get_context", get_context, {"entity_type": "client", "id": cid}) is not None:
                        filled += 1
        elif route.intent == "info":
            if await read("search_context", search_context, {"query": query}) is not None:
                filled += 1
    except Exception:
        pass
    return filled


async def preload_when_ready(route_task: asyncio.Task, state: TurnState, caller=None) -> int:
    """Await the background route (bounded) then preload. Called as a background task itself."""
    try:
        route = await asyncio.wait_for(route_task, JEV_TIMEOUT_S + 0.3)
    except Exception:
        return 0
    return await preload_for_route(route, state, caller)


# ── tool decoration: all of it lives here, nothing in the shared tool modules ──

_wrapped: set[str] = set()
_tasks: list[asyncio.Task] = []


def _background(coro) -> None:
    t = asyncio.create_task(coro)
    _tasks.append(t)
    if len(_tasks) > 64:
        _tasks[:] = [x for x in _tasks if not x.done()]


def _decorate(name: str, fn, guard) -> Any:
    @functools.wraps(fn)  # keeps __module__ = app.tools.* (the policy test relies on it)
    async def wrapped(ctx, **args):
        return await guard(ctx, args, fn)

    return wrapped


async def _confirm_guard(ctx, args: dict, fn) -> Any:
    recap = _last_assistant_text(getattr(ctx, "messages", None))
    answer = _last_user_text(getattr(ctx, "messages", None))
    if recap and not await confirm_action(recap, answer):
        raise PermissionError("Confirmation non obtenue : je te redemande « c'est bon ? » avant de confirmer la commande.")
    return await fn(ctx, **args)


async def _claim_guard(ctx, args: dict, fn) -> Any:
    title = str(args.get("title") or "")
    text = " ".join((title, str(args.get("description") or args.get("body") or ""))).strip()
    p = await _claim_probability(
        text,
        {"role": ctx.caller.role, "client_id": ctx.caller.client_id, "type": args.get("type") or args.get("kind")},
    )
    if p is None:  # no key / no answer: the existing write path (and its own provenance tags) continues
        return await fn(ctx, **args)
    if p <= CLAIM_THRESHOLD:
        raise PermissionError("Revendication pas assez claire : je redemande avant de l'enregistrer.")
    args = {**args, "tags": [*(args.get("tags") or []), "unverified"]}
    if args.get("severity") is None:  # a claim declared by a caller is low severity, never an established fact
        args["severity"] = "low"
    return await fn(ctx, **args)


async def _cache_guard(ctx, args: dict, fn) -> Any:
    hit = cache_get(ctx.tool_name, args) if hasattr(ctx, "tool_name") else None
    if hit is not None:
        return hit
    result = await fn(ctx, **args)
    cache_put(ctx.tool_name, args, result)
    return result


def _install_wrappers() -> None:
    """Idempotent. Decorate the registered Tool objects in place; run_agent sees them via all_tools()."""
    if _wrapped or _client() is None:
        return
    from app.tools import TOOLS

    for name, t in TOOLS.items():
        if name == "confirm_order":
            t.fn = _decorate(name, t.fn, _confirm_guard)
            _wrapped.add(name)
        elif name in ("log_client_event", "save_context"):
            t.fn = _decorate(name, t.fn, _claim_guard)
            _wrapped.add(name)
        elif name in CACHEABLE:
            # the guard needs the tool name: bind it in a per-tool closure
            def guard_factory(tool_name: str):
                async def guard(ctx, args, fn):
                    hit = cache_get(tool_name, args)
                    if hit is not None:
                        return hit
                    result = await fn(ctx, **args)
                    cache_put(tool_name, args, result)
                    return result

                return guard

            t.fn = _decorate(name, t.fn, guard_factory(name))
            _wrapped.add(name)


async def clarify_hints(heard: str, client_id: str | None = None) -> str:
    """Lexicon hints with Jev disambiguation: resolved names are repeated, unsure ones ask for spelling."""
    from app.lexicon.resolver import format_hints
    from app.lexicon.runtime import analyse, READY_WAIT_S
    from app.lexicon.store import store

    if _client() is None:
        return ""  # no key: the existing lexicon annotate() path stays untouched by the caller
    try:
        if not await store.ready(READY_WAIT_S):
            return ""
        mentions, usual, _ = await analyse(heard, client_id, use_jev=False)  # Jev is called by us, once
        mentions = await disambiguate_entities(mentions)
        return format_hints(mentions, usual)
    except Exception as e:
        print(f"[jev] clarification ignorée ({type(e).__name__}: {e})", flush=True)
        return ""


async def on_final_transcript(conv, heard: str) -> str:
    """THE single voice_session hook. Starts routing/preload in the background, returns extra prompt hints.

    No key → "" and no side effect. Never awaits the route: the model call proceeds immediately.
    """
    if _client() is None:
        return ""
    _install_wrappers()
    state = TurnState(
        transcript=heard,
        client_id=getattr(conv, "client_id", None),
        role=getattr(getattr(conv, "caller", None), "role", "unknown"),
        last_assistant_text=_last_assistant_text(getattr(conv, "history", None)),
    )
    route_task = asyncio.create_task(route_turn(heard, state))
    _background(preload_when_ready(route_task, state, getattr(conv, "caller", None)))
    return await clarify_hints(heard, state.client_id)


__all__ = [
    "CLAIM_THRESHOLD",
    "CACHE_TTL_S",
    "JEV_TIMEOUT_S",
    "MIN_CONFIDENCE",
    "YES_THRESHOLD",
    "ResolvedMention",
    "TurnRoute",
    "TurnState",
    "cache_get",
    "cache_put",
    "clear_cache",
    "clarify_hints",
    "confirm_action",
    "default_route",
    "disambiguate_entities",
    "latency_stats",
    "on_final_transcript",
    "preload_for_route",
    "reset_latency",
    "route_turn",
    "score_claim",
]
