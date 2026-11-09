"""Backend contract: independent QA roles cannot receive tool side effects.

All tests are offline and use file-backed SQLite or real HTTP ASGI endpoints.
"""
from __future__ import annotations

import pytest

from agent_management.errors import BusinessRuleError
from agent_management.models import AgentDefinition
from agent_management.native_profile_snapshot import (
    NativeProfileExportError, export_native_profile,
)
from tests.test_api import client_for


FORBIDDEN = ("fs_write", "git", "shell", "network")
ROLES = ("tester", "reviewer", "security")


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("kind", FORBIDDEN)
@pytest.mark.asyncio
async def test_independent_profile_create_denies_unsafe_tool_policy(harness, role, kind):
    policy = await harness.service.tool_policies.create({
        "name": f"unsafe-{role}-{kind}",
        "permissions": {kind: ["/workspace/**" if kind.startswith("fs_") else "*"]},
    })
    with pytest.raises(BusinessRuleError, match="read-only"):
        await harness.service.agent_definitions.create({
            "name": f"invalid-{role}-{kind}", "role": role,
            "default_tool_policy_id": policy.id,
        })
    rows, total, _ = await harness.service.agent_definitions.list()
    assert total == 0 and rows == []


@pytest.mark.asyncio
async def test_profile_patch_and_role_change_are_atomic(harness):
    unsafe = await harness.service.tool_policies.create({
        "name": "patch-unsafe", "permissions": {"git": ["commit"]},
    })
    safe = await harness.service.tool_policies.create({
        "name": "patch-readonly", "permissions": {"fs_read": ["/workspace/src/**"]},
    })
    reviewer = await harness.service.agent_definitions.create({
        "name": "existing-reviewer", "role": "reviewer",
        "default_tool_policy_id": safe.id,
    })
    with pytest.raises(BusinessRuleError, match="read-only"):
        await harness.service.agent_definitions.update(reviewer.id, {
            "default_tool_policy_id": unsafe.id, "version": reviewer.version,
        })
    assert (await harness.service.agent_definitions.get(reviewer.id)).version == reviewer.version
    developer = await harness.service.agent_definitions.create({
        "name": "developer-to-reviewer", "role": "developer",
        "default_tool_policy_id": unsafe.id,
    })
    with pytest.raises(BusinessRuleError, match="read-only"):
        await harness.service.agent_definitions.update(developer.id, {
            "role": "reviewer", "version": developer.version,
        })
    unchanged = await harness.service.agent_definitions.get(developer.id)
    assert unchanged.role == "developer" and unchanged.version == developer.version
    updated = await harness.service.agent_definitions.update(developer.id, {
        "role": "reviewer", "default_tool_policy_id": safe.id,
        "version": developer.version,
    })
    assert updated.role == "reviewer" and updated.default_tool_policy_id == safe.id


@pytest.mark.asyncio
async def test_instance_override_and_existing_policy_widening_denied(harness):
    unsafe = await harness.service.tool_policies.create({
        "name": "instance-unsafe", "permissions": {"shell": ["python"]},
    })
    safe = await harness.service.tool_policies.create({
        "name": "instance-safe", "permissions": {"fs_read": ["/workspace/src/**"]},
    })
    definition = await harness.service.agent_definitions.create({
        "name": "instance-reviewer", "role": "reviewer",
        "default_tool_policy_id": safe.id,
    })
    with pytest.raises(BusinessRuleError, match="read-only"):
        await harness.service.agent_instances.create({
            "agent_definition_id": definition.id, "tool_policy_id": unsafe.id,
        })
    with pytest.raises(BusinessRuleError, match="Cannot widen"):
        await harness.service.tool_policies.update(safe.id, {
            "permissions": {"fs_write": ["/workspace/out/**"]}, "version": safe.version,
        })
    stored = await harness.service.tool_policies.get(safe.id)
    assert stored.version == safe.version and stored.permissions.get("fs_read")

    # A policy only selected by an instance override is equally protected.
    second = await harness.service.tool_policies.create({
        "name": "override-only", "permissions": {"fs_read": ["/workspace/input/**"]},
    })
    await harness.service.agent_instances.create({
        "agent_definition_id": definition.id, "tool_policy_id": second.id,
    })
    with pytest.raises(BusinessRuleError, match="Cannot widen"):
        await harness.service.tool_policies.update(second.id, {
            "permissions": {"network": ["*"]}, "version": second.version,
        })


@pytest.mark.asyncio
async def test_role_change_cannot_keep_existing_unsafe_instance_override(harness):
    safe = await harness.service.tool_policies.create({
        "name": "convert-safe", "permissions": {"fs_read": ["/workspace/**"]},
    })
    unsafe = await harness.service.tool_policies.create({
        "name": "convert-unsafe", "permissions": {"network": ["*"]},
    })
    definition = await harness.service.agent_definitions.create({
        "name": "instance-convert", "role": "developer",
        "default_tool_policy_id": safe.id,
    })
    await harness.service.agent_instances.create({
        "agent_definition_id": definition.id, "tool_policy_id": unsafe.id,
    })
    with pytest.raises(BusinessRuleError, match="read-only"):
        await harness.service.agent_definitions.update(definition.id, {
            "role": "tester", "version": definition.version,
        })
    assert (await harness.service.agent_definitions.get(definition.id)).role == "developer"


@pytest.mark.asyncio
async def test_http_denies_direct_profile_and_policy_escalation(app):
    async with await client_for(app) as client:
        dangerous = (await client.post("/api/v1/tool-policies", json={
            "name": "http-dangerous", "permissions": {"fs_write": ["/workspace/**"]},
        })).json()
        safe = (await client.post("/api/v1/tool-policies", json={
            "name": "http-qa-safe", "permissions": {"fs_read": ["/workspace/src/**"]},
        })).json()
        forbidden = await client.post("/api/v1/agents/definitions", json={
            "name": "http-unauthorized-reviewer", "role": "reviewer",
            "default_tool_policy_id": dangerous["id"],
        })
        assert forbidden.status_code == 422
        assert forbidden.json()["type"] == "urn:agent-management:error:business-rule"
        review = (await client.post("/api/v1/agents/definitions", json={
            "name": "http-reviewer", "role": "reviewer",
            "default_tool_policy_id": safe["id"],
        })).json()
        override = await client.post("/api/v1/agents/instances", json={
            "agent_definition_id": review["id"], "tool_policy_id": dangerous["id"],
        })
        assert override.status_code == 422
        patch = await client.patch(f"/api/v1/tool-policies/{safe['id']}", json={
            "permissions": {"network": ["*"]}, "version": safe["version"],
        })
        assert patch.status_code == 422
        unchanged = await client.get(f"/api/v1/tool-policies/{safe['id']}")
        assert unchanged.json()["version"] == safe["version"]


@pytest.mark.asyncio
async def test_legacy_qa_policy_rejected_before_provider_and_native_export(harness):
    provider = await harness.service.providers.create_provider({
        "name": "legacy-qa-provider", "type": "openrouter",
        "auth_config": {"api_key": "no-paid-call"},
    })
    model = await harness.service.model_profiles.create({
        "provider_id": provider.id, "name": "legacy-qa-model", "model_id": "offline/model",
    })
    unsafe = await harness.service.tool_policies.create({
        "name": "legacy-qa-unsafe", "permissions": {"fs_write": ["/workspace/out/**"]},
    })
    definition = await harness.service.agent_definitions.create({
        "name": "legacy-qa-identity", "role": "developer",
        "system_prompt": "Review safely", "default_model_profile_id": model.id,
        "default_tool_policy_id": unsafe.id,
    })
    instance = await harness.service.agent_instances.create({
        "agent_definition_id": definition.id,
    })
    await harness.service.agent_instances.transition(instance.id, "running")
    # Simulate an old/externally migrated row without rewriting version. The
    # current write API refuses to create such a persisted configuration.
    async with harness.sf() as session:
        row = await session.get(AgentDefinition, definition.id)
        row.role = "reviewer"
        await session.commit()
    with pytest.raises(BusinessRuleError, match="read-only"):
        await harness.service.run_completion(
            provider_id=provider.id, agent_instance_id=instance.id,
            messages=[{"role": "user", "content": "Do not contact provider"}],
        )
    with pytest.raises(NativeProfileExportError, match="read-only"):
        await export_native_profile(harness.sf, definition.id, model.id, unsafe.id)
    _, count = await harness.service.usage.list_for_agent(instance.id)
    assert count == 0


@pytest.mark.asyncio
async def test_concurrent_reviewer_create_and_policy_escalation_are_serialized(harness, monkeypatch):
    import asyncio

    from agent_management.services import AgentDefinitionService

    safe = await harness.service.tool_policies.create({
        "name": "racing-read-only", "permissions": {"fs_read": ["/workspace/**"]},
    })
    checked = asyncio.Event()
    release = asyncio.Event()
    original = AgentDefinitionService._validate_refs

    async def paused_after_validation(session, data, current=None):
        await original(session, data, current)
        if data.get("name") == "racing-reviewer":
            checked.set()
            await asyncio.wait_for(release.wait(), timeout=10)

    monkeypatch.setattr(AgentDefinitionService, "_validate_refs", staticmethod(paused_after_validation))
    created = asyncio.create_task(harness.service.agent_definitions.create({
        "name": "racing-reviewer", "role": "reviewer", "default_tool_policy_id": safe.id,
    }))
    try:
        await asyncio.wait_for(checked.wait(), timeout=10)
        # Before the regression this update read no assignments and committed
        # the unsafe policy while reviewer creation was paused after validation.
        widening = asyncio.create_task(harness.service.tool_policies.update(safe.id, {
            "permissions": {"fs_write": ["/workspace/out/**"]}, "version": safe.version,
        }))
        await asyncio.sleep(0.05)
        assert not widening.done()
    finally:
        release.set()
    reviewer = await asyncio.wait_for(created, timeout=10)
    with pytest.raises(BusinessRuleError, match="Cannot widen"):
        await asyncio.wait_for(widening, timeout=10)
    assert reviewer.role == "reviewer"
    assert (await harness.service.tool_policies.get(safe.id)).version == safe.version


@pytest.mark.asyncio
async def test_concurrent_policy_escalation_then_reviewer_create_fails_closed(harness, monkeypatch):
    import asyncio

    import agent_management.services as services
    from agent_management.models import ToolPolicy

    safe = await harness.service.tool_policies.create({
        "name": "racing-policy-first", "permissions": {"fs_read": ["/workspace/**"]},
    })
    checked = asyncio.Event()
    release = asyncio.Event()
    original = services._apply_patch

    async def pause_before_update(session, record, patch, allowed):
        if isinstance(record, ToolPolicy) and record.id == safe.id:
            checked.set()
            await asyncio.wait_for(release.wait(), timeout=10)
        await original(session, record, patch, allowed)

    monkeypatch.setattr(services, "_apply_patch", pause_before_update)
    widening = asyncio.create_task(harness.service.tool_policies.update(safe.id, {
        "permissions": {"network": ["*"]}, "version": safe.version,
    }))
    try:
        await asyncio.wait_for(checked.wait(), timeout=10)
        creating = asyncio.create_task(harness.service.agent_definitions.create({
            "name": "racing-second-reviewer", "role": "reviewer",
            "default_tool_policy_id": safe.id,
        }))
        await asyncio.sleep(0.05)
        assert not creating.done()
    finally:
        release.set()
    updated = await asyncio.wait_for(widening, timeout=10)
    assert updated.version == safe.version + 1
    with pytest.raises(BusinessRuleError, match="read-only"):
        await asyncio.wait_for(creating, timeout=10)
    _, count, _ = await harness.service.agent_definitions.list()
    assert count == 0
