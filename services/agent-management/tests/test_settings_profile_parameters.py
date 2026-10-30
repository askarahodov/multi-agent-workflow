"""Exercise temperature/max_tokens resolution from persisted model profiles."""
import pytest
from agent_management.providers import MockProvider


@pytest.mark.asyncio
async def test_model_profile_parameters_applied_and_request_override(harness, monkeypatch):
    provider = await harness.service.providers.create_provider({
        "name": "profile-parameter-test", "type": "mock",
        "auth_config": {"reply": "done"},
    })
    profile = await harness.service.model_profiles.create({
        "provider_id": provider.id, "name": "configured",
        "model_id": "mock-v1", "is_default": True,
        "parameters": {"temperature": 0.3, "max_tokens": 240},
    })
    seen = []
    original = MockProvider.complete

    async def checked(self, messages, *, model=None, **kwargs):
        seen.append((model, kwargs.get("temperature"), kwargs.get("max_tokens")))
        return await original(self, messages, model=model, **kwargs)

    monkeypatch.setattr(MockProvider, "complete", checked)
    first = await harness.service.run_completion(
        provider_id=provider.id, model_profile_id=profile.id,
        messages=[{"role": "user", "content": "ping"}],
    )
    assert first["model"] == "mock-v1"
    second = await harness.service.run_completion(
        provider_id=provider.id, model_profile_id=profile.id,
        temperature=0.6, max_tokens=16,
        messages=[{"role": "user", "content": "ping"}],
    )
    assert second["model"] == "mock-v1"
    assert seen == [("mock-v1", 0.3, 240), ("mock-v1", 0.6, 16)]
