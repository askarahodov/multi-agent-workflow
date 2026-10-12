"""Tests for tools.resilience (task item (f)): retries, backoffs, timeouts,
circuit breaker, and classification helpers."""

from __future__ import annotations

import asyncio
import time

import pytest

from tools.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    OperationTimeout,
    RetriesExhausted,
    RetryableError,
    is_retryable,
    request_id,
    retry,
    retry_async,
    with_timeout,
    with_timeout_async,
)


def test_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RetryableError("temporary failure")
        return "ok"

    assert retry(flaky, max_attempts=5, base_delay_s=0.01) == "ok"
    assert calls["n"] == 3


def test_retry_exhausts_attempts():
    calls = {"n": 0}

    def always():
        calls["n"] += 1
        raise RetryableError("nope")

    with pytest.raises(RetriesExhausted) as excinfo:
        retry(always, max_attempts=4, base_delay_s=0.01, jitter_pct=0)
    assert excinfo.value.attempts == 4
    assert calls["n"] == 4


def test_retry_respects_non_retryable():
    calls = {"n": 0}

    def fatal():
        calls["n"] += 1
        raise ValueError("permanent")

    with pytest.raises(ValueError):
        retry(fatal, max_attempts=5, base_delay_s=0.01, jitter_pct=0, retryable=lambda exc: not isinstance(exc, ValueError))
    assert calls["n"] == 1


async def test_retry_async_succeeds():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RetryableError("temporary")
        return "done"

    assert await retry_async(flaky, max_attempts=4, base_delay_s=0.01) == "done"
    assert calls["n"] == 2


async def test_with_timeout_async_expires():
    async def slow():
        await asyncio.sleep(5)

    with pytest.raises(OperationTimeout):
        await with_timeout_async(slow(), 0.1)


def test_with_timeout_sync_expires():
    with pytest.raises(OperationTimeout):
        with_timeout(lambda: time.sleep(5), 0.1)


def test_with_timeout_sync_returns_value():
    assert with_timeout(lambda: 42, 1.0) == 42


def test_circuit_breaker_opens_and_stays_open_within_recovery():
    breaker = CircuitBreaker("up", failure_threshold=3, recovery_timeout_s=3600)
    calls = {"n": 0}

    def fail():
        calls["n"] += 1
        raise RetryableError("boom")

    for _ in range(3):
        with pytest.raises(RetryableError):
            breaker.call(fail)
    assert breaker.state == "open"
    with pytest.raises(CircuitOpenError):
        breaker.call(fail)
    assert calls["n"] == 3  # open circuit never reached the underlying call


def test_circuit_breaker_success_resets():
    breaker = CircuitBreaker("up", failure_threshold=2)
    ok = {"v": 0}

    def flaky():
        ok["v"] += 1
        if ok["v"] < 2:
            raise RetryableError("boom")
        return "ok"

    with pytest.raises(RetryableError):
        breaker.call(flaky)
    assert breaker.failure_count == 1
    assert breaker.call(flaky) == "ok"
    assert breaker.state == "closed"
    assert breaker.failure_count == 0


def test_circuit_breaker_wrapper_decorator():
    breaker = CircuitBreaker("fn", failure_threshold=2, recovery_timeout_s=3600)
    calls = {"n": 0}

    @breaker
    def guarded():
        calls["n"] += 1
        raise RetryableError("boom")

    for _ in range(2):
        with pytest.raises(RetryableError):
            guarded()
    with pytest.raises(CircuitOpenError):
        guarded()


def test_is_retryable_classification():
    assert is_retryable(RetryableError("x"))
    assert is_retryable(ConnectionError("connection reset by peer"))
    assert is_retryable(TimeoutError("operation timed out"))
    assert not is_retryable(ValueError("invalid value"))


def test_request_id_shape():
    rid = request_id()
    assert isinstance(rid, str)
    assert len(rid) == 16