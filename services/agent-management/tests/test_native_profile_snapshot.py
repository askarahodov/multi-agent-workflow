"""Export derives native model/system/policy from one real SQLite profile, never auth JSON."""
from __future__ import annotations

import json
import os

import pytest

from agent_management.native_profile_snapshot import (
    NativeProfileExportError, export_native_profile, write_private_snapshot,
)


@pytest.mark.asyncio
async def test_export_applies_persisted_definition_model_policy_without_secrets(harness, tmp_path):
    provider = await harness.service.providers.create_provider({
        "name": "native-export-provider", "type": "openrouter",
        "auth_config": {"api_key": "never-export-secret"},
    })
    model = await harness.service.model_profiles.create({
        "provider_id": provider.id, "name": "native-model", "model_id": "example/model",
        "parameters": {"max_tokens": 64},
    })
    policy = await harness.service.tool_policies.create({
        "name": "native-export-policy",
        "permissions": {"fs_read": ["/workspace/src/**"], "fs_write": []},
    })
    definition = await harness.service.agent_definitions.create({
        "name": "native-export-agent", "system_prompt": "Trusted operator instructions",
        "default_model_profile_id": model.id, "default_tool_policy_id": policy.id,
    })
    snapshot = await export_native_profile(harness.sf, definition.id, model.id, policy.id)
    assert snapshot["model_id"] == "example/model"
    assert snapshot["model_max_tokens"] == 64
    assert snapshot["system_prompt"] == "Trusted operator instructions"
    assert snapshot["agent_definition_version"] == definition.version
    assert snapshot["permissions"]["fs_read"] == ["/workspace/src/**"]
    assert "never-export-secret" not in json.dumps(snapshot)
    assert "auth_config" not in snapshot
    output = tmp_path / "snapshot.json"
    write_private_snapshot(str(output), snapshot)
    assert os.stat(output).st_mode & 0o077 == 0
    assert json.loads(output.read_text()) == snapshot
    with pytest.raises(FileExistsError):
        write_private_snapshot(str(output), snapshot)


@pytest.mark.asyncio
async def test_export_fails_closed_on_foreign_refs_and_unenforced_budget(harness):
    provider = await harness.service.providers.create_provider({
        "name": "native-deny-provider", "type": "openrouter",
    })
    model = await harness.service.model_profiles.create({
        "provider_id": provider.id, "name": "native-deny-model", "model_id": "m",
    })
    policy = await harness.service.tool_policies.create({
        "name": "native-deny-policy", "permissions": {"fs_read": ["/workspace/src/**"]},
    })
    definition = await harness.service.agent_definitions.create({
        "name": "native-deny-agent", "system_prompt": "Do only approved actions",
        "default_model_profile_id": model.id, "default_tool_policy_id": policy.id,
        "budget_limit": 0.10,
    })
    with pytest.raises(NativeProfileExportError, match="references unavailable"):
        await export_native_profile(harness.sf, definition.id, model.id, provider.id)
    with pytest.raises(NativeProfileExportError, match="USD budget"):
        await export_native_profile(harness.sf, definition.id, model.id, policy.id)
    await harness.service.agent_definitions.update(definition.id, {"budget_limit": None})
    await harness.service.providers.update_provider(provider.id, {"is_active": False})
    with pytest.raises(NativeProfileExportError, match="unavailable"):
        await export_native_profile(harness.sf, definition.id, model.id, policy.id)
