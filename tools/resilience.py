"""Resilience primitives (task item (f)): retries, backoffs, timeouts.

These helpers give the agent runtime and the various subsystem call-sites a
uniform way to handle transient failures:

* :func:`retry` / :func:`retry_async` — call a sync/async function with
  exponential backoff + jitter and a cap on attempts.
* :func:`with_timeout` / :func:`with_timeout_async` — run a function under a
  deadline and raise :class:`TimeoutError`-based :class:`OperationTimeout` on
  expiry.
* :class:`CircuitBreaker` — a single-host, in-process breaker so a failing
  upstream does not cascade into every caller (mirrors the runtime-hardening
  breaker semantics for the service-integration layer).
* :func:`is_retryable` — classify an exception as transient vs permanent.

The module is intentionally dependency-free (stdlib only) so it can be used
from every subsystem and unit-tested in isolation.
"""

from __future__ import annotations

import asyncio
import functools
import random
import time
import uuid


class ResilienceError(Exception):
    """Base class for resilience-layer errors."""


class OperationTimeout(ResilienceError):
    """Raised when an operation exceeds its deadline."""

    def __init__(self, message: str = "operation timed out", operation: str | None = None, timeout_s: float | None = None) -> None:
        super().__init__(message)
        self.operation = operation
        self.timeout_s = timeout_s


class RetriesExhausted(ResilienceError):
    """Raised when a function keeps failing after the configured attempt budget."""

    def __init__(self, attempts: int, last_error: Exception | None = None) -> None:
        super().__init__(f"operation failed after {attempts} attempt(s)")
        self.attempts = attempts
        self.last_error = last_error


def _jitter(backoff_s: float, jitter_pct: float = 0.2) -> float:
    if jitter_pct <= 0:
        return backoff_s
    span = backoff_s * jitter_pct
    return backoff_s + random.uniform(-span, span)


def retry(
    func,
    *,
    max_attempts: int = 5,
    base_delay_s: float = 0.1,
    max_delay_s: float = 4.0,
    multiplier: float = 2.0,
    jitter_pct: float = 0.2,
    retryable=None,
    on_retry=None,
):
    """Retry a *sync* callable with exponential backoff and jitter.

    ``retryable`` is a predicate ``(exc) -> bool`` deciding which exceptions are
    transient (default: all exceptions). ``on_retry`` (optional) is invoked with
    ``(attempt, exc, delay_s)`` before sleeping.
    """
    retryable = retryable or (lambda exc: True)
    attempt = 0
    delay = base_delay_s
    last_error: Exception | None = None
    while attempt < max_attempts:
        attempt += 1
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 - deliberately broad
            last_error = exc
            if not retryable(exc):
                raise
            if attempt >= max_attempts:
                break
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            time.sleep(_jitter(delay, jitter_pct))
            delay = min(delay * multiplier, max_delay_s)
    raise RetriesExhausted(attempt, last_error)


async def retry_async(
    coro_factory,
    *,
    max_attempts: int = 5,
    base_delay_s: float = 0.1,
    max_delay_s: float = 4.0,
    multiplier: float = 2.0,
    jitter_pct: float = 0.2,
    retryable=None,
    on_retry=None,
):
    """Retry a coroutine factory with exponential backoff + jitter.

    ``coro_factory`` is a zero-argument callable returning a coroutine (pass a
    lambda/partial so each attempt gets a fresh coroutine).
    """
    retryable = retryable or (lambda exc: True)
    attempt = 0
    delay = base_delay_s
    last_error: Exception | None = None
    while attempt < max_attempts:
        attempt += 1
        try:
            return await coro_factory()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if not retryable(exc):
                raise
            if attempt >= max_attempts:
                break
            if on_retry is not None:
                on_retry(attempt, exc, delay)
            await asyncio.sleep(_jitter(delay, jitter_pct))
            delay = min(delay * multiplier, max_delay_s)
    raise RetriesExhausted(attempt, last_error)


def with_timeout(func, timeout_s: float, *, operation: str | None = None):
    """Run a *blocking sync* function under a wall-clock deadline.

    Because cooperative cancellation is impossible for a plain blocking call,
    the timeout is enforced in the *calling* thread by spawning ``func`` on a
    worker thread. Raises :class:`OperationTimeout` on expiry. Note the worker
    may keep running in the background after expiry — prefer the async variant
    when you need strong cancellation.
    """
    import threading

    result: dict = {}
    stop = threading.Event()

    def _run() -> None:
        try:
            value = func()
            result["value"] = value
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc
        finally:
            result["done"] = True

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout_s)
    if result.get("done"):
        if "error" in result:
            raise result["error"]  # type: ignore[misc]
        return result["value"]
    raise OperationTimeout(f"operation timed out after {timeout_s}s", operation=operation, timeout_s=timeout_s)


async def with_timeout_async(awaitable, timeout_s: float, *, operation: str | None = None):
    """Run an awaitable under a per-operation deadline using ``asyncio.wait_for``."""
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise OperationTimeout(f"operation timed out after {timeout_s}s", operation=operation, timeout_s=timeout_s) from exc


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


class CircuitOpenError(ResilienceError):
    """Raised when a breaker is open and refusing further calls."""


class CircuitBreaker:
    """A minimal in-process circuit breaker.

    States: ``closed`` (normal) → ``open`` (after ``failure_threshold``
    consecutive failures) → ``half_open`` (after ``recovery_timeout_s``, one
    probe attempt allowed) → back to ``closed`` (probe success) or back to
    ``open`` (probe failure).

    Not thread-safe by design; create one per upstream/call-site.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout_s: float = 30.0,
        air_lock_s: float = 0.0,
    ) -> None:
        self.name = name
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_timeout_s = max(0.0, recovery_timeout_s)
        self.air_lock_s = air_lock_s
        self.failure_count = 0
        self.state = "closed"
        self._opened_at: float | None = None
        self._last_failure: float | None = None

    def reset(self) -> None:
        self.failure_count = 0
        self.state = "closed"
        self._opened_at = None

    def can_proceed(self) -> bool:
        now = time.monotonic()
        if self.state == "open":
            if self._opened_at is not None and now - self._opened_at >= self.recovery_timeout_s:
                self.state = "half_open"  # allow one probe attempt
                return True
            return False
        return True

    def record_success(self) -> None:
        if self.failure_count:
            self.failure_count = 0
        if self.state in ("half_open", "open"):
            self.reset()

    def record_failure(self, exc: Exception | None = None) -> None:
        self._last_failure = time.monotonic()
        if self.state == "half_open":
            self.failure_count = 1
            self.state = "open"
            self._opened_at = time.monotonic()
            return
        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            self._opened_at = time.monotonic()

    @property
    def last_failure(self) -> float | None:
        return self._last_failure

    def __call__(self, func):
        """Use ``breaker(fn)(...)`` to wrap a callable with breaker semantics."""

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return self.call(func, *args, **kwargs)

        return wrapper

    def call(self, func, *args, **kwargs):
        if not self.can_proceed():
            raise CircuitOpenError(f"circuit '{self.name}' is open")
        try:
            result = func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self.record_failure(exc)
            raise
        self.record_success()
        return result

    async def call_async(self, await_func, *args, **kwargs):
        if not self.can_proceed():
            raise CircuitOpenError(f"circuit '{self.name}' is open")
        try:
            result = await await_func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self.record_failure(exc)
            raise
        self.record_success()
        return result


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

class RetryableError(ResilienceError):
    """Marker: raise (or subclass) this for exceptions that SHOULD be retried.

    ``is_retryable`` returns True for instances of this class and for messages
    that look transient. Library code that knows a failure is transient can
    raise/cause a :class:`RetryableError` to be unambiguous.
    """


_TRANSIENT_MSGS = ("temporarily", "too many", "timeout", "timed out", "503", "502", "504", "connection resp", "reset", "network is unreachable", "name or service not known")


def is_retryable(exc: Exception) -> bool:
    """Conservative guess whether ``exc`` is transient and worth retrying."""
    if isinstance(exc, RetryableError):
        return True
    msg = str(exc).lower()
    return any(token in msg for token in _TRANSIENT_MSGS)


def request_id() -> str:
    """Short correlation id for outbound calls (used as X-Request-ID)."""
    return uuid.uuid4().hex[:16]