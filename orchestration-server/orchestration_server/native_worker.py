"""Trusted bounded worker for already-registered orchestration tasks.

Stage 1: a single worker can discover pending work and drive the existing
native bridge without Hermes. Tooling, role policy, workspace and model
selection are supplied by trusted runner_factory; task data never authorizes
these capabilities. No background daemon or remote API polling is implied.
"""
from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .engine import OrchestrationEngine, _aware
from .errors import ConflictError, StateTransitionError
from .models import Task
from .native_bridge import NativeBridgeResult, Runner
from .queries import OrchestrationQueries


class RunnerFactory(Protocol):
    def __call__(self, task: Task) -> Runner: ...


@dataclass(frozen=True)
class NativeWorkerBatch:
    """One explicitly bounded pass; no implicit infinite provider polling."""

    attempts: tuple[NativeBridgeResult, ...]
    stopped_on_failure: bool


class NativeWorker:
    """Discover eligible tasks and run at most one claimed task per iteration.

    All claims, retries, statuses and JSON Schema verification stay owned by
    OrchestrationEngine. A second worker racing for the same task receives a
    conflict without invoking the model. An unavailable/idle worker performs
    no model calls at all.
    """

    def __init__(
        self,
        engine: OrchestrationEngine,
        queries: OrchestrationQueries,
        *,
        agent_id: str,
        runner_factory: RunnerFactory,
        max_runs_scan: int = 50,
        max_tasks_per_run: int = 100,
    ) -> None:
        if not agent_id or not isinstance(agent_id, str):
            raise ValueError("Trusted agent ID is required")
        if not callable(runner_factory):
            raise TypeError("Trusted runner factory is required")
        if (
            type(max_runs_scan) is not int or type(max_tasks_per_run) is not int
            or not (1 <= max_runs_scan <= 1000 and 1 <= max_tasks_per_run <= 1000)
        ):
            raise ValueError("Scan bounds must be between 1 and 1000")
        self.engine = engine
        self.queries = queries
        self.agent_id = agent_id
        self.runner_factory = runner_factory
        self.max_runs_scan = max_runs_scan
        self.max_tasks_per_run = max_tasks_per_run

    async def run_once(self) -> NativeBridgeResult | None:
        """Attempt one pending task, or return None without provider I/O.

        Retries are eligible only after the engine-owned retry_at deadline.
        Claims are atomic in the engine; a concurrently won task is skipped.
        """
        agent = await self.queries.get_agent(self.agent_id)
        if agent.status != "idle":
            return None
        now = datetime.now(timezone.utc)
        runs = await self.queries.list_runs(status="running", limit=self.max_runs_scan)
        for run in runs:
            tasks = await self.queries.list_tasks(run.id, limit=self.max_tasks_per_run)
            for task in tasks:
                if task.status != "pending":
                    continue
                retry_at = _aware(task.retry_at)
                if retry_at is not None and retry_at > now:
                    continue
                # The model is not called before engine.claim_task. The
                # runner factory only creates the trusted execution closure.
                runner = self.runner_factory(task)
                if not callable(runner):
                    raise TypeError("Trusted runner factory must return a runner")
                try:
                    return await self._run_task(task.id, runner)
                except (ConflictError, StateTransitionError):
                    # Another worker can win claim_task between discovery and
                    # reservation. Never retry that task without re-discovery.
                    continue
        return None

    async def _run_task(self, task_id: str, runner: Runner) -> NativeBridgeResult:
        from .native_bridge import run_native_task_attempt

        return await run_native_task_attempt(
            self.engine, task_id=task_id, agent_id=self.agent_id, runner=runner
        )

    async def run_batch(self, *, max_attempts: int = 1) -> NativeWorkerBatch:
        """Perform at most max_attempts, with fail-closed stop on failures.

        The caller must opt into each batch. A failed provider/contract never
        triggers a rapid quota-consuming retry loop. Engine retry and recovery
        remain authoritative and can be resumed on a later scheduled batch.
        """
        if type(max_attempts) is not int or not 1 <= max_attempts <= 100:
            raise ValueError("Batch size must be from 1 to 100")
        results: list[NativeBridgeResult] = []
        for _ in range(max_attempts):
            attempt = await self.run_once()
            if attempt is None:
                break
            results.append(attempt)
            if not attempt.verified:
                return NativeWorkerBatch(tuple(results), stopped_on_failure=True)
        return NativeWorkerBatch(tuple(results), stopped_on_failure=False)


    async def poll_bounded(
        self, *, max_polls: int = 1, interval_seconds: float = 0,
        stop_event: asyncio.Event | None = None,
    ) -> NativeWorkerBatch:
        """Opt-in bounded polling, never a detached daemon.

        Each poll claims at most one task. Idle polls do not call a provider.
        Cancellation propagates to the caller; interrupted attempts remain
        subject to explicit recovery, never implicit replay.
        """
        if type(max_polls) is not int or not 1 <= max_polls <= 100:
            raise ValueError("Poll count must be from 1 to 100")
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or not 0 <= interval_seconds <= 60
            or not math.isfinite(interval_seconds)
        ):
            raise ValueError("Poll interval must be finite and from 0 to 60 seconds")
        if stop_event is not None and not isinstance(stop_event, asyncio.Event):
            raise TypeError("Stop event must be an asyncio.Event")

        results: list[NativeBridgeResult] = []
        for index in range(max_polls):
            if stop_event is not None and stop_event.is_set():
                break
            attempt = await self.run_once()
            if attempt is not None:
                results.append(attempt)
                if not attempt.verified:
                    return NativeWorkerBatch(tuple(results), stopped_on_failure=True)
            if index + 1 < max_polls and interval_seconds:
                if stop_event is None:
                    await asyncio.sleep(interval_seconds)
                else:
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
                    except TimeoutError:
                        pass
        return NativeWorkerBatch(tuple(results), stopped_on_failure=False)
