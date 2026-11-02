"""Offline OpenRouter SSE contract tests; no API keys or live provider needed."""
from __future__ import annotations

import json

import httpx
import pytest

from agent_management.errors import ProviderError
from agent_management.providers import OpenRouterProvider
from agent_management.providers.streaming import StreamAssembler, sse_payloads


def sse(*messages: dict | str) -> bytes:
    return "".join(
        "data: " + (m if isinstance(m, str) else json.dumps(m)) + "\n\n"
        for m in messages
    ).encode()


def provider(handler):
    return OpenRouterProvider(
        {"api_key": "test-token", "model": "offline-model"},
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.asyncio
async def test_stream_text_and_usage():
    def handler(req):
        body = json.loads(req.content)
        assert body["stream"] is True
        assert body["stream_options"]["include_usage"] is True
        assert req.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, content=sse(
            {"id": "s1", "model": "model-a", "choices": [
                {"index": 0, "delta": {"content": "Hel"}, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {"content": "lo"}, "finish_reason": "stop"}]},
            {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}},
            "[DONE]",
        ), headers={"content-type": "text/event-stream"})
    p = provider(handler)
    events = [e async for e in p.stream([{"role": "user", "content": "hi"}])]
    await p.close()
    assert [e["type"] for e in events] == ["text_delta", "text_delta", "usage", "done"]
    assert "".join(e["text"] for e in events[:2]) == "Hello"
    assert events[2]["total_tokens"] == 6
    assert events[-1]["id"] == "s1"
    assert events[-1]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_stream_assembles_fragmented_tool_calls_without_executing():
    def handler(req):
        body = json.loads(req.content)
        assert body["tools"][0]["type"] == "function"
        return httpx.Response(200, content=sse(
            {"choices": [{"index": 0, "delta": {
                "tool_calls": [{"index": 0, "id": "call-1", "type": "function",
                                "function": {"name": "read_", "arguments": '{"pa'}}]}}]},
            {"choices": [{"index": 0, "delta": {
                "tool_calls": [{"index": 0, "function": {
                    "name": "file", "arguments": 'th":"safe.txt"}'}}]
            }, "finish_reason": "tool_calls"}]},
            "[DONE]",
        ))
    p = provider(handler)
    tools = [{"type": "function", "function": {"name": "read_file", "parameters": {}}}]
    events = [e async for e in p.stream([{"role": "user", "content": "read"}], tools=tools)]
    await p.close()
    assert [e["type"] for e in events] == ["tool_call", "done"]
    assert events[0] == {"type": "tool_call", "index": 0, "id": "call-1",
                         "name": "read_file", "arguments": {"path": "safe.txt"}}
    assert events[1]["finish_reason"] == "tool_calls"


@pytest.mark.asyncio
async def test_stream_rejects_http_error_without_exposing_provider_message():
    p = provider(lambda req: httpx.Response(
        429, json={"error": {"message": "secret upstream value"}}))
    with pytest.raises(ProviderError, match="429") as exc:
        _ = [e async for e in p.stream([{"role": "user", "content": "hi"}])]
    assert "secret upstream" not in str(exc.value)
    await p.close()


@pytest.mark.asyncio
async def test_stream_rejects_truncation_and_invalid_json_arguments():
    p = provider(lambda req: httpx.Response(200, content=sse(
        {"choices": [{"index": 0, "delta": {"content": "partial"}}]},
    )))
    with pytest.raises(ProviderError, match="completion marker"):
        _ = [e async for e in p.stream([{"role": "user", "content": "hi"}])]
    await p.close()

    a = StreamAssembler()
    a.feed({"choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": 0, "id": "c1", "function": {"name": "shell", "arguments": "{"}}
    ]}}]})
    with pytest.raises(ProviderError, match="Invalid JSON"):
        a.finish()


@pytest.mark.asyncio
async def test_multiline_sse_and_size_limit():
    async def lines():
        yield ": heartbeat"
        yield "data: {\"a\":"
        yield "data: 1}"
        yield ""
    assert [x async for x in sse_payloads(lines())] == ['{"a":\n1}']
    a = StreamAssembler()
    with pytest.raises(ProviderError, match="size limit"):
        a.feed({"choices": [{"index": 0, "delta": {"tool_calls": [
            {"index": 0, "id": "c1", "function": {
                "name": "write_file", "arguments": "a" * 262145}}
        ]}}]})


@pytest.mark.parametrize("invalid_usage", [
    {"prompt_tokens": 1.9, "completion_tokens": 0.9, "total_tokens": 2.9},
    {"prompt_tokens": True, "completion_tokens": 0, "total_tokens": 1},
    {"prompt_tokens": "1", "completion_tokens": 0, "total_tokens": 1},
    {"prompt_tokens": 1, "completion_tokens": False, "total_tokens": 1},
    {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": None},
    {"prompt_tokens": 1, "completion_tokens": 0},
])
def test_stream_assembler_rejects_raw_untrusted_usage(invalid_usage):
    with pytest.raises(ProviderError, match="Invalid usage information"):
        StreamAssembler().feed({"choices": [], "usage": invalid_usage})


@pytest.mark.asyncio
async def test_openrouter_stream_rejects_fractional_usage_before_agent_loop():
    def handler(_request):
        return httpx.Response(200, content=sse(
            {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
            {"choices": [], "usage": {
                "prompt_tokens": 1.9, "completion_tokens": 0.9, "total_tokens": 2.9,
            }},
            "[DONE]",
        ))
    p = provider(handler)
    try:
        with pytest.raises(ProviderError, match="Invalid usage information"):
            _ = [event async for event in p.stream([{"role": "user", "content": "go"}])]
    finally:
        await p.close()


@pytest.mark.asyncio
async def test_sse_rejects_oversized_multiline_message_without_emitting():
    async def lines():
        yield "data: " + "x" * 600_000
        yield "data: " + "x" * 600_000
        yield ""
    with pytest.raises(ProviderError, match="size limit"):
        _ = [x async for x in sse_payloads(lines())]


@pytest.mark.parametrize("payload", [
    {"choices": [], "usage": {"prompt_tokens": -1, "completion_tokens": 1, "total_tokens": 2}},
    {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 1}},
    {"choices": "not a list"},
    {"choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": True, "id": "call", "function": {"name": "read_file", "arguments": "{}"}},
    ]}}]},
    {"choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": 0, "id": "call", "function": {"name": "a" * 129, "arguments": "{}"}},
    ]}}]},
    {"choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": 0, "id": "x" * 129, "function": {"name": "read_file", "arguments": "{}"}},
    ]}}]},
])
def test_untrusted_stream_fragments_fail_closed(payload):
    with pytest.raises(ProviderError):
        StreamAssembler().feed(payload)


@pytest.mark.parametrize("arguments", [
    '{"path":"safe","path":"../secret"}',
    '{"path":NaN}',
    '{"path":Infinity}',
    '{"path":-Infinity}',
])
def test_streamed_tool_args_reject_ambiguous_and_nonfinite_json(arguments):
    a = StreamAssembler()
    a.feed({"choices": [{"index": 0, "delta": {"tool_calls": [
        {"index": 0, "id": "read-once", "function": {
            "name": "read_file", "arguments": arguments,
        }},
    ]}}]})
    with pytest.raises(ProviderError, match="Invalid JSON"):
        a.finish()


def test_repeated_stream_usage_and_conflicting_finish_rejected():
    a = StreamAssembler()
    usage = {"choices": [], "usage": {
        "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
    }}
    a.feed(usage)
    with pytest.raises(ProviderError, match="Duplicate usage"):
        a.feed(usage)
    b = StreamAssembler()
    b.feed({"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]})
    with pytest.raises(ProviderError, match="Conflicting streamed finish"):
        b.feed({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})


@pytest.mark.asyncio
async def test_openrouter_429_and_server_error_remain_redacted():
    for code in (401, 429, 500, 503):
        p = provider(lambda req: httpx.Response(
            code, json={"error": {"message": "sk-sensitive-provider-message"}},
        ))
        try:
            with pytest.raises(ProviderError, match=str(code)) as exc:
                _ = [event async for event in p.stream([{"role": "user", "content": "hi"}])]
            assert "sk-sensitive" not in str(exc.value)
        finally:
            await p.close()


@pytest.mark.asyncio
async def test_non_json_completion_does_not_echo_upstream_body():
    p = provider(lambda req: httpx.Response(200, text="upstream-secret-canary"))
    try:
        with pytest.raises(ProviderError, match="non-JSON response") as exc:
            await p.complete([{"role": "user", "content": "go"}])
        assert "upstream-secret-canary" not in str(exc.value)
    finally:
        await p.close()
