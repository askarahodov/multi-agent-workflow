"""Durable profile budget accounting through actual SQLite + read-only HTTP.

The API reports the same reservations used by the admission/settlement
control plane. No mock provider or paid completions are invoked here.
"""
from __future__ import annotations

import httpx
import pytest

from agent_management.api import build_app
from agent_management.db import build_engine, build_session_factory, create_all
from agent_management.models import AgentBudgetReservation, TokenUsage
from agent_management.services import AgentManagementService


@pytest.mark.asyncio
async def test_budget_status_includes_other_instances_reserved_and_restarts(harness):
    provider = await harness.service.providers.create_provider({
        "name": "budget-status-provider", "type": "mock",
    })
    model = await harness.service.model_profiles.create({
        "provider_id": provider.id, "name": "budget-status-model",
        "model_id": "offline/model",
    })
    definition = await harness.service.agent_definitions.create({
        "name": "budget-status-agent",
        "default_model_profile_id": model.id,
        "budget_limit": 1.0,
    })
    instance = await harness.service.agent_instances.create({
        "agent_definition_id": definition.id, "model_profile_id": model.id,
    })
    other = await harness.service.agent_definitions.create({
        "name": "unlimited-account", "default_model_profile_id": model.id,
    })
    other_instance = await harness.service.agent_instances.create({
        "agent_definition_id": other.id, "model_profile_id": model.id,
    })
    async with harness.sf() as session:
        session.add(TokenUsage(
            agent_instance_id=instance.id, provider_id=provider.id,
            model_profile_id=model.id, model="offline/model",
            prompt_tokens=20, completion_tokens=10, total_tokens=30,
            est_cost=0.4, currency="USD",
        ))
        session.add(AgentBudgetReservation(
            agent_definition_id=definition.id, reserved_microusd=200_000,
        ))
        session.add(TokenUsage(
            agent_instance_id=other_instance.id, provider_id=provider.id,
            model_profile_id=model.id, model="offline/model",
            prompt_tokens=10, completion_tokens=10, total_tokens=20,
            est_cost=19.0, currency="USD",
        ))
        await session.commit()

    app = build_app(lambda: harness.service)
    url = f"/api/v1/agents/definitions/{definition.id}/budget"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver",
    ) as client:
        resp = await client.get(url)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "agent_definition_id": definition.id, "definition_version": definition.version,
            "currency": "USD", "limit_microusd": 1_000_000,
            "spent_estimated_microusd": 400_000,
            "reserved_microusd": 200_000,
            "remaining_estimated_microusd": 400_000,
            "unsettled_reservations": 1,
            "completion_budget_status": "available",
            "native_budget_enforced": False,
        }
        assert (await client.get(
            f"/api/v1/agents/definitions/{other.id}/budget"
        )).json()["completion_budget_status"] == "not_configured"
        assert (await client.get(
            "/api/v1/agents/definitions/no-such-profile/budget"
        )).status_code == 404

    # Independent physical engine, new service and app: reservations are NOT
    # released by restart and data from another profile is not mixed in.
    engine = build_engine(harness.url)
    try:
        await create_all(engine)
        restarted = AgentManagementService(build_session_factory(engine))
        rebuilt = build_app(lambda: restarted)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rebuilt), base_url="http://testserver",
        ) as client:
            durable = (await client.get(url)).json()
            assert durable["reserved_microusd"] == 200_000
            assert durable["unsettled_reservations"] == 1
            assert durable["remaining_estimated_microusd"] == 400_000

        # A reduction below spent + reservation fails closed in the report.
        await restarted.agent_definitions.update(definition.id, {"budget_limit": 0.5})
        exhausted = await restarted.budget_status(definition.id)
        assert exhausted["completion_budget_status"] == "exhausted"
        assert exhausted["remaining_estimated_microusd"] == 0
        assert exhausted["reserved_microusd"] == 200_000
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_zero_budget_is_exhausted_and_missing_budget_is_not_approved(harness):
    zero = await harness.service.agent_definitions.create({
        "name": "zero-budget", "budget_limit": 0,
    })
    unknown = await harness.service.agent_definitions.create({
        "name": "no-budget",
    })
    assert (await harness.service.budget_status(zero.id))["completion_budget_status"] == "exhausted"
    missing = await harness.service.budget_status(unknown.id)
    assert missing["completion_budget_status"] == "not_configured"
    assert missing["remaining_estimated_microusd"] is None
    assert missing["native_budget_enforced"] is False
