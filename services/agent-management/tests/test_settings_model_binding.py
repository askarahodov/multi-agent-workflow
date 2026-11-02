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
    override = await harness.service.run_completion(
        provider_id=p.id, agent_instance_id=instance.id,
        model_profile_id=default.id,
        messages=[{"role": "user", "content": "hello"}],
    )
    assert override["model"] == "model-a"
