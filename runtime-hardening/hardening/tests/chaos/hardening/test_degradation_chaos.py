"""Chaos tests: resilience + degradation under adversarial conditions (spec §8)."""

from __future__ import annotations

import threading
import time

import pytest

from runtime.hardening.degradation import DegradationController
from runtime.hardening.models import (
    DegradationMode,
    PressureReport,
    PressureSample,
    ResourceClass,
)
from runtime.hardening.resilience import (
    Bulkhead,
    CircuitBreaker,
    RateLimiter,
    ResilientCaller,
    RetryBudget,
    RetryPolicy,
    TimeLimiter,
)

pytestmark = pytest.mark.chaos


def test_concurrent_bulkhead_rejects_overflow() -> None:
    """Bulkhead isolation: excess concurrent calls are rejected, not queued forever."""
    bulkhead = Bulkhead(resource=ResourceClass.CPU, max_concurrent_calls=2, max_wait_seconds=0.0)
    held: list[threading.Event] = []
    results: list[str] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        try:
            with bulkhead.slot():
                with lock:
                    held.append(threading.Event())
                # Block until released.
                time.sleep(0.05)
                with lock:
                    results.append(f"ok-{i}")
        except Exception:
            with lock:
                results.append(f"reject-{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    time.sleep(0.1)
    for t in threads:
        t.join()
    # Only 2 slots; at least the first two succeeded and some were rejected.
    ok_count = sum(1 for r in results if r.startswith("ok"))
    reject_count = sum(1 for r in results if r.startswith("reject"))
    assert ok_count >= 2
    assert reject_count >= 1
    assert ok_count + reject_count == 5


def test_retry_storm_amplification_capped() -> None:
    """AC-6: retry budget caps amplification; exhaustion fails fast."""
    budget = RetryBudget(ratio=0.0)  # no tokens ever -> first retry fails fast
    attempts = {"n": 0}
    lock = threading.Lock()

    def flaky() -> None:
        with lock:
            attempts["n"] += 1
        raise RuntimeError("always fails")

    caller = ResilientCaller(
        name="storm",
        bulkhead=Bulkhead(resource=ResourceClass.NETWORK, max_concurrent_calls=5),
        time_limiter=TimeLimiter(timeout_seconds=5.0),
        rate_limiter=RateLimiter(rate_per_second=100.0, burst=10),
        circuit_breaker=CircuitBreaker(
            failure_rate_threshold=0.9, sliding_window_size=100, minimum_number_of_calls=20
        ),
        retry_policy=RetryPolicy(max_attempts=3, base_seconds=0.0, jitter=False),
        retry_budget=budget,
    )
    # Budget is exhausted -> first retry attempt fails fast.
    from runtime.hardening.resilience import RetryBudgetExhausted

    with pytest.raises(RetryBudgetExhausted):
        caller.call(flaky)
    # No unbounded retry storm: only 1 actual execution happened.
    assert attempts["n"] <= 1


def test_pressure_driven_escalation_and_recovery() -> None:
    """AC-5/§5.3: memory-pressure agent degrades and recovers."""
    from runtime.hardening.resilience import ResilienceRegistry

    registry = ResilienceRegistry()
    transitions: list[tuple[DegradationMode, DegradationMode]] = []
    controller = DegradationController(
        registry,
        on_transition=lambda a, prev, new, r: transitions.append((prev, new)),
    )

    def report(mem: float) -> PressureReport:
        s = PressureSample(avg10=mem)
        return PressureReport(cpu=PressureSample(avg10=0.0), memory=s, io=PressureSample(avg10=0.0))

    assert controller.update_from_pressure("a1", report(0.9)) == DegradationMode.THROTTLED
    assert controller.update_from_pressure("a1", report(0.95)) == DegradationMode.READ_ONLY
    # Pressure clears -> recover THROTTLED then FULL.
    controller.update_from_pressure("a1", report(0.0))
    assert controller.mode("a1") == DegradationMode.THROTTLED
    controller.update_from_pressure("a1", report(0.0))
    assert controller.mode("a1") == DegradationMode.FULL
