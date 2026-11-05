"""Model discovery never makes inference calls and cannot be used as an SSRF proxy."""
from types import SimpleNamespace

import httpx
import pytest

from agent_management.crypto import encrypt_auth_config
from agent_management.errors import ProviderError
from agent_management.model_catalog import OPENROUTER_MODELS_URL, discover_openrouter_models, normalize_models


def test_normalize_catalog_metadata_and_units():
    out = normalize_models({"data": [{"id": "lab/model", "name": "Example", "context_length": 128000,
        "supported_parameters": ["temperature", "tools", "unsupported"],
        "default_parameters": {"temperature": 0.3, "max_tokens": 1234, "not_supported": 1},
        "pricing": {"prompt": "0.000001", "completion": "0.000002"}}]})
    assert out == [{"id": "lab/model", "name": "Example", "context_length": 128000,
        "supported_parameters": ["temperature", "tools"],
        "default_parameters": {"temperature": 0.3, "max_tokens": 1234},
        "pricing_per_token": {"prompt": "0.000001", "completion": "0.000002"}}]


@pytest.mark.asyncio
async def test_discovery_fixed_origin_and_secret_not_in_response():
    urls = []
    def handler(request: httpx.Request):
        urls.append(str(request.url))
        assert request.headers.get("Authorization") == "Bearer injected-secret"
        return httpx.Response(200, json={"data": [{"id": "x/y", "name": "Test"}]})
    provider = SimpleNamespace(type="openrouter", is_active=True,
        base_url="https://attacker.invalid/ignore", auth_config=encrypt_auth_config({"api_key": "injected-secret"}))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        models = await discover_openrouter_models(provider, client=client)
    assert urls == [OPENROUTER_MODELS_URL]
    assert models[0]["id"] == "x/y"
    assert "injected-secret" not in str(models)


@pytest.mark.asyncio
async def test_custom_provider_fails_closed_and_cannot_probe_internal_hosts():
    provider = SimpleNamespace(type="custom", is_active=True, base_url="http://127.0.0.1:5000",
                               auth_config=encrypt_auth_config({}))
    with pytest.raises(ProviderError, match="OpenRouter only"):
        await discover_openrouter_models(provider)


@pytest.mark.asyncio
async def test_upstream_errors_are_redacted():
    provider = SimpleNamespace(type="openrouter", is_active=True, auth_config=encrypt_auth_config({}))
    async def handler(request: httpx.Request):
        return httpx.Response(401, json={"credential": "private-marker"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError, match="HTTP 401") as error:
            await discover_openrouter_models(provider, client=client)
    assert "private-marker" not in str(error.value)
