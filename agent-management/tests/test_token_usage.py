"""Token-usage tracking accuracy: running completions via the provider abstraction
records a TokenUsage row per call, and the aggregate summary sums prompt/completion/
total tokens and estimated cost exactly.
"""

from __future__ import annotations

import pytest

from tests.conftest import seed_profile, seed_provider

# Default mock provider token counts used across these tests.
PROMPT = 10
COMPLETION = 5
TOTAL = PROMPT + COMPLETION


async def _seed_running(harness, cost_in: float, cost_out: float, provider_name="tok", model="m"):
    p = await seed_provider(harness, name=provider_name, type="mock")
    mp = await seed_profile(
        harness, p.id, name="default", model_id=model,
        cost_in=cost_in, cost_out=cost_out,
    )
    d = await harness.service.agent_definitions.create(
        {"name": f"def-{provider_name}", "default_model_profile_id": mp.id}
    )
    inst = await harness.service.agent_instances.create(
        {"agent_definition_id": d.id, "model_profile_id": mp.id}
    )
    await harness.service.agent_instances.transition(inst.id, "running")
    return p, mp, inst


class TestTokenUsageRecording:
    async def test_completion_records_usage_row(self, harness):
        p, mp, inst = await _seed_running(harness, 0, 0)
        result = await harness.service.run_completion(
            provider_id=p.id,
            model_profile_id=mp.id,
            agent_instance_id=inst.id,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert result["prompt_tokens"] == PROMPT
        assert result["completion_tokens"] == COMPLETION
        assert result["total_tokens"] == TOTAL
        assert result["usage_record_id"] is not None
        rows, total = await harness.service.usage.list_for_agent(inst.id)
        assert total == 1
        assert rows[0].total_tokens == TOTAL

    async def test_usage_not_recorded_without_instance(self, harness):
        p = await seed_provider(harness, name="noinst", type="mock")
        result = await harness.service.run_completion(
            provider_id=p.id, messages=[{"role": "user", "content": "hi"}]
        )
        assert result["usage_record_id"] is None

    async def test_cost_estimate_uses_profile_rates(self, harness):
        # 1000 prompt tokens cost $1.00 per 1k; 1000 completion tokens $2.00 per 1k.
        # With PROMPT=10, COMPLETION=5 => 0.01 + 0.01 = 0.02
        p, mp, inst = await _seed_running(harness, cost_in=1.0, cost_out=2.0)
        result = await harness.service.run_completion(
            provider_id=p.id,
            model_profile_id=mp.id,
            agent_instance_id=inst.id,
            messages=[{"role": "user", "content": "x"}],
        )
        assert abs(result["est_cost"] - (10 / 1000 * 1.0 + 5 / 1000 * 2.0)) < 1e-9

    async def test_completion_requires_running_instance(self, harness):
        p, mp, _ = await _seed_running(harness, 0, 0)
        d = await harness.service.agent_definitions.create(
            {"name": "pending-inst", "default_model_profile_id": mp.id}
        )
        pending = await harness.service.agent_instances.create(
            {"agent_definition_id": d.id, "model_profile_id": mp.id}
        )
        from agent_management.errors import StateTransitionError

        with pytest.raises(StateTransitionError):
            await harness.service.run_completion(
                provider_id=p.id,
                model_profile_id=mp.id,
                agent_instance_id=pending.id,
                messages=[{"role": "user", "content": "x"}],
            )


class TestTokenUsageSummary:
    async def test_summary_aggregates_multiple_calls(self, harness):
        p, mp, inst = await _seed_running(harness, cost_in=0.5, cost_out=1.0)
        for _ in range(3):
            await harness.service.run_completion(
                provider_id=p.id,
                model_profile_id=mp.id,
                agent_instance_id=inst.id,
                messages=[{"role": "user", "content": "hi"}],
            )
        summary = await harness.service.usage.summary()
        assert summary["request_count"] == 3
        assert summary["total_prompt_tokens"] == 3 * PROMPT
        assert summary["total_completion_tokens"] == 3 * COMPLETION
        assert summary["total_tokens"] == 3 * TOTAL
        assert "unknown" not in summary["by_model"]
        assert summary["total_est_cost"] == pytest.approx(
            3 * (PROMPT / 1000 * 0.5 + COMPLETION / 1000 * 1.0)
        )

    async def test_empty_summary_is_zeroed(self, harness):
        summary = await harness.service.usage.summary()
        assert summary["request_count"] == 0
        assert summary["total_tokens"] == 0
        assert summary["total_est_cost"] == 0.0

    async def test_summary_grouped_by_provider(self, harness):
        p, mp, inst = await _seed_running(harness, 0, 0, provider_name="grp")
        await harness.service.run_completion(
            provider_id=p.id,
            model_profile_id=mp.id,
            agent_instance_id=inst.id,
            messages=[{"role": "user", "content": "hi"}],
        )
        summary = await harness.service.usage.summary()
        assert p.id in summary["by_provider"]
        assert summary["by_provider"][p.id]["total_tokens"] == TOTAL