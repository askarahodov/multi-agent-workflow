"""Real disposable PostgreSQL budget/read-only API and micro-USD admission."""
from __future__ import annotations

import os

import httpx
import pytest

from agent_management.api import build_app
from agent_management.db import build_engine, build_session_factory, create_all
from agent_management.models import AgentBudgetReservation, AgentExecutionBinding, TokenUsage
from agent_management.services import AgentManagementService


@pytest.mark.asyncio
async def test_numeric_postgres_aggregates_and_exact_fit_budget_admission():
    url = os.environ.get("MAW_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Disposable PostgreSQL CI is required")
    engine = build_engine(url)
    try:
        await create_all(engine)
        sf = build_session_factory(engine)
        svc = AgentManagementService(sf)
        provider = await svc.providers.create_provider({
            "name": "pg-budget-provider", "type": "mock",
        })
        model = await svc.model_profiles.create({
            "provider_id": provider.id, "name": "pg-budget-model",
            "model_id": "offline/pg", "cost_per_1k_output": 0.1,
            "parameters": {"max_tokens": 1000},
        })
        definition = await svc.agent_definitions.create({
            "name": "pg-budget-exact-fit", "budget_limit": 0.4,
            "default_model_profile_id": model.id,
        })
        instance = await svc.agent_instances.create({
            "agent_definition_id": definition.id, "model_profile_id": model.id,
        })
        async with sf() as session:
            binding = await session.get(AgentExecutionBinding, instance.id)
            assert binding is not None
            for cost in (0.1, 0.2):
                session.add(TokenUsage(
                    agent_instance_id=instance.id, provider_id=provider.id,
                    model_profile_id=model.id, model="offline/pg",
                    prompt_tokens=0, completion_tokens=1000, total_tokens=1000,
                    est_cost=cost, currency="USD",
                ))
            await session.commit()
        # PG SUM(bigint) returns NUMERIC/Decimal, including COALESCE(0).
        app = build_app(lambda: svc)
        path = f"/api/v1/agents/definitions/{definition.id}/budget"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(path)
            assert response.status_code == 200, response.text
            assert response.json()["spent_estimated_microusd"] == 300_000
            assert response.json()["reserved_microusd"] == 0
        reservation = await svc._reserve_estimated_budget(
            instance=instance, binding=binding, profile=model, provider=provider,
            max_tokens=1000, messages=[{"role": "user", "content": "test"}],
        )
        assert reservation
        updated = await svc.budget_status(definition.id)
        assert updated["reserved_microusd"] == 100_000
        assert updated["remaining_estimated_microusd"] == 0
        assert updated["completion_budget_status"] == "exhausted"
        # A second profile cannot leak the first profile's spend/reservations.
        other = await svc.agent_definitions.create({"name": "pg-budget-empty"})
        assert (await svc.budget_status(other.id))["spent_estimated_microusd"] == 0
    finally:
        await engine.dispose()
