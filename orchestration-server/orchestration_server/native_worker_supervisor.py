"""Finite, cooperative supervisor for a trusted native HTTP worker.

This component is a *control loop*, not a runnable production daemon:
- no provider credentials, dynamic imports, shell or Git
- no implicit background task or infinite LLM spending
- all polls and execution attempts are explicitly bounded
- first failure stops processing; no quota-wall retry spin
- stopping is cooperative, without swallowing CancelledError
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Protocol

from .native_http_worker import RemoteWorkerBatch


class BatchWorker(Protocol):
    async def run_batch(self, *, max_attempts: int = 1) -> RemoteWorkerBatch: ...


@dataclass(frozen=True)
class SupervisorReport:
    polls: int
    completed_attempts: int
    failed_attempts: int
    reason: str


class NativeWorkerSupervisor:
    """Explicit finite polling, cooperative shutdown and stop-on-failure."""

    def __init__(
        self,
        worker: BatchWorker,
        *,
        max_polls: int = 1,
        max_attempts_per_poll: int = 1,
        poll_interval_seconds: float = 5.0,
    ) -> None:
        if type(max_polls) is not int or not 1 <= max_polls <= 1_000:
            raise ValueError("Supervisor max_polls must be between 1 and 1000")
        if type(max_attempts_per_poll) is not int or not 1 <= max_attempts_per_poll <= 100:
            raise ValueError("Supervisor batch must be between 1 and 100")
        if (
            isinstance(poll_interval_seconds, bool)
            or not isinstance(poll_interval_seconds, (int, float))
            or (isinstance(poll_interval_seconds, float) and not math.isfinite(poll_interval_seconds))
            or not 0.01 <= poll_interval_seconds <= 3_600
        ):
            raise ValueError("Supervisor poll interval must be 0.01..3600 seconds")
        if not callable(getattr(worker, "run_batch", None)):
            raise TypeError("Trusted batch worker required")
        self.worker = worker
        self.max_polls = max_polls
        self.max_attempts_per_poll = max_attempts_per_poll
        self.poll_interval_seconds = poll_interval_seconds

    async def run(self, stop_event: asyncio.Event) -> SupervisorReport:
        """Run at most max_polls with no hidden retry after a failed attempt.

        A cancelled task raises CancelledError; orphaned engine attempts are
        reconciled by the separate safe-recovery workflow (#36/#38).
        """
        if not isinstance(stop_event, asyncio.Event):
            raise TypeError("An explicit shutdown signal is required")
        polls = 0
        completed = 0
        failed = 0

        for i in range(self.max_polls):
            if stop_event.is_set():
                return SupervisorReport(polls, completed, failed, "STOPPED")
            # Any transport/DB exception propagates: never silently consume
            # an error and keep spending provider quota in the next poll.
            batch = await self.worker.run_batch(
                max_attempts=self.max_attempts_per_poll,
            )
            polls += 1
            completed += sum(bool(x.verified) for x in batch.attempts)
            failed += sum(not x.verified for x in batch.attempts)
            if batch.stopped_on_failure or failed:
                return SupervisorReport(polls, completed, failed, "FAIL_CLOSED")
            if i + 1 < self.max_polls:
                try:
                    await asyncio.wait_for(
                        stop_event.wait(), timeout=self.poll_interval_seconds,
                    )
                except TimeoutError:
                    pass
                else:
                    return SupervisorReport(polls, completed, failed, "STOPPED")

        return SupervisorReport(polls, completed, failed, "POLL_LIMIT")
