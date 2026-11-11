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


@pytest.mark.asyncio
async def test_persisted_profile_export_controls_native_model_prompt_and_token_cap(tmp_path):
    """Cross-package proof: real SQLite settings configure the leased runner, not task JSON."""
    from agent_management.db import build_engine, build_session_factory, create_all
    from agent_management.native_profile_snapshot import (
        export_native_profile, write_private_snapshot,
    )
    from agent_management.services import AgentManagementService
    from orchestration_server.native_profile_binding import ENV_KEYS

    engine = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'native-profiles.db'}")
    await create_all(engine)
    sf = build_session_factory(engine)
    service = AgentManagementService(sf)
    try:
        provider = await service.providers.create_provider({
            "name": "native-db-provider", "type": "openrouter",
            "auth_config": {"api_key": "not-exported-secret"},
        })
        model = await service.model_profiles.create({
            "provider_id": provider.id, "name": "native-db-model",
            "model_id": "example/verified", "parameters": {"max_tokens": 7},
        })
        policy = await service.tool_policies.create({
            "name": "native-db-file-policy",
            "permissions": {"fs_read": ["/srv/maw/workspace/src/**"], "fs_write": []},
        })
        definition = await service.agent_definitions.create({
            "name": "native-db-agent",
            "default_model_profile_id": model.id,
            "default_tool_policy_id": policy.id,
            "system_prompt": "Use only trusted native profile instructions.",
        })
        snapshot = await export_native_profile(sf, definition.id, model.id, policy.id)
    finally:
        await engine.dispose()

    approved = tmp_path / "approved.json"
    write_private_snapshot(str(approved), snapshot)
    gateway = tmp_path / "gateway.key"
    provider_key = tmp_path / "provider.key"
    gateway.write_text("gateway-credential-private-123456789012", encoding="ascii")
    provider_key.write_text("provider-credential-private-123456789012", encoding="ascii")
    os.chmod(gateway, 0o600)
    os.chmod(provider_key, 0o600)

    env = {
        "MAW_TRUSTED_GATEWAY_ENABLED": "1",
        "MAW_TRUSTED_GATEWAY_URL": "https://gateway.internal",
        "MAW_TRUSTED_GATEWAY_KEY_FILE": str(gateway),
        "MAW_OPENROUTER_KEY_FILE": str(provider_key),
        "MAW_NATIVE_WORKER_AGENT_ID": "trusted-native-agent",
        "MAW_OPENROUTER_MODEL": snapshot["model_id"],
        "MAW_NATIVE_WORKER_TRUSTED_PROMPT": snapshot["system_prompt"],
        "MAW_NATIVE_WORKER_MAX_TURNS": "2",
        "MAW_NATIVE_WORKER_MAX_TOTAL_TOKENS": "256",
        "MAW_NATIVE_WORKER_MAX_TOOL_CALLS": "2",
        "MAW_NATIVE_PROFILE_GATEWAY_ROOT": "/srv/maw/workspace",
        "MAW_NATIVE_PROFILE_SNAPSHOT_FILE": str(approved),
        **dict(zip(ENV_KEYS, (definition.id, model.id, policy.id))),
    }
    config = trusted_runner_config_from_env(env)
    # Cross-service consistency: persisted AgentManagement policy must match
    # the *deployed* trusted gateway path, not an unrelated operator mount.
    with pytest.raises(ValueError, match="policy paths outside gateway workspace"):
        trusted_runner_config_from_env({
            **env, "MAW_NATIVE_PROFILE_GATEWAY_ROOT": "/workspace",
        })
    runner, provider_wrapper = construct_trusted_runner(config)
    try:
        assert runner._messages == [
            {"role": "system", "content": snapshot["system_prompt"]},
        ]
        assert runner._profile_permissions["fs_write"] == []
        assert runner._profile_workspace_root == "/srv/maw/workspace"
        assert provider_wrapper._adapter._default_model() == "example/verified"
        calls = []

        async def fake_stream(messages, *, tools, max_tokens, model):
            calls.append((model, max_tokens))
            if False:
                yield {}

        provider_wrapper._adapter.stream = fake_stream
        async for _ in provider_wrapper.stream(
            [{"role": "user", "content": "offline"}],
            tools=[], max_tokens=150,
        ):
            pass
        assert calls == [("example/verified", 7)]
        assert "not-exported-secret" not in str(snapshot)
        assert "not-exported-secret" not in repr(config)
    finally:
        await provider_wrapper.aclose()
