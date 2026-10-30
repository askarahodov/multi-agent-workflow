"""Retry, timeout, circuit breaker and checkpoint/restore (ADR-104)."""

from __future__ import annotations

import asyncio

import pytest

from agent_runtime.errors import ErrorKind, PlatformError
from agent_runtime.limits import Budget, BudgetState
from agent_runtime.retry import (
    AgentRunState,
    CheckpointStore,
    CircuitBreaker,
    CircuitState,
    RunStatus,
    restore_budget,
    resume_point,
    resume_run,
    retry_async,
    with_timeout,
)


async def _no_sleep(_delay):
    return None


async def test_retry_async_retries_transient_then_succeeds():
    attempts = {"n": 0}

    async def op():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise PlatformError(ErrorKind.PROVIDER_SERVER, "boom")
        return "ok"

    result = await retry_async(op, max_attempts=5, sleep=_no_sleep)
    assert result == "ok"
    assert attempts["n"] == 3


async def test_retry_async_does_not_retry_non_retryable():
    attempts = {"n": 0}

    async def op():
        attempts["n"] += 1
        raise PlatformError(ErrorKind.TOOL_POLICY_DENIED, "denied")

    with pytest.raises(PlatformError):
        await retry_async(op, max_attempts=5, sleep=_no_sleep)
    assert attempts["n"] == 1


async def test_retry_async_reraises_after_exhaustion():
    async def op():
        raise PlatformError(ErrorKind.PROVIDER_TIMEOUT, "timeout")

    with pytest.raises(PlatformError):
        await retry_async(op, max_attempts=2, sleep=_no_sleep)


async def test_with_timeout_raises_platform_error():
    async def slow():
        await asyncio.sleep(5)

    with pytest.raises(PlatformError) as exc:
        await with_timeout(slow(), timeout_s=0.01, operation="unit")
    assert exc.value.kind is ErrorKind.TOOL_TIMEOUT


async def test_circuit_breaker_opens_and_half_opens():
    clock = {"t": 0.0}
    breaker = CircuitBreaker("gates", failure_threshold=2, reset_timeout_s=10.0, clock=lambda: clock["t"])

    async def boom():
        raise RuntimeError("down")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await breaker.call(boom)
    assert breaker.state is CircuitState.OPEN

    with pytest.raises(PlatformError) as exc:
        await breaker.call(boom)
    assert exc.value.kind is ErrorKind.GATE_UNAVAILABLE

    clock["t"] = 20.0
    await breaker.call(lambda: _ok())
    assert breaker.state is CircuitState.CLOSED


async def _ok():
    return "ok"


def test_checkpoint_store_records_turns_and_survives_reload(tmp_path):
    store = CheckpointStore(tmp_path)
    run = store.create("t-1", "inst-1", spec_version="v1")
    budget = BudgetState(tokens_used=10, steps_used=1)
    store.record_turn(run, messages=[{"role": "user", "content": "hi"}], result="success", budget=budget)
    assert run.last_completed_turn == 1

    reloaded = CheckpointStore(tmp_path).load(run.run_id)
    assert reloaded.last_completed_turn == 1
    assert reloaded.task_id == "t-1"
    assert restore_budget(reloaded).tokens_used == 10


def test_resume_point_rejects_terminal_runs():
    run = AgentRunState("run-1", "t-1", "inst-1", status=RunStatus.COMPLETED, last_completed_turn=3)
    with pytest.raises(PlatformError) as exc:
        resume_point(run)
    assert exc.value.kind is ErrorKind.VALIDATION_ERROR


async def test_resume_run_continues_from_last_completed_turn():
    run = AgentRunState("run-1", "t-1", "inst-1", last_completed_turn=4)
    seen = {}

    async def turn_runner(_run, next_turn):
        seen["turn"] = next_turn
        return "resumed"

    result = await resume_run(
        run, budget=Budget(max_steps=10, max_tokens=100, max_cost_usd=1, max_wall_time_ms=1000), turn_runner=turn_runner
    )
    assert result == "resumed"
    assert seen["turn"] == 5


async def test_resume_run_blocks_when_budget_already_exhausted():
    run = AgentRunState("run-1", "t-1", "inst-1", budget_state={"steps_used": 5})

    async def turn_runner(_run, _turn):
        return "should not run"

    with pytest.raises(PlatformError) as exc:
        await resume_run(run, budget=Budget(max_steps=5), turn_runner=turn_runner)
    assert exc.value.kind is ErrorKind.BUDGET_EXHAUSTED
