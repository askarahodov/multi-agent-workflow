"""Fail-closed server recovery: never auto-replay ambiguous native side effects."""
from __future__ import annotations

import pytest
from sqlalchemy import select

from conftest import seed_workflow
from orchestration_server.errors import StateTransitionError
from orchestration_server.models import SagaEvent
from orchestration_server.native_worker import NativeWorker


async def test_restart_quarantines_interrupted_attempt_and_releases_agent(harness):
    _, _, agent, run, tasks = await seed_workflow(
        harness.orch, harness.queries, task_count=2,
    )
    running = await harness.orch.claim_task(tasks[0].id, agent.id)
    assert (await harness.queries.get_task(tasks[0].id)).status == "in_progress"

    first = await harness.orch.recover()
    assert first == {"recovered_attempts": 1, "recovered_tasks": 1}
    task = await harness.queries.get_task(tasks[0].id)
    assert task.status == "blocked"
    assert task.assigned_agent_id is None
    assert task.retry_at is None
    assert (await harness.queries.list_attempts(tasks[0].id))[0].status == "interrupted"
    assert (await harness.queries.get_agent(agent.id)).status == "idle"
    assert (await harness.queries.get_task(tasks[1].id)).status == "pending"

    with pytest.raises(StateTransitionError):
        await harness.orch.claim_task(tasks[0].id, agent.id)

    async with harness.sf() as session:
        events = (await session.scalars(
            select(SagaEvent).where(SagaEvent.run_id == run.id)
        )).all()
    quarantines = [e for e in events if e.event_type == "task.recovery_quarantined"]
    assert len(quarantines) == 1
    assert quarantines[0].payload == {
        "reason": "interrupted_attempt_requires_reconciliation"
    }

    assert await harness.orch.recover() == {
        "recovered_attempts": 0, "recovered_tasks": 0,
    }
    assert (await harness.queries.get_task(tasks[0].id)).status == "blocked"


async def test_restarted_native_worker_never_replays_blocked_task(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    await harness.orch.claim_task(tasks[0].id, agent.id)
    await harness.orch.recover()

    calls = []

    def forbidden(_task):
        calls.append("invoked")
        raise AssertionError("Quarantined side effect may not be replayed")

    worker = NativeWorker(
        harness.orch, harness.queries,
        agent_id=agent.id, runner_factory=forbidden,
    )
    assert await worker.run_once() is None
    assert not calls
    assert (await harness.queries.get_task(tasks[0].id)).attempt_count == 1


async def test_unrelated_pending_work_remains_eligible(harness):
    _, _, agent, _, tasks = await seed_workflow(
        harness.orch, harness.queries, task_count=2,
    )
    await harness.orch.claim_task(tasks[0].id, agent.id)
    await harness.orch.recover()

    received = []

    def factory(task):
        async def runner(task_id, attempt_id):
            received.append(task_id)
            return '{"summary":"safe unrelated task"}'
        return runner

    worker = NativeWorker(
        harness.orch, harness.queries,
        agent_id=agent.id, runner_factory=factory,
    )
    result = await worker.run_once()
    assert result is not None and result.verified
    assert received == [tasks[1].id]
    assert (await harness.queries.get_task(tasks[0].id)).status == "blocked"


async def test_terminal_task_is_preserved_during_recovery(harness):
    _, _, agent, run, tasks = await seed_workflow(
        harness.orch, harness.queries,
    )
    attempt = await harness.orch.claim_task(tasks[0].id, agent.id)
    await harness.orch.submit(
        tasks[0].id, attempt.id, agent.id,
        {"summary": "already verified"},
    )
    assert (await harness.queries.get_run(run.id)).status == "completed"
    assert await harness.orch.recover() == {
        "recovered_attempts": 0, "recovered_tasks": 0,
    }
    assert (await harness.queries.get_task(tasks[0].id)).status == "completed"
