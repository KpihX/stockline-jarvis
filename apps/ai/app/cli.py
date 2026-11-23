"""
Chat with the agent in the terminal — the same agent as POST /chat and WS /voice.

    uv run python -m app.cli            (chat mode)
    uv run python -m app.cli --voice    (short spoken-style answers)
    uv run python -m app.cli --role client --client cli_0082   (talk as another identity: unknown | client | sales | direction)

Commands: /reset clears the conversation, /exit quits.
"""

import asyncio
import json
import sys

from app.agent import run_agent
from app.clients import get_llm_client
from app.policy import Caller
from app.schemas import ChatMessage, DoneEvent, ErrorEvent, TextEvent, ToolCallEvent, ToolResultEvent
from app.tools import all_tools


def dim(s: str) -> str:
    return f"\x1b[2m{s}\x1b[0m"


async def main() -> None:
    mode = "voice" if "--voice" in sys.argv else "chat"
    # The terminal is the operator's: management access unless told otherwise (--role unknown | client --client cli_0082 | sales | direction)
    arg = lambda name, default=None: next((sys.argv[i + 1] for i, a in enumerate(sys.argv[:-1]) if a == name), default)  # noqa: E731
    caller = Caller.declare(arg("--role", "direction"), arg("--client"), "CLI")
    llm = get_llm_client()
    messages: list[ChatMessage] = []
    print(dim(f"llm={llm.provider}:{llm.model} mode={mode} — /reset, /exit"))
    while True:
        try:
            line = (await asyncio.to_thread(input, "\nvous › ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if line == "/exit":
            break
        if line == "/reset":
            messages = []
            print(dim("(conversation effacée)"))
            continue
        if not line:
            continue
        messages.append(ChatMessage(role="user", content=line))
        print("agent › ", end="", flush=True)
        async for ev in run_agent(messages, llm=llm, tools=all_tools(), mode=mode, actor_name="CLI", caller=caller):
            match ev:
                case TextEvent(delta=delta):
                    print(delta, end="", flush=True)
                case ToolCallEvent(call=call):
                    print(dim(f"\n  → {call.name} {json.dumps(call.arguments, ensure_ascii=False)}"))
                case ToolResultEvent(ok=ok, ms=ms, result=result):
                    print(dim(f"  ← {'ok' if ok else 'ERREUR'} {ms}ms {json.dumps(result, ensure_ascii=False)[:160]}"))
                case DoneEvent(ms=ms, usage=usage):
                    cache = f", cache lu {usage.cache_read_input_tokens} / écrit {usage.cache_creation_input_tokens or 0}" if usage.cache_read_input_tokens is not None else ""
                    print(dim(f"\n  ({ms}ms, {usage.input_tokens or 0}→{usage.output_tokens or 0} tokens{cache})"))
                case ErrorEvent(message=message):
                    print(f"\n[erreur] {message}")


if __name__ == "__main__":
    asyncio.run(main())
