"""
Configuration, read once from the environment at import time.

The repo-root `.env` (see `.env.example`) is loaded if present; real environment variables win.
Every setting has a default, so with no `.env` at all the service runs on the mock providers.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# apps/ai/app/config.py → the repo root is three folders up.
REPO_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(REPO_ROOT / ".env", override=False)  # never overrides variables already set


def env(name: str, default: str = "") -> str:
    """An environment variable, trimmed; empty counts as unset."""
    return os.environ.get(name, "").strip() or default


def env_float(name: str) -> float | None:
    """A number from the environment; unset or not a number → None (never breaks the import)."""
    try:
        return float(env(name))
    except ValueError:
        return None


@dataclass(frozen=True)
class LLMSettings:
    provider: str  # opencode-go | nvidia | deepseek | openai | openai-compatible | anthropic | gemini | mock (or comma-separated chain)
    model: str  # empty → the provider's default model
    api_key: str
    base_url: str  # empty → the provider's public endpoint
    effort: str  # anthropic: low | medium | high · nvidia preset: none | low | medium | high (thinking on/off)
    nvidia_api_key: str = ""  # NVIDIA_API_KEY: fallback key for LLM_PROVIDER=nvidia (same key as NVIDIA STT)
    opencode_api_key: str = ""  # OPENCODE_API_KEY / OPENCODE_GO_API_KEY
    anthropic_api_key: str = ""  # ANTHROPIC_API_KEY (fallback: LLM_API_KEY)
    openai_api_key: str = ""  # OPENAI_API_KEY (fallback: LLM_API_KEY)
    gemini_api_key: str = ""  # GEMINI_API_KEY (fallback: LLM_API_KEY)
    deepseek_api_key: str = ""  # DEEPSEEK_API_KEY (fallback: LLM_API_KEY)
    fallbacks: str = ""  # LLM_FALLBACKS: optional comma-separated fallback providers (e.g. "nvidia,anthropic")
    opencode_model: str = ""  # optional per-provider override in multi-provider fallback chains
    nvidia_model: str = ""
    anthropic_model: str = ""
    include_usage: bool | None = None  # LLM_INCLUDE_USAGE: optional 1/0 override for openai-compatible endpoints


@dataclass(frozen=True)
class STTSettings:
    provider: str  # openai | deepgram | soniox | gradium | nvidia | mock
    api_key: str
    model: str  # empty → the provider's default model (see clients/factory.py)
    language: str  # ISO code of what the caller speaks
    mock_text: str  # what the mock STT "hears"
    # NVIDIA (Riva on NVCF) only, all optional (clients/nvidia.py):
    nvidia_api_key: str = ""  # NVIDIA_API_KEY; STT_API_KEY is the fallback
    nvidia_function_id: str = ""  # empty → the function of STT_MODEL (parakeet | whisper)
    nvidia_uri: str = ""  # empty → grpc.nvcf.nvidia.com:443
    nvidia_boost: float | None = None  # vocabulary boost score; None → the model's default, 0 → off
    nvidia_streaming: str = "auto"  # auto | on | off


@dataclass(frozen=True)
class TTSSettings:
    provider: str  # openai | elevenlabs | gradium | mock
    api_key: str
    model: str  # empty → the provider's default model
    voice: str  # empty → the provider's default (French) voice
    language: str  # elevenlabs language_code; Gradium / OpenAI follow the voice and the text


@dataclass(frozen=True)
class JevSettings:
    api_key: str  # empty → no Jev client (get_jev_client() returns None)
    base_url: str
    model: str


@dataclass(frozen=True)
class Settings:
    port: int
    erp_api_url: str
    data_dir: Path  # data pack (separate repo); relative paths are resolved from the repo root
    max_steps: int  # max model ↔ tools round-trips per turn
    llm: LLMSettings
    stt: STTSettings
    tts: TTSSettings
    jev: JevSettings  # optional decision model, used next to the LLM (clients/jev.py)


settings = Settings(
    port=int(env("AI_PORT", "4100")),
    erp_api_url=env("ERP_API_URL", "http://localhost:4000").rstrip("/"),
    data_dir=(REPO_ROOT / env("DATA_DIR", "../hackathon-data")).resolve(),
    max_steps=int(env("AGENT_MAX_STEPS", "8")),
    llm=LLMSettings(
        provider=env("LLM_PROVIDER", "mock").lower(),
        model=env("LLM_MODEL"),
        api_key=env("LLM_API_KEY"),
        base_url=env("LLM_BASE_URL"),
        effort=env("LLM_EFFORT", "low"),
        nvidia_api_key=env("NVIDIA_API_KEY"),
        opencode_api_key=env("OPENCODE_API_KEY") or env("OPENCODE_GO_API_KEY"),
        anthropic_api_key=env("ANTHROPIC_API_KEY"),
        openai_api_key=env("OPENAI_API_KEY"),
        gemini_api_key=env("GEMINI_API_KEY"),
        deepseek_api_key=env("DEEPSEEK_API_KEY"),
        fallbacks=env("LLM_FALLBACKS").lower(),
        opencode_model=env("OPENCODE_MODEL"),
        nvidia_model=env("NVIDIA_MODEL"),
        anthropic_model=env("ANTHROPIC_MODEL"),
        include_usage={"1": True, "true": True, "0": False, "false": False}.get(env("LLM_INCLUDE_USAGE").lower()),
    ),
    stt=STTSettings(
        provider=env("STT_PROVIDER", "mock").lower(),
        api_key=env("STT_API_KEY"),
        model=env("STT_MODEL"),
        language=env("STT_LANGUAGE", "fr"),
        mock_text=env("MOCK_STT_TEXT", "Bonjour, il vous reste du bar ?"),
        nvidia_api_key=env("NVIDIA_API_KEY"),
        nvidia_function_id=env("NVIDIA_STT_FUNCTION_ID"),
        nvidia_uri=env("NVIDIA_STT_URI"),
        nvidia_boost=env_float("NVIDIA_STT_BOOST"),
        nvidia_streaming=env("NVIDIA_STT_STREAMING", "auto").lower(),
    ),
    tts=TTSSettings(
        provider=env("TTS_PROVIDER", "mock").lower(),
        api_key=env("TTS_API_KEY"),
        model=env("TTS_MODEL"),
        voice=env("TTS_VOICE"),
        language=env("TTS_LANGUAGE", "fr"),
    ),
    jev=JevSettings(
        api_key=env("JEV_API_KEY"),
        base_url=env("JEV_BASE_URL", "https://api.typesafe.ai").rstrip("/"),
        model=env("JEV_MODEL", "jev-latest"),
    ),
)
