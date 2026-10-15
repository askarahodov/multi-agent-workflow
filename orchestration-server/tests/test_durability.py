"""Durability: state must survive a simulated server restart.

The harness opens a brand-new engine + session factory over the same SQLite file
to model the server process restarting: confirmed results must still be there and
incomplete work must be recovered rather than lost.
"""

from __future__ import annotations

import pytest

from conftest import seed_workflow
from orchestration_server.errors import StateTransitionError

OUTPUT = {"summary": "ok", "confidence": 0.5}


async def test_confirmed_results_survive_restart(harness_factory):
    h1 = await harness_factory()
    _, _, agent, run, tasks = await seed_workflow(h1.orch, h1.queries)
    task = tasks[0]
    attempt = await h1.orch.claim_task(task.id, agent.id)
    await h1.orch.submit(task.id, attempt.id, agent.id, OUTPUT)
    assert (await h1.queries.get_task(task.id)).status == "completed"
    await h1.stop()  # process goes away

    h2 = await harness_factory()  # process comes back
    recovered = await h2.orch.recover()
    assert recovered == {"recovered_attempts": 0, "recovered_tasks": 0}

    t = await h2.queries.get_task(task.id)
    assert t.status == "completed"
    assert t.output_data == OUTPUT
    assert (await h2.queries.get_run(run.id)).status == "completed"
    attempts = await h2.queries.list_attempts(task.id)
    assert attempts[-1].status == "completed"


async def test_incomplete_attempt_is_recovered_not_lost(harness_factory):
    h1 = await harness_factory()
    _, _, agent, run, tasks = await seed_workflow(
        h1.orch, h1.queries, max_attempts=2
    )
    task = tasks[0]
    # A worker claims the task and then the server dies before submitting.
    await h1.orch.claim_task(task.id, agent.id)
    await h1.stop()

    h2 = await harness_factory()
    recovered = await h2.orch.recover()
    assert recovered == {"recovered_attempts": 1, "recovered_tasks": 1}

    t = await h2.queries.get_task(task.id)
    assert t.status == "blocked"  # side effects may be ambiguous after crash
    assert t.assigned_agent_id is None
    attempts = await h2.queries.list_attempts(task.id)
    assert attempts[0].status == "interrupted"

    # A remote executor may survive the orchestration-server restart.
    # Preserve its non-claimable identity until independently reconciled.
    assert (await h2.queries.get_agent(agent.id)).status == "inactive"
    with pytest.raises(StateTransitionError):
        await h2.orch.claim_task(task.id, agent.id)
    assert (await h2.queries.get_run(run.id)).status == "running"


async def test_restart_keeps_completed_and_quarantines_incomplete_in_same_run(
    harness_factory,
):
    h1 = await harness_factory()
    _, _, agent, run, tasks = await seed_workflow(
        h1.orch, h1.queries, task_count=2
    )
    first, second = tasks[0], tasks[1]
    a1 = await h1.orch.claim_task(first.id, agent.id)
    await h1.orch.submit(first.id, a1.id, agent.id, OUTPUT)
    await h1.orch.claim_task(second.id, agent.id)  # left in progress
    await h1.stop()

    h2 = await harness_factory()
    recovered = await h2.orch.recover()
    assert recovered == {"recovered_attempts": 1, "recovered_tasks": 1}

    assert (await h2.queries.get_task(first.id)).status == "completed"
    assert (await h2.queries.get_task(second.id)).status == "blocked"
    # The run must NOT be falsely completed while one task is quarantined.
    assert (await h2.queries.get_run(run.id)).status == "running"
    with pytest.raises(StateTransitionError):
        await h2.orch.claim_task(second.id, agent.id)


async def test_recover_is_idempotent(harness_factory):
    h1 = await harness_factory()
    _, _, agent, _, tasks = await seed_workflow(h1.orch, h1.queries)
    await h1.orch.claim_task(tasks[0].id, agent.id)
    await h1.stop()

    h2 = await harness_factory()
    assert (await h2.orch.recover()) == {
        "recovered_attempts": 1,
        "recovered_tasks": 1,
    }
    # A second pass has nothing left to do and must not double-count.
    assert (await h2.orch.recover()) == {
        "recovered_attempts": 0,
        "recovered_tasks": 0,
    }


async def test_recovered_attempt_is_terminal(harness_factory):
    h1 = await harness_factory()
    _, _, agent, _, tasks = await seed_workflow(h1.orch, h1.queries)
    task = tasks[0]
    attempt = await h1.orch.claim_task(task.id, agent.id)
    await h1.stop()

    h2 = await harness_factory()
    await h2.orch.recover()
    # Submitting against the interrupted attempt is rejected.
    with pytest.raises(StateTransitionError):
        await h2.orch.submit(task.id, attempt.id, agent.id, OUTPUT)
