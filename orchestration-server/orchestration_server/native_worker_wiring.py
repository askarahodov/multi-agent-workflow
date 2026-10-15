"""Explicit trusted wiring for an opt-in leased OpenRouter → HTTPS gateway runner.

No provider is called at import/build time. Configuration is operator-owned,
model/workspace IDs are never accepted from model or task payload, and the
gateway credential differs from the orchestrator and provider API keys.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlsplit

from .native_worker_bootstrap import _private_key


@dataclass(frozen=True, repr=False)
class TrustedRunnerConfig:
    gateway_url: str
    gateway_key: str
    provider_key: str
    agent_id: str
    model: str
    prompt: str
    max_turns: int
    max_total_tokens: int
    max_tool_calls: int

    def __repr__(self) -> str:
        return "TrustedRunnerConfig(<redacted>)"


def trusted_runner_config_from_env(env: Mapping[str, str]) -> TrustedRunnerConfig:
    if env.get("MAW_TRUSTED_GATEWAY_ENABLED") != "1":
        raise ValueError("Trusted gateway requires explicit opt-in")
    try:
        config = TrustedRunnerConfig(
            gateway_url=env["MAW_TRUSTED_GATEWAY_URL"],
            gateway_key=_private_key(env["MAW_TRUSTED_GATEWAY_KEY_FILE"]),
            provider_key=_private_key(env["MAW_OPENROUTER_KEY_FILE"]),
            agent_id=env["MAW_NATIVE_WORKER_AGENT_ID"],
            model=env["MAW_OPENROUTER_MODEL"],
            prompt=env["MAW_NATIVE_WORKER_TRUSTED_PROMPT"],
            max_turns=int(env["MAW_NATIVE_WORKER_MAX_TURNS"]),
            max_total_tokens=int(env["MAW_NATIVE_WORKER_MAX_TOTAL_TOKENS"]),
            max_tool_calls=int(env["MAW_NATIVE_WORKER_MAX_TOOL_CALLS"]),
        )
    except KeyError:
        raise ValueError("Trusted runner configuration incomplete") from None
    url = urlsplit(config.gateway_url)
    if (
        url.scheme != "https" or not url.hostname
        or url.username or url.password or url.query or url.fragment
        or url.path not in ("", "/")
    ):
        raise ValueError("Trusted gateway requires bare HTTPS origin")
    if not 32 <= len(config.gateway_key) <= 128:
        raise ValueError("Trusted gateway key length invalid")
    if config.gateway_key in (config.provider_key,) or config.provider_key == "":
        raise ValueError("Trusted credential separation required")
    if not config.model or len(config.model) > 128 or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/" for c in config.model
    ):
        raise ValueError("Operator must select a valid fixed model")
    if not 1 <= len(config.prompt) <= 4096 or not config.prompt.strip():
        raise ValueError("Trusted prompt required")
    if not (1 <= config.max_turns <= 16 and 1 <= config.max_total_tokens <= 16384
            and 0 <= config.max_tool_calls <= 32):
        raise ValueError("Trusted runner budgets outside bounds")
    return config


def construct_trusted_runner(config: TrustedRunnerConfig):
    """Inject trusted provider and gateway; never rely on task-supplied config."""
    from agent_management.providers.adapters import OpenRouterProvider
    from agent_management.trusted_fs_client import TrustedLeasedGatewayRunner

    class FixedModelProvider:
        def __init__(self):
            self._adapter = OpenRouterProvider({
                "api_key": config.provider_key,
                "model": config.model,
                "timeout_seconds": 30,
            })

        def stream(self, messages, *, tools, max_tokens):
            return self._adapter.stream(
                messages, tools=tools, max_tokens=max_tokens,
                model=config.model,
            )

        async def aclose(self):
            await self._adapter.aclose()

    provider = FixedModelProvider()
    runner = TrustedLeasedGatewayRunner(
        gateway_url=config.gateway_url, gateway_key=config.gateway_key,
        agent_id=config.agent_id, provider=provider,
        messages=[{"role": "system", "content": config.prompt}],
        max_turns=config.max_turns,
        max_total_tokens=config.max_total_tokens,
        max_tool_calls=config.max_tool_calls,
    )
    return runner, provider
