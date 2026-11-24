"""
Factories: settings (LLM_*, STT_*, TTS_*, JEV_* env vars) → one client of each kind, built once.

To add a provider: write a class implementing LLMClient / STTClient / TTSClient (see base.py)
in a new file, then add a `case` below.
"""

from functools import cache

from app.config import JevSettings, LLMSettings, STTSettings, TTSSettings, settings

from .anthropic import AnthropicLLM
from .base import LLMClient, STTClient, TTSClient
from .deepgram import DeepgramSTT
from .elevenlabs import ElevenLabsTTS
from .fallback import FallbackLLM
from .gemini import GeminiLLM
from .gradium import GradiumSTT, GradiumTTS
from .jev import JevClient
from .mock_llm import MockLLM
from .mock_speech import MockSTT, MockTTS
from .nvidia import NvidiaSTT
from .openai import OpenAILLM, OpenAISTT, OpenAITTS
from .presets import LLM_PRESETS, normalize_provider_name
from .soniox import SonioxSTT

DEFAULT_MODELS = {"openai": "gpt-4.1-mini", "anthropic": "claude-sonnet-5-5", "gemini": "gemini-2.5-flash"}
# Speech defaults, all fine for French. STT_MODEL / TTS_MODEL / TTS_VOICE override them.
DEFAULT_STT_MODELS = {
    "openai": "gpt-4o-mini-transcribe",
    "deepgram": "nova-3",
    "soniox": "stt-rt-v6",
    "gradium": "default",
    "nvidia": "parakeet-1.1b-rnnt-multilingual",
}
DEFAULT_TTS = {  # provider → (model, voice)
    "openai": ("gpt-4o-mini-tts", "alloy"),
    "elevenlabs": ("eleven_flash_v2_5", "JBFqnCBsd6RMkjVDRZzb"),  # premade multilingual voice
    "gradium": ("default", "F7Iib4MAyHIRed0x"),  # Armand, flagship fr-FR voice
}


class ConfigError(Exception):
    """A provider is selected but a required setting is missing."""


def need(name: str, value: str) -> str:
    if not value:
        raise ConfigError(f"{name} is required for this provider")
    return value


def _env_key_map(cfg: LLMSettings, *, chain_mode: bool) -> dict[str, str]:
    """Build key lookup map. In multi-provider chains, never leak an Anthropic `sk-ant-` LLM_API_KEY to non-Anthropic providers."""
    generic = cfg.api_key
    is_anthropic_key = generic.startswith("sk-ant-")
    return {
        "OPENCODE_API_KEY": cfg.opencode_api_key,
        "OPENCODE_GO_API_KEY": cfg.opencode_api_key,
        "NVIDIA_API_KEY": cfg.nvidia_api_key,
        "ANTHROPIC_API_KEY": cfg.anthropic_api_key,
        "OPENAI_API_KEY": cfg.openai_api_key,
        "GEMINI_API_KEY": cfg.gemini_api_key,
        "DEEPSEEK_API_KEY": cfg.deepseek_api_key,
        "LLM_API_KEY": "" if (chain_mode and is_anthropic_key) else generic,
        "LLM_API_KEY_ANY": generic,
    }


def _parse_provider_specs(cfg: LLMSettings) -> list[tuple[str, str]]:
    """Parse `LLM_PROVIDER` + `LLM_FALLBACKS` into ordered `(provider, explicit_model)` tuples."""
    raw = [p.strip() for p in f"{cfg.provider},{cfg.fallbacks}".split(",") if p.strip()]
    specs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw:
        prov_part, _, mod_part = item.partition(":")
        prov = normalize_provider_name(prov_part)
        mod = mod_part.strip()
        if (prov, mod) not in seen:
            seen.add((prov, mod))
            specs.append((prov, mod))
    return specs or [("mock", "")]


def _make_single_llm(
    provider: str,
    cfg: LLMSettings,
    *,
    explicit_model: str = "",
    is_primary: bool = True,
    chain_mode: bool = False,
) -> LLMClient:
    env_map = _env_key_map(cfg, chain_mode=chain_mode)
    per_provider_model = {
        "opencode-go": cfg.opencode_model,
        "nvidia": cfg.nvidia_model,
        "anthropic": cfg.anthropic_model,
    }.get(provider, "")
    model = explicit_model or per_provider_model or (cfg.model if is_primary else "") or DEFAULT_MODELS.get(provider, "")
    base_url = cfg.base_url if is_primary else ""
    retries = 1 if chain_mode else 2

    if provider in LLM_PRESETS:  # opencode-go | nvidia | deepseek
        preset = LLM_PRESETS[provider]
        key = next((env_map[k] for k in preset.key_envs if env_map.get(k)), "")
        include_usage = preset.include_usage if cfg.include_usage is None else cfg.include_usage
        return OpenAILLM(
            model or preset.model,
            need(" / ".join(preset.key_envs), key),
            base_url or preset.base_url,
            provider=provider,
            include_usage=include_usage,
            extra_body=preset.extra_body(cfg.effort),
            extra_headers=dict(preset.extra_headers),
            retries=retries,
        )
    match provider:
        case "mock":
            return MockLLM()
        case "openai":
            key = env_map["OPENAI_API_KEY"] or env_map["LLM_API_KEY"]
            include_usage = True if cfg.include_usage is None else cfg.include_usage
            return OpenAILLM(
                model,
                need("OPENAI_API_KEY / LLM_API_KEY", key),
                base_url or "https://api.openai.com/v1",
                include_usage=include_usage,
                retries=retries,
            )
        case "openai-compatible":  # Groq, Mistral, OpenRouter, Ollama, vLLM… (API key optional for local servers)
            key = env_map["LLM_API_KEY"]
            include_usage = False if cfg.include_usage is None else cfg.include_usage
            return OpenAILLM(
                need("LLM_MODEL", model),
                key,
                need("LLM_BASE_URL (e.g. http://localhost:11434/v1)", base_url or cfg.base_url),
                provider="openai-compatible",
                include_usage=include_usage,
                retries=retries,
            )
        case "anthropic":
            key = env_map["ANTHROPIC_API_KEY"] or env_map["LLM_API_KEY_ANY"]
            return AnthropicLLM(
                model,
                need("ANTHROPIC_API_KEY / LLM_API_KEY", key),
                base_url or "https://api.anthropic.com",
                cfg.effort,
                retries=retries,
            )
        case "gemini":
            key = env_map["GEMINI_API_KEY"] or env_map["LLM_API_KEY"]
            return GeminiLLM(
                model,
                need("GEMINI_API_KEY / LLM_API_KEY", key),
                base_url or "https://generativelanguage.googleapis.com/v1beta",
            )
    raise ConfigError(
        f'Unknown LLM_PROVIDER "{provider}" (opencode-go | nvidia | anthropic | deepseek | openai | openai-compatible | gemini | mock)'
    )


def make_llm_client(cfg: LLMSettings) -> LLMClient:
    specs = _parse_provider_specs(cfg)
    if len(specs) == 1:
        prov, explicit_model = specs[0]
        return _make_single_llm(prov, cfg, explicit_model=explicit_model, is_primary=True, chain_mode=False)

    clients: list[LLMClient] = []
    errors: list[str] = []
    for idx, (prov, explicit_model) in enumerate(specs):
        try:
            clients.append(
                _make_single_llm(prov, cfg, explicit_model=explicit_model, is_primary=(idx == 0), chain_mode=True)
            )
        except ConfigError as exc:
            errors.append(f"{prov}: {exc}")
    if not clients:
        raise ConfigError("; ".join(errors))
    if len(clients) == 1:
        return clients[0]
    return FallbackLLM(clients)


def make_stt_client(cfg: STTSettings) -> STTClient:
    model, lang = cfg.model or DEFAULT_STT_MODELS.get(cfg.provider, ""), cfg.language
    match cfg.provider:
        case "mock":
            return MockSTT(cfg.mock_text)
        case "openai":
            return OpenAISTT(need("STT_API_KEY", cfg.api_key), model, lang)
        case "deepgram":
            return DeepgramSTT(need("STT_API_KEY", cfg.api_key), model, lang)
        case "soniox":
            return SonioxSTT(need("STT_API_KEY", cfg.api_key), model, lang)
        case "gradium":
            return GradiumSTT(need("STT_API_KEY", cfg.api_key), model, lang)
        case "nvidia":  # optional: needs `uv sync --extra nvidia` (imported on first use, see clients/nvidia.py)
            try:
                return NvidiaSTT(
                    need("NVIDIA_API_KEY (or STT_API_KEY)", cfg.nvidia_api_key or cfg.api_key),
                    model,
                    lang,
                    function_id=cfg.nvidia_function_id,
                    uri=cfg.nvidia_uri,
                    boost=cfg.nvidia_boost,
                    streaming=cfg.nvidia_streaming,
                )
            except ValueError as e:  # unknown STT_MODEL without NVIDIA_STT_FUNCTION_ID
                raise ConfigError(str(e)) from None
    raise ConfigError(f'Unknown STT_PROVIDER "{cfg.provider}" (mock | soniox | deepgram | gradium | openai | nvidia)')


def make_tts_client(cfg: TTSSettings) -> TTSClient:
    model, voice = DEFAULT_TTS.get(cfg.provider, ("", ""))
    model, voice = cfg.model or model, cfg.voice or voice
    match cfg.provider:
        case "mock":
            return MockTTS()
        case "openai":
            return OpenAITTS(need("TTS_API_KEY", cfg.api_key), model, voice)
        case "elevenlabs":
            return ElevenLabsTTS(need("TTS_API_KEY", cfg.api_key), model, voice, cfg.language)
        case "gradium":
            return GradiumTTS(need("TTS_API_KEY", cfg.api_key), model, voice)
    raise ConfigError(f'Unknown TTS_PROVIDER "{cfg.provider}" (elevenlabs | gradium | openai | mock)')


def make_jev_client(cfg: JevSettings) -> JevClient | None:
    """Jev is optional: no JEV_API_KEY → None (agent code checks `if jev:`)."""
    return JevClient(cfg.api_key, cfg.model, cfg.base_url) if cfg.api_key else None


# The clients the service uses, built once from the environment.
@cache
def get_llm_client() -> LLMClient:
    return make_llm_client(settings.llm)


@cache
def get_stt_client() -> STTClient:
    return make_stt_client(settings.stt)


@cache
def get_tts_client() -> TTSClient:
    return make_tts_client(settings.tts)


@cache
def get_jev_client() -> JevClient | None:
    """The Jev decision model (clients/jev.py), or None when JEV_API_KEY is not set."""
    return make_jev_client(settings.jev)
