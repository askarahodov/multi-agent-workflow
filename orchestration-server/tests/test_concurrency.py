"""Concurrency controls: racing workers must not double-execute a task."""

from __future__ import annotations

import asyncio

import pytest

from conftest import seed_workflow
from orchestration_server.errors import ConflictError, OrchestrationError


async def test_concurrent_claims_have_exactly_one_winner(harness):
    orch = harness.orch
    _, _, agent1, run, tasks = await seed_workflow(orch, harness.queries)
    agent2 = await orch.register_agent("agent-2")
    task = tasks[0]

    results = await asyncio.gather(
        orch.claim_task(task.id, agent1.id),
        orch.claim_task(task.id, agent2.id),
        return_exceptions=True,
    )
    winners = [r for r in results if not isinstance(r, Exception)]
    losers = [r for r in results if isinstance(r, Exception)]

    assert len(winners) == 1, f"expected one winner, got {results!r}"
    assert len(losers) == 1
    assert isinstance(losers[0], OrchestrationError)

    # Exactly one attempt exists and the task is owned by exactly one agent.
    attempts = await harness.queries.list_attempts(task.id)
    assert len(attempts) == 1
    t = await harness.queries.get_task(task.id)
    assert t.status == "in_progress"
    assert t.attempt_count == 1
    assert t.assigned_agent_id in {agent1.id, agent2.id}

    # The winning agent is the one that owns the attempt.
    assert t.assigned_agent_id == attempts[0].agent_id


async def test_agent_exclusivity_blocks_second_task(harness):
    orch = harness.orch
    _, _, agent, run, tasks = await seed_workflow(
        orch, harness.queries, task_count=2
    )
    first, second = tasks[0], tasks[1]

    await orch.claim_task(first.id, agent.id)
    with pytest.raises(ConflictError):
        await orch.claim_task(second.id, agent.id)

    # Once the first task completes, the agent is free again.
    await orch.submit(
        first.id,
        (await harness.queries.list_attempts(first.id))[0].id,
        agent.id,
        {"summary": "ok"},
    )
    attempt2 = await orch.claim_task(second.id, agent.id)
    assert attempt2.attempt_number == 1
