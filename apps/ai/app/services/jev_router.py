"""
Jev routing around a voice turn — optional, opportunistic, bounded, additive.

Jev (TypeSafe's decision model) answers typed questions in 168-752 ms measured by this kit
(clients/jev.py): a 150 ms timeout would mean ALWAYS falling back. Every call here is cut at
JEV_TIMEOUT_S = 0.9 s and timed (latency_stats() → measured p50/p90, never guessed).

    route_turn         4 questions in ONE request; launched in the background at the final transcript.
                       Its result is only used if it is already there when the preload starts: it never
                       delays the model, it only arms an opportunistic read-only cache (TTL 30 s).
    disambiguate       ambiguous resolver mentions → resolved (>= 0.6, decidedBy="jev") or
                       needs_clarification (the agent asks / offers to spell, never guesses).
    confirm_action     the ONE awaited call: a security gate inside execute_tool before confirm_order.
                       No Jev answer (error / timeout) → the existing word-for-word check; the gate is
                       never opened by a missing decision. No key at all → existing behaviour untouched.
    score_claim        noul probability that an utterance is a claim (discount, payment, legal): tag the
                       write 'unverified' + severity low, or ask again when unsure.

No JEV_API_KEY → get_jev_client() is None → deterministic fallbacks, no preload, no gate change,
no added latency, no error. Nothing is mutated globally: the tool guards live in ONE function
(execute_with_guards) called by agent/access.py::execute_tool, so /chat, /command and tests are covered.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from dataclasses import dataclass, field
from typing import Any

from app.clients import get_jev_client
from app.clients.jev import choice_question, yes_no_question

# Measured 168-752 ms (clients/jev.py). 0.9 s keeps the slow tail without stalling a turn.
JEV_TIMEOUT_S = 0.9
MIN_CONFIDENCE = 0.6
YES_THRESHOLD = 0.8
CLAIM_THRESHOLD = 0.6
PRELOAD_TIMEOUT_S = 1.5
CACHE_TTL_S = 30.0
HINT_MARK = "\n\n[Lexique"  # services/compaction.py: the lexicon block is dropped from the summary

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
CACHEABLE = frozenset({"search", "get_product_stock", "get_price", "get_client", "get_context", "search_context"})


# ── types ──


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
        res = await asyncio.wait_for(jev.ask(state, questions), JEV_TIMEOUT_S)
    except Exception:  # no network, bad key, malformed answer, timeout → caller falls back
        _record(kind, (time.perf_counter() - t0) * 1000, failed=True)
        return None
    _record(kind, (time.perf_counter() - t0) * 1000)  # never in `else`: a `return` in try would skip it
    return res


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
    """The recap the agent gave before the caller's answer (lexicon hint blocks stripped)."""
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
    """Jev chooses between the candidates of each ambiguous mention, in parallel. Threshold 0.6."""
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
            return ResolvedMention(m.heard, picked + others, "resolved", "jev")
        return ResolvedMention(m.heard, m.candidates, "needs_clarification")

    return list(await asyncio.gather(*(settle(m) if m.status == "ambiguous" else _same(m) for m in mentions)))


async def _same(m: ResolvedMention) -> ResolvedMention:
    return m


async def confirm_action(question: str, answer: str) -> bool:
    """Awaited security gate. Jev is_yes >= 0.8; no Jev answer → the existing word-for-word check."""
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
    return _prob(_answers(res, "q").get("noul"))


async def score_claim(claim: str, context: dict | None = None) -> float:
    """Probability (0..1) that `claim` is an unverified claim. No Jev → 0.0 (no signal)."""
    p = await _claim_probability(claim, context)
    return p if p is not None else 0.0


# ── opportunistic read-only preload (30 s cache, scoped to the caller) ──

_cache: dict[tuple, tuple[float, Any]] = {}
_tasks: list[asyncio.Task] = []


def _scope(caller) -> tuple[str, str | None]:
    return (getattr(caller, "role", "unknown"), getattr(caller, "client_id", None))


def _freeze(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return tuple(_freeze(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((str(k), _freeze(x)) for k, x in v.items()))
    return v


def _cache_key(name: str, args: dict, caller) -> tuple:
    return (name, tuple(sorted((k, _freeze(v)) for k, v in (args or {}).items() if v is not None)), _scope(caller))


def cache_get(name: str, args: dict, caller) -> Any:
    hit = _cache.get(_cache_key(name, args, caller))
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return hit[1]
    return None


def cache_put(name: str, args: dict, caller, result: Any) -> None:
    _cache[_cache_key(name, args, caller)] = (time.monotonic(), result)


def clear_cache() -> None:
    _cache.clear()


async def preload_for_route(route: TurnRoute, state: TurnState, caller) -> int:
    """Fill the 30 s cache with the reads the next model turn is likely to make. Never raises.

    Every read goes through policy.authorize(caller, ...) and redact(caller, ...): the background
    task has exactly the same rights as the tool call that would otherwise be made by the model.
    """
    if route.tools_needed != "read_only" or route.decided_by != "jev":
        return 0  # no Jev decision → no preload at all
    from app import policy
    from app.policy import UNKNOWN
    from app.tools.catalog import get_client, get_price, get_product_stock, search
    from app.tools.context import get_context, search_context
    from app.tools.erp import ErpClient
    from app.tools.registry import ToolContext

    who = caller or UNKNOWN
    ctx = ToolContext(erp=ErpClient("voice_agent", who.erp_name if who != UNKNOWN else None), actor="voice_agent", caller=who)
    query = " ".join(state.transcript.split())[:100]

    async def read(name: str, t, args: dict):
        try:
            policy.authorize(who, name, args)  # the SAME policy gate as execute_tool
            result = await asyncio.wait_for(t.fn(ctx, **args), PRELOAD_TIMEOUT_S)
            result = policy.redact(who, name, result)  # never cache something the role may not read
            cache_put(name, args, who, result)
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
                    cid = state.client_id  # a client may only preload its own id; an internal caller may use the declared one
                    if cid and cid.startswith("cli_") and await read("get_price", get_price, {"client_id": cid, "product_id": pid}) is not None:
                        filled += 1
        elif route.intent in ("client", "order"):
            args = {"query": query, "types": ["client"]}
            hits = await read("search", search, args)
            if hits:
                filled += 1
                cid = state.client_id
                if who.role != "client":  # an internal caller may search a name; a client must stay on its own id
                    cid = cid or next((h.get("id") for h in hits if str(h.get("id", "")).startswith("cli_")), None)
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


async def preload_when_ready(route_task: asyncio.Task, state: TurnState, caller) -> int:
    """Await the background route (bounded) then preload. Called as a background task itself."""
    try:
        route = await asyncio.wait_for(route_task, JEV_TIMEOUT_S + 0.3)
    except Exception:
        return 0
    return await preload_for_route(route, state, caller)


# ── guards, executed inside agent/access.py::execute_tool (no global mutation) ──


class _ClaimCaller:
    """A caller whose provenance also carries 'unverified' (history.py builds tags from .provenance)."""

    def __init__(self, base, tag: str = "unverified"):
        self._base, self._tag = base, tag

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)

    @property
    def provenance(self) -> str:
        return f"{self._base.provenance}:{self._tag}"


async def guard_tool(name: str, args: dict, ctx) -> tuple[dict, bool]:
    """Return (validated-ish args, claim_detected). Raise PermissionError to ask again.

    No key → the caller (execute_with_guards) skips this entirely: existing behaviour untouched.
    """
    out = dict(args or {})
    claim = False
    if name == "confirm_order":
        recap = _last_assistant_text(getattr(ctx, "messages", None))
        answer = _last_user_text(getattr(ctx, "messages", None))
        if recap and not await confirm_action(recap, answer):
            raise PermissionError("Confirmation non obtenue : je te redemande « c'est bon ? » avant de confirmer la commande.")
    elif name in ("log_client_event", "save_context"):
        text = " ".join((str(out.get("title") or ""), str(out.get("description") or out.get("body") or ""))).strip()
        p = await _claim_probability(
            text,
            {"role": ctx.caller.role, "client_id": ctx.caller.client_id, "type": out.get("type") or out.get("kind")},
        )
        # Only tag financial/contractual claims as unverified; ordinary preferences or quality reports pass normally.
        if p is not None and p > CLAIM_THRESHOLD:
            claim = True
            if name == "save_context":
                out["tags"] = [*(out.get("tags") or []), "unverified"]
            elif out.get("severity") is None:
                out["severity"] = "low"
    return out, claim


async def execute_with_guards(tool, args: dict, ctx) -> Any:
    """The single entry point used by the agent loop: guards → cache → tool → cache/write invalidation."""
    if _client() is None:
        return await tool.run(args, ctx)  # no key: no routing, no preload, no new gate
    from app.policy import WRITE_TOOLS

    guarded, claim = await guard_tool(tool.name, args, ctx)
    if tool.name in CACHEABLE:
        hit = cache_get(tool.name, guarded, ctx.caller)
        if hit is not None:
            return hit
    run_ctx = ctx
    if claim and tool.name == "log_client_event":  # this tool has no `tags` argument: tag via its provenance
        run_ctx = dataclasses.replace(ctx, caller=_ClaimCaller(ctx.caller))
    result = await tool.run(guarded, run_ctx)
    if tool.name in CACHEABLE:
        cache_put(tool.name, guarded, ctx.caller, result)
    if tool.name in WRITE_TOOLS:
        clear_cache()  # a stale stock / price must never survive a write
    return result


async def clarify_hints(heard: str, client_id: str | None, caller, *, spoken: bool = False) -> str:
    """Resolver hints for typed turns (spoken turns already ran annotate()). Starts with HINT_MARK."""
    if spoken:
        return ""
    from app.lexicon.resolver import Candidate, Mention, format_hints
    from app.lexicon.runtime import READY_WAIT_S, analyse
    from app.lexicon.store import store

    try:
        if not await store.ready(READY_WAIT_S):
            return ""
        mentions, usual, _ = await analyse(heard, client_id, use_jev=False)
        resolved: list[Mention] = []
        for m in mentions:
            if m.status != "ambiguous":
                resolved.append(m)
                continue
            rm = ResolvedMention(
                heard=m.surface,
                candidates=[
                    {"id": c.entry.eid or c.entry.label, "label": c.entry.label, "type": c.entry.etype, "score": c.score}
                    for c in m.candidates
                ],
                status=m.status,
            )
            settled = (await disambiguate_entities([rm]))[0]
            if settled.status == "resolved" and settled.candidates:
                top_id = settled.candidates[0]["id"]
                reordered = sorted(
                    m.candidates,
                    key=lambda c: 0 if (c.entry.eid or c.entry.label) == top_id else 1,
                )
                resolved.append(Mention(m.surface, m.start, m.end, "resolved", reordered, m.margin, settled.decided_by))
            else:
                resolved.append(Mention(m.surface, m.start, m.end, "ambiguous", m.candidates, m.margin, m.decided_by))
        hints = format_hints(resolved, usual)
        return f"{HINT_MARK}{hints}" if hints else ""
    except Exception as e:
        print(f"[jev] clarification ignorée ({type(e).__name__}: {e})", flush=True)
        return ""


async def on_final_transcript(conv, heard: str, *, spoken: bool = False) -> str:
    """THE single voice_session hook. Launches route/preload in the background; returns prompt hints.

    No key or role 'unknown' → "" and no side effect. The route is NEVER awaited on this path.
    """
    caller = getattr(conv, "caller", None)
    if _client() is None or caller is None or caller.role == "unknown" or not heard.strip():
        return ""
    state = TurnState(
        transcript=heard,
        client_id=getattr(conv, "client_id", None),
        role=caller.role,
        last_assistant_text=_last_assistant_text(getattr(conv, "history", None)),
    )
    route_task = asyncio.create_task(route_turn(heard, state))
    task = asyncio.create_task(preload_when_ready(route_task, state, caller))
    _tasks.append(task)
    if len(_tasks) > 64:
        _tasks[:] = [t for t in _tasks if not t.done()]
    return await clarify_hints(heard, state.client_id, caller, spoken=spoken)


__all__ = [
    "CACHE_TTL_S",
    "CLAIM_THRESHOLD",
    "HINT_MARK",
    "JEV_TIMEOUT_S",
    "MIN_CONFIDENCE",
    "YES_THRESHOLD",
    "ResolvedMention",
    "TurnRoute",
    "TurnState",
    "cache_get",
    "cache_put",
    "clarify_hints",
    "clear_cache",
    "confirm_action",
    "default_route",
    "disambiguate_entities",
    "execute_with_guards",
    "latency_stats",
    "on_final_transcript",
    "preload_for_route",
    "reset_latency",
    "route_turn",
    "score_claim",
]
