"""Bridge between the native agent runtime and the orchestration server API.

The runtime engine (:mod:`agent_runtime.runner`) is intentionally
transport-agnostic: it executes a validated task DAG and delegates real side
effects to injected executors. This module is the *other* half of that
separation — the adapter that lets the same engine drive a real workflow run
owned by the orchestration server (``/api/v1``, ADR-101 §5.3, ADR-107):

* read the server's server-owned claimable task set,
* claim an attempt for a worker identity,
* execute the task through :class:`AgentRuntime`,
* submit the result (or fail the attempt) back to the server.

Keeping the server behind a :class:`ServerRunClient` protocol means the bridge
carries no HTTP/SDK dependency (ADR-107 R1 — the runtime stays stdlib-only) and
is unit-testable against an in-memory server, while production wires the same
protocol to the real API client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Protocol, Sequence, runtime_checkable

from .graph import TaskGraph, TaskStatus
from .runner import AgentExecutor, AgentRuntime, NodeResult

__all__ = [
    "ServerRunClient",
    "RunBridge",
    "BridgeReport",
    "graph_from_run_spec",
    "single_task_graph",
    "submission_payload",
]


@runtime_checkable
class ServerRunClient(Protocol):
    """The subset of the orchestration API the runtime needs to execute a run.

    Implemented in production by the HTTP API client; in tests by an in-memory
    fake. Every method is async so a real HTTP client is a drop-in.
    """

    async def list_ready_tasks(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Server-owned claimable tasks (``GET /workflows/ready-tasks``)."""
        ...

    async def claim_task(self, task_id: str, agent_id: str) -> dict[str, Any]:
        """Atomically claim an attempt (``POST /tasks/{id}/claim``)."""
        ...

    async def submit_task(
        self,
        task_id: str,
        attempt_id: str,
        agent_id: str,
        output: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Report a successful attempt (``POST /tasks/{id}/attempts/{aid}/submit``)."""
        ...

    async def fail_task(
        self,
        task_id: str,
        attempt_id: str,
        agent_id: str,
        error: str,
    ) -> dict[str, Any]:
        """Report a crashed/failed attempt (``POST /tasks/{id}/attempts/{aid}/fail``)."""
        ...


@dataclass
class BridgeReport:
    """What one drain of the server's ready queue accomplished."""

    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "completed": list(self.completed),
            "failed": list(self.failed),
            "skipped": list(self.skipped),
        }


def graph_from_run_spec(tasks: Sequence[Mapping[str, Any]]) -> TaskGraph:
    """Build a validated DAG from a ``POST /workflows/runs`` ``tasks[]`` payload.

    The server and the runtime must agree on what a run *is*; reusing the
    runtime's own validator here means a run the server accepts can never be a
    run the runtime rejects mid-flight.
    """
    return TaskGraph.from_spec(tasks)


def single_task_graph(
    task_id: str, title: str, *, metadata: Optional[Mapping[str, Any]] = None
) -> TaskGraph:
    """Wrap one server task as a claimable one-node graph for ``run_node``."""
    return TaskGraph.from_spec(
        [{"id": task_id, "title": title, "metadata": dict(metadata or {})}]
    )


def submission_payload(result: NodeResult) -> dict[str, Any]:
    """Map a completed node result onto the attempt-submit ``output`` body."""
    output: dict[str, Any] = dict(result.result or {})
    if result.summary:
        output.setdefault("summary", result.summary)
    return output


def failure_reason(result: NodeResult) -> str:
    """Human-readable failure reason for the attempt-fail body."""
    if result.error:
        message = result.error.get("message") or result.error.get("error_code")
        if message:
            return str(message)
    return result.summary or f"task {result.task_id} {result.status.value}"


class RunBridge:
    """Executes the orchestration server's ready tasks through the runtime.

    One ``RunBridge`` is one worker identity: it drains the server's
    claimable-task queue, executes each task with the injected
    :class:`AgentExecutor`, and reports the outcome back. The server remains the
    single source of truth (ordering, claimability, retries); the runtime never
    invents claimability for itself.
    """

    def __init__(
        self,
        *,
        runtime: AgentRuntime,
        executor: AgentExecutor,
        client: ServerRunClient,
        agent_id: str,
        role: str = "default",
        run_id: Optional[str] = None,
        max_tasks: int = 100,
    ) -> None:
        if not agent_id:
            raise ValueError("agent_id is required")
        self.runtime = runtime
        self.executor = executor
        self.client = client
        self.agent_id = agent_id
        self.role = role
        self.run_id = run_id
        self.max_tasks = max_tasks

    async def run_ready(self, *, limit: int = 20) -> BridgeReport:
        """Drain the ready queue until it is empty (or ``max_tasks`` reached)."""
        report = BridgeReport()
        processed = 0
        while processed < self.max_tasks:
            ready = await self.client.list_ready_tasks(limit=limit)
            if self.run_id is not None:
                ready = [t for t in ready if t.get("run_id") == self.run_id]
            if not ready:
                break
            progressed = False
            for task in ready:
                if processed >= self.max_tasks:
                    break
                task_id = str(task["task_id"])
                if (
                    task_id in report.completed
                    or task_id in report.failed
                    or task_id in report.skipped
                ):
                    continue
                if await self._execute_one(task, report):
                    processed += 1
                    progressed = True
            if not progressed:
                # Ready set contains only tasks we already handled; stop rather
                # than spin (the server has not advanced, e.g. a retry window).
                break
        return report

    async def _execute_one(self, task: Mapping[str, Any], report: BridgeReport) -> bool:
        """Execute one ready task. Returns ``False`` when the claim was skipped."""
        task_id = str(task["task_id"])
        claim = await self.client.claim_task(task_id, self.agent_id)
        attempt_id = claim.get("id") if isinstance(claim, Mapping) else None
        if not attempt_id:
            # A raced/lost claim (another worker won, or the server declined the
            # attempt) returns no attempt id. The task remains ready on the
            # server, so record it as skipped for this drain and move on instead
            # of aborting the whole loop with a KeyError.
            report.skipped.append(task_id)
            return False
        attempt_id = str(attempt_id)
        graph = single_task_graph(
            task_id, str(task.get("title") or task_id), metadata={"role": self.role}
        )
        result = await self.runtime.run_node(graph, task_id, self.executor)
        if result.status is TaskStatus.COMPLETED:
            await self.client.submit_task(
                task_id, attempt_id, self.agent_id, submission_payload(result)
            )
            report.completed.append(task_id)
        else:
            await self.client.fail_task(
                task_id, attempt_id, self.agent_id, failure_reason(result)
            )
            report.failed.append(task_id)
        return True
