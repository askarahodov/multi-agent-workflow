"""Retry, timeout, circuit breaker and checkpoint/restore (ADR-104).

Long-running agent runs must survive a worker crash without redoing completed
turns. This module persists a run's turn state and can reconstruct the exact
resume point, so ``resume_run`` continues from ``last_completed_turn + 1``.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

from .errors import ErrorKind, PlatformError, is_retryable
from .limits import Budget, BudgetState

# ---------------------------------------------------------------------------
# Retry / timeout
# ---------------------------------------------------------------------------


def _jitter(delay_s: float, jitter_pct: float) -> float:
    if jitter_pct <= 0:
        return delay_s
    span = delay_s * jitter_pct
    return max(0.0, delay_s + random.uniform(-span, span))


async def retry_async(
    coro_factory: Callable[[], Awaitable[Any]],
    *,
    max_attempts: int = 3,
    base_delay_s: float = 0.1,
    max_delay_s: float = 4.0,
    multiplier: float = 2.0,
    jitter_pct: float = 0.2,
    retryable: Optional[Callable[[BaseException], bool]] = None,
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Any:
    """Call *coro_factory* with exponential backoff + jitter.

    ``retryable`` decides which exceptions are transient (default:
    :func:`agent_runtime.errors.is_retryable`). Non-retryable exceptions and the
    final failed attempt are re-raised unchanged.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")
    predicate = retryable or is_retryable
    attempt = 0
    delay = base_delay_s
    last_error: Optional[BaseException] = None
    while attempt < max_attempts:
        attempt += 1
        try:
            return await coro_factory()
        except BaseException as exc:  # noqa: BLE001 - classify via predicate
            last_error = exc
            if not predicate(exc):
                raise
            if attempt >= max_attempts:
                break
            wait = _jitter(delay, jitter_pct)
            if on_retry is not None:
                on_retry(attempt, exc, wait)
            await sleep(wait)
            delay = min(delay * multiplier, max_delay_s)
    assert last_error is not None
    raise last_error


async def with_timeout(
    coro: Awaitable[Any],
    *,
    timeout_s: float,
    operation: str = "operation",
    kind: ErrorKind = ErrorKind.TOOL_TIMEOUT,
) -> Any:
    """Await *coro* under a deadline, raising :class:`PlatformError` on expiry."""
    try:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise PlatformError(
            kind,
            f"{operation} timed out after {timeout_s}s",
            context={"operation": operation, "timeout_s": timeout_s},
        ) from exc


# ---------------------------------------------------------------------------
# Circuit breaker (ADR-104 §3.5)
# ---------------------------------------------------------------------------


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Single-host in-process breaker so a failing upstream does not cascade."""

    def __init__(
        self,
        service_name: str,
        *,
        failure_threshold: int = 5,
        reset_timeout_s: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.reset_timeout_s = reset_timeout_s
        self._clock = clock
        self.failure_count = 0
        self.last_failure: Optional[float] = None
        self.state = CircuitState.CLOSED

    def _maybe_half_open(self) -> None:
        if (
            self.state is CircuitState.OPEN
            and self.last_failure is not None
            and self._clock() - self.last_failure > self.reset_timeout_s
        ):
            self.state = CircuitState.HALF_OPEN

    async def call(self, func: Callable[[], Awaitable[Any]]) -> Any:
        self._maybe_half_open()
        if self.state is CircuitState.OPEN:
            from .errors import gate_unavailable

            raise gate_unavailable(self.service_name, "circuit open")
        try:
            result = await func()
        except BaseException:  # noqa: BLE001
            self._on_failure()
            raise
        self._on_success()
        return result

    def _on_success(self) -> None:
        self.failure_count = 0
        self.last_failure = None
        self.state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        self.failure_count += 1
        self.last_failure = self._clock()
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN


# ---------------------------------------------------------------------------
# Checkpoint / restore (ADR-104 §3.4)
# ---------------------------------------------------------------------------


class RunStatus(str, Enum):
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    TERMINATED = "terminated"


@dataclass
class TurnState:
    turn_number: int
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    result: str = "success"  # success | blocked | approval_required | error
    started_at: str = ""
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentRunState:
    run_id: str
    task_id: str
    agent_instance_id: str
    status: RunStatus = RunStatus.RUNNING
    current_turn: int = 0
    last_completed_turn: int = 0
    budget_state: dict[str, Any] = field(default_factory=lambda: BudgetState().to_dict())
    messages: list[dict[str, Any]] = field(default_factory=list)
    turns: list[dict[str, Any]] = field(default_factory=list)
    error: Optional[dict[str, Any]] = None
    spec_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "agent_instance_id": self.agent_instance_id,
            "status": self.status.value,
            "current_turn": self.current_turn,
            "last_completed_turn": self.last_completed_turn,
            "budget_state": self.budget_state,
            "messages": self.messages,
            "turns": self.turns,
            "error": self.error,
            "spec_version": self.spec_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AgentRunState":
        return cls(
            run_id=data["run_id"],
            task_id=data["task_id"],
            agent_instance_id=data["agent_instance_id"],
            status=RunStatus(data.get("status", RunStatus.RUNNING.value)),
            current_turn=int(data.get("current_turn", 0)),
            last_completed_turn=int(data.get("last_completed_turn", 0)),
            budget_state=dict(data.get("budget_state", {})),
            messages=list(data.get("messages", [])),
            turns=list(data.get("turns", [])),
            error=dict(data["error"]) if data.get("error") else None,
            spec_version=data.get("spec_version", ""),
        )


class CheckpointStore:
    """Durable checkpoint store for agent runs.

    Backed by a directory of JSON files (one per run) so a crashed worker's
    state survives on disk. An in-memory-only mode (``directory=None``) is used
    in unit tests.
    """

    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = Path(directory) if directory is not None else None
        if self.directory is not None:
            self.directory.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, AgentRunState] = {}

    def _path(self, run_id: str) -> Path:
        assert self.directory is not None
        return self.directory / f"{run_id}.json"

    def create(self, task_id: str, agent_instance_id: str, *, spec_version: str = "") -> AgentRunState:
        run = AgentRunState(
            run_id=f"run-{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            agent_instance_id=agent_instance_id,
            spec_version=spec_version,
        )
        self.save(run)
        return run

    def save(self, run: AgentRunState) -> None:
        self._mem[run.run_id] = run
        if self.directory is not None:
            self._path(run.run_id).write_text(
                json.dumps(run.to_dict(), sort_keys=True, indent=2), encoding="utf-8"
            )

    def load(self, run_id: str) -> AgentRunState:
        if run_id in self._mem:
            return self._mem[run_id]
        if self.directory is not None and self._path(run_id).exists():
            data = json.loads(self._path(run_id).read_text(encoding="utf-8"))
            run = AgentRunState.from_dict(data)
            self._mem[run_id] = run
            return run
        raise PlatformError(ErrorKind.NOT_FOUND, f"no checkpoint for run {run_id!r}")

    # -- turn recording ----------------------------------------------------
    def record_turn(
        self,
        run: AgentRunState,
        *,
        messages: Sequence[Mapping[str, Any]],
        tool_calls: Sequence[Mapping[str, Any]] = (),
        result: str = "success",
        budget: Optional[BudgetState] = None,
    ) -> TurnState:
        turn_number = run.current_turn + 1
        turn = TurnState(
            turn_number=turn_number,
            messages=[dict(m) for m in messages],
            tool_calls=[dict(t) for t in tool_calls],
            result=result,
            completed_at=_now(),
        )
        run.current_turn = turn_number
        run.last_completed_turn = turn_number
        run.messages = [dict(m) for m in messages]
        run.turns.append(turn.to_dict())
        if budget is not None:
            run.budget_state = budget.to_dict()
        self.save(run)
        return turn


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def resume_point(run: AgentRunState) -> int:
    """Return the next turn number to execute for a resumable run."""
    if run.status not in (RunStatus.RUNNING, RunStatus.BLOCKED):
        raise PlatformError(
            ErrorKind.VALIDATION_ERROR,
            f"cannot resume run in status {run.status.value!r}",
            context={"run_id": run.run_id, "status": run.status.value},
        )
    return run.last_completed_turn + 1


def restore_budget(run: AgentRunState) -> BudgetState:
    """Reconstruct a :class:`BudgetState` from a checkpointed run."""
    data = run.budget_state or {}
    state = BudgetState(
        steps_used=int(data.get("steps_used", 0)),
        tokens_used=int(data.get("tokens_used", 0)),
        cost_usd=float(data.get("cost_usd", 0.0)),
        time_elapsed_ms=int(data.get("time_elapsed_ms", 0)),
    )
    return state


async def resume_run(
    run: AgentRunState,
    *,
    budget: Budget,
    turn_runner: Callable[[AgentRunState, int], Awaitable[Any]],
) -> Any:
    """Resume a run from its last completed turn (ADR-104 §3.4 recovery algorithm).

    ``turn_runner`` is invoked with ``(run, next_turn_number)`` and is responsible
    for executing exactly one turn and checkpointing it.
    """
    next_turn = resume_point(run)
    restored = restore_budget(run)
    if not restored.check(budget).ok:
        from .errors import budget_exhausted

        raise budget_exhausted(list(restored.check(budget).violations))
    return await turn_runner(run, next_turn)
