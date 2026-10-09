"""Unit tests for the resilience framework (spec §5, AC-5/AC-6)."""

from __future__ import annotations

import time

import pytest

from runtime.hardening.models import CircuitBreakerState, DegradationMode, ResourceClass
from runtime.hardening.resilience import (
    Bulkhead,
    BulkheadFull,
    CircuitBreaker,
    CircuitOpen,
    DegradationLadder,
    RateLimiter,
    RecoveryCoordinator,
    ResilientCaller,
    RetryBudget,
    RetryBudgetExhausted,
    RetryPolicy,
    TimeLimiter,
    TimeoutExceeded,
)


def _cb(**kwargs) -> CircuitBreaker:
    return CircuitBreaker(sliding_window_size=10, minimum_number_of_calls=3, **kwargs)


def test_cb_trips_open_on_failure_rate() -> None:
    """AC-5: flaky dependency trips the breaker to OPEN within config."""
    cb = _cb(failure_rate_threshold=0.5)
    for _ in range(5):
        cb.record_failure()
    assert cb.state == CircuitBreakerState.OPEN


def test_cb_fast_fails_while_open() -> None:
    cb = _cb(failure_rate_threshold=0.5, wait_duration_in_open_state=60.0)
    for _ in range(5):
        cb.record_failure()
    assert cb.allow_request() is False  # OPEN -> reject, no retry


def test_cb_half_open_after_wait() -> None:
    cb = _cb(failure_rate_threshold=0.5, wait_duration_in_open_state=0.1)
    for _ in range(5):
        cb.record_failure()
    time.sleep(0.15)
    assert cb.state == CircuitBreakerState.HALF_OPEN


def test_cb_closes_after_half_open_successes() -> None:
    """AC-5: closes after the permitted half-open successes."""
    cb = _cb(
        failure_rate_threshold=0.5,
        wait_duration_in_open_state=0.0,
        permitted_number_of_calls_in_half_open_state=3,
    )
    for _ in range(5):
        cb.record_failure()
    assert cb.state == CircuitBreakerState.HALF_OPEN or cb.allow_request()  # transitioned
    cb.record_success()
    cb.record_success()
    cb.record_success()
    assert cb.state == CircuitBreakerState.CLOSED


def test_cb_guard_rejects_when_open() -> None:
    cb = _cb(failure_rate_threshold=0.5, wait_duration_in_open_state=60.0)
    for _ in range(5):
        cb.record_failure()
    with pytest.raises(CircuitOpen), cb.guard():
        pass


def test_cb_does_not_trip_below_min_calls() -> None:
    cb = _cb(failure_rate_threshold=0.5)
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitBreakerState.CLOSED  # only 2 < min 3


def test_bulkhead_full() -> None:
    bh = Bulkhead(resource=ResourceClass.CPU, max_concurrent_calls=1)
    with bh.slot(), pytest.raises(BulkheadFull), bh.slot():
        pass


def test_bulkhead_available() -> None:
    bh = Bulkhead(resource=ResourceClass.CPU, max_concurrent_calls=5)
    assert bh.available == 5
    with bh.slot():
        assert bh.available == 4


def test_rate_limiter_exhausted() -> None:
    rl = RateLimiter(rate_per_second=0.0, burst=1)
    assert rl.acquire() is True
    assert rl.acquire() is False


def test_time_limiter_expires() -> None:
    tl = TimeLimiter(timeout_seconds=0.05)

    def slow() -> None:
        time.sleep(1.0)

    with pytest.raises(TimeoutExceeded):
        tl.call(slow)


def test_retry_budget_exhaustion_fails_fast() -> None:
    """AC-6: retry budget exhaustion fails fast (no retries)."""
    budget = RetryBudget(ratio=0.1)
    # No tokens accrued -> consumption fails.
    assert budget.try_consume() is False


def test_retry_budget_refills_from_volume() -> None:
    # ratio=0.1 => 1 token per 10 requests (spec §5.2).
    budget = RetryBudget(ratio=0.1)
    assert budget.try_consume() is False
    for _ in range(10):
        budget.record_request()
    assert budget.try_consume() is True
    assert budget.try_consume() is False  # single token consumed


def test_degradation_ladder_escalate_and_recover() -> None:
    ladder = DegradationLadder()
    assert ladder.escalate() == DegradationMode.THROTTLED
    assert ladder.escalate() == DegradationMode.READ_ONLY
    assert ladder.recover(1) == DegradationMode.THROTTLED
    assert ladder.recover(1) == DegradationMode.FULL


def test_degradation_ladder_terminal() -> None:
    ladder = DegradationLadder()
    ladder.terminate()
    assert ladder.mode == DegradationMode.TERMINATED
    assert ladder.recoverable is False
    assert ladder.recover() == DegradationMode.TERMINATED


def test_recovery_coordinator_backoff() -> None:
    rc = RecoveryCoordinator(base_seconds=2.0, max_seconds=60.0, jitter=False)
    assert rc.next_delay() == 2.0
    assert rc.next_delay() == 4.0
    assert rc.next_delay() == 8.0
    rc.reset()
    assert rc.attempts == 0


def test_retry_policy_backoff_grows() -> None:
    policy = RetryPolicy(base_seconds=0.1, max_seconds=10.0, jitter=False)
    assert policy.delay(0) == 0.1
    assert policy.delay(1) == 0.2
    assert policy.delay(2) == 0.4


def test_retry_policy_ignores_4xx() -> None:
    class FourHundred(RuntimeError):
        status_code = 400

    policy = RetryPolicy()
    assert policy.should_retry(FourHundred()) is False


def test_resilient_caller_retries_transient_then_succeeds() -> None:
    calls: list[int] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 2:
            raise RuntimeError("transient")
        return "ok"

    caller = ResilientCaller(
        name="dep",
        bulkhead=Bulkhead(resource=ResourceClass.NETWORK, max_concurrent_calls=5),
        time_limiter=TimeLimiter(timeout_seconds=5.0),
        rate_limiter=RateLimiter(rate_per_second=100.0, burst=10),
        circuit_breaker=_cb(failure_rate_threshold=0.9),
        retry_policy=RetryPolicy(max_attempts=3, base_seconds=0.0, jitter=False),
        retry_budget=RetryBudget(ratio=1.0),
    )
    assert caller.call(flaky) == "ok"
    assert len(calls) == 2


def test_resilient_caller_retry_budget_exhausted() -> None:
    budget = RetryBudget(ratio=0.0, ttl_seconds=1.0, min_per_second=0.0)
    budget._tokens = 0.0

    def always_fail() -> None:
        raise RuntimeError("fail")

    caller = ResilientCaller(
        name="dep",
        bulkhead=Bulkhead(resource=ResourceClass.NETWORK, max_concurrent_calls=5),
        time_limiter=TimeLimiter(timeout_seconds=5.0),
        rate_limiter=RateLimiter(rate_per_second=100.0),
        circuit_breaker=_cb(failure_rate_threshold=0.9),
        retry_policy=RetryPolicy(max_attempts=3, base_seconds=0.0, jitter=False),
        retry_budget=budget,
    )
    with pytest.raises(RetryBudgetExhausted):
        caller.call(always_fail)


def test_resilient_caller_circuit_blocks() -> None:
    cb = _cb(failure_rate_threshold=0.5, wait_duration_in_open_state=60.0)
    for _ in range(5):
        cb.record_failure()

    def ok() -> str:
        return "x"

    caller = ResilientCaller(
        name="dep",
        bulkhead=Bulkhead(resource=ResourceClass.CPU, max_concurrent_calls=5),
        time_limiter=TimeLimiter(timeout_seconds=5.0),
        rate_limiter=RateLimiter(rate_per_second=100.0),
        circuit_breaker=cb,
        retry_policy=RetryPolicy(max_attempts=1, base_seconds=0.0, jitter=False),
        retry_budget=RetryBudget(ratio=1.0, ttl_seconds=1.0, min_per_second=0.0),
    )
    with pytest.raises(CircuitOpen):
        caller.call(ok)
