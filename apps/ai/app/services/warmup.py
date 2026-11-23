"""
Warm connections and canned audio for the voice session (GUIDE-VOIX.md 4.7 and 4.9).

  - Fillers: a few short wait phrases ("Je regarde.") synthesised ONCE and kept as mp3 bytes, so the first sound of a
    tool turn costs no TTS call at the moment it is needed.
  - TTS warm-up: one tiny word, so the TLS connection to the provider is already open at the first real sentence.
  - LLM warm-up: a request with the real system prompt + tools and max_tokens=1 primes Anthropic's prompt cache (5-minute
    TTL; each hit refreshes it). A keep-alive loop repeats it while a session is open and the caller is active.

Everything is best effort: a failure is logged and never reaches the session. Nothing runs for the mock providers.
The functions take the clients as arguments (the voice session passes its own), they do not fetch them.
"""

import asyncio
import random
import time
from collections.abc import Callable
from contextlib import aclosing
from dataclasses import dataclass

from app.agent.prompts import build_session_block, build_system_prompt
from app.clients import LLMClient, LLMRequest, LLMUsage, TTSClient
from app.config import settings
from app.policy import UNKNOWN, Caller
from app.schemas import ChatMessage
from app.tools import Tool

FILLERS = ("Je regarde.", "Deux secondes.", "Je vérifie.", "Un instant.", "Je regarde ça.", "Je jette un œil.")
WARM_WORD = "Oui."
CACHE_TTL_S = 300  # Anthropic prompt cache, refreshed by every read
KEEPALIVE_S = 230  # ping when the cache has been idle this long (well inside the TTL)
KEEPALIVE_POLL_S = 15
KEEPALIVE_ACTIVE_WINDOW_S = 1800  # stop paying for pings once nobody has talked for 30 minutes
TTS_WARM_EVERY_S = 60


@dataclass(frozen=True)
class Clip:
    text: str
    mime: str
    data: bytes


_clips: dict[tuple, list[Clip]] = {}  # (tts name, voice, model) → synthesised fillers
_clips_lock = asyncio.Lock()
_last_filler: str | None = None
_llm_warm_at = float("-inf")  # monotonic time of the last request that (re)read or primed the prompt cache
_activity_at = float("-inf")  # last real turn
_tts_warm_at = float("-inf")


def _key(tts: TTSClient) -> tuple:
    return (tts.name, settings.tts.voice, settings.tts.model)


def cached_fillers(tts: TTSClient) -> list[Clip]:
    return _clips.get(_key(tts), [])


def choose_filler(clips: list[Clip] | None = None, rng: Callable = random.choice) -> Clip | str:
    """A filler that differs from the previous one: its cached clip when there is one, else its text (spoken by the TTS)."""
    global _last_filler
    pool = clips or [Clip(t, "", b"") for t in FILLERS]
    pool = [c for c in pool if c.text != _last_filler] or pool
    pick = rng(pool)
    _last_filler = pick.text
    return pick if pick.data else pick.text


async def _synthesize(tts: TTSClient, text: str) -> tuple[str, bytes]:
    result = await tts.synthesize(text, settings.tts.voice or None)
    async with aclosing(result.chunks) as chunks:  # type: ignore[type-var]
        return result.mime, b"".join([c async for c in chunks])


async def load_fillers(tts: TTSClient) -> None:
    """Synthesise the fillers once per (provider, voice, model). ~70 characters in total."""
    if tts.name == "mock" or cached_fillers(tts):
        return
    async with _clips_lock:
        if cached_fillers(tts):
            return
        clips = []
        for text in FILLERS:
            try:
                mime, data = await _synthesize(tts, text)
                if data:
                    clips.append(Clip(text, mime, data))
            except Exception as e:
                print(f"[warm-up] filler {text!r} not cached ({type(e).__name__}: {e})", flush=True)
        if clips:
            _clips[_key(tts)] = clips
            print(f"[warm-up] {len(clips)} fillers cached ({sum(len(c.data) for c in clips) // 1024} KB)", flush=True)


async def warm_tts(tts: TTSClient) -> None:
    global _tts_warm_at
    if tts.name == "mock" or time.monotonic() - _tts_warm_at < TTS_WARM_EVERY_S:
        return
    _tts_warm_at = time.monotonic()
    t = time.perf_counter()
    await _synthesize(tts, WARM_WORD)
    print(f"[warm-up] tts connection open ({int((time.perf_counter() - t) * 1000)} ms)", flush=True)


async def prime_llm(
    llm: LLMClient, tools: list[Tool], actor_name: str | None, *, force: bool = False,
    caller: Caller | None = None, session_block: str | None = None,  # the session's identity and frozen prompt tail (None: built from `caller`)
) -> None:
    """One request that is byte-identical to a real turn's prefix (system prompt + tools) with max_tokens=1: writes (or
    refreshes) the prompt cache and opens the connection. Skipped when the cache was touched less than KEEPALIVE_S ago."""
    global _llm_warm_at
    if llm.provider == "mock" or (not force and time.monotonic() - _llm_warm_at < KEEPALIVE_S):
        return
    before, _llm_warm_at = _llm_warm_at, time.monotonic()  # set first: concurrent sessions do not all ping
    t = time.perf_counter()
    usage = None
    try:
        request = LLMRequest(
            system=await build_system_prompt("voice", actor_name, caller),
            messages=[ChatMessage(role="user", content="Bonjour")],
            tools=[t.info for t in tools],
            max_tokens=1,
            system_suffix=session_block if session_block is not None else await build_session_block(caller or UNKNOWN),
        )
        async with aclosing(llm.stream(request)) as events:  # type: ignore[type-var]
            async for ev in events:
                if isinstance(ev, LLMUsage):
                    usage = ev
    except BaseException:
        _llm_warm_at = before  # it did not work: the next session may try again
        raise
    print(
        f"[warm-up] llm primed in {int((time.perf_counter() - t) * 1000)} ms"
        + (f" (cache read {usage.cache_read_input_tokens}, written {usage.cache_creation_input_tokens})" if usage else ""),
        flush=True,
    )


def touch() -> None:
    """A real turn just used the LLM: the cache TTL restarted and the caller is active."""
    global _llm_warm_at, _activity_at
    _llm_warm_at = _activity_at = time.monotonic()


async def keep_warm(
    llm: LLMClient, tools: Callable[[], list[Tool]], actor_name: Callable[[], str | None],
    identity: Callable[[], tuple[Caller, str | None]] | None = None,  # (declared identity, frozen prompt tail) of the session, read at each ping
) -> None:
    """While a session is open and the caller active, keep the Anthropic prompt cache alive. Cancelled when the session closes."""
    if llm.provider in ("mock", "nvidia", "deepseek", "openai", "openai-compatible", "gemini"):
        return  # only Anthropic has an explicit 5-min ephemeral cache TTL worth keeping alive
    while True:
        await asyncio.sleep(KEEPALIVE_POLL_S)
        now = time.monotonic()
        if now - _llm_warm_at >= KEEPALIVE_S and now - _activity_at < KEEPALIVE_ACTIVE_WINDOW_S:
            who = {} if identity is None else dict(zip(("caller", "session_block"), identity()))
            await safely("llm keep-alive", prime_llm(llm, tools(), actor_name(), **who))


async def safely(what: str, coro) -> None:
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as e:
        print(f"[warm-up] {what} failed: {type(e).__name__}: {e}", flush=True)


async def warm_up(
    llm: LLMClient, tts: TTSClient, tools: list[Tool], actor_name: str | None,
    *, caller: Caller | None = None, session_block: str | None = None,
) -> None:
    """At session open: fillers + TTS connection + LLM cache, in parallel. Counts as activity (the caller just arrived)."""
    global _activity_at
    _activity_at = time.monotonic()
    await asyncio.gather(
        safely("fillers", load_fillers(tts)),
        safely("tts", warm_tts(tts)),
        safely("llm", prime_llm(llm, tools, actor_name, caller=caller, session_block=session_block)),
    )
