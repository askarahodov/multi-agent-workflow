"""Resilience: circuit breaker, bulkheads and the degradation ladder (ADR-003).

Runtime-level resilience for the agent sandbox:

* per-agent :class:`CircuitBreaker` (``CLOSED → OPEN → HALF_OPEN → CLOSED``),
* semaphore-based :class:`Bulkhead` pools keyed by :class:`ResourceClass`,
* the container :class:`DegradationLadder`
  (``FULL → THROTTLED → READ_ONLY → PAUSED → TERMINATED``),
* a :class:`RecoveryCoordinator` with exponential backoff + jitter,
* a global :class:`RetryBudget` token bucket (~10% of request volume).
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

from runtime.models import CircuitBreakerState, DegradationMode, ResourceClass


class BulkheadFull(RuntimeError):
    """Raised when a bulkhead pool has no free capacity."""


class CircuitOpen(RuntimeError):
    """Raised when a request is rejected by an open circuit breaker."""


# --------------------------------------------------------------------------- #
# Circuit breaker
# --------------------------------------------------------------------------- #
@dataclass
class CircuitBreakerConfig:
    sliding_window_size: int = 100
    minimum_number_of_calls: int = 20
    failure_rate_threshold: float = 0.5
    wait_duration_in_open_state: float = 30.0
    permitted_number_of_calls_in_half_open_state: int = 3
    slow_call_duration: float | None = None
    slow_call_rate_threshold: float | None = None
    _clock: Callable[[], float] = field(default=time.monotonic)

    def validate(self) -> None:
        if self.sliding_window_size < 1:
            raise ValueError("sliding_window_size must be >= 1")
        if not 0.0 < self.failure_rate_threshold <= 1.0:
            raise ValueError("failure_rate_threshold must be in (0, 1]")
        if self.minimum_number_of_calls > self.sliding_window_size:
            raise ValueError("minimum_number_of_calls cannot exceed sliding_window_size")


@dataclass
class CircuitBreaker:
    """Sliding-window circuit breaker (Resilience4j semantics)."""

    name: str = "default"
    config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    _state: CircuitBreakerState = CircuitBreakerState.CLOSED
    _window: deque[bool] = field(default_factory=deque)
    _opened_at: float = 0.0
    _half_open_calls: int = 0
    _half_open_successes: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.config.validate()
        self._window = deque(maxlen=self.config.sliding_window_size)

    @property
    def state(self) -> CircuitBreakerState:
        with self._lock:
            self._maybe_half_open()
            return self._state

    def _maybe_half_open(self) -> None:
        if (
            self._state == CircuitBreakerState.OPEN
            and self.config._clock() - self._opened_at >= self.config.wait_duration_in_open_state
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
                if self._half_open_calls < self.config.permitted_number_of_calls_in_half_open_state:
                    self._half_open_calls += 1
                    return True
                return False
            return False  # OPEN

    def record_success(self) -> None:
        with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._half_open_successes += 1
                if (
                    self._half_open_successes
                    >= self.config.permitted_number_of_calls_in_half_open_state
                ):
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
        if len(self._window) < self.config.minimum_number_of_calls:
            return False
        failures = sum(1 for ok in self._window if not ok)
        rate = failures / len(self._window)
        return rate >= self.config.failure_rate_threshold

    def _trip(self) -> None:
        self._state = CircuitBreakerState.OPEN
        self._opened_at = self.config._clock()
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
# Bulkheads
# --------------------------------------------------------------------------- #
@dataclass
class Bulkhead:
    """Semaphore-based concurrency pool for one resource class."""

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


@dataclass
class BulkheadPool:
    """Bulkhead pools keyed by resource class."""

    limits: dict[ResourceClass, int] = field(default_factory=dict)
    max_wait_seconds: float = 0.0
    _pools: dict[ResourceClass, Bulkhead] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for resource, size in self.limits.items():
            self._pools[resource] = Bulkhead(
                resource=resource,
                max_concurrent_calls=size,
                max_wait_seconds=self.max_wait_seconds,
            )

    def get(self, resource: ResourceClass) -> Bulkhead:
        if resource not in self._pools:
            self._pools[resource] = Bulkhead(
                resource=resource,
                max_concurrent_calls=self.limits.get(resource, 25),
                max_wait_seconds=self.max_wait_seconds,
            )
        return self._pools[resource]


# --------------------------------------------------------------------------- #
# Degradation ladder
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
    """Container degradation state machine (ADR-003)."""

    mode: DegradationMode = DegradationMode.FULL
    history: list[DegradationMode] = field(default_factory=list)

    def escalate(self, reason: str = "") -> DegradationMode:
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


# --------------------------------------------------------------------------- #
# Recovery coordinator
# --------------------------------------------------------------------------- #
@dataclass
class RecoveryCoordinator:
    """Exponential backoff (base 2s, max 60s, full jitter)."""

    base_seconds: float = 2.0
    max_seconds: float = 60.0
    jitter: bool = True
    max_attempts: int = 10
    attempts: int = 0
    _rand: random.Random = field(default_factory=random.Random)

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
# Retry budget
# --------------------------------------------------------------------------- #
@dataclass
class RetryBudget:
    """Token bucket limiting retries to ~10% of total request volume."""

    ratio: float = 0.1
    ttl_seconds: float = 10.0
    min_per_second: float = 10.0
    _tokens: float = 0.0
    _requests: int = 0
    _last_refill: float = field(default_factory=time.monotonic)
    _clock: Callable[[], float] = field(default=time.monotonic)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _refill(self) -> None:
        now = self._clock()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        rate = max(self.min_per_second, self._requests / self.ttl_seconds) * self.ratio
        self._tokens = min(self._requests * self.ratio, self._tokens + rate * elapsed)
        self._last_refill = now
        self._requests = 0

    def record_request(self) -> None:
        with self._lock:
            self._refill()
            self._requests += 1

    def try_consume(self) -> bool:
        """Consume one retry token; False when the budget is exhausted."""
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #
@dataclass
class ResilienceRegistry:
    """Per-agent breakers/ladders and shared bulkhead pools."""

    breaker_config: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    bulkhead_pool: BulkheadPool = field(default_factory=BulkheadPool)
    retry_budget: RetryBudget = field(default_factory=RetryBudget)
    _breakers: dict[str, CircuitBreaker] = field(default_factory=dict)
    _ladders: dict[str, DegradationLadder] = field(default_factory=dict)
    _coordinators: dict[str, RecoveryCoordinator] = field(default_factory=dict)

    def breaker(self, agent_id: str) -> CircuitBreaker:
        if agent_id not in self._breakers:
            self._breakers[agent_id] = CircuitBreaker(name=agent_id, config=self.breaker_config)
        return self._breakers[agent_id]

    def ladder(self, agent_id: str) -> DegradationLadder:
        if agent_id not in self._ladders:
            self._ladders[agent_id] = DegradationLadder()
        return self._ladders[agent_id]

    def coordinator(self, agent_id: str) -> RecoveryCoordinator:
        if agent_id not in self._coordinators:
            self._coordinators[agent_id] = RecoveryCoordinator()
        return self._coordinators[agent_id]

    def remove(self, agent_id: str) -> None:
        self._breakers.pop(agent_id, None)
        self._ladders.pop(agent_id, None)
        self._coordinators.pop(agent_id, None)
