"""
OpenAI adapters, raw HTTP:
  - LLM: Chat Completions (POST {base_url}/chat/completions, stream: true). Also every "OpenAI-compatible"
    server: Mistral, Groq, OpenRouter, Ollama, vLLM, LM Studio… (set LLM_BASE_URL).
  - STT: POST /audio/transcriptions (gpt-4o-mini-transcribe, whisper-1…)
  - TTS: POST /audio/speech (gpt-4o-mini-tts, tts-1…), streamed mp3.
"""

import json
from collections.abc import AsyncIterator

import httpx

from app.schemas import ChatMessage, ToolCall

from .base import LLMClient, LLMEvent, LLMFinish, LLMRequest, LLMText, LLMToolCall, LLMUsage, STTClient, TTSClient, TTSResult
from .http import ProviderError, body_chunks, check_ok, http_client, parse_args, post_stream, sse_json

OPENAI_URL = "https://api.openai.com/v1"

THINK_OPEN, THINK_CLOSE = "<think>", "</think>"


class ThinkFilter:
    """Streaming filter: remove `<think>…</think>` blocks split across any number of SSE deltas.
    Reasoning must never reach the TTS nor the conversation history (the agent loop keeps only LLMText).
    Keeps back at most the length of a tag so a tag cut between two chunks is still recognised."""

    def __init__(self):
        self.inside = False
        self.buf = ""

    def feed(self, text: str) -> str:
        self.buf += text
        out = ""
        while True:
            if self.inside:
                end = self.buf.find(THINK_CLOSE)
                if end < 0:  # keep a possible partial closing tag for the next chunk
                    keep = len(THINK_CLOSE) - 1
                    self.buf = self.buf[-keep:] if len(self.buf) > keep else self.buf
                    return out
                self.buf = self.buf[end + len(THINK_CLOSE) :]
                self.inside = False
            start = self.buf.find(THINK_OPEN)
            if start < 0:  # emit everything except a possible partial opening tag
                keep = len(THINK_OPEN) - 1
                tail = self.buf[-keep:] if keep else ""
                if any(tail.startswith(THINK_OPEN[:n]) for n in range(1, len(THINK_OPEN))):
                    out += self.buf[: len(self.buf) - len(tail)]
                    self.buf = tail
                else:
                    out += self.buf
                    self.buf = ""
                return out
            out += self.buf[:start]
            self.buf = self.buf[start + len(THINK_OPEN) :]
            self.inside = True

    def flush(self) -> str:
        """Emit the held-back tail; a still-open thinking block is discarded."""
        out = "" if self.inside else self.buf
        self.buf = ""
        return out


class OpenAILLM(LLMClient):
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = OPENAI_URL,
        provider: str = "openai",
        include_usage: bool = True,  # stream_options.include_usage: some compatible servers reject unknown fields
        extra_body: dict | None = None,  # provider-specific body fields (e.g. Nemotron: chat_template_kwargs.enable_thinking)
        http: httpx.AsyncClient | None = None,
    ):
        self.provider, self.model = provider, model
        self.api_key, self.base_url, self.include_usage = api_key, base_url.rstrip("/"), include_usage
        self.extra_body, self.http = extra_body or {}, http

    def build_body(self, req: LLMRequest) -> dict:
        body: dict = {
            "model": self.model,
            "stream": True,
            "messages": [{"role": "system", "content": req.full_system}, *map(to_openai_message, req.messages)],
        }
        if req.tools:
            body["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in req.tools
            ]
        if req.max_tokens:
            body["max_tokens"] = req.max_tokens
        if self.include_usage:
            body["stream_options"] = {"include_usage": True}
        body.update(self.extra_body)  # last: lets a preset override optional fields without touching this adapter
        return body

    async def stream(self, req: LLMRequest) -> AsyncIterator[LLMEvent]:
        headers = {"authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        res = await post_stream(
            self.http or http_client(), f"{self.base_url}/chat/completions", json=self.build_body(req), headers=headers, limit=500
        )

        # Tool calls stream in pieces, keyed by index: accumulate them, emit them at the end.
        pending: dict[int, dict] = {}
        think = ThinkFilter()  # Nemotron / DeepSeek / DeepSeek-R1 style models may emit <think>…</think> in `content`
        finish_reason = ""
        async for chunk in sse_json(res):
            if chunk.get("error"):  # some compatible servers return errors INSIDE a 200 SSE stream
                err = chunk["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise ProviderError(f"{self.provider}: {msg or 'stream error'}")
            choice = (chunk.get("choices") or [{}])[0] or {}
            delta = choice.get("delta") or {}
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
            # `reasoning_content` / `reasoning` are never spoken nor stored in the history: thinking is ephemeral.
            text = delta.get("content")
            if text:
                shown = think.feed(text if isinstance(text, str) else str(text))
                if shown:
                    yield LLMText(shown)
            for tc in delta.get("tool_calls") or []:
                cur = pending.setdefault(tc.get("index") or 0, {"id": "", "name": "", "args": ""})
                fn = tc.get("function") or {}
                if tc.get("id"):
                    cur["id"] = tc["id"]
                cur["name"] += fn.get("name") or ""
                arguments = fn.get("arguments")
                if arguments is not None:  # a few servers send an already decoded object instead of a JSON string
                    cur["args"] += arguments if isinstance(arguments, str) else compact_json(arguments)
            if chunk.get("usage"):
                u = chunk["usage"]
                cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
                yield LLMUsage(
                    u.get("prompt_tokens", u.get("input_tokens")),
                    u.get("completion_tokens", u.get("output_tokens")),
                    cache_read_input_tokens=cached,
                )

        tail = think.flush()  # a final <think> fragment is discarded, a normal tail is emitted
        if tail:
            yield LLMText(tail)
        for i, tc in sorted(pending.items()):
            yield LLMToolCall(ToolCall(id=tc["id"] or f"call_{i}", name=tc["name"], arguments=parse_args(tc["args"])))
        if finish_reason:
            yield LLMFinish(finish_reason)


def to_openai_message(m: ChatMessage) -> dict:
    if m.role == "tool":
        return {"role": "tool", "tool_call_id": m.tool_call_id, "content": m.content}
    if m.role == "assistant" and m.tool_calls:
        return {
            "role": "assistant",
            "content": m.content or None,
            "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": compact_json(c.arguments)}}
                for c in m.tool_calls
            ],
        }
    return {"role": m.role, "content": m.content}


def compact_json(value) -> str:
    """JSON like JavaScript's JSON.stringify: no spaces, accents kept."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class OpenAISTT(STTClient):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini-transcribe", language: str = "fr", http: httpx.AsyncClient | None = None):
        self.api_key, self.model, self.language, self.http = api_key, model, language, http

    async def transcribe(self, audio: bytes, mime: str, hint: str | None = None) -> str:
        data = {"model": self.model, "language": self.language}
        if hint:
            data["prompt"] = hint  # vocabulary hint: product / client names
        res = await (self.http or http_client()).post(
            f"{OPENAI_URL}/audio/transcriptions",
            headers={"authorization": f"Bearer {self.api_key}"},
            files={"file": (f"audio.{extension_for(mime)}", audio, mime)},
            data=data,
        )
        await check_ok(res, "openai stt")
        return (res.json().get("text") or "").strip()


class OpenAITTS(TTSClient):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini-tts", voice: str = "alloy", http: httpx.AsyncClient | None = None):
        self.api_key, self.model, self.voice, self.http = api_key, model, voice, http

    async def synthesize(self, text: str, voice: str | None = None) -> TTSResult:
        res = await post_stream(
            self.http or http_client(),
            f"{OPENAI_URL}/audio/speech",
            who="openai tts",
            headers={"authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "voice": voice or self.voice, "input": text, "response_format": "mp3"},
        )
        return TTSResult("audio/mpeg", body_chunks(res))


def extension_for(mime: str) -> str:
    """File extension the transcription APIs expect for a recording mime type."""
    if "webm" in mime:
        return "webm"
    if "ogg" in mime:
        return "ogg"
    if "mp4" in mime or "m4a" in mime:
        return "m4a"
    if "mpeg" in mime or "mp3" in mime:
        return "mp3"
    return "wav"
