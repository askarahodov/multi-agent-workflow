"""Cross-service injection smoke: both product packages installed in Native E2E CI."""
from __future__ import annotations

import os

import pytest

from orchestration_server.native_worker_wiring import (
    construct_trusted_runner, trusted_runner_config_from_env,
)


@pytest.mark.asyncio
async def test_trusted_runner_builds_with_both_installed_packages_without_io(tmp_path):
    gateway = tmp_path / "gateway"
    provider_file = tmp_path / "provider"
    gateway.write_text("gateway-private-key-long-enough-12345678", encoding="ascii")
    provider_file.write_text("provider-private-key-not-same-12345678", encoding="ascii")
    os.chmod(gateway, 0o600)
    os.chmod(provider_file, 0o600)
    config = trusted_runner_config_from_env({
        "MAW_TRUSTED_GATEWAY_ENABLED": "1",
        "MAW_TRUSTED_GATEWAY_URL": "https://gateway.internal",
        "MAW_TRUSTED_GATEWAY_KEY_FILE": str(gateway),
        "MAW_OPENROUTER_KEY_FILE": str(provider_file),
        "MAW_NATIVE_WORKER_AGENT_ID": "trusted-agent",
        "MAW_OPENROUTER_MODEL": "openai/gpt-4o-mini",
        "MAW_NATIVE_WORKER_TRUSTED_PROMPT": "Only approved file tools.",
        "MAW_NATIVE_WORKER_MAX_TURNS": "2",
        "MAW_NATIVE_WORKER_MAX_TOTAL_TOKENS": "256",
        "MAW_NATIVE_WORKER_MAX_TOOL_CALLS": "2",
    })
    runner, wrapper = construct_trusted_runner(config)
    try:
        assert runner._agent_id == "trusted-agent"
        assert runner._gateway_url == "https://gateway.internal"
        assert runner._limits == (2, 256, 2)
        assert wrapper._adapter._client is None
        assert wrapper._adapter._default_model() == "openai/gpt-4o-mini"
        assert "provider-private" not in repr(config)
    finally:
        await wrapper.aclose()
