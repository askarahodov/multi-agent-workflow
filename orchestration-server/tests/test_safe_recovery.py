"""Fail-closed server recovery: never auto-replay ambiguous native side effects."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from conftest import seed_workflow
from orchestration_server.api import build_app
from orchestration_server.config import Settings
from orchestration_server.errors import ConflictError, StateTransitionError
from orchestration_server.models import Agent, SagaEvent
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
    assert (await harness.queries.get_agent(agent.id)).status == "inactive"
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

    # A quarantined worker identity cannot be silently reused. Unrelated
    # work may proceed only on a separately provisioned idle identity.
    fresh_agent = await harness.orch.register_agent("trusted-replacement")
    worker = NativeWorker(
        harness.orch, harness.queries,
        agent_id=fresh_agent.id, runner_factory=factory,
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

@pytest.mark.parametrize("agent_state", ["inactive", "terminated"])
async def test_claim_rejects_nonidle_agent_statuses(harness, agent_state):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    async with harness.sf() as session:
        persisted = await session.get(Agent, agent.id)
        persisted.status = agent_state
        await session.commit()

    with pytest.raises(ConflictError, match="not idle"):
        await harness.orch.claim_task(tasks[0].id, agent.id)
    assert (await harness.queries.get_task(tasks[0].id)).status == "pending"


async def test_crash_recovery_keeps_old_identity_fenced_from_other_tasks(harness):
    _, _, agent, _, tasks = await seed_workflow(
        harness.orch, harness.queries, task_count=2,
    )
    await harness.orch.claim_task(tasks[0].id, agent.id)
    await harness.orch.recover()
    assert (await harness.queries.get_agent(agent.id)).status == "inactive"

    # A queued, unrelated task must not be assigned to a potentially
    # still-running worker, even if its original task is now blocked.
    with pytest.raises(ConflictError, match="not idle"):
        await harness.orch.claim_task(tasks[1].id, agent.id)
    assert (await harness.queries.get_task(tasks[1].id)).status == "pending"


async def test_admin_recover_is_disabled_without_verified_worker_quiescence(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    attempt = await harness.orch.claim_task(tasks[0].id, agent.id)
    app = build_app(Settings(database_url=harness.url, recover_on_startup=False))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post("/api/v1/admin/recover")
            assert response.status_code == 409
            assert "fencing" in response.text

    assert (await harness.queries.get_task(tasks[0].id)).status == "in_progress"
    assert (await harness.queries.list_attempts(tasks[0].id))[0].status == "running"
    assert (await harness.queries.get_agent(agent.id)).status == "busy"
    await harness.orch.submit(
        tasks[0].id, attempt.id, agent.id, {"summary": "completed without interruption"},
    )
    assert (await harness.queries.get_task(tasks[0].id)).status == "completed"


async def test_admin_recover_denies_even_with_idle_db_to_avoid_claim_race(harness):
    app = build_app(Settings(database_url=harness.url, recover_on_startup=False))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            assert (await client.post("/api/v1/admin/recover")).status_code == 409
