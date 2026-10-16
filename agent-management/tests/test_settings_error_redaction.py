"""Provider errors must never echo upstream secret-looking content in logs."""
import logging

import httpx
import pytest

from agent_management.errors import ProviderError
from agent_management.providers import OpenRouterProvider


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 429, 500])
async def test_openrouter_error_body_does_not_enter_logs(caplog, status):
    marker = "sk-secret-leak-canary"
    async def handler(_request):
        return httpx.Response(status, json={"error": {"message": marker}})
    provider = OpenRouterProvider(
        {"api_key": "sk-provider"},
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    try:
        with caplog.at_level(logging.WARNING):
            with pytest.raises(ProviderError) as failure:
                await provider.complete([{"role": "user", "content": "ping"}])
        assert marker not in str(failure.value)
        assert marker not in caplog.text
        assert str(status) in str(failure.value)
    finally:
        await provider.close()
