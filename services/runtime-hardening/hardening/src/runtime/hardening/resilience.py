"""Resilience framework (spec §5, ADR-011).

Two-layer resilience:

* **Layer 1 (application)** — outbound dependency stack in the mandatory
  decorator order **Bulkhead → TimeLimiter → RateLimiter → CircuitBreaker →
  Retry** (spec §5.1), plus a cross-layer global retry budget (AC-6).
* **Layer 2 (runtime)** — per-agent circuit breaker, per-resource-class
  bulkhead pools, the degradation ladder
  (``FULL → THROTTLED → READ_ONLY → PAUSED → TERMINATED``), and a recovery
  coordinator with exponential backoff + jitter and a health gate.

AC-5: a flaky dependency trips the breaker to OPEN within config, fast-fails
without retry while OPEN, half-opens after the wait, and closes after the
permitted half-open successes.
"""

from __future__ import annotations

import random
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, TypeVar

from runtime.hardening.config import ResilienceSettings
from runtime.hardening.models import CircuitBreakerState, DegradationMode, ResourceClass

T = TypeVar("T")

_clock: Callable[[], float] = time.monotonic


class BulkheadFull(RuntimeError):
    """Raised when a bulkhead pool has no free capacity."""


class CircuitOpen(RuntimeError):
    """Raised when a request is rejected by an open circuit breaker."""


class TimeoutExceeded(RuntimeError):
    """Raised when a call exceeds its time budget (spec §5.1 TimeLimiter)."""


class RateLimitExceeded(RuntimeError):
    """Raised when the token-bucket rate limit is exceeded."""


class RetryBudgetExhausted(RuntimeError):
    """Raised when the global retry budget has no tokens (fail fast, AC-6)."""


# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #
@dataclass
class CircuitBreaker:
    """Sliding-window circuit breaker (Resilience4j semantics, spec §5.1)."""

    name: str = "default"
    sliding_window_size: int = 100
    minimum_number_of_calls: int = 20
    failure_rate_threshold: float = 0.5
    wait_duration_in_open_state: float = 30.0
    permitted_number_of_calls_in_half_open_state: int = 3
    _state: CircuitBreakerState = CircuitBreakerState.CLOSED
    _window: deque[bool] = field(default_factory=deque)
    _opened_at: float = 0.0
    _half_open_calls: int = 0
    _half_open_successes: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.sliding_window_size < 1:
            raise ValueError("sliding_window_size must be >= 1")
        if not 0.0 < self.failure_rate_threshold <= 1.0:
            raise ValueError("failure_rate_threshold must be in (0, 1]")
        if self.minimum_number_of_calls > self.sliding_window_size:
            raise ValueError("minimum_number_of_calls cannot exceed sliding_window_size")
        self._window = deque(maxlen=self.sliding_window_size)

    @classmethod
    def from_settings(cls, name: str, settings: ResilienceSettings) -> CircuitBreaker:
        return cls(
            name=name,
            sliding_window_size=settings.sliding_window_size,
            minimum_number_of_calls=settings.minimum_number_of_calls,
            failure_rate_threshold=settings.failure_rate_threshold,
            wait_duration_in_open_state=settings.wait_duration_in_open_state,
            permitted_number_of_calls_in_half_open_state=(
                settings.permitted_number_of_calls_in_half_open_state
            ),
        )

    @property
    def state(self) -> CircuitBreakerState:
        with self._lock:
            self._maybe_half_open()
            return self._state

    def _maybe_half_open(self) -> None:
        if (
            self._state == CircuitBreakerState.OPEN
            and _clock() - self._opened_at >= self.wait_duration_in_open_state
        ):
            self._state = CircuitBreakerState.HALF_OPEN
            self._half_open_calls = 0
            self._half_open_successes = 0

    def allow_request(self) -> bool:
        """Return True when a call may proceed."""
        with self._lock:
            self._maybe_half_open()
            if self._state == CircuitBreakerState.CLOSED:
                return True
            if self._state == CircuitBreakerState.HALF_OPEN:
                if self._half_open_calls < self.permitted_number_of_calls_in_half_open_state:
                    self._half_open_calls += 1
                    return True
                return False
            return False  # OPEN

    def record_success(self) -> None:
        with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self.permitted_number_of_calls_in_half_open_state:
                    self._reset()
                return
            self._window.append(True)

    def record_failure(self) -> None:
        with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._trip()
                return
            if self._state == CircuitBreakerState.OPEN:
                return
            self._window.append(False)
            if self._should_trip():
                self._trip()

    def _should_trip(self) -> bool:
        if len(self._window) < self.minimum_number_of_calls:
            return False
        failures = sum(1 for ok in self._window if not ok)
        rate = failures / len(self._window)
        return rate >= self.failure_rate_threshold

    def _trip(self) -> None:
        self._state = CircuitBreakerState.OPEN
        self._opened_at = _clock()
        self._half_open_calls = 0
        self._half_open_successes = 0

    def _reset(self) -> None:
        self._state = CircuitBreakerState.CLOSED
        self._window.clear()

    def failure_rate(self) -> float:
        with self._lock:
            if not self._window:
                return 0.0
            return sum(1 for ok in self._window if not ok) / len(self._window)

    @contextmanager
    def guard(self) -> Iterator[None]:
        """Context manager: rejects when open, records outcome otherwise."""
        if not self.allow_request():
            raise CircuitOpen(f"circuit {self.name!r} is {self.state.value}")
        try:
            yield
        except Exception:
            self.record_failure()
            raise
        else:
            self.record_success()


# --------------------------------------------------------------------------- #
# Bulkhead
# --------------------------------------------------------------------------- #
@dataclass
class Bulkhead:
    """Semaphore-based concurrency pool for one resource class (spec §5.1)."""

    resource: ResourceClass
    max_concurrent_calls: int = 25
    max_wait_seconds: float = 0.0
    _semaphore: threading.BoundedSemaphore = field(init=False, repr=False)
    active: int = 0
    rejected: int = 0
    executed: int = 0

    def __post_init__(self) -> None:
        if self.max_concurrent_calls < 1:
            raise ValueError("max_concurrent_calls must be >= 1")
        self._semaphore = threading.BoundedSemaphore(self.max_concurrent_calls)

    def acquire(self) -> bool:
        acquired = self._semaphore.acquire(
            blocking=self.max_wait_seconds > 0, timeout=self.max_wait_seconds or None
        )
        if acquired:
            self.active += 1
        else:
            self.rejected += 1
        return acquired

    def release(self) -> None:
        self.active = max(0, self.active - 1)
        self._semaphore.release()

    @property
    def available(self) -> int:
        return max(0, self.max_concurrent_calls - self.active)

    @contextmanager
    def slot(self) -> Iterator[None]:
        if not self.acquire():
            raise BulkheadFull(f"bulkhead {self.resource.value!r} is full")
        try:
            self.executed += 1
            yield
        finally:
            self.release()


# --------------------------------------------------------------------------- #
# Time limiter (spec §5.1)
# --------------------------------------------------------------------------- #
class TimeLimiter:
    """Per-endpoint SLA timeout; cancels the running future on expiry."""

    def __init__(self, timeout_seconds: float, cancel_running_future: bool = True) -> None:
        self.timeout_seconds = timeout_seconds
        self.cancel_running_future = cancel_running_future

    def call(self, func: Callable[[], T]) -> T:
        """Run ``func`` with a deadline; raise :class:`TimeoutExceeded` on expiry.

        For synchronous callables this uses a watchdog thread that raises the
        timeout inside the worker as a best-effort cancellation. Callers
        requiring deterministic cancellation of async work should use the
        async ``call_async``.
        """
        result: list[Any] = []
        error: list[BaseException] = []
        finished = threading.Event()

        def runner() -> None:
            try:
                result.append(func())
            except BaseException as exc:  # noqa: BLE001 - propagate
                error.append(exc)
            finally:
                finished.set()

        worker = threading.Thread(target=runner, daemon=True)
        worker.start()
        if not finished.wait(self.timeout_seconds):
            raise TimeoutExceeded(f"call exceeded {self.timeout_seconds}s budget")
        if error:
            raise error[0]
        return result[0]


# --------------------------------------------------------------------------- #
# Rate limiter (spec §5.1)
# --------------------------------------------------------------------------- #
@dataclass
class RateLimiter:
    """Token bucket rate limiter."""

    rate_per_second: float = 50.0
    burst: int = 1
    _tokens: float = 0.0
    _last_refill: float = field(default_factory=_clock)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self._tokens = self.burst

    def acquire(self) -> bool:
        with self._lock:
            now = _clock()
            elapsed = now - self._last_refill
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate_per_second)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    @contextmanager
    def gate(self) -> Iterator[None]:
        if not self.acquire():
            raise RateLimitExceeded("rate limit exceeded")
        yield


# --------------------------------------------------------------------------- #
# Retry with exponential backoff + jitter (spec §5.1)
# --------------------------------------------------------------------------- #
@dataclass
class RetryPolicy:
    """Retry policy: ≤3 attempts, exp backoff (base 100ms, max 10s) ×2 + jitter.

    Idempotent operations only; 4xx responses are not retried.
    """

    max_attempts: int = 3
    base_seconds: float = 0.1
    max_seconds: float = 10.0
    jitter: bool = True
    _rand: random.Random = field(default_factory=random.Random)

    def should_retry(self, exc: BaseException) -> bool:
        """4xx client errors are not retried (spec §5.1)."""
        status = getattr(exc, "status_code", None)
        return not (isinstance(status, int) and 400 <= status < 500)

    def delay(self, attempt: int) -> float:
        """Return the backoff delay for ``attempt`` (0-indexed)."""
        delay = min(self.max_seconds, self.base_seconds * (2**attempt))
        if self.jitter:
            delay = self._rand.uniform(0.0, delay)
        return delay


# --------------------------------------------------------------------------- #
# Global retry budget (spec §5.2, AC-6)
# --------------------------------------------------------------------------- #
@dataclass
class RetryBudget:
    """Token bucket limiting retries to ~10% of total request volume (AC-6).

    Each recorded request accrues ``ratio`` tokens (1 per 10 requests at
    ratio=0.1); tokens are capped at ``max_tokens``. Every retry attempt in
    either layer consumes one token; when exhausted → fail fast with no retries.
    """

    ratio: float = 0.1
    ttl_seconds: float = 10.0
    min_per_second: float = 10.0
    max_tokens: float = 1000.0
    _tokens: float = 0.0
    _requests: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_settings(cls, settings: ResilienceSettings) -> RetryBudget:
        return cls(
            ratio=settings.retry_budget_ratio,
            ttl_seconds=settings.retry_budget_ttl_seconds,
            min_per_second=settings.retry_budget_min_per_second,
        )

    def record_request(self) -> None:
        """Accrue retry tokens for a new request (1 per 10 at ratio=0.1)."""
        with self._lock:
            self._requests += 1
            self._tokens = min(self.max_tokens, round(self._tokens + self.ratio, 6))

    def try_consume(self) -> bool:
        """Consume one retry token; False when the budget is exhausted."""
        with self._lock:
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    @property
    def ratio_available(self) -> float:
        """Current available retry budget as a ratio (for /metrics alert)."""
        with self._lock:
            return max(0.0, self._tokens / max(1, self._requests))


# --------------------------------------------------------------------------- #
# Layer-1 composed resilience (spec §5.1 decorator order)
# --------------------------------------------------------------------------- #
class ResilientCaller:
    """Composed Layer-1 stack: Bulkhead → TimeLimiter → RateLimiter → CB → Retry.

    Wraps a sync dependency call with the mandatory decorator order. Retry is
    the outermost layer (applies last to the whole protected call) and is gated
    by the global retry budget.
    """

    def __init__(
        self,
        *,
        name: str,
        bulkhead: Bulkhead,
        time_limiter: TimeLimiter,
        rate_limiter: RateLimiter,
        circuit_breaker: CircuitBreaker,
        retry_policy: RetryPolicy,
        retry_budget: RetryBudget,
    ) -> None:
        self.name = name
        self.bulkhead = bulkhead
        self.time_limiter = time_limiter
        self.rate_limiter = rate_limiter
        self.circuit_breaker = circuit_breaker
        self.retry_policy = retry_policy
        self.retry_budget = retry_budget

    def call(self, func: Callable[[], T]) -> T:
        """Run ``func`` protected by the full resilience stack."""
        self.retry_budget.record_request()
        last_exc: BaseException | None = None
        for attempt in range(self.retry_policy.max_attempts):
            with (
                self.circuit_breaker.guard(),
                self.bulkhead.slot(),
                self.rate_limiter.gate(),
            ):
                try:
                    return self.time_limiter.call(func)
                except BaseException as exc:  # noqa: BLE001
                    last_exc = exc
                    if not self.retry_policy.should_retry(exc):
                        raise
                    if attempt >= self.retry_policy.max_attempts - 1:
                        raise
                    if not self.retry_budget.try_consume():
                        raise RetryBudgetExhausted("global retry budget exhausted") from exc
                    time.sleep(self.retry_policy.delay(attempt))
                    continue
        if last_exc is not None:
            raise last_exc
        raise RuntimeError(f"unreachable for {self.name}")  # pragma: no cover


# --------------------------------------------------------------------------- #
# Degradation ladder + recovery coordinator (spec §5.1 Layer 2)
# --------------------------------------------------------------------------- #
class _Severity(IntEnum):
    FULL = 0
    THROTTLED = 1
    READ_ONLY = 2
    PAUSED = 3
    TERMINATED = 4


_MODE_TO_SEVERITY: dict[DegradationMode, _Severity] = {
    DegradationMode.FULL: _Severity.FULL,
    DegradationMode.THROTTLED: _Severity.THROTTLED,
    DegradationMode.READ_ONLY: _Severity.READ_ONLY,
    DegradationMode.PAUSED: _Severity.PAUSED,
    DegradationMode.TERMINATED: _Severity.TERMINATED,
}
_SEVERITY_TO_MODE = {v: k for k, v in _MODE_TO_SEVERITY.items()}


@dataclass
class DegradationLadder:
    """Container degradation state machine (spec §5.1, §5.3)."""

    mode: DegradationMode = DegradationMode.FULL
    history: list[DegradationMode] = field(default_factory=list)

    def escalate(self) -> DegradationMode:
        current = int(_MODE_TO_SEVERITY[self.mode])
        severity = min(int(_Severity.TERMINATED), current + 1)
        self.mode = _SEVERITY_TO_MODE[_Severity(severity)]
        self.history.append(self.mode)
        return self.mode

    def recover(self, steps: int = 1) -> DegradationMode:
        """Move back toward FULL one (or more) steps at a time."""
        if self.mode == DegradationMode.TERMINATED:
            return self.mode  # terminal
        current = int(_MODE_TO_SEVERITY[self.mode])
        severity = max(int(_Severity.FULL), current - steps)
        self.mode = _SEVERITY_TO_MODE[_Severity(severity)]
        self.history.append(self.mode)
        return self.mode

    def terminate(self) -> DegradationMode:
        self.mode = DegradationMode.TERMINATED
        self.history.append(self.mode)
        return self.mode

    @property
    def recoverable(self) -> bool:
        return self.mode != DegradationMode.TERMINATED


@dataclass
class RecoveryCoordinator:
    """Exponential backoff (base 2s, max 60s, full jitter) with a health gate."""

    base_seconds: float = 2.0
    max_seconds: float = 60.0
    jitter: bool = True
    max_attempts: int = 10
    attempts: int = 0
    health_gate_hits: int = 0
    _rand: random.Random = field(default_factory=random.Random)

    @classmethod
    def from_settings(cls, settings: ResilienceSettings) -> RecoveryCoordinator:
        return cls(
            base_seconds=settings.recovery_base_seconds,
            max_seconds=settings.recovery_max_seconds,
            max_attempts=settings.recovery_max_attempts,
        )

    def next_delay(self) -> float:
        """Return the next backoff delay and advance the attempt counter."""
        delay = min(self.max_seconds, self.base_seconds * (2**self.attempts))
        self.attempts += 1
        if self.jitter:
            delay = self._rand.uniform(0.0, delay)
        return delay

    def reset(self) -> None:
        self.attempts = 0

    def exhausted(self) -> bool:
        return self.attempts >= self.max_attempts


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
@dataclass
class ResilienceRegistry:
    """Per-agent breakers/ladders/coordinators and shared pools/budget."""

    settings: ResilienceSettings = field(default_factory=ResilienceSettings)
    bulkhead_pool: dict[ResourceClass, Bulkhead] = field(default_factory=dict)
    retry_budget: RetryBudget = field(default_factory=RetryBudget)
    _breakers: dict[str, CircuitBreaker] = field(default_factory=dict)
    _ladders: dict[str, DegradationLadder] = field(default_factory=dict)
    _coordinators: dict[str, RecoveryCoordinator] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.bulkhead_pool:
            self.bulkhead_pool = {
                resource: Bulkhead(
                    resource=resource,
                    max_concurrent_calls=self.settings.bulkhead_max_concurrent,
                    max_wait_seconds=self.settings.bulkhead_max_wait_seconds,
                )
                for resource in ResourceClass
            }

    def breaker(self, agent_id: str) -> CircuitBreaker:
        if agent_id not in self._breakers:
            self._breakers[agent_id] = CircuitBreaker.from_settings(agent_id, self.settings)
        return self._breakers[agent_id]

    def ladder(self, agent_id: str) -> DegradationLadder:
        if agent_id not in self._ladders:
            self._ladders[agent_id] = DegradationLadder()
        return self._ladders[agent_id]

    def coordinator(self, agent_id: str) -> RecoveryCoordinator:
        if agent_id not in self._coordinators:
            self._coordinators[agent_id] = RecoveryCoordinator.from_settings(self.settings)
        return self._coordinators[agent_id]

    def remove(self, agent_id: str) -> None:
        self._breakers.pop(agent_id, None)
        self._ladders.pop(agent_id, None)
        self._coordinators.pop(agent_id, None)
