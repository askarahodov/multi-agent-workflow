"""Export derives native model/system/policy from one real SQLite profile, never auth JSON."""
from __future__ import annotations

import json
import os

import pytest

from agent_management.models import AgentDefinition, ModelProfile, Provider, ToolPolicy
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
    assert snapshot["schema_version"] == 2
    assert snapshot["agent_role"] == definition.role == "generalist"
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


@pytest.mark.parametrize("permissions", [
    {"untrusted-sensitive-field-name": ["x"]},
    {"fs_read": "not-a-list"},
    {"fs_read": [17]},
    ["fs_read"],
    "fs_read",
    {"fs_read": [""]},
    {"fs_read": ["x" * 513]},
    {"fs_read": [f"/workspace/src/{i}" for i in range(33)]},
    {"fs_write": [""]},
])
@pytest.mark.asyncio
async def test_export_rejects_malformed_legacy_policy_without_leaking_fields(harness, permissions):
    provider = await harness.service.providers.create_provider({
        "name": "legacy-invalid-native", "type": "openrouter",
    })
    model = await harness.service.model_profiles.create({
        "provider_id": provider.id, "name": "legacy-invalid-model", "model_id": "offline/model",
    })
    policy = await harness.service.tool_policies.create({
        "name": "legacy-invalid-policy", "permissions": {"fs_read": ["/workspace/src/**"]},
    })
    definition = await harness.service.agent_definitions.create({
        "name": "legacy-invalid-definition", "role": "developer",
        "system_prompt": "Trusted instructions", "default_model_profile_id": model.id,
        "default_tool_policy_id": policy.id,
    })
    # Simulate rows imported before the service's validation; exporter is a
    # separate trust boundary and must refuse them with a sanitized error.
    async with harness.sf() as session:
        stored = await session.get(ToolPolicy, policy.id)
        stored.permissions = permissions
        await session.commit()
    with pytest.raises(NativeProfileExportError, match="(?i)tool policy") as error:
        await export_native_profile(harness.sf, definition.id, model.id, policy.id)
    assert "untrusted-sensitive-field-name" not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.asyncio
async def test_export_accepts_worker_compatible_policy_bounds(harness):
    provider = await harness.service.providers.create_provider({
        "name": "bounded-native-provider", "type": "openrouter",
    })
    model = await harness.service.model_profiles.create({
        "provider_id": provider.id, "name": "bounded-native-model", "model_id": "offline/model",
    })
    patterns = [f"/workspace/src/{i}" for i in range(31)] + ["x" * 512]
    policy = await harness.service.tool_policies.create({
        "name": "bounded-native-policy", "permissions": {"fs_read": patterns},
    })
    definition = await harness.service.agent_definitions.create({
        "name": "bounded-native-tester", "role": "tester", "system_prompt": "Review evidence",
        "default_model_profile_id": model.id, "default_tool_policy_id": policy.id,
    })
    snapshot = await export_native_profile(harness.sf, definition.id, model.id, policy.id)
    assert snapshot["schema_version"] == 2 and snapshot["agent_role"] == "tester"
    assert snapshot["permissions"]["fs_read"] == patterns
    assert all(not snapshot["permissions"][kind] for kind in ("fs_write", "git", "shell", "network"))


@pytest.mark.parametrize("role", ["Reviewer", "reviewer ", "", "x" * 33, "a/b"])
@pytest.mark.asyncio
async def test_export_rejects_invalid_legacy_role_identity(harness, role):
    provider = await harness.service.providers.create_provider({
        "name": "invalid-role-provider", "type": "openrouter",
    })
    model = await harness.service.model_profiles.create({
        "provider_id": provider.id, "name": "invalid-role-model", "model_id": "offline/model",
    })
    policy = await harness.service.tool_policies.create({
        "name": "invalid-role-policy", "permissions": {},
    })
    definition = await harness.service.agent_definitions.create({
        "name": "invalid-role-agent", "system_prompt": "Review safely",
        "default_model_profile_id": model.id, "default_tool_policy_id": policy.id,
    })
    async with harness.sf() as session:
        row = await session.get(AgentDefinition, definition.id)
        row.role = role
        await session.commit()
    with pytest.raises(NativeProfileExportError, match="role invalid"):
        await export_native_profile(harness.sf, definition.id, model.id, policy.id)


async def _persisted_profile_for_boundary_test(harness):
    provider = await harness.service.providers.create_provider({
        "name": "revision-bound-provider", "type": "openrouter",
    })
    model = await harness.service.model_profiles.create({
        "provider_id": provider.id, "name": "revision-bound-model", "model_id": "offline/model",
    })
    policy = await harness.service.tool_policies.create({
        "name": "revision-bound-policy", "permissions": {},
    })
    definition = await harness.service.agent_definitions.create({
        "name": "revision-bound-agent", "role": "developer", "system_prompt": "Review safely",
        "default_model_profile_id": model.id, "default_tool_policy_id": policy.id,
    })
    return definition, model, policy, provider


@pytest.mark.parametrize("record_type,index", [
    (AgentDefinition, 0), (ModelProfile, 1), (ToolPolicy, 2), (Provider, 3),
])
@pytest.mark.parametrize("version", [0, -1, 2147483648])
@pytest.mark.asyncio
async def test_export_rejects_invalid_persisted_revision_at_producer(harness, record_type, index, version):
    records = await _persisted_profile_for_boundary_test(harness)
    async with harness.sf() as session:
        row = await session.get(record_type, records[index].id)
        row.version = version
        await session.commit()
    with pytest.raises(NativeProfileExportError, match="revision invalid"):
        await export_native_profile(harness.sf, *(r.id for r in records[:3]))


@pytest.mark.asyncio
async def test_export_accepts_maximum_supported_revision(harness):
    records = await _persisted_profile_for_boundary_test(harness)
    async with harness.sf() as session:
        for cls, record in zip((AgentDefinition, ModelProfile, ToolPolicy, Provider), records):
            row = await session.get(cls, record.id)
            row.version = 2147483647
        await session.commit()
    snapshot = await export_native_profile(harness.sf, *(r.id for r in records[:3]))
    for field in ("agent_definition_version", "model_profile_version",
                  "tool_policy_version", "provider_version"):
        assert snapshot[field] == 2147483647


@pytest.mark.parametrize("parameters", [[], "", False, 0])
@pytest.mark.asyncio
async def test_export_rejects_falsy_non_object_persisted_model_parameters(harness, parameters):
    records = await _persisted_profile_for_boundary_test(harness)
    async with harness.sf() as session:
        model = await session.get(ModelProfile, records[1].id)
        model.parameters = parameters
        await session.commit()
    with pytest.raises(NativeProfileExportError, match="Model parameters invalid"):
        await export_native_profile(harness.sf, *(r.id for r in records[:3]))


def test_shared_profile_identity_and_revision_bounds():
    from shared.agent_role import valid_profile_uuid, valid_profile_revision_number
    assert valid_profile_uuid("11111111-1111-4111-8111-111111111111")
    for invalid in (None, "", "11111111-1111-0111-8111-111111111111", "not-a-uuid"):
        assert not valid_profile_uuid(invalid)
    for valid in (1, 2147483647):
        assert valid_profile_revision_number(valid)
    for invalid in (True, False, 0, -1, 2147483648, 1.0, "1", None):
        assert not valid_profile_revision_number(invalid)
