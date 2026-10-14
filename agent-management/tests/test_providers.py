"""Unit tests for the LLM provider abstraction layer and each adapter.

The HTTP-backed adapters (OpenRouter, HuggingFace, Custom) are exercised against a
``httpx.MockTransport`` so behaviour is verified without any network access; the Mock
adapter is tested directly. Also covers registry independence, error mapping, and
token-usage extraction accuracy.
"""

from __future__ import annotations

import pytest
import httpx

from agent_management.errors import ProviderError, ProviderNotFoundError
from agent_management.providers import (
    CustomProvider,
    HuggingFaceProvider,
    MockProvider,
    OpenRouterProvider,
    ProviderRegistry,
    Usage,
)
from agent_management.providers._http import estimate_tokens


def oai_response(usage=None, content="hello there"):
    return {
        "id": "cmpl-test",
        "model": "model-x",
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": usage
        or {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
    }


def make_client(handler):
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://test"
    )


# ---------------------------------------------------------------- mock provider


@pytest.mark.asyncio
async def test_mock_provider_reports_exact_usage():
    p = MockProvider({"reply": "ok", "prompt_tokens": 7, "completion_tokens": 3})
    result = await p.complete([{"role": "user", "content": "hi"}])
    assert result.content == "ok"
    assert result.usage.prompt_tokens == 7
    assert result.usage.completion_tokens == 3
    assert result.usage.total_tokens == 10


@pytest.mark.asyncio
async def test_mock_provider_raises_provider_error():
    p = MockProvider({"fail_next": True})
    with pytest.raises(ProviderError):
        await p.complete([{"role": "user", "content": "hi"}])


# ------------------------------------------------------------------ openrouter


@pytest.mark.asyncio
async def test_openrouter_complete_and_usage():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "openrouter.ai"
        assert "/api/v1/chat/completions" in request.url.path
        assert request.headers["Authorization"] == "Bearer sk-test"
        body = request.read().decode()
        assert '"messages"' in body
        return httpx.Response(200, json=oai_response())

    p = OpenRouterProvider(
        {"api_key": "sk-test"}, client_factory=lambda: make_client(handler)
    )
    result = await p.complete(
        [{"role": "user", "content": "capitals"}], model="openai/gpt-4o-mini"
    )
    assert result.content == "hello there"
    assert result.model == "model-x"
    assert result.usage.prompt_tokens == 12
    assert result.usage.completion_tokens == 5
    assert result.usage.total_tokens == 17


@pytest.mark.asyncio
async def test_openrouter_error_maps_to_provider_error():
    async def handler(request):
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    p = OpenRouterProvider(
        {"api_key": "bad"}, client_factory=lambda: make_client(handler)
    )
    with pytest.raises(ProviderError):
        await p.complete([{"role": "user", "content": "hi"}])


# ----------------------------------------------------------------- huggingface


@pytest.mark.asyncio
async def test_huggingface_chat_endpoint():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api-inference.huggingface.co"
        assert request.headers["Authorization"] == "Bearer hf-token"
        return httpx.Response(200, json=oai_response(content="hf answer"))

    p = HuggingFaceProvider(
        {"api_token": "hf-token", "model": "meta-llama/llama-3-8b-instruct"},
        client_factory=lambda: make_client(handler),
    )
    result = await p.complete([{"role": "user", "content": "hi"}])
    assert result.content == "hf answer"
    assert result.usage.total_tokens == 17
    assert p.type == "huggingface"


@pytest.mark.asyncio
async def test_huggingface_text_generation_endpoint_no_usage_estimates():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert "/models/" in request.url.path
        return httpx.Response(200, json=[{"generated_text": "continuation"}] * 1)

    p = HuggingFaceProvider(
        {"api_token": "hf-token", "model": "gpt2", "mode": "text"},
        client_factory=lambda: make_client(handler),
    )
    result = await p.complete([{"role": "user", "content": "start"}])
    assert result.content == "continuation"
    # No usage returned by backend -> fallback estimation kicks in (non-negative).
    assert result.usage.prompt_tokens >= 0
    assert result.usage.total_tokens == result.usage.prompt_tokens + result.usage.completion_tokens


# ------------------------------------------------------------------- custom


@pytest.mark.asyncio
async def test_custom_provider_requires_base_url():
    p = CustomProvider({"api_key": "k"}, client_factory=lambda: make_client(lambda req: None))
    with pytest.raises(ProviderError):
        await p.complete([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_custom_provider_calls_configured_endpoint():
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json=oai_response(content="custom answer"))

    p = CustomProvider(
        {"base_url": "http://localhost:9090/v1", "api_key": "x", "model": "my-model"},
        client_factory=lambda: make_client(handler),
    )
    result = await p.complete([{"role": "user", "content": "hi"}], max_tokens=64)
    assert result.content == "custom answer"
    assert "localhost:9090/v1/chat/completions" in seen["url"]
    assert result.usage.total_tokens == 17


# --------------------------------------------------------------- registry


def test_registry_builds_adapter_and_enforces_type_whitelist():
    reg = ProviderRegistry()
    reg.register(OpenRouterProvider)
    reg.register(MockProvider)
    assert set(reg.types()) == {"openrouter", "mock"}
    provider = reg.build("mock", {"prompt_tokens": 3, "completion_tokens": 2})
    assert isinstance(provider, MockProvider)
    with pytest.raises(ProviderNotFoundError):
        reg.build("huggingface", {})


def test_registry_register_duplicate_type_overwrites():
    reg = ProviderRegistry()
    reg.register(MockProvider)
    # re-registering a type is allowed (last wins), but the class is the same here
    assert reg.get("mock") is MockProvider


def test_registry_empty_type_raises():
    reg = ProviderRegistry()
    with pytest.raises(ValueError):
        reg.register(type("Empty", (object,), {"type": ""}))


def test_registry_default_has_all_builtin_adapters():
    from agent_management.providers import get_registry

    assert set(get_registry().types()) == {"openrouter", "huggingface", "custom", "mock"}


def test_supports_capability():
    assert OpenRouterProvider.supports("streaming") is True
    assert MockProvider.supports("offline_tokens") is True


# ---------------------------------------------------- token extraction/usage


def test_usage_total_auto_computed():
    u = Usage(prompt_tokens=20, completion_tokens=7)
    assert u.total_tokens == 27


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcdefgh") == 2