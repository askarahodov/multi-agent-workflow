"""Native supervisor proves no idle spending, stop-on-failure and finite polling."""
from __future__ import annotations

import asyncio

import pytest

from orchestration_server.native_http_worker import RemoteAttemptResult, RemoteWorkerBatch
from orchestration_server.native_worker_supervisor import NativeWorkerSupervisor


class FakeBatchWorker:
    def __init__(self, batches=None, exception=None):
        self.batches = list(batches or [])
        self.exception = exception
        self.calls = []

    async def run_batch(self, *, max_attempts=1):
        self.calls.append(max_attempts)
        if self.exception:
            raise self.exception
        if self.batches:
            return self.batches.pop(0)
        return RemoteWorkerBatch((), False)


def ok(task_id="a"):
    return RemoteAttemptResult(task_id, "attempt-id", "completed", True)


def fail(task_id="a"):
    return RemoteAttemptResult(task_id, "attempt-id", "verification_failed", False)


async def test_no_model_calls_from_idle_queue_and_finite_polling():
    worker = FakeBatchWorker()
    report = await NativeWorkerSupervisor(
        worker, max_polls=3, max_attempts_per_poll=2,
        poll_interval_seconds=0.01,
    ).run(asyncio.Event())
    assert report.polls == 3 and report.reason == "POLL_LIMIT"
    assert report.completed_attempts == report.failed_attempts == 0
    assert worker.calls == [2, 2, 2]


async def test_one_failure_stops_without_retry():
    worker = FakeBatchWorker([
        RemoteWorkerBatch((fail(),), True),
        RemoteWorkerBatch((ok(),), False),
    ])
    report = await NativeWorkerSupervisor(
        worker, max_polls=100, poll_interval_seconds=0.01,
    ).run(asyncio.Event())
    assert report.reason == "FAIL_CLOSED"
    assert report.polls == 1 and report.failed_attempts == 1
    assert worker.calls == [1]


async def test_successful_work_is_accounted_without_infinite_loop():
    worker = FakeBatchWorker([
        RemoteWorkerBatch((ok("first"), ok("second")), False),
        RemoteWorkerBatch((), False),
    ])
    report = await NativeWorkerSupervisor(
        worker, max_polls=2, max_attempts_per_poll=2, poll_interval_seconds=0.01,
    ).run(asyncio.Event())
    assert report.completed_attempts == 2
    assert report.failed_attempts == 0
    assert report.reason == "POLL_LIMIT"
    assert worker.calls == [2, 2]


async def test_signal_before_start_produces_no_http_or_provider_call():
    worker = FakeBatchWorker()
    flag = asyncio.Event()
    flag.set()
    report = await NativeWorkerSupervisor(
        worker, max_polls=100,
    ).run(flag)
    assert report.reason == "STOPPED" and report.polls == 0
    assert worker.calls == []


async def test_signal_during_interval_interrupts_next_poll():
    worker = FakeBatchWorker()
    flag = asyncio.Event()
    supervisor = NativeWorkerSupervisor(
        worker, max_polls=100,
        poll_interval_seconds=120,
    )
    task = asyncio.create_task(supervisor.run(flag))
    for _ in range(500):
        if worker.calls:
            break
        await asyncio.sleep(0)
    assert worker.calls == [1]
    flag.set()
    report = await asyncio.wait_for(task, timeout=2)
    assert report.reason == "STOPPED" and report.polls == 1
    assert worker.calls == [1]


async def test_transport_error_propagates_and_never_retries():
    worker = FakeBatchWorker(exception=RuntimeError("transport down"))
    supervisor = NativeWorkerSupervisor(
        worker, max_polls=100, poll_interval_seconds=0.01,
    )
    with pytest.raises(RuntimeError, match="transport down"):
        await supervisor.run(asyncio.Event())
    assert worker.calls == [1]


async def test_cancelled_supervisor_propagates_cancel():
    started = asyncio.Event()

    class HangingWorker:
        async def run_batch(self, *, max_attempts=1):
            started.set()
            await asyncio.sleep(3600)
            return RemoteWorkerBatch((), False)

    supervisor = NativeWorkerSupervisor(HangingWorker(), max_polls=10)
    task = asyncio.create_task(supervisor.run(asyncio.Event()))
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.parametrize("settings", [
    {"max_polls": 0}, {"max_polls": 1001},
    {"max_attempts_per_poll": 0}, {"max_attempts_per_poll": 101},
    {"poll_interval_seconds": 0}, {"poll_interval_seconds": 3601},
])
def test_unbounded_configuration_is_rejected(settings):
    with pytest.raises(ValueError):
        NativeWorkerSupervisor(FakeBatchWorker(), **settings)


async def test_no_implicit_background_execution():
    worker = FakeBatchWorker()
    supervisor = NativeWorkerSupervisor(worker)
    assert worker.calls == []  # constructing supervisor must not start polling
    result = await supervisor.run(asyncio.Event())
    assert result.polls == 1 and worker.calls == [1]
