"""
Sessions & Assistant/Voix unification.

The SQLite store of `services/memory.py` is the ONLY source of truth for a conversation's history. The browser sends
just a sessionId + the new message: here the history is rebuilt from the store, the turn is run, then committed back.
Both surfaces (POST /chat and WS /voice) therefore continue the same `Conversation` — even across an uvicorn reload.

Pure helpers (titles, accent-folded search, access scope) live here too, so they can be tested without a database.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, Literal

from app.agent import run_agent
from app.agent.prompts import build_session_block
from app.clients import get_llm_client
from app.policy import Caller, UNKNOWN
from app.schemas import ChatMessage, ChatStreamEvent, ErrorEvent, ToolResultEvent
from app.tools import all_tools

from . import memory
from .voice_session import Conversation, conversations

ORDER_ID = re.compile(r"\bord_\d+\b")
ANY_ID = re.compile(r"\b(?:ord|cli|prd|ctx)_\d+\b")
DEFAULT_TITLE = "Nouvelle session"


# ── pure logic ────────────────────────────────────────────────────────────────────────────────────────────────────────


def fold(text: str) -> str:
    """Strip accents and case: 'élève' and 'eleve' match (French full-text search)."""
    return "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).lower()


def clip(text: str, n: int = 180) -> str:
    one = " ".join((text or "").split())
    return one if len(one) <= n else one[: n - 1].rstrip() + "…"


def auto_title(text: str, caller: Caller | None = None) -> str:
    """Short deterministic French title from the first useful message (or the client / order mentioned)."""
    raw = clip((text or "").split("\n\n[", 1)[0], 200).strip(" ,.;:!?")
    ids = ANY_ID.findall(raw)
    core = re.sub(r"^(bonjour|bonsoir|salut|allo|coucou)\b[ ,.!]*", "", raw, flags=re.I).strip(" ,.;:!?")
    if len(core) >= 4:
        title = core
    elif ids:
        title = f"Commande {ids[0]}" if ids[0].startswith("ord_") else f"Client {ids[0]}"
    elif caller is not None and caller.client_id:
        title = f"Client {caller.client_id}"
    else:
        title = DEFAULT_TITLE
    if len(title) > 44:
        title = title[:44].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return title or DEFAULT_TITLE


def visible(summary: dict, caller: Caller) -> bool:
    """Same scope as policy.py: internal sees all, client/supplier only their own, unknown only unknown sessions."""
    if caller.internal:
        return True
    if caller.role == "client":
        return summary.get("role") == "client" and summary.get("clientId") == caller.client_id
    if caller.role == "supplier":
        return summary.get("role") == "supplier" and summary.get("supplierId") == caller.supplier_id
    return summary.get("role") in (None, "unknown")


def note_commands(conv: Conversation, result: Any) -> None:
    """Remember order ids returned by a tool (used by the list, recall and the prompt tail)."""
    conv.command_ids = list(conv.command_ids or [])
    for oid in ORDER_ID.findall(json.dumps(result, ensure_ascii=False, default=str)):
        if oid not in conv.command_ids:
            conv.command_ids.append(oid)


# ── storage helpers (memory.py owns the database) ────────────────────────────────────────────────────────────────────


def new_id() -> str:
    return f"sess_{uuid.uuid4().hex[:12]}"


def get(sid: str | None, *, caller: Caller | None = None, actor_name: str | None = None,
        surface: Literal["chat", "voice"] | None = None, create: bool = True) -> Conversation | None:
    """In-memory registry → SQLite → new conversation. A different declared identity wipes the previous history (as /voice does)."""
    conv = conversations.get(sid or "") or memory.restore(Conversation, sid or "")
    if conv is None:
        return Conversation(id=sid or new_id(), created_at=time.time(), caller=caller or UNKNOWN, surface=surface) if create else None
    if caller is not None and caller != UNKNOWN and conv.caller != caller:
        conv.caller, conv.history, conv.session_block, conv.client_id, conv.facts = caller, [], None, caller.client_id, {}
    if not conv.surface and surface:
        conv.surface = surface
    if not conv.created_at:
        conv.created_at = time.time()
    if actor_name:
        conv.actor_name = actor_name
    conversations[conv.id] = conv  # both surfaces must see the same live object
    return conv


def _iso(ts: float) -> str:
    try:
        return datetime.fromtimestamp(float(ts), UTC).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError, OSError):
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _caller_of(meta: dict) -> Caller:
    raw = meta.get("caller")
    if isinstance(raw, dict) and isinstance(raw.get("__dataclass__"), dict):
        d = raw["__dataclass__"]
        if d.get("verified"):
            return Caller.verified_account({
                "id": d.get("account_id"),
                "role": d.get("role"),
                "entityId": d.get("client_id") or d.get("supplier_id"),
                "displayName": d.get("actor_name"),
            })
        return Caller.declare(d.get("role"), d.get("client_id"), d.get("actor_name"), supplier_id=d.get("supplier_id"))
    return UNKNOWN


def _text_of(history: list[ChatMessage]) -> str:
    return " ".join(m.content for m in history if isinstance(m.content, str))


def _summary(sid: str, updated: float, meta: dict, history: list[ChatMessage]) -> dict:
    caller = _caller_of(meta)
    preview = ""
    for m in reversed(history):
        if m.role in ("user", "assistant") and m.content.strip():
            preview = clip(m.content, 160)
            break
    commands = list(meta.get("command_ids") or [])
    for oid in ORDER_ID.findall(json.dumps([m.content for m in history if m.role == "tool"], ensure_ascii=False)):
        if oid not in commands:
            commands.append(oid)
    return {
        "id": sid,
        "title": meta.get("title") or auto_title(_text_of(history)[:200]),
        "createdAt": _iso(meta.get("created_at") or updated),
        "updatedAt": _iso(updated),
        "surface": meta.get("surface"),
        "turns": int(meta.get("turns") or sum(1 for m in history if m.role == "user")),
        "clientId": caller.client_id,
        "supplierId": caller.supplier_id,
        "role": caller.role,
        "actorName": caller.actor_name,
        "commandIds": commands,
        "preview": preview,
        "pendingQuestion": clip((meta.get("facts") or {}).get("pending") or "", 160),
    }


def _from_row(row: tuple) -> tuple[dict, list[ChatMessage]]:
    sid, updated, meta_json, history_json = row
    meta = json.loads(meta_json) if meta_json else {}
    try:
        history = [ChatMessage.model_validate(m) for m in json.loads(history_json)]
    except (ValueError, TypeError):
        history = []
    return _summary(sid, updated, meta, history), history


def _rows() -> list[tuple]:
    return memory.get_store().run(
        lambda db: db.execute("SELECT id, updated, meta, history FROM sessions ORDER BY updated DESC").fetchall(), []
    )


def list_sessions(q: str = "", caller: Caller = UNKNOWN, *, role: str | None = None, client_id: str | None = None,
                  surface: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    """Recent first, accent-folded full-text on title + messages, scope-filtered, paginated."""
    terms = fold(q).split()
    out: list[dict] = []
    for row in _rows():
        s, history = _from_row(row)
        if role and s["role"] != role:
            continue
        if client_id and s["clientId"] != client_id:
            continue
        if surface and s["surface"] != surface:
            continue
        if not visible(s, caller):
            continue
        if terms:
            hay = fold(s["title"] + " " + _text_of(history))
            if not all(term in hay for term in terms):
                continue
        out.append(s)
    return out[max(0, offset) : max(0, offset) + max(0, min(limit, 200))]


def detail(sid: str, caller: Caller = UNKNOWN) -> dict | None:
    """One session: metadata + summarised messages + compact facts. None when unknown or out of scope."""
    conv = get(sid, create=False)
    if conv is None:
        return None
    s = _summary(conv.id, time.time(), memory.snapshot(conv), conv.history)
    if not visible(s, caller):
        return None
    facts = conv.facts or {}
    messages = []
    for m in conv.history:
        text = f"{m.name or 'outil'} : {clip(m.content, 160)}" if m.role == "tool" else clip(m.content, 320)
        messages.append({"role": m.role, "text": text, "name": m.name})
    return {
        **s,
        "messages": messages,
        "facts": {
            "client": facts.get("caller"),
            "commandes": s["commandIds"] or list((facts.get("orders") or {}).keys()),
            "actions": (facts.get("actions") or [])[-5:],
            "questionsEnAttente": facts.get("pending") or "",
        },
    }


def compact(d: dict) -> dict:
    """What the agent tools receive: a few lines, not a transcript."""
    return {
        "id": d["id"], "titre": d["title"], "date": d["updatedAt"][:10],
        "surface": d["surface"], "client": d["clientId"],
        "commandes": d["facts"]["commandes"][:5],
        "decisions": d["facts"]["actions"][:4],
        "questionsEnAttente": d["facts"]["questionsEnAttente"],
    }


def create_session(title: str | None = None, surface: str | None = None, caller: Caller = UNKNOWN) -> dict:
    conv = Conversation(id=new_id(), title=clip(title, 80) if title else DEFAULT_TITLE, surface=surface,  # type: ignore[arg-type]
                        caller=caller, created_at=time.time())
    memory.persist(conv, conversations)
    conversations[conv.id] = conv
    return detail(conv.id, caller)  # type: ignore[return-value]


def rename(sid: str, title: str, caller: Caller = UNKNOWN) -> dict | None:
    conv = get(sid, create=False)
    if conv is None or not visible(_summary(conv.id, 0, memory.snapshot(conv), conv.history), caller):
        return None
    conv.title = clip(title, 80) or DEFAULT_TITLE
    memory.persist(conv, conversations)
    return detail(sid, caller)


def remove(sid: str, caller: Caller = UNKNOWN) -> bool:
    conv = get(sid, create=False)
    if conv is None or not visible(_summary(conv.id, 0, memory.snapshot(conv), conv.history), caller):
        return False
    memory.forget(conv)
    conversations.pop(sid, None)
    return True


def reopen(sid: str, caller: Caller = UNKNOWN) -> dict | None:
    """'Continuer' = load the session back into the live registry and return it (no new id, history preserved)."""
    return detail(sid, caller)


def with_recent_block(block: str, caller: Caller, exclude_sid: str | None = None) -> str:
    """2–3 lines appended at the END of the system prompt when the client is known. Frozen with the session block → cache stable."""
    if caller.client_id is None:
        return block
    lines: list[str] = []
    for s in list_sessions(caller=caller, client_id=caller.client_id, limit=8):
        if s["id"] == exclude_sid:
            continue
        bits = [f"- {s['title']}", s["updatedAt"][:10]]
        if s["commandIds"]:
            bits.append("commandes " + ", ".join(s["commandIds"][:3]))
        if s["pendingQuestion"]:
            bits.append("en attente : " + s["pendingQuestion"])
        lines.append(" ".join(bits))
        if len(lines) == 3:
            break
    if not lines:
        return block
    tail = "# Dernières sessions de ce client\n" + "\n".join(lines)
    return f"{block}\n\n{tail}" if block else tail


def recall(query: str, caller: Caller) -> list[dict]:
    return [compact(d) for d in list_sessions(q=query, caller=caller, limit=8)]


# ── chat turn: the browser sends only {sessionId, messages:[new message]} ────────────────────────────────────────────


async def chat_turn(conv: Conversation, *, messages: list[ChatMessage], caller: Caller,
                    actor_name: str | None = None, mode: str = "chat", current_path: str | None = None) -> AsyncIterator[ChatStreamEvent]:
    """Run one chat turn on the server-owned history and commit it (same store, same Conversation as /voice)."""
    users = [m for m in messages if m.role == "user"]
    content = users[-1].content.strip() if users else ""
    if not content:
        yield ErrorEvent(message="Message vide.")
        return
    if current_path:
        content = f"{content}\n\n[Écran ouvert : {current_path}]"

    base = conv.history
    working = [*base, ChatMessage(role="user", content=content)]
    if not conv.title or conv.title == DEFAULT_TITLE:
        conv.title = auto_title(users[-1].content, caller)
    conv.turns = (conv.turns or 0) + 1
    llm = get_llm_client()
    if conv.session_block is None:
        conv.session_block = with_recent_block(await build_session_block(caller), caller, conv.id)

    try:
        async for ev in run_agent(working, llm=llm, tools=all_tools(), mode=mode,  # type: ignore[arg-type]
                                  actor_name=actor_name, caller=caller, session_block=conv.session_block):
            if isinstance(ev, ToolResultEvent) and ev.ok:
                note_commands(conv, ev.result)
            yield ev
    finally:
        # Also runs on client disconnect (StreamingResponse closes the generator): keep what happened, as /voice does.
        memory.commit(conv, base, working, conversations)
        memory.background(memory.compact_later(conv, llm, conversations))
