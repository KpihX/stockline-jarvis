"""
Conversation compaction: replace the OLD turns of a long call by one short summary message, keep the last turns verbatim.

Why not just cut at 40 messages: the model would forget the client, the order it is building, the prices it quoted.
What must survive is business FACTS, not chatter. So the summary is built (deterministically, pure Python, ~1 ms) from the
tool calls / results (ids, orders and their lines, prices, actions and errors) and from short extracts of what the caller asked.

    history = [summary (user), "Bien noté." (assistant), turn k, …, turn n]        ← after compaction
              └── one cache-stable head: it changes only when a compaction happens (every few turns, not every turn)

  - The summary lives in `messages`, never in the system prompt: the cached prompt prefix (tools + system) is untouched and
    the cache breakpoint on the LAST block keeps working (a compaction re-writes the cache of the conversation once, then it is
    stable again until the next one; hysteresis: compact above TRIGGER turns, back down to KEEP turns).
  - Cuts are made on turn boundaries (a user message), so a tool call is never separated from its result.
  - `facts` (a plain JSON dict) is carried by the conversation and persisted with it: a second compaction merges the new old
    turns into it instead of re-reading the previous summary text.
  - What the caller SAYS is reported as said, never as verified: only tool results are facts.
  - An optional LLM refinement (flag, default OFF) exists, validated so that it can only compress, never drop an id.

Pure functions, no I/O (the refinement takes the LLM client as an argument).
"""

import json
import re
from dataclasses import dataclass
from typing import Any

from app.agent.sanitize import sanitize_history
from app.schemas import ChatMessage

SUMMARY_MARK = "[Résumé de l'appel"
SUMMARY_ACK = "Bien noté."
HINT_MARK = "\n\n[Lexique"  # the spoken-turn lexicon block (lexicon/runtime.py): not the caller's words, not worth keeping

ID = re.compile(r"\b[a-z]{2,4}_\d{3,}\b")  # cli_0082, prd_0031, ord_0345…
NUMBERISH = re.compile(r"\d|euro|€|prix|tarif|kilo|\bkg\b|caisse|pièce|demain|lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|semaine|livr", re.I)
READ_PREFIXES = ("get_", "search", "find_", "resolve_", "identify_", "list_")

# size limits of the summary (it is re-read at every model call: keep it small)
MAX_ASKS, MAX_CLAIMS, MAX_ANNOUNCED, MAX_ACTIONS, MAX_LOOKUPS = 8, 8, 5, 14, 8
TEXT_MAX = 170
SUMMARY_MAX_CHARS = 3200


@dataclass(frozen=True)
class Policy:
    keep_turns: int = 6  # last turns kept verbatim
    trigger_turns: int = 12  # compact when there are more turns than this (hysteresis: one cache rewrite per ~6 turns)
    max_chars: int = 48_000  # …or when the history is bigger than this (≈ 12k tokens) and has more than keep_turns turns


# ── structure ──


def is_summary(m: ChatMessage) -> bool:
    return m.role == "user" and m.content.startswith(SUMMARY_MARK)


def split_head(history: list[ChatMessage]) -> tuple[list[ChatMessage], list[ChatMessage]]:
    """([summary, ack] or [], the rest)."""
    if len(history) >= 2 and is_summary(history[0]) and history[1].role == "assistant" and not history[1].tool_calls:
        return history[:2], history[2:]
    return [], history


def split_turns(messages: list[ChatMessage]) -> list[list[ChatMessage]]:
    """Turns = a user message and everything up to the next user message (assistant steps and their tool results included)."""
    turns: list[list[ChatMessage]] = []
    for m in messages:
        if m.role == "user" or not turns:
            turns.append([m])
        else:
            turns[-1].append(m)
    return turns


def size(messages: list[ChatMessage]) -> int:
    return sum(len(m.content) + sum(len(json.dumps(c.arguments, ensure_ascii=False)) for c in (m.tool_calls or [])) for m in messages)


def needs_compaction(history: list[ChatMessage], policy: Policy = Policy()) -> bool:
    _, rest = split_head(history)
    n = len(split_turns(rest))
    return n > policy.trigger_turns or (n > policy.keep_turns and size(rest) > policy.max_chars)


# ── extraction ──


def clip(text: str, n: int = TEXT_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def caller_words(m: ChatMessage) -> str:
    return clip(m.content.split(HINT_MARK, 1)[0])


def parse(content: str) -> Any:
    try:
        return json.loads(content)
    except (ValueError, TypeError):
        return None


def is_write(tool: str) -> bool:
    return not tool.startswith(READ_PREFIXES)


def label_of(d: dict) -> str | None:
    value = d.get("name") or d.get("label") or d.get("number") or d.get("productName")
    return clip(str(value), 60) if value else None


def walk(value: Any, labels: dict[str, str]) -> None:
    """Every `{id: "cli_…", name|label|number}` in a tool result, plus `productId`/`productName` pairs of order lines."""
    if isinstance(value, dict):
        ident = value.get("id")
        if isinstance(ident, str) and ID.fullmatch(ident) and (lab := label_of(value)):
            labels.setdefault(ident, lab)
        pid = value.get("productId")
        if isinstance(pid, str) and ID.fullmatch(pid) and value.get("productName"):
            labels.setdefault(pid, clip(str(value["productName"]), 60))
        for v in value.values():
            walk(v, labels)
    elif isinstance(value, list):
        for v in value:
            walk(v, labels)


def order_state(o: dict) -> dict:
    """The latest known state of an order, from an order tool result: what the ERP said, not what anyone claimed."""
    lines = [
        {k: line[k] for k in ("productId", "productName", "qty", "unit", "unitPrice", "note") if line.get(k) not in (None, "")}
        for line in (o.get("lines") or [])
        if isinstance(line, dict)
    ]
    out = {k: o[k] for k in ("number", "status", "client", "deliveryDate", "totalHt") if o.get(k) not in (None, "")}
    out["lines"] = lines
    if o.get("warnings"):
        out["warnings"] = [clip(str(w), 110) for w in o["warnings"][:2]]
    return out


def scalars(value: Any, limit: int = 6) -> str:
    """`k=v` of the first scalar fields of a result (a price, a stock, a status), on one short line."""
    if isinstance(value, list):
        value = value[0] if value else {}
    if not isinstance(value, dict):
        return clip(str(value), 80)
    items = [f"{k}={v}" for k, v in value.items() if isinstance(v, (str, int, float, bool)) and v not in ("", None)]
    return clip(", ".join(items[:limit]), 150)


def args_text(args: dict) -> str:
    return ", ".join(
        f"{k}={clip(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False), 40)}" for k, v in args.items() if v not in (None, "", [])
    )


def new_facts() -> dict:
    return {"caller": None, "labels": {}, "orders": {}, "actions": [], "lookups": [], "asks": [], "claims": [], "announced": [], "pending": ""}


def extract(turns: list[list[ChatMessage]], facts: dict | None = None) -> dict:
    """Fold turns into `facts` (a new dict; the input is not modified). Later information wins over earlier."""
    facts = json.loads(json.dumps(facts)) if facts else new_facts()
    for key, default in new_facts().items():
        facts.setdefault(key, default)
    labels: dict[str, str] = {}
    chosen: set[str] = set()  # ids the model actually used in a tool call: those matter, the other search candidates do not
    for turn in turns:
        calls = {c.id: c for m in turn for c in (m.tool_calls or [])}
        for m in turn:
            if m.role == "user":
                words = "" if is_summary(m) else caller_words(m)
                if words and NUMBERISH.search(words):  # figures, prices, dates, quantities: kept, but as unverified declarations
                    facts["claims"].append(words)
                elif words and calls:  # a request that made the agent use a tool (the rest of a turn without any is chatter)
                    facts["asks"].append(words)
            elif m.role == "assistant" and m.tool_calls:
                for c in m.tool_calls:
                    chosen.update(ID.findall(json.dumps(c.arguments, ensure_ascii=False)))
                    cid = c.arguments.get("client_id") or c.arguments.get("clientId")
                    if isinstance(cid, str) and cid.startswith("cli_"):
                        facts["caller"] = cid
            elif m.role == "assistant":
                if m.content.strip():
                    if NUMBERISH.search(m.content):  # what the agent told the caller about figures / dates (a quote, a recap): kept as announced
                        facts["announced"].append(clip(m.content, 200))
                    facts["pending"] = clip(re.split(r"(?<=[.!])\s+", m.content.strip())[-1], 160) if m.content.strip().endswith("?") else ""
            elif m.role == "tool":
                result, call = parse(m.content), calls.get(m.tool_call_id or "")
                name = m.name or (call.name if call else "?")
                walk(result, labels)
                failed = isinstance(result, dict) and "error" in result
                if isinstance(result, dict) and str(result.get("id", "")).startswith("ord_") and result.get("lines") is not None:
                    facts["orders"][result["id"]] = order_state(result)
                    chosen.add(result["id"])
                if name in ("get_client", "identify_caller") and isinstance(result, dict) and str(result.get("id", "")).startswith("cli_"):
                    facts["caller"] = result["id"]
                    chosen.add(result["id"])
                call_text = f"{name}({args_text(call.arguments) if call else ''})"
                if is_write(name):
                    facts["actions"].append(call_text + (f" → ERREUR : {clip(str(result.get('error')), 90)}" if failed else " → ok"))
                elif name in ("get_price", "get_product_stock", "find_alternatives") and not failed:
                    facts["lookups"] = [x for x in facts["lookups"] if not x.startswith(call_text)]
                    facts["lookups"].append(f"{call_text} → {scalars(result)}")
    facts["labels"].update({i: lab for i, lab in labels.items() if i in chosen})
    for key, cap in (("asks", MAX_ASKS), ("claims", MAX_CLAIMS), ("announced", MAX_ANNOUNCED), ("actions", MAX_ACTIONS), ("lookups", MAX_LOOKUPS)):
        facts[key] = facts[key][-cap:]
    # keep only the labels of what the summary still mentions (orders, caller, actions, lookups): it stays small
    mentioned = set(ID.findall(json.dumps([facts["orders"], facts["caller"], facts["actions"], facts["lookups"]], ensure_ascii=False)))
    facts["labels"] = {i: lab for i, lab in facts["labels"].items() if i in mentioned}
    return facts


# ── rendering ──


def named(ident: str, labels: dict[str, str]) -> str:
    return f"{labels[ident]} ({ident})" if ident in labels else ident


def render(facts: dict) -> str:
    labels = facts.get("labels") or {}
    out = [f"{SUMMARY_MARK} jusqu'ici : faits repris des outils, déclarations de l'appelant non vérifiées, le reste de l'échange est supprimé.]"]
    if facts.get("caller"):
        out.append(f"Client concerné : {named(facts['caller'], labels)}")
    for oid, o in (facts.get("orders") or {}).items():
        head = " · ".join(str(o[k]) for k in ("number", "status", "client", "deliveryDate") if o.get(k)) or "?"
        total = f", total HT {o['totalHt']}" if o.get("totalHt") is not None else ""
        lines = "; ".join(
            f"{ln.get('qty')} {ln.get('unit', '')} {ln.get('productName', '')} [{ln.get('productId', '')}]"
            + (f" à {ln['unitPrice']}" if ln.get("unitPrice") is not None else "")
            + (f" ({ln['note']})" if ln.get("note") else "")
            for ln in o.get("lines") or []
        )
        out.append(f"Commande {oid} : {head}{total}. Lignes : {lines or 'aucune'}")
        if o.get("warnings"):
            out.append("  alertes : " + " | ".join(o["warnings"]))
    if facts.get("actions"):
        out.append("Actions ERP (dans l'ordre) : " + " ; ".join(facts["actions"]))
    if facts.get("lookups"):
        out.append("Constats : " + " ; ".join(facts["lookups"]))
    if facts.get("asks"):
        out.append("L'appelant a demandé : " + " | ".join(facts["asks"]))
    if facts.get("claims"):
        out.append("L'appelant a dit (chiffres, dates, prix ; NON vérifié) : " + " | ".join(facts["claims"]))
    if facts.get("announced"):
        out.append("L'agent a annoncé (chiffres, dates) : " + " | ".join(facts["announced"]))
    if facts.get("pending"):
        out.append(f"Question restée en attente : {facts['pending']}")
    text = "\n".join(out)
    return text if len(text) <= SUMMARY_MAX_CHARS else text[: SUMMARY_MAX_CHARS - 1].rstrip() + "…"


def summary_messages(text: str) -> list[ChatMessage]:
    return [ChatMessage(role="user", content=text), ChatMessage(role="assistant", content=SUMMARY_ACK)]


# ── compaction ──


def compact(history: list[ChatMessage], facts: dict | None = None, policy: Policy = Policy()) -> tuple[list[ChatMessage], dict, int]:
    """(new history, new facts, number of messages folded). Unchanged when there is nothing to fold."""
    head, rest = split_head(history)
    facts = facts if head else None  # facts describe the summary at the head of the history: no summary (new / reset / new identity) = no facts
    turns = split_turns(rest)
    if len(turns) <= policy.keep_turns:
        return history, facts or new_facts(), 0
    old, kept = turns[: -policy.keep_turns], turns[-policy.keep_turns :]
    new = extract(old, facts)
    tail = [m for t in kept for m in t]
    out = sanitize_history([*summary_messages(render(new)), *tail])
    return out, new, sum(len(t) for t in old) + len(head)


def ids_in(text: str) -> set[str]:
    return set(ID.findall(text))


REFINE_SYSTEM = (
    "Tu condenses le résumé d'un appel de prise de commande pour un grossiste. Réécris-le en moins de 1200 caractères, en français, "
    "sans rien inventer. Garde TOUS les identifiants (cli_…, prd_…, ord_…), nombres, prix, quantités, dates, noms propres, les actions "
    "faites, les erreurs et la question en attente. Supprime le bavardage et les répétitions. Réponds uniquement par le résumé, "
    f"qui commence par « {SUMMARY_MARK} »."
)


async def refine(llm, text: str) -> str | None:
    """Optional LLM pass over the deterministic summary. Returns the refined text only if it is valid: starts with the mark, shorter,
    and every id of the original is still there. Anything else (provider error, dropped id) → None: the deterministic summary stays."""
    from app.clients import LLMRequest, LLMText  # local: this module stays importable without the provider layer

    try:
        reply = ""
        async for ev in llm.stream(LLMRequest(system=REFINE_SYSTEM, messages=[ChatMessage(role="user", content=text)], max_tokens=600)):
            if isinstance(ev, LLMText):
                reply += ev.delta
    except Exception:
        return None
    reply = reply.strip()
    ok = reply.startswith(SUMMARY_MARK) and 0 < len(reply) < len(text) and ids_in(text) <= ids_in(reply)
    return reply if ok else None
