"""Offline trust-boundary tests: no OpenRouter request is made."""
from __future__ import annotations

import os
from dataclasses import replace

import pytest

from orchestration_server.native_worker_wiring import (
    construct_trusted_runner, trusted_runner_config_from_env,
)


def trusted_env(tmp_path):
    gateway = tmp_path / "gateway-secret"
    provider = tmp_path / "provider-secret"
    gateway.write_text("gateway-secret-with-32-characters-0001", encoding="ascii")
    provider.write_text("provider-secret-with-32-characters-0002", encoding="ascii")
    os.chmod(gateway, 0o600)
    os.chmod(provider, 0o600)
    return {
        "MAW_TRUSTED_GATEWAY_ENABLED": "1",
        "MAW_TRUSTED_GATEWAY_URL": "https://gateway.internal",
        "MAW_TRUSTED_GATEWAY_KEY_FILE": str(gateway),
        "MAW_OPENROUTER_KEY_FILE": str(provider),
        "MAW_NATIVE_WORKER_AGENT_ID": "agent-owned-by-control-plane",
        "MAW_OPENROUTER_MODEL": "openai/gpt-4o-mini",
        "MAW_NATIVE_WORKER_TRUSTED_PROMPT": "Use only approved file tools.",
        "MAW_NATIVE_WORKER_MAX_TURNS": "2",
        "MAW_NATIVE_WORKER_MAX_TOTAL_TOKENS": "256",
        "MAW_NATIVE_WORKER_MAX_TOOL_CALLS": "2",
    }


def test_trusted_runner_defaults_to_disabled(tmp_path):
    e = trusted_env(tmp_path)
    e.pop("MAW_TRUSTED_GATEWAY_ENABLED")
    with pytest.raises(ValueError, match="opt-in"):
        trusted_runner_config_from_env(e)


@pytest.mark.parametrize("url", [
    "http://gateway.internal", "https://gateway.internal/dispatch",
    "https://user:key@gateway.internal", "https://gateway.internal?x=secret",
    "http://127.0.0.1",
])
def test_untrusted_gateway_urls_denied(tmp_path, url):
    with pytest.raises(ValueError):
        trusted_runner_config_from_env({**trusted_env(tmp_path), "MAW_TRUSTED_GATEWAY_URL": url})


def test_reusing_gateway_and_provider_key_denied(tmp_path):
    e = trusted_env(tmp_path)
    e["MAW_OPENROUTER_KEY_FILE"] = e["MAW_TRUSTED_GATEWAY_KEY_FILE"]
    with pytest.raises(ValueError, match="separation"):
        trusted_runner_config_from_env(e)


@pytest.mark.parametrize("var,bad", [
    ("MAW_OPENROUTER_MODEL", ""),
    ("MAW_OPENROUTER_MODEL", "https://attacker"),
    ("MAW_OPENROUTER_MODEL", "bad model"),
    ("MAW_NATIVE_WORKER_MAX_TURNS", "17"),
    ("MAW_NATIVE_WORKER_MAX_TOTAL_TOKENS", "16385"),
    ("MAW_NATIVE_WORKER_MAX_TOOL_CALLS", "33"),
    ("MAW_NATIVE_WORKER_TRUSTED_PROMPT", ""),
])
def test_unbounded_or_untrusted_settings_denied(tmp_path, var, bad):
    with pytest.raises(ValueError):
        trusted_runner_config_from_env({**trusted_env(tmp_path), var: bad})


async def test_trusted_injected_runner_construction_has_no_provider_io(tmp_path):
    config = trusted_runner_config_from_env(trusted_env(tmp_path))
    assert "provider-secret" not in repr(config)
    runner, provider = construct_trusted_runner(config)
    try:
        assert runner._agent_id == config.agent_id
        assert runner._gateway_url == "https://gateway.internal"
        assert runner._limits == (2, 256, 2)
        assert provider._adapter._client is None
        assert provider._adapter._default_model() == "openai/gpt-4o-mini"
    finally:
        await provider.aclose()
