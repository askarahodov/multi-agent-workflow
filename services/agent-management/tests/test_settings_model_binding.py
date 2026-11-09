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
