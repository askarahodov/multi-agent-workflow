"""OpenRouter provider adapter.

Calls the public OpenRouter ``/api/v1/chat/completions`` endpoint. The adapter is
pure: all credentials and defaults come from the ``auth_config`` dict resolved by the
service layer, so no business logic touches a concrete backend.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._http import OpenAICompatHttpProvider
from .base import BaseProvider, CompletionResult, Usage


class OpenRouterProvider(OpenAICompatHttpProvider, BaseProvider):
    type: str = "openrouter"
    capabilities: Dict[str, bool] = {"streaming": True}

    def _base_url(self) -> str:
        return (self.config.get("base_url") or "https://openrouter.ai/api/v1").rstrip("/")

    def _default_model(self) -> Optional[str]:
        # OpenRouter supports sentinel models like "openai/gpt-4o" or defaults.
        return super()._default_model() or "openai/gpt-4o-mini"


class HuggingFaceProvider(OpenAICompatHttpProvider, BaseProvider):
    """Adapter for OpenAI-compatible HuggingFace Inference endpoints.

    Points at a hosted Inference Endpoint or the Inference API's chat/completions
    route (``https://api-inference.huggingface.co/v1/chat/completions``) and
    authenticates with an ``api_token`` (``HF_API_TOKEN``.) Falls back to the
    text-generation route when ``mode='text'`` is configured.
    """

    type: str = "huggingface"
    capabilities: Dict[str, bool] = {"streaming": False, "offline_tokens": False}

    def __init__(self, config: Dict[str, Any], **kwargs: Any) -> None:
        self.mode = config.get("mode", "chat")
        super().__init__(config, **kwargs)

    def _base_url(self) -> str:
        return (self.config.get("base_url") or "https://api-inference.huggingface.co").rstrip("/")

    def _completions_url(self) -> str:
        if self.mode == "text":
            model = self._default_model() or "gpt2"
            return f"{self._base_url()}/models/{model}"
        return super()._completions_url()

    def _request_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        token = self.config.get("api_token") or self.config.get("token") or self.config.get("api_key")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        extra = self.config.get("headers")
        if isinstance(extra, dict):
            headers.update({str(k): str(v) for k, v in extra.items()})
        return headers

    async def complete(self, messages, **kwargs):
        if self.mode == "text":
            return await self._complete_text(messages, **kwargs)
        return await super().complete(messages, **kwargs)

    async def _complete_text(self, messages, *, model=None, temperature=None, max_tokens=None, **kwargs):
        # text-generation payload: join messages into a prompt, run, read "generated_text".
        from ..errors import ProviderError

        client = await self._get_client()
        prompt = "".join(str(m.get("content") or "") for m in messages) or ""
        payload: Dict[str, Any] = {"inputs": prompt}
        parameters: Dict[str, Any] = {}
        if temperature is not None:
            parameters["temperature"] = temperature
        if max_tokens is not None:
            parameters["max_new_tokens"] = max_tokens
        if parameters:
            payload["parameters"] = parameters
        try:
            resp = await client.post(
                self._completions_url(), json=payload, headers=self._request_headers()
            )
        except Exception as exc:
            raise ProviderError(f"Provider '{self.type}' transport error: {exc}") from exc
        if resp.status_code >= 400:
            raise ProviderError(
                f"Provider '{self.type}' returned status {resp.status_code}: {resp.text[:400]}"
            )
        try:
            data = resp.json()
        except Exception as exc:
            raise ProviderError("Provider returned non-JSON response") from exc
        if isinstance(data, list) and data:
            content = data[0].get("generated_text", "")
        elif isinstance(data, dict):
            content = data.get("generated_text", "")
            if "error" in data:
                content = f"{data['error']}\n{content}"
        else:
            content = ""
        usage = self._extract_usage({"text": content}, messages)
        return CompletionResult(
            content=content,
            usage=usage,
            model=model or self._default_model(),
            metadata={"http_status": resp.status_code, "mode": "text"},
        )


class CustomProvider(OpenAICompatHttpProvider, BaseProvider):
    """Generic adapter for any custom / self-hosted OpenAI-compatible server.

    ``base_url`` is required (e.g. ``http://localhost:8080/v1``). Credentials are
    passed via ``api_key``/``token`` (optionally a custom ``auth_header``), and
    ``completions_path`` can override ``/chat/completions``."""

    type: str = "custom"
    capabilities: Dict[str, bool] = {"streaming": False, "offline_tokens": True}

    def _base_url(self) -> str:
        base = super()._base_url()
        if base.startswith("https://api.openai.com"):
            from ..errors import ProviderError

            raise ProviderError("Custom provider requires a 'base_url'")
        return base

    def _default_model(self) -> Optional[str]:
        return super()._default_model() or "model"


class MockProvider(BaseProvider):
    """Deterministic, offline provider used for unit tests and offline development.

    Ignores the model and returns a fixed echo reply while reporting a controllable,
    reproducible token count -- making token-usage assertions independent of any remote
    service.
    """

    type: str = "mock"
    capabilities: Dict[str, bool] = {"streaming": False, "offline_tokens": True}

    def __init__(self, config: Dict[str, Any] = None) -> None:
        from .base import ResolvedProviderConfig

        ResolvedProviderConfig.__init__(self, config)
        self.reply = self.config.get("reply", "mock reply")
        self.prompt_tokens = int(self.config.get("prompt_tokens", 10))
        self.completion_tokens = int(self.config.get("completion_tokens", 5))
        self.fail_next = bool(self.config.get("fail_next", False))

    async def complete(self, messages, *, model=None, **kwargs):
        from ..errors import ProviderError

        if self.fail_next:
            self.fail_next = False
            raise ProviderError("mock provider configured to fail")
        usage = Usage(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
        )
        return CompletionResult(
            content=self.reply,
            usage=usage,
            model=model or self.config.get("model") or "mock-model",
        )