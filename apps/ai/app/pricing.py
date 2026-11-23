"""
Price constants for the per-turn cost estimate (agent_done.cost). ONE place: edit the numbers here.

⚠ ESTIMATES. Public list prices read on 2026-11-23 (platform.claude.com/docs/en/about-claude/pricing, soniox.com/pricing,
elevenlabs.io/pricing/api), no discount, no taxes, a fixed USD→EUR rate. Not an invoice: use it to compare techniques
(cache hit or not, filler, shorter answers), not to bill anyone. A model / provider missing from the tables costs 0
(mock providers, other LLMs): the token counts are still reported.
"""

from dataclasses import dataclass

from app.schemas import TurnCost, Usage

USD_TO_EUR = 0.86  # rough; update if it matters


@dataclass(frozen=True)
class LLMPrice:
    """USD per million tokens."""

    input: float
    output: float
    cache_read: float
    cache_write: float  # 5-minute cache write


# Longest prefix wins (model ids look like "claude-sonnet-5-5-20261001"). Haiku 5.5: prompts up to 100k tokens.
# Sources (ESTIMATES, read 2026-11-24):
# - Anthropic: platform.claude.com/docs/en/about-claude/pricing
# - NVIDIA NIM build.nvidia.com: free tier ($0/tok under dev quota); hosted DeepInfra reference is $0.50 in / $2.20 out / $0.10 cache per MTok
# - DeepSeek: api-docs.deepseek.com/quick_start/pricing ($0.30 in / $1.20 out / $0.003 cache peak; $0.15/$0.60 off-peak)
LLM_PRICES = {
    "claude-sonnet-5-5": LLMPrice(input=2.0, output=10.0, cache_read=0.10, cache_write=2.5),
    "claude-haiku-5-5": LLMPrice(input=0.10, output=0.50, cache_read=0.01, cache_write=0.125),
    "nvidia/nemotron-3-ultra-550b-a55b": LLMPrice(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0),
    "deepseek-chat": LLMPrice(input=0.30, output=1.20, cache_read=0.003, cache_write=0.30),
    "deepseek-flash": LLMPrice(input=0.30, output=1.20, cache_read=0.003, cache_write=0.30),
}
STT_USD_PER_HOUR = {"soniox": 0.12}  # real-time streaming
TTS_USD_PER_1K_CHARS = {"elevenlabs": 0.04}  # Flash v2.5


def llm_price(model: str) -> LLMPrice | None:
    prefix = max((p for p in LLM_PRICES if model.startswith(p)), key=len, default=None)
    return LLM_PRICES[prefix] if prefix else None


def llm_usd(usage: Usage | None, model: str) -> float:
    price = llm_price(model)
    if not usage or not price:
        return 0.0
    return (
        (usage.input_tokens or 0) * price.input
        + (usage.output_tokens or 0) * price.output
        + (usage.cache_read_input_tokens or 0) * price.cache_read
        + (usage.cache_creation_input_tokens or 0) * price.cache_write
    ) / 1_000_000


def estimate_cost(
    usage: Usage | None, stt_seconds: float, tts_chars: int, *, llm_model: str, stt: str, tts: str
) -> TurnCost:
    usd = (
        llm_usd(usage, llm_model)
        + stt_seconds / 3600 * STT_USD_PER_HOUR.get(stt, 0.0)
        + tts_chars / 1000 * TTS_USD_PER_1K_CHARS.get(tts, 0.0)
    )
    return TurnCost(
        llm_input_tokens=usage.input_tokens if usage else None,
        llm_output_tokens=usage.output_tokens if usage else None,
        llm_cache_read_tokens=usage.cache_read_input_tokens if usage else None,
        llm_cache_creation_tokens=usage.cache_creation_input_tokens if usage else None,
        stt_seconds=round(stt_seconds, 2),
        tts_chars=tts_chars,
        estimated_usd=round(usd, 5),
        estimated_eur=round(usd * USD_TO_EUR, 5),
    )
