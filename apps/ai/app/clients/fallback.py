"""Ordered multi-provider LLM fallback client.

Tries configured providers in exact priority order (e.g. opencode-go -> nvidia -> anthropic).
If a provider fails BEFORE yielding any text or tool call (auth, quota, 429, network, 5xx),
it cools down briefly and seamlessly fails over to the next provider without altering caller code.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import httpx

from .base import LLMClient, LLMEvent, LLMRequest, LLMText, LLMToolCall, LLMToolStart
from .http import ProviderError

_HARD_COOLDOWN_S = 300.0  # 401/402/403/quota/usage limit
_SOFT_COOLDOWN_S = 25.0   # 429 rate-limit / transient 5xx / timeout


def _cooldown_for(exc: Exception) -> float:
    msg = str(exc).lower()
    if any(k in msg for k in ("401", "402", "403", "unauthori", "usage limits", "quota", "billing", "insufficient")):
        return _HARD_COOLDOWN_S
    return _SOFT_COOLDOWN_S


class FallbackLLM(LLMClient):
    """Composite LLMClient that routes through ordered providers with transparent failover."""

    def __init__(self, clients: list[LLMClient]):
        if not clients:
            raise ValueError("FallbackLLM requires at least one client")
        self.clients = list(clients)
        self._cooldown_until: dict[int, float] = {}
        self._last_used: LLMClient = self.clients[0]

    @property
    def provider(self) -> str:
        return "->".join(c.provider for c in self.clients)

    @property
    def model(self) -> str:
        return self._last_used.model

    def _ordered_indices(self) -> list[int]:
        now = time.monotonic()
        ready = [i for i in range(len(self.clients)) if self._cooldown_until.get(i, 0.0) <= now]
        cooled = [i for i in range(len(self.clients)) if self._cooldown_until.get(i, 0.0) > now]
        # Prefer healthy providers first; if all are in cooldown, retry all from top as last resort.
        return [*ready, *cooled] if ready else list(range(len(self.clients)))

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMEvent]:
        last_exc: Exception | None = None
        for idx in self._ordered_indices():
            client = self.clients[idx]
            emitted = False
            try:
                async for ev in client.stream(request):
                    if isinstance(ev, (LLMText, LLMToolStart, LLMToolCall)):
                        emitted = True
                    yield ev
                self._last_used = client
                self._cooldown_until.pop(idx, None)
                return
            except (ProviderError, httpx.HTTPError, OSError, asyncio.TimeoutError) as exc:
                if emitted:
                    raise
                last_exc = exc
                cd = _cooldown_for(exc)
                self._cooldown_until[idx] = time.monotonic() + cd
                print(
                    f"[llm] fallback: {client.provider}/{client.model} failed ({exc}); cooldown {int(cd)}s, trying next provider",
                    flush=True,
                )
        assert last_exc is not None
        raise last_exc
