"""
The agent loop — the heart of the service.

    system prompt + conversation ──► model ──► text? ──────────────► stream it ──► done
                                       │
                                       └► tool calls ─► run them (ERP API) ─► append results ─► model again …

`run_agent` is an async generator of ChatStreamEvent: exactly the events POST /chat streams.
It APPENDS the new assistant / tool messages to `messages`, so a caller that keeps that list
(voice session, CLI) keeps the full history, including the ids returned by tools.

Interrupting: cancel the task that iterates it (asyncio). Nothing is yielded after a cancellation.
"""

import asyncio
import json
import time
import traceback
from collections.abc import AsyncIterator

from app.clients import LLMClient, LLMRequest, LLMText, LLMToolCall, LLMToolStart, LLMUsage
from app.config import settings
from app.policy import UNKNOWN, AccessDenied, Caller
from app.schemas import (
    ChatMessage,
    ChatMode,
    ChatStreamEvent,
    DoneEvent,
    ErrorEvent,
    TextEvent,
    ToolCall,
    ToolCallEvent,
    ToolResultEvent,
    ToolStartEvent,
    Usage,
)
from app.tools import ErpClient, Tool, ToolContext

from .access import enforce, guard_result
from .prompts import build_session_block, build_system_prompt

GIVE_UP = "Désolé, je n'ai pas réussi à aller au bout. Pouvez-vous reformuler ?"


async def run_agent(
    messages: list[ChatMessage],  # conversation so far, ending with the user's message (no system message)
    *,
    llm: LLMClient,
    tools: list[Tool],
    mode: ChatMode = "chat",  # command = single turn, act-first
    actor_name: str | None = None,
    max_steps: int | None = None,
    caller: Caller | None = None,  # WHO is on the line (declared identity). None = unknown: the safest role, enforced by app/policy.py
    session_block: str | None = None,  # the per-session prompt tail if the caller already built (and froze) it, else it is built here
    announce_tools: bool = False,  # also yield a ToolStartEvent as soon as the model starts a tool call (voice session: filler without waiting for the arguments)
) -> AsyncIterator[ChatStreamEvent | ToolStartEvent]:
    started = time.perf_counter()
    actor = "ai_chat" if mode == "chat" else "voice_agent"
    who = caller or UNKNOWN
    ctx = ToolContext(erp=ErpClient(actor, who.erp_name if caller else actor_name), actor=actor, messages=messages, caller=who)
    usage = Usage(input_tokens=0, output_tokens=0)

    try:
        system = await build_system_prompt(mode, actor_name, who)
        suffix = session_block if session_block is not None else await build_session_block(who)
        request = LLMRequest(system=system, messages=messages, tools=[t.info for t in tools], system_suffix=suffix)
        said_something = False

        for _step in range(max_steps or settings.max_steps):
            # 1. Ask the model. Stream the text as it comes; collect the tool calls.
            text = ""
            calls: list[ToolCall] = []
            async for ev in llm.stream(request):
                match ev:
                    case LLMText(delta=delta):
                        # keep words apart when the model speaks again after a tool call
                        shown = f" {delta}" if said_something and not text and not delta[:1].isspace() else delta
                        text += delta
                        yield TextEvent(delta=shown)
                    case LLMToolStart(name=name, id=call_id):
                        if announce_tools:
                            yield ToolStartEvent(name=name, call_id=call_id)
                    case LLMToolCall(call=call):
                        calls.append(call)
                        yield ToolCallEvent(call=call)
                    case LLMUsage(input_tokens=i, output_tokens=o, cache_creation_input_tokens=cw, cache_read_input_tokens=cr):
                        usage.input_tokens += i or 0
                        usage.output_tokens += o or 0
                        if cw is not None:
                            usage.cache_creation_input_tokens = (usage.cache_creation_input_tokens or 0) + cw
                        if cr is not None:
                            usage.cache_read_input_tokens = (usage.cache_read_input_tokens or 0) + cr
            said_something = said_something or bool(text)

            # 2. No tool call → that was the final answer.
            if not calls:
                message = ChatMessage(role="assistant", content=text)
                messages.append(message)
                yield DoneEvent(message=message, usage=usage, ms=ms_since(started))
                return

            # 3. Run the tools (in parallel), append the results, loop.
            messages.append(ChatMessage(role="assistant", content=text, tool_calls=calls))
            results = await asyncio.gather(*(execute_tool(call, tools, ctx) for call in calls))
            for r in results:
                messages.append(ChatMessage(role="tool", tool_call_id=r.call_id, name=r.name, content=to_json(r.result)))
                yield r

        # Safety net: the model kept calling tools.
        message = ChatMessage(role="assistant", content=GIVE_UP)
        messages.append(message)
        yield TextEvent(delta=GIVE_UP)
        yield DoneEvent(message=message, usage=usage, ms=ms_since(started))
    except Exception as e:  # provider down, bad key… (a cancellation is not an Exception: it just stops us)
        print("[agent] erreur pendant le tour :", flush=True)
        traceback.print_exc()
        yield ErrorEvent(message=str(e) or type(e).__name__)


async def execute_tool(call: ToolCall, tools: list[Tool], ctx: ToolContext) -> ToolResultEvent:
    """Run one tool call. Never raises: errors become `{"error": ...}` so the model can explain or retry."""
    started = time.perf_counter()
    tool = next((t for t in tools if t.name == call.name), None)
    try:
        if not tool:
            raise LookupError(f"Outil inconnu : {call.name}")
        await enforce(tool, call.arguments, ctx)  # the access policy: before anything runs, whatever the model was told or claims
        result = guard_result(ctx, call.name, await tool.run(call.arguments, ctx))
        try:  # a value the model can't read back (datetime, set, object…) is the tool's error, not the turn's
            to_json(result)
        except (TypeError, ValueError) as e:
            raise TypeError(f"résultat de {call.name} non sérialisable en JSON : {e}") from e
        ok = True
    except AccessDenied as e:  # not a failure: the role may not do this. The sentence is for the model to say.
        print(f"[access] refusé role={ctx.caller.role} client={ctx.caller.client_id} outil={call.name} : {e}", flush=True)
        ok, result = False, {"error": str(e), "denied": True}
    except Exception as e:
        print(f"[tool {call.name}] erreur :", flush=True)
        traceback.print_exc()
        ok, result = False, {"error": str(e) or type(e).__name__}
    return ToolResultEvent(call_id=call.id, name=call.name, ok=ok, result=result, ms=ms_since(started))


def ms_since(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000 + 0.5)


def to_json(value) -> str:
    """Compact JSON, accents kept (what the model reads back)."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
