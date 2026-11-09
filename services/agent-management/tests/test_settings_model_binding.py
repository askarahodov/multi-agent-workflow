"""Verify runtime model resolution honours control-plane agent assignment."""
import pytest


@pytest.mark.asyncio
async def test_agent_instance_uses_assigned_model_not_provider_default(harness):
    p = await harness.service.providers.create_provider({
        "name": "runtime-model-binding", "type": "mock",
        "auth_config": {"reply": "offline-ok"},
    })
    default = await harness.service.model_profiles.create({
        "provider_id": p.id, "name": "provider-default",
        "model_id": "model-a", "is_default": True,
    })
    assigned = await harness.service.model_profiles.create({
        "provider_id": p.id, "name": "agent-assigned",
        "model_id": "model-b", "is_default": False,
    })
    definition = await harness.service.agent_definitions.create({
        "name": "model-bound-agent", "default_model_profile_id": assigned.id,
    })
    instance = await harness.service.agent_instances.create({
        "agent_definition_id": definition.id,
    })
    assert instance.model_profile_id == assigned.id
    await harness.service.agent_instances.transition(instance.id, "running")
    result = await harness.service.run_completion(
        provider_id=p.id, agent_instance_id=instance.id,
        messages=[{"role": "user", "content": "hello"}],
    )
    assert result["model"] == "model-b"
    assert result["content"] == "offline-ok"
    explicit = await harness.service.run_completion(
        provider_id=p.id, agent_instance_id=instance.id,
        model_profile_id=assigned.id,
        messages=[{"role": "user", "content": "hello"}],
    )
    assert explicit["model"] == "model-b"

    from agent_management.errors import ValidationError

    with pytest.raises(ValidationError, match="conflicts"):
        await harness.service.run_completion(
            provider_id=p.id, agent_instance_id=instance.id,
            model_profile_id=default.id,
            messages=[{"role": "user", "content": "hello"}],
        )
    _, total = await harness.service.usage.list_for_agent(instance.id)
    assert total == 2  # Rejected override did not call the provider or record usage.



@pytest.mark.asyncio
async def test_running_instance_refuses_mutated_model_provider_definition_and_policy(harness):
    from agent_management.errors import BusinessRuleError

    provider = await harness.service.providers.create_provider({
        "name": "revision-provider", "type": "mock", "auth_config": {"reply": "ok"},
    })
    model = await harness.service.model_profiles.create({
        "provider_id": provider.id, "name": "revision-model", "model_id": "before",
    })
    policy = await harness.service.tool_policies.create({
        "name": "revision-policy", "permissions": {"fs_read": ["/workspace/src/**"]},
    })
    definition = await harness.service.agent_definitions.create({
        "name": "revision-agent", "default_model_profile_id": model.id,
        "default_tool_policy_id": policy.id,
    })

    async def running_instance():
        instance = await harness.service.agent_instances.create({
            "agent_definition_id": definition.id,
        })
        await harness.service.agent_instances.transition(instance.id, "running")
        return instance

    async def must_deny(instance):
        with pytest.raises(BusinessRuleError, match="changed"):
            await harness.service.run_completion(
                provider_id=provider.id, agent_instance_id=instance.id,
                messages=[{"role": "user", "content": "hello"}],
            )
        _, count = await harness.service.usage.list_for_agent(instance.id)
        assert count == 0

    i_model = await running_instance()
    await harness.service.model_profiles.update(model.id, {
        "model_id": "after", "version": model.version,
    })
    await must_deny(i_model)

    i_policy = await running_instance()
    await harness.service.tool_policies.update(policy.id, {
        "permissions": {"fs_read": []}, "version": policy.version,
    })
    await must_deny(i_policy)

    i_definition = await running_instance()
    await harness.service.agent_definitions.update(definition.id, {
        "system_prompt": "Changed instructions", "version": definition.version,
    })
    await must_deny(i_definition)

    i_provider = await running_instance()
    await harness.service.providers.update_provider(provider.id, {
        "rate_limits": {"rpm": 10}, "version": provider.version,
    })
    await must_deny(i_provider)

    fresh = await running_instance()
    result = await harness.service.run_completion(
        provider_id=provider.id, agent_instance_id=fresh.id,
        messages=[{"role": "user", "content": "hello"}],
    )
    assert result["model"] == "after"


@pytest.mark.asyncio
async def test_reject_caller_supplied_revision_binding_and_inactive_provider(harness):
    from agent_management.errors import BusinessRuleError, ValidationError

    provider = await harness.service.providers.create_provider({
        "name": "inactive-revision-provider", "type": "mock",
    })
    model = await harness.service.model_profiles.create({
        "provider_id": provider.id, "name": "revision-model", "model_id": "mock-v1",
    })
    definition = await harness.service.agent_definitions.create({
        "name": "snapshot-agent", "default_model_profile_id": model.id,
    })
    with pytest.raises(ValidationError, match="Reserved"):
        await harness.service.agent_instances.create({
            "agent_definition_id": definition.id,
            "runtime_config": {"_execution_binding_v1": {"model_version": 9999}},
        })
    await harness.service.providers.update_provider(provider.id, {
        "is_active": False, "version": provider.version,
    })
    with pytest.raises(BusinessRuleError, match="unavailable"):
        await harness.service.agent_instances.create({
            "agent_definition_id": definition.id,
        })



@pytest.mark.asyncio
async def test_legacy_runtime_json_cannot_forge_server_owned_execution_binding(harness):
    from agent_management.errors import BusinessRuleError
    from agent_management.models import AgentInstance

    provider = await harness.service.providers.create_provider({
        "name": "legacy-provider", "type": "mock",
    })
    model = await harness.service.model_profiles.create({
        "provider_id": provider.id, "name": "legacy-model", "model_id": "old",
    })
    definition = await harness.service.agent_definitions.create({
        "name": "legacy-definition", "default_model_profile_id": model.id,
    })
    # Reproduce a pre-migration row: runtime_config was historically arbitrary
    # caller JSON, including the exact new key and forged valid-looking versions.
    async with harness.sf() as session:
        old = AgentInstance(
            agent_definition_id=definition.id, model_profile_id=model.id,
            status="running",
            runtime_config={"_execution_binding_v1": {
                "definition_version": definition.version,
                "model_version": model.version,
                "provider_id": provider.id, "provider_version": provider.version,
            }},
        )
        session.add(old)
        await session.commit()
        old_id = old.id
    with pytest.raises(BusinessRuleError, match="no trusted revision binding"):
        await harness.service.run_completion(
            provider_id=provider.id, agent_instance_id=old_id,
            messages=[{"role": "user", "content": "hello"}],
        )
    _, count = await harness.service.usage.list_for_agent(old_id)
    assert count == 0


@pytest.mark.asyncio
async def test_execution_binding_persists_on_file_sqlite_restart(harness):
    from tests.conftest import Harness

    provider = await harness.service.providers.create_provider({
        "name": "restart-provider", "type": "mock",
    })
    model = await harness.service.model_profiles.create({
        "provider_id": provider.id, "name": "restart-model", "model_id": "stable",
    })
    definition = await harness.service.agent_definitions.create({
        "name": "restart-definition", "default_model_profile_id": model.id,
    })
    instance = await harness.service.agent_instances.create({
        "agent_definition_id": definition.id,
    })
    assert "_execution_binding_v1" not in instance.runtime_config
    await harness.service.agent_instances.transition(instance.id, "running")
    await harness.stop()
    reloaded = await Harness(harness.url).start()
    try:
        again = await reloaded.service.agent_instances.get(instance.id)
        assert again.status == "running"
        result = await reloaded.service.run_completion(
            provider_id=provider.id, agent_instance_id=instance.id,
            messages=[{"role": "user", "content": "hello"}],
        )
        assert result["model"] == "stable"
    finally:
        await reloaded.stop()
