"""Task lifecycle and platform-owned orchestration rules (engine level)."""

from __future__ import annotations

import pytest

from conftest import seed_workflow
from orchestration_server.errors import (
    BusinessRuleError,
    ConflictError,
    DuplicateKeyError,
    NotFoundError,
    StateTransitionError,
)

VALID_OUTPUT = {"summary": "done", "confidence": 0.9}


async def test_project_and_workspace_crud_and_duplicates(harness):
    orch = harness.orch
    project = await orch.create_project("alpha", description="first")
    assert project.id and project.version == 1

    ws = await orch.create_workspace(project.id, "ws-1", path="/tmp/ws-1")
    assert ws.project_id == project.id

    with pytest.raises(DuplicateKeyError):
        await orch.create_project("alpha")

    with pytest.raises(DuplicateKeyError):
        await orch.create_workspace(project.id, "ws-1")

    with pytest.raises(NotFoundError):
        await orch.create_workspace("does-not-exist", "ws")

    projects = await harness.queries.list_projects()
    assert [p.name for p in projects] == ["alpha"]


async def test_create_contract_rejects_invalid_schema(harness):
    orch = harness.orch
    with pytest.raises(BusinessRuleError):
        await orch.create_contract("bad", {"type": "not-a-type"})
    contract = await orch.create_contract("good", {"type": "object"})
    assert contract.schema == {"type": "object"}


async def test_launch_run_creates_tasks_and_validates_refs(harness):
    orch = harness.orch
    queries = harness.queries
    project = await orch.create_project("p")

    with pytest.raises(BusinessRuleError):
        await orch.launch_run(project.id, "empty", [])

    with pytest.raises(NotFoundError):
        await orch.launch_run(project.id, "bad", [{"title": "t", "contract_id": "nope"}])

    with pytest.raises(NotFoundError):
        await orch.launch_run("missing-project", "run", [{"title": "t"}])

    run = await orch.launch_run(
        project.id, "run", [{"title": "t1"}, {"title": "t2", "priority": 5}]
    )
    assert run.status == "running"
    tasks = await queries.list_tasks(run.id)
    assert len(tasks) == 2
    # Ordered by priority desc.
    assert tasks[0].title == "t2"


async def test_claim_and_valid_submit_completes_task_and_run(harness):
    orch = harness.orch
    _, contract, agent, run, tasks = await seed_workflow(orch, harness.queries)
    task = tasks[0]

    attempt = await orch.claim_task(task.id, agent.id)
    assert attempt.status == "running"
    assert attempt.attempt_number == 1

    result = await orch.submit(task.id, attempt.id, agent.id, VALID_OUTPUT)
    assert result.status == "completed"
    assert result.verification_result == {"valid": True, "errors": []}

    refreshed_task = await harness.queries.get_task(task.id)
    assert refreshed_task.status == "completed"
    assert refreshed_task.output_data == VALID_OUTPUT

    refreshed_run = await harness.queries.get_run(run.id)
    assert refreshed_run.status == "completed"
    assert refreshed_run.output_data == {"tasks_completed": 1}

    refreshed_agent = await harness.queries.get_agent(agent.id)
    assert refreshed_agent.status == "idle"


async def test_invalid_submission_retries_then_fails_run(harness):
    orch = harness.orch
    _, _, agent, run, tasks = await seed_workflow(
        orch, harness.queries, max_attempts=2
    )
    task = tasks[0]

    # First attempt: output violates the contract -> verification_failed + retry.
    attempt = await orch.claim_task(task.id, agent.id)
    result = await orch.submit(task.id, attempt.id, agent.id, {"summary": ""})
    assert result.status == "verification_failed"
    assert result.verification_result["valid"] is False
    t = await harness.queries.get_task(task.id)
    assert t.status == "pending"  # re-queued by the platform retry policy
    assert (await harness.queries.get_run(run.id)).status == "running"

    # Advance the (zero-delay) retry window and claim again.
    assert await orch.tick() == 1
    attempt2 = await orch.claim_task(task.id, agent.id)
    assert attempt2.attempt_number == 2

    # Attempts exhausted -> task and run fail; the agent never declared success.
    result2 = await orch.submit(task.id, attempt2.id, agent.id, {"summary": ""})
    assert result2.status == "verification_failed"
    assert (await harness.queries.get_task(task.id)).status == "failed"
    assert (await harness.queries.get_run(run.id)).status == "failed"


async def test_agent_cannot_self_complete_without_contract_verification(harness):
    """An agent cannot make a task `completed`; only the engine can."""
    orch = harness.orch
    _, _, agent, _, tasks = await seed_workflow(orch, harness.queries, max_attempts=3)
    task = tasks[0]
    attempt = await orch.claim_task(task.id, agent.id)

    # Bad output never yields a completed task.
    await orch.submit(task.id, attempt.id, agent.id, {"totally": "wrong"})
    assert (await harness.queries.get_task(task.id)).status == "pending"

    # There is no API on the engine to force completion.
    assert not hasattr(orch, "complete_task")
    assert not hasattr(orch, "mark_completed")


async def test_only_owner_agent_may_submit_or_fail(harness):
    orch = harness.orch
    _, _, agent, _, tasks = await seed_workflow(orch, harness.queries)
    task = tasks[0]
    other = await orch.register_agent("agent-2")
    attempt = await orch.claim_task(task.id, agent.id)

    with pytest.raises(ConflictError):
        await orch.submit(task.id, attempt.id, other.id, VALID_OUTPUT)
    with pytest.raises(ConflictError):
        await orch.fail_attempt(task.id, attempt.id, other.id, "nope")


async def test_claim_is_rejected_for_terminal_and_busy_contexts(harness):
    orch = harness.orch
    _, _, agent, _, tasks = await seed_workflow(orch, harness.queries)
    task = tasks[0]

    # Unknown ids are 404s.
    with pytest.raises(NotFoundError):
        await orch.claim_task(task.id, "missing-agent")
    with pytest.raises(NotFoundError):
        await orch.claim_task("missing-task", agent.id)

    attempt = await orch.claim_task(task.id, agent.id)

    # Same task cannot be claimed twice, and a busy agent cannot take another task.
    with pytest.raises(ConflictError):
        await orch.claim_task(task.id, agent.id)

    run2 = await orch.launch_run(
        (await harness.queries.list_projects())[0].id, "run2", [{"title": "other"}]
    )
    other_task = (await harness.queries.list_tasks(run2.id))[0]
    with pytest.raises(ConflictError):
        await orch.claim_task(other_task.id, agent.id)

    # Terminal tasks cannot be claimed.
    await orch.submit(task.id, attempt.id, agent.id, VALID_OUTPUT)
    with pytest.raises(StateTransitionError):
        await orch.claim_task(task.id, agent.id)


async def test_fail_attempt_then_retry_reclaims(harness):
    orch = harness.orch
    _, _, agent, run, tasks = await seed_workflow(
        orch, harness.queries, max_attempts=2
    )
    task = tasks[0]
    attempt = await orch.claim_task(task.id, agent.id)

    failed = await orch.fail_attempt(task.id, attempt.id, agent.id, "boom")
    assert failed.status == "failed"
    t = await harness.queries.get_task(task.id)
    assert t.status == "pending"
    assert (await harness.queries.get_run(run.id)).status == "running"

    assert await orch.tick() == 1
    attempt2 = await orch.claim_task(task.id, agent.id)
    assert attempt2.attempt_number == 2
    await orch.submit(task.id, attempt2.id, agent.id, VALID_OUTPUT)
    assert (await harness.queries.get_run(run.id)).status == "completed"


async def test_block_task_is_terminal_for_agent_flow(harness):
    orch = harness.orch
    _, _, agent, run, tasks = await seed_workflow(orch, harness.queries)
    task = tasks[0]
    blocked = await orch.block_task(task.id, agent.id, "needs input")
    assert blocked.status == "blocked"
    with pytest.raises(StateTransitionError):
        await orch.claim_task(task.id, agent.id)
    # A blocked task leaves the run open (not failed/completed).
    assert (await harness.queries.get_run(run.id)).status == "running"


async def test_multi_task_run_completes_only_when_all_tasks_done(harness):
    orch = harness.orch
    queries = harness.queries
    _, _, agent, run, tasks = await seed_workflow(orch, queries, task_count=2)

    a1 = await orch.claim_task(tasks[0].id, agent.id)
    await orch.submit(tasks[0].id, a1.id, agent.id, VALID_OUTPUT)
    assert (await queries.get_run(run.id)).status == "running"

    a2 = await orch.claim_task(tasks[1].id, agent.id)
    await orch.submit(tasks[1].id, a2.id, agent.id, VALID_OUTPUT)
    assert (await queries.get_run(run.id)).status == "completed"
    assert (await queries.get_run(run.id)).output_data == {"tasks_completed": 2}


async def test_saga_journal_records_every_transition(harness):
    from sqlalchemy import select

    from orchestration_server.models import SagaEvent

    orch = harness.orch
    _, _, agent, run, tasks = await seed_workflow(orch, harness.queries)
    task = tasks[0]
    attempt = await orch.claim_task(task.id, agent.id)
    await orch.submit(task.id, attempt.id, agent.id, VALID_OUTPUT)

    async with harness.sf() as session:
        events = list(
            (
                await session.scalars(
                    select(SagaEvent).where(SagaEvent.run_id == run.id)
                )
            ).all()
        )
    kinds = [e.event_type for e in events]
    for expected in (
        "run.launched",
        "task.created",
        "task.claimed",
        "attempt.started",
        "attempt.completed",
        "task.completed",
        "run.completed",
    ):
        assert expected in kinds
