"""Safe read-only OpenRouter catalogue; never proxy caller-provided URLs."""
from __future__ import annotations

from typing import Any
import httpx

from .crypto import decrypt_auth_config
from .errors import ProviderError

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
ALLOWED_PARAMS = {"temperature", "top_p", "max_tokens", "frequency_penalty",
                  "presence_penalty", "tools", "tool_choice", "reasoning", "response_format"}


def normalize_models(data: Any) -> list[dict[str, Any]]:
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ProviderError("OpenRouter model catalogue format is invalid")
    result = []
    for row in rows[:5000]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        model_id = row["id"]
        if not 1 <= len(model_id) <= 255:
            continue
        params = row.get("supported_parameters")
        defaults = row.get("default_parameters")
        price = row.get("pricing")
        context = row.get("context_length")
        result.append({
            "id": model_id,
            "name": str(row.get("name") or model_id)[:255],
            "context_length": context if type(context) is int and context >= 0 else None,
            "supported_parameters": sorted({p for p in params
                                            if isinstance(p, str) and p in ALLOWED_PARAMS})
                                    if isinstance(params, list) else [],
            "default_parameters": {k: v for k, v in defaults.items()
                                   if k in ALLOWED_PARAMS and type(v) in (float, int)
                                   and -1000000 <= v <= 1000000}
                                   if isinstance(defaults, dict) else {},
            # OpenRouter publishes pricing per-token in USD. Avoid corrupting
            # model profile's per-1000-token cost bookkeeping.
            "pricing_per_token": {k: price[k] for k in ("prompt", "completion")
                                  if isinstance(price.get(k), str)}
                                  if isinstance(price, dict) else {},
        })
    return result


async def discover_openrouter_models(provider: Any, *, client: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    if provider.type != "openrouter":
        raise ProviderError("Model discovery is available for OpenRouter only")
    if not provider.is_active:
        raise ProviderError("Provider is inactive")
    config = decrypt_auth_config(provider.auth_config or {})
    token = config.get("api_key") or config.get("token")
    headers = {"Accept": "application/json"}
    if isinstance(token, str) and token:
        headers["Authorization"] = f"Bearer {token}"
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(timeout=httpx.Timeout(12.0), follow_redirects=False)
    assert client is not None
    try:
        try:
            reply = await client.get(OPENROUTER_MODELS_URL, headers=headers)
        except httpx.RequestError:
            raise ProviderError("OpenRouter model catalogue network error") from None
        if reply.status_code >= 400:
            raise ProviderError(f"OpenRouter model catalogue returned HTTP {reply.status_code}")
        try:
            return normalize_models(reply.json())
        except ValueError:
            raise ProviderError("OpenRouter model catalogue returned invalid JSON") from None
    finally:
        if own_client:
            await client.aclose()
