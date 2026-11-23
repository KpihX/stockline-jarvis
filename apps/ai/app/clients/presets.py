"""
Readable presets for hosted OpenAI-compatible chat endpoints.

One row = one extra `LLM_PROVIDER` value; everything stays overridable from `.env`:
`LLM_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_EFFORT`. A preset never contains a key.

Naming a preset is only a convenience: `LLM_PROVIDER=openai-compatible` + explicit
`LLM_BASE_URL` / `LLM_MODEL` reaches the very same endpoints.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LLMPreset:
    base_url: str
    model: str
    key_envs: tuple[str, ...]  # accepted key names, in order of preference (documentation + factory)
    include_usage: bool = False  # default off: some compatible servers reject `stream_options`
    # effort → optional body fields (Anthropic's `LLM_EFFORT` has no meaning elsewhere)
    effort_body: dict[str, dict] = field(default_factory=dict)

    def extra_body(self, effort: str) -> dict:
        """Provider-specific fields for this effort value. Unknown effort → ignored, never an error."""
        return dict(self.effort_body.get((effort or "").lower(), {}))


# NVIDIA reasoning is ON by default on Nemotron 3; for a voice agent it costs latency and tokens.
# `chat_template_kwargs.enable_thinking=false` is the documented switch (docs.api.nvidia.com, model reference
# "Reasoning Mode: configurable on/off via chat template", read 2026-11-23).
_NEMOTRON_THINKING = {
    "none": {"chat_template_kwargs": {"enable_thinking": False}},
    "low": {"chat_template_kwargs": {"enable_thinking": False}},
    "medium": {"chat_template_kwargs": {"enable_thinking": True, "medium_effort": True}},
    "high": {"chat_template_kwargs": {"enable_thinking": True}},
}

LLM_PRESETS: dict[str, LLMPreset] = {
    "nvidia": LLMPreset(
        base_url="https://integrate.api.nvidia.com/v1",
        model="nvidia/nemotron-3-ultra-550b-a55b",
        key_envs=("NVIDIA_API_KEY", "LLM_API_KEY"),  # prefer NVIDIA_API_KEY so an Anthropic LLM_API_KEY in .env never leaks to NVIDIA
        include_usage=True,  # verified live 2026-11-24: integrate.api.nvidia.com returns usage tokens in SSE
        effort_body=_NEMOTRON_THINKING,
    ),
    # `deepseek-chat` is the requested example name. It is a retired alias since 2026-07-24
    # (api-docs.deepseek.com/quick_start/pricing, read 2026-11-23): override with LLM_MODEL=deepseek-flash.
    "deepseek": LLMPreset(
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
        key_envs=("LLM_API_KEY",),
        include_usage=True,
    ),
}

__all__ = ["LLM_PRESETS", "LLMPreset"]
