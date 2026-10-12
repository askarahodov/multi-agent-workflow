"""Shared OpenAI-compatible HTTP plumbing for provider adapters.

Most hosted LLM backends (OpenRouter, HuggingFace's OpenAI-compatible endpoints,
and arbitrary custom OpenAI-format servers) expose a ``POST /chat/completions``
that returns OpenAI-shaped payloads. This base class centralizes the request
construction, transport, response parsing and token-usage extraction so the concrete
adapters stay thin and the parsing behavior is tested in one place.

The HTTP client can be injected (``client_factory``) so tests can run against a
``httpx.MockTransport`` without any network access.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from .base import CompletionResult, ResolvedProviderConfig, Usage

DEFAULT_COMPLETIONS_PATH = "/chat/completions"


def estimate_tokens(text: str) -> int:
    """Rough token estimate used only when a backend omits usage accounting."""
    return max(0, len(text) // 4) if text else 0


class OpenAICompatHttpProvider(ResolvedProviderConfig):
    """Base adapter for OpenAI-compatible ``/chat/completions`` endpoints."""

    type: str = ""
    # Header that carries the API credential, if any.
    auth_header: Optional[str] = "Authorization"
    auth_scheme: Optional[str] = "Bearer"

    def __init__(
        self,
        config: Dict[str, Any],
        *,
        client_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        super().__init__(config)
        self._client_factory = client_factory
        self._client = None
        self._owns_client = client_factory is not None or self._make_default_client is not None

    # -- client lifecycle ---------------------------------------------------
    def _make_default_client(self):  # pragma: no cover - exercised via transport
        import httpx

        timeout = httpx.Timeout(self.config.get("timeout_seconds", 60.0))
        return httpx.AsyncClient(timeout=timeout)

    async def _get_client(self):
        if self._client is None:
            if self._client_factory is not None:
                self._client = self._client_factory()
            else:
                self._client = self._make_default_client()
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    # -- config resolution --------------------------------------------------
    def _base_url(self) -> str:
        base = (self.config.get("base_url") or "").rstrip("/")
        return base or "https://api.openai.com/v1"

    def _completions_url(self) -> str:
        base = self._base_url()
        path = self.config.get("completions_path") or DEFAULT_COMPLETIONS_PATH
        if not path.startswith("/"):
            path = "/" + path
        return f"{base}{path}"

    def _default_model(self) -> Optional[str]:
        return self.config.get("model") or self.config.get("default_model")

    def _request_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.auth_header and self.auth_scheme:
            key = self.config.get("api_key") or self.config.get("token")
            if key:
                headers[self.auth_header] = f"{self.auth_scheme} {key}".strip()
        elif self.auth_header and not self.auth_scheme:
            key = self.config.get("api_key") or self.config.get("token")
            if key:
                headers[self.auth_header] = key
        extra = self.config.get("headers")
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    # -- core completion ----------------------------------------------------
    async def complete(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> CompletionResult:
        from ..errors import ProviderError

        model = model or self._default_model()
        payload: Dict[str, Any] = {"model": model, "messages": messages}
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        params = self.config.get("parameters") or {}
        for k, v in (params or {}).items():
            payload.setdefault(k, v)
        payload.update(kwargs)

        client = await self._get_client()
        try:
            resp = await client.post(
                self._completions_url(), json=payload, headers=self._request_headers()
            )
        except Exception as exc:  # httpx.TransportError and others
            raise ProviderError(f"Provider '{self.type}' transport error: {exc}") from exc

        if resp.status_code >= 400:
            # SECURITY: don't leak upstream provider response bodies to callers.
            # Log the full detail server-side instead; expose only a stable,
            # generic message that carries the status code.
            logging.getLogger(__name__).warning(
                "provider '%s' returned HTTP %s: %.400s",
                self.type,
                resp.status_code,
                resp.text,
            )
            raise ProviderError(
                f"Provider '{self.type}' returned error status {resp.status_code}"
            )

        data = self._parse_json(resp)

        usage = self._extract_usage(data, messages)
        content = self._extract_content(data)
        return CompletionResult(
            content=content,
            usage=usage,
            model=data.get("model") or model,
            metadata={
                "id": data.get("id"),
                "finish_reason": self._first_finish_reason(data),
                "http_status": resp.status_code,
            },
        )

    # -- parsing helpers ------------------------------------------------------
    @staticmethod
    def _parse_json(resp):
        from ..errors import ProviderError

        try:
            return resp.json()
        except Exception as exc:
            raise ProviderError(
                f"Provider returned non-JSON response: {resp.text[:300]!r}"
            ) from exc

    @staticmethod
    def _first_finish_reason(data: Dict[str, Any]) -> Optional[str]:
        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            return choices[0].get("finish_reason")
        return None

    @staticmethod
    def _extract_content(data: Dict[str, Any]) -> str:
        from ..errors import ProviderError

        choices = data.get("choices")
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") or {}
            content = message.get("content")
            if isinstance(content, str):
                return content
        # Also accept a top-level "text" for text-generation style responses.
        if isinstance(data.get("text"), str):
            return data["text"]
        raise ProviderError("Provider response contained no usable content")

    def _extract_usage(
        self, data: Dict[str, Any], messages: List[Dict[str, str]]
    ) -> Usage:
        from ..errors import TokenUsageError

        u = data.get("usage")
        if isinstance(u, dict):
            prompt = int(u.get("prompt_tokens") or 0)
            completion = int(u.get("completion_tokens") or 0)
            total = int(u.get("total_tokens") or 0)
            if prompt or completion or total:
                return Usage(
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    total_tokens=total,
                )
        # Fallback: estimate from payload/text if the backend omitted usage.
        prompt_text = "".join(str(m.get("content") or "") for m in messages if m.get("role") != "assistant") or ""
        content = self._safe_content(data)
        return Usage(
            prompt_tokens=estimate_tokens(prompt_text),
            completion_tokens=estimate_tokens(content),
        )

    @staticmethod
    def _safe_content(data: Dict[str, Any]) -> str:
        try:
            return OpenAICompatHttpProvider._extract_content(data)
        except Exception:
            return ""