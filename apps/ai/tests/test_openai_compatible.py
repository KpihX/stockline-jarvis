"""
OpenAI-compatible adapter: the edge cases an OpenAI-style server can produce
(thinking tokens, parallel tool calls, partial JSON, usage variants, stream errors).

Offline only: httpx.MockTransport, no key, no network.
"""

import json

import httpx
import pytest

from app.clients import LLMFinish, LLMRequest, LLMText, LLMToolCall, LLMUsage
from app.clients.http import ProviderError
from app.clients.openai import OpenAILLM, to_openai_message
from app.schemas import ChatMessage, ToolCall, ToolInfo

TOOLS = [
    ToolInfo(name="search", description="Recherche", parameters={"type": "object", "properties": {"query": {"type": "string"}}}),
    ToolInfo(name="get_price", description="Prix", parameters={"type": "object", "properties": {"clientId": {"type": "string"}}}),
]


def sse(*events: dict) -> httpx.Response:
    body = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events) + "data: [DONE]\n\n"
    raw = body.encode()
    chunks = (raw[i : i + 11] for i in range(0, len(raw), 11))  # cut lines across chunks

    async def stream():
        for chunk in chunks:
            yield chunk

    return httpx.Response(200, content=stream(), headers={"content-type": "text/event-stream"})


def recorder(*responses: httpx.Response):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[min(len(seen) - 1, len(responses) - 1)]

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


def llm(http: httpx.AsyncClient, *, include_usage: bool = False, **kwargs) -> OpenAILLM:
    return OpenAILLM("nemotron-x", "", "https://llm.test/v1", provider="openai-compatible", include_usage=include_usage, http=http, **kwargs)


REQ = LLMRequest(system="SYS", messages=[ChatMessage(role="user", content="Bonjour")], tools=TOOLS)


async def collect(client: OpenAILLM, req: LLMRequest = REQ) -> list:
    return [event async for event in client.stream(req)]


# ── thinking must never reach TTS / history ──


async def test_think_tags_split_across_chunks_are_removed():
    events = [
        {"choices": [{"delta": {"content": "Je re<thi"}}]},
        {"choices": [{"delta": {"content": "nk>il faut vérifier le stock</th"}}]},
        {"choices": [{"delta": {"content": "ink> le prix."}}]},
    ]
    http, _ = recorder(sse(*events))
    out = await collect(llm(http))
    assert out == [LLMText("Je re"), LLMText(" le prix.")]  # reasoning gone, whatever the chunk boundaries
    assert all("vérifier" not in str(e) for e in out)


async def test_reasoning_content_field_is_never_emitted():
    events = [
        {"choices": [{"delta": {"reasoning_content": "analyse secrète", "reasoning": "encore"}}]},
        {"choices": [{"delta": {"content": "Réponse."}, "finish_reason": "stop"}]},
    ]
    http, _ = recorder(sse(*events))
    assert await collect(llm(http)) == [LLMText("Réponse."), LLMFinish("stop")]


async def test_unclosed_think_block_tail_is_discarded():
    http, _ = recorder(sse({"choices": [{"delta": {"content": "Bonjour<think>raison"}}]}))
    assert await collect(llm(http)) == [LLMText("Bonjour")]


# ── tool calls ──


async def test_text_before_tool_partial_json_and_parallel_calls():
    events = [
        {"choices": [{"delta": {"content": "Je regarde."}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "sea", "arguments": '{"qu'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 1, "id": "c2", "function": {"name": "get_price", "arguments": '{"clientId":"cli_1"}'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "rch", "arguments": 'ery":"bar"}'}}]}}]},
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 4}},
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
    ]
    http, seen = recorder(sse(*events))
    out = await collect(llm(http, include_usage=True))
    assert out == [
        LLMText("Je regarde."),
        LLMUsage(10, 4),
        LLMToolCall(ToolCall(id="c1", name="search", arguments={"query": "bar"})),
        LLMToolCall(ToolCall(id="c2", name="get_price", arguments={"clientId": "cli_1"})),
        LLMFinish("tool_calls"),
    ]
    assert json.loads(seen[0].content)["stream_options"] == {"include_usage": True}


async def test_json_object_arguments_and_missing_id():
    events = [
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"name": "search", "arguments": {"query": "bar"}}}]}}]},
    ]
    http, _ = recorder(sse(*events))
    out = await collect(llm(http))
    assert out == [LLMToolCall(ToolCall(id="call_0", name="search", arguments={"query": "bar"}))]


def test_tool_call_id_and_arguments_replayed_to_server():
    msg = ChatMessage(
        role="assistant",
        content="Je regarde.",
        tool_calls=[
            ToolCall(id="c1", name="search", arguments={"query": "bar"}),
            ToolCall(id="c2", name="get_price", arguments={"clientId": "cli_1"}),
        ],
    )
    result = ChatMessage(role="tool", tool_call_id="c2", name="get_price", content='{"price":2}')
    assert to_openai_message(msg) == {
        "role": "assistant",
        "content": "Je regarde.",
        "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "search", "arguments": '{"query":"bar"}'}},
            {"id": "c2", "type": "function", "function": {"name": "get_price", "arguments": '{"clientId":"cli_1"}'}},
        ],
    }
    assert to_openai_message(result) == {"role": "tool", "tool_call_id": "c2", "content": '{"price":2}'}


# ── usage / finish / errors / provider-specific fields ──


async def test_usage_variants_and_cached_tokens():
    events = [
        {"choices": [{"delta": {"content": "ok"}}]},
        {"choices": [], "usage": {"input_tokens": 100, "output_tokens": 7, "prompt_tokens_details": {"cached_tokens": 40}}},
    ]
    http, _ = recorder(sse(*events))
    assert await collect(llm(http)) == [LLMText("ok"), LLMUsage(100, 7, cache_read_input_tokens=40)]


async def test_sse_error_object_is_readable():
    http, _ = recorder(sse({"choices": [], "error": {"message": "model overloaded", "code": 503}}))
    with pytest.raises(ProviderError, match="openai-compatible: model overloaded"):
        await collect(llm(http))


async def test_429_error_is_readable():
    http, _ = recorder(httpx.Response(429, text='{"error":"quota exceeded"}'))
    with pytest.raises(ProviderError, match="HTTP 429.*quota"):
        await collect(llm(http))


async def test_nemotron_extra_body_and_no_unknown_fields():
    http, seen = recorder(sse({"choices": [{"delta": {"content": "salut"}}]}))
    client = llm(
        http,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    assert await collect(client) == [LLMText("salut")]
    body = json.loads(seen[0].content)
    assert "stream_options" not in body and "authorization" not in seen[0].headers
    assert body["chat_template_kwargs"] == {"enable_thinking": False}
