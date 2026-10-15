"""Bounded native worker orchestration with a real SQLite engine."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from conftest import seed_workflow
from orchestration_server.models import Task
from orchestration_server.native_worker import NativeWorker


def worker(harness, agent_id, factory):
    return NativeWorker(
        harness.orch, harness.queries, agent_id=agent_id,
        runner_factory=factory,
    )


async def test_native_worker_discovers_and_completes_without_manual_task_id(harness):
    _, _, agent, run, tasks = await seed_workflow(
        harness.orch, harness.queries, task_count=2,
    )
    called = []

    def factory(task):
        async def runner(task_id, attempt_id):
            assert task_id == task.id
            called.append((task_id, attempt_id))
            return '{"summary":"native verified"}'
        return runner

    batch = await worker(harness, agent.id, factory).run_batch(max_attempts=2)
    assert not batch.stopped_on_failure
    assert len(batch.attempts) == 2 and all(x.verified for x in batch.attempts)
    assert {task_id for task_id, _ in called} == {task.id for task in tasks}
    assert (await harness.queries.get_run(run.id)).status == "completed"
    statuses = [(await harness.queries.get_task(t.id)).status for t in tasks]
    assert statuses == ["completed", "completed"]


async def test_empty_queue_does_not_create_runner_or_call_provider(harness):
    agent = await harness.orch.register_agent("no-task-agent")
    called = 0

    def factory(_task):
        nonlocal called
        called += 1
        raise AssertionError("No model/provider work when idle")

    w = worker(harness, agent.id, factory)
    assert await w.run_once() is None
    batch = await w.run_batch(max_attempts=3)
    assert batch.attempts == () and not batch.stopped_on_failure
    assert called == 0


async def test_invalid_contract_stops_batch_without_fast_retry(harness):
    _, _, agent, run, tasks = await seed_workflow(
        harness.orch, harness.queries,
        max_attempts=2, task_count=2, retry_base=0.0,
    )
    calls = []

    def factory(task):
        async def runner(task_id, attempt_id):
            calls.append(task_id)
            return '{"summary":""}'  # deliberately invalid contract
        return runner

    batch = await worker(harness, agent.id, factory).run_batch(max_attempts=10)
    assert batch.stopped_on_failure
    assert len(batch.attempts) == 1 and not batch.attempts[0].verified
    assert len(calls) == 1
    assert (await harness.queries.get_run(run.id)).status == "running"
    assert (await harness.queries.get_task(calls[0])).status == "pending"


async def test_worker_does_not_claim_task_until_retry_window(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    task = tasks[0]
    future = datetime.now(timezone.utc) + timedelta(hours=5)
    async with harness.sf() as session:
        row = await session.get(Task, task.id)
        row.retry_at = future
        await session.commit()

    def forbidden(_task):
        raise AssertionError("Future retry window should prevent factory call")

    assert await worker(harness, agent.id, forbidden).run_once() is None
    assert (await harness.queries.get_task(task.id)).status == "pending"


async def test_busy_agent_does_not_start_second_task(harness):
    _, _, agent, _, tasks = await seed_workflow(
        harness.orch, harness.queries, task_count=2,
    )
    await harness.orch.claim_task(tasks[0].id, agent.id)
    def forbidden(_task):
        raise AssertionError("Busy agent must not spawn more work")
    assert await worker(harness, agent.id, forbidden).run_once() is None


async def test_concurrent_workers_cannot_complete_one_task_twice(harness):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)
    other = await harness.orch.register_agent("another-agent")
    calls = 0

    def factory(_task):
        async def runner(task_id, attempt_id):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.03)
            return '{"summary":"once"}'
        return runner

    # Separate orchestration objects simulate independent worker processes.
    w1 = worker(harness, agent.id, factory)
    w2 = worker(harness, other.id, factory)
    outcome1, outcome2 = await asyncio.gather(
        w1.run_once(), w2.run_once()
    )
    winners = [x for x in (outcome1, outcome2) if x is not None]
    assert len(winners) == 1 and winners[0].verified
    assert calls == 1
    assert (await harness.queries.get_run(run.id)).status == "completed"
    assert (await harness.queries.get_task(tasks[0].id)).attempt_count == 1


async def test_invalid_bounds_fail_without_changing_task(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    for value in (0, 101):
        with pytest.raises(ValueError):
            await worker(harness, agent.id, lambda t: lambda a,b: None).run_batch(
                max_attempts=value
            )
    with pytest.raises(ValueError):
        NativeWorker(
            harness.orch, harness.queries, agent_id=agent.id,
            runner_factory=lambda task: None, max_runs_scan=0,
        )
    assert (await harness.queries.get_task(tasks[0].id)).status == "pending"


@pytest.mark.parametrize("bad_bound", [True, False, 1.5, "2", None, -1, 1001])
async def test_worker_scan_bounds_reject_non_integer_or_out_of_range(harness, bad_bound):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    for dimension in ("max_runs_scan", "max_tasks_per_run"):
        with pytest.raises(ValueError, match="Scan bounds"):
            NativeWorker(
                harness.orch, harness.queries,
                agent_id=agent.id, runner_factory=lambda task: None,
                **{dimension: bad_bound},
            )
    assert (await harness.queries.get_task(tasks[0].id)).status == "pending"


@pytest.mark.parametrize("bad_bound", [True, False, 1.5, "2", None, -1, 101])
async def test_batch_bounds_reject_non_integer_or_out_of_range(harness, bad_bound):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    with pytest.raises(ValueError, match="Batch size"):
        await worker(harness, agent.id, lambda task: None).run_batch(
            max_attempts=bad_bound,
        )
    assert (await harness.queries.get_task(tasks[0].id)).status == "pending"


async def test_factory_invalid_result_is_detected_before_claim(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    w = worker(harness, agent.id, lambda task: None)
    with pytest.raises(TypeError, match="runner factory"):
        await w.run_once()
    assert (await harness.queries.get_task(tasks[0].id)).status == "pending"


@pytest.mark.parametrize("bad", [True, False, 0, 101, 1.5, "3", None, -1])
async def test_polling_rejects_invalid_poll_count_without_claim(harness, bad):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    with pytest.raises(ValueError, match="Poll count"):
        await worker(harness, agent.id, lambda t: None).poll_bounded(max_polls=bad)
    assert (await harness.queries.get_task(tasks[0].id)).status == "pending"


@pytest.mark.parametrize("bad", [True, False, -1, 61, float("inf"), float("nan"), "0", None])
async def test_polling_rejects_invalid_interval_without_claim(harness, bad):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    with pytest.raises(ValueError, match="Poll interval"):
        await worker(harness, agent.id, lambda t: None).poll_bounded(interval_seconds=bad)
    assert (await harness.queries.get_task(tasks[0].id)).status == "pending"


async def test_polling_pre_set_stop_does_not_access_provider(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    stopped = asyncio.Event()
    stopped.set()
    result = await worker(harness, agent.id, lambda t: (_ for _ in ()).throw(
        AssertionError("No factory call after stop")
    )).poll_bounded(max_polls=3, stop_event=stopped)
    assert result.attempts == () and not result.stopped_on_failure
    assert (await harness.queries.get_task(tasks[0].id)).status == "pending"


async def test_polling_processes_two_tasks_in_one_bounded_pass(harness):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries, task_count=2)
    seen = []
    def factory(_task):
        async def runner(task_id, attempt_id):
            seen.append((task_id, attempt_id))
            return '{"summary":"poll complete"}'
        return runner
    result = await worker(harness, agent.id, factory).poll_bounded(max_polls=2)
    assert len(result.attempts) == 2 and all(a.verified for a in result.attempts)
    assert len(set(a[0] for a in seen)) == 2
    assert (await harness.queries.get_run(run.id)).status == "completed"


async def test_polling_idle_does_not_invoke_factory(harness):
    agent = await harness.orch.register_agent("polling-empty")
    def forbidden(_task):
        raise AssertionError("No provider activity without tasks")
    outcome = await worker(harness, agent.id, forbidden).poll_bounded(max_polls=3)
    assert outcome.attempts == ()


async def test_polling_stops_on_invalid_contract_without_retry_storm(harness):
    _, _, agent, _, tasks = await seed_workflow(
        harness.orch, harness.queries, task_count=2, max_attempts=2, retry_base=0.0,
    )
    calls = []
    def factory(_task):
        async def runner(task_id, attempt_id):
            calls.append(attempt_id)
            return '{"summary":""}'
        return runner
    outcome = await worker(harness, agent.id, factory).poll_bounded(max_polls=10)
    assert outcome.stopped_on_failure and len(outcome.attempts) == len(calls) == 1


async def test_polling_rejects_invalid_stop_control(harness):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    with pytest.raises(TypeError, match="Stop event"):
        await worker(harness, agent.id, lambda t: None).poll_bounded(stop_event=True)
    assert (await harness.queries.get_task(tasks[0].id)).status == "pending"


async def test_polling_stop_interrupts_idle_sleep(harness):
    agent = await harness.orch.register_agent("polling-stop")
    stop = asyncio.Event()
    w = worker(harness, agent.id, lambda t: None)
    async def request_stop():
        await asyncio.sleep(0.01)
        stop.set()
    pending = asyncio.create_task(request_stop())
    result = await asyncio.wait_for(
        w.poll_bounded(max_polls=50, interval_seconds=1, stop_event=stop), timeout=1,
    )
    await pending
    assert result.attempts == ()
