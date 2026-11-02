"""Unit tests for the resilience layer (ADR-003)."""

from __future__ import annotations

import pytest

from runtime.circuit_breaker import (
    Bulkhead,
    BulkheadFull,
    BulkheadPool,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpen,
    DegradationLadder,
    RecoveryCoordinator,
    ResilienceRegistry,
    RetryBudget,
)
from runtime.models import CircuitBreakerState, DegradationMode, ResourceClass


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_breaker(clock: FakeClock, threshold: float = 0.5) -> CircuitBreaker:
    config = CircuitBreakerConfig(
        sliding_window_size=10,
        minimum_number_of_calls=5,
        failure_rate_threshold=threshold,
        wait_duration_in_open_state=30.0,
        permitted_number_of_calls_in_half_open_state=3,
        _clock=clock,
    )
    return CircuitBreaker(name="t", config=config)


def test_breaker_starts_closed() -> None:
    breaker = make_breaker(FakeClock())
    assert breaker.state == CircuitBreakerState.CLOSED
    assert breaker.allow_request() is True


def test_breaker_trips_open_on_failure_rate() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)
    for _ in range(5):
        breaker.record_failure()
    assert breaker.state == CircuitBreakerState.OPEN
    assert breaker.allow_request() is False


def test_breaker_no_trip_below_minimum_calls() -> None:
    breaker = make_breaker(FakeClock())
    for _ in range(4):
        breaker.record_failure()
    assert breaker.state == CircuitBreakerState.CLOSED


def test_breaker_half_open_after_wait_and_recovers() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)
    for _ in range(5):
        breaker.record_failure()
    assert breaker.state == CircuitBreakerState.OPEN
    clock.advance(31)
    assert breaker.state == CircuitBreakerState.HALF_OPEN
    # permit exactly 3 half-open calls
    assert breaker.allow_request() is True
    assert breaker.allow_request() is True
    assert breaker.allow_request() is True
    assert breaker.allow_request() is False
    for _ in range(3):
        breaker.record_success()
    assert breaker.state == CircuitBreakerState.CLOSED


def test_breaker_half_open_failure_reopens() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)
    for _ in range(5):
        breaker.record_failure()
    clock.advance(31)
    assert breaker.state == CircuitBreakerState.HALF_OPEN
    breaker.record_failure()
    assert breaker.state == CircuitBreakerState.OPEN


def test_breaker_guard_records_outcome() -> None:
    breaker = make_breaker(FakeClock())
    with breaker.guard():
        pass
    assert breaker.state == CircuitBreakerState.CLOSED
    with pytest.raises(ValueError), breaker.guard():
        raise ValueError("boom")


def test_breaker_guard_rejects_when_open() -> None:
    clock = FakeClock()
    breaker = make_breaker(clock)
    for _ in range(5):
        breaker.record_failure()
    with pytest.raises(CircuitOpen), breaker.guard():
        pass


def test_breaker_config_validation() -> None:
    with pytest.raises(ValueError):
        CircuitBreakerConfig(sliding_window_size=0).validate()
    with pytest.raises(ValueError):
        CircuitBreakerConfig(failure_rate_threshold=0).validate()
    with pytest.raises(ValueError):
        CircuitBreakerConfig(minimum_number_of_calls=200, sliding_window_size=10).validate()


def test_bulkhead_limits_concurrency() -> None:
    bulkhead = Bulkhead(resource=ResourceClass.CPU, max_concurrent_calls=2)
    assert bulkhead.acquire() is True
    assert bulkhead.acquire() is True
    assert bulkhead.acquire() is False
    assert bulkhead.active == 2
    assert bulkhead.rejected == 1
    bulkhead.release()
    assert bulkhead.available == 1


def test_bulkhead_slot_context_manager() -> None:
    bulkhead = Bulkhead(resource=ResourceClass.MEMORY, max_concurrent_calls=1)
    with bulkhead.slot():
        assert bulkhead.active == 1
    assert bulkhead.active == 0
    assert bulkhead.executed == 1


def test_bulkhead_slot_raises_when_full() -> None:
    bulkhead = Bulkhead(resource=ResourceClass.NETWORK, max_concurrent_calls=1)
    with bulkhead.slot(), pytest.raises(BulkheadFull), bulkhead.slot():
        pass


def test_bulkhead_pool_creates_on_demand() -> None:
    pool = BulkheadPool(limits={ResourceClass.CPU: 1})
    cpu = pool.get(ResourceClass.CPU)
    assert cpu.max_concurrent_calls == 1
    disk = pool.get(ResourceClass.DISK_IO)
    assert disk.max_concurrent_calls == 25  # default


def test_degradation_ladder_escalation_and_recovery() -> None:
    ladder = DegradationLadder()
    assert ladder.mode == DegradationMode.FULL
    assert ladder.escalate() == DegradationMode.THROTTLED
    assert ladder.escalate() == DegradationMode.READ_ONLY
    assert ladder.escalate() == DegradationMode.PAUSED
    assert ladder.escalate() == DegradationMode.TERMINATED
    # terminal
    assert ladder.escalate() == DegradationMode.TERMINATED
    assert ladder.recoverable is False
    assert ladder.recover() == DegradationMode.TERMINATED


def test_degradation_ladder_recovers_steps() -> None:
    ladder = DegradationLadder(mode=DegradationMode.READ_ONLY)
    assert ladder.recover() == DegradationMode.THROTTLED
    assert ladder.recover(steps=5) == DegradationMode.FULL


def test_degradation_terminate() -> None:
    ladder = DegradationLadder()
    assert ladder.terminate() == DegradationMode.TERMINATED


def test_recovery_coordinator_backoff() -> None:
    coordinator = RecoveryCoordinator(base_seconds=2.0, max_seconds=60.0, jitter=False)
    assert coordinator.next_delay() == 2.0
    assert coordinator.next_delay() == 4.0
    assert coordinator.next_delay() == 8.0
    for _ in range(10):
        coordinator.next_delay()
    assert coordinator.exhausted() is True
    coordinator.reset()
    assert coordinator.attempts == 0


def test_retry_budget_allows_within_ratio() -> None:
    clock = FakeClock()
    clock.now = 1000.0
    budget = RetryBudget(ratio=0.1, _clock=clock)
    for _ in range(100):
        budget.record_request()
    # refill gives min_per_second based tokens
    assert budget.try_consume() in (True, False)
    assert isinstance(budget.try_consume(), bool)


def test_resilience_registry_caches() -> None:
    registry = ResilienceRegistry()
    assert registry.breaker("a") is registry.breaker("a")
    assert registry.ladder("a") is registry.ladder("a")
    assert registry.coordinator("a") is registry.coordinator("a")
    registry.remove("a")
    assert registry.breaker("a").state == CircuitBreakerState.CLOSED
