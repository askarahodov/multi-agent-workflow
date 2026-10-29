"""Server bridge: the runtime executes the orchestration server's ready tasks.

The bridge is the seam between the transport-agnostic engine and the real
workflow API. These tests drive a genuine :class:`AgentRuntime` (real DAG,
real workspace provisioning, real permission checks) against an in-memory
stand-in that reproduces the server's claim/submit/fail contract, proving the
runtime can execute a run end to end without any HTTP dependency.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from agent_runtime.errors import ErrorKind, PlatformError
from agent_runtime.graph import TaskGraph, TaskStatus
from agent_runtime.runner import AgentRuntime, NodeOutcome
from agent_runtime.server_bridge import (
    BridgeReport,
    RunBridge,
    failure_reason,
    graph_from_run_spec,
    single_task_graph,
    submission_payload,
)
from agent_runtime.workspace import WorkspaceKind, WorkspaceManager


def make_workspaces(tmp_path):
    return WorkspaceManager(tmp_path / "ws")


async def _echo_tool(action, resource, params, workspace):
    return {"action": action, "resource": resource}


class FakeServer:
    """In-memory orchestration server implementing the bridge's contract."""

    def __init__(self, run_id: str, tasks: list[dict[str, Any]]):
        self.run_id = run_id
        self.tasks = {t["task_id"]: {**t, "status": "pending"} for t in tasks}
        self._attempts = 0
        self.submissions: dict[str, Mapping[str, Any]] = {}
        self.failures: dict[str, str] = {}
        self.claims: list[str] = []

    def _ready(self) -> list[dict[str, Any]]:
        ready = []
        for task in self.tasks.values():
            if task["status"] != "pending":
                continue
            deps = task.get("depends_on", [])
            if all(self.tasks[d]["status"] == "completed" for d in deps):
                ready.append(task)
        return ready

    async def list_ready_tasks(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return [
            {
                "task_id": t["task_id"],
                "run_id": t.get("run_id", self.run_id),
                "title": t["title"],
            }
            for t in self._ready()[:limit]
        ]

    async def claim_task(self, task_id: str, agent_id: str) -> dict[str, Any]:
        assert self.tasks[task_id]["status"] == "pending"
        self.tasks[task_id]["status"] = "running"
        self._attempts += 1
        self.claims.append(task_id)
        return {"id": f"attempt-{self._attempts}", "task_id": task_id, "agent_id": agent_id}

    async def submit_task(
        self, task_id: str, attempt_id: str, agent_id: str, output: Mapping[str, Any]
    ) -> dict[str, Any]:
        self.tasks[task_id]["status"] = "completed"
        self.submissions[task_id] = dict(output)
        return {"id": attempt_id, "task_id": task_id, "status": "completed"}

    async def fail_task(
        self, task_id: str, attempt_id: str, agent_id: str, error: str
    ) -> dict[str, Any]:
        self.tasks[task_id]["status"] = "failed"
        self.failures[task_id] = error
        return {"id": attempt_id, "task_id": task_id, "status": "failed"}


def build_bridge(tmp_path, profiles, client, executor, **kw) -> RunBridge:
    runtime = AgentRuntime(
        profiles=profiles,
        workspaces=make_workspaces(tmp_path),
        tool_executor=_echo_tool,
        workspace_kind=WorkspaceKind.SCRATCH,
    )
    return RunBridge(runtime=runtime, executor=executor, client=client, agent_id="worker-1", **kw)


async def test_bridge_drains_dependent_tasks_in_order(tmp_path, profiles):
    server = FakeServer(
        "run-1",
        [
            {"task_id": "t-a", "title": "Research"},
            {"task_id": "t-b", "title": "Build", "depends_on": ["t-a"]},
        ],
    )
    order: list[str] = []

    async def executor(inv):
        order.append(inv.node.title)
        return NodeOutcome(result={"ok": True}, summary=f"done {inv.node.title}")

    bridge = build_bridge(tmp_path, profiles, server, executor, run_id="run-1")
    report = await bridge.run_ready()

    assert report.completed == ["t-a", "t-b"]
    assert report.failed == []
    assert order == ["Research", "Build"]  # server ordering honoured
    assert server.submissions["t-a"]["summary"] == "done Research"


async def test_bridge_reports_executor_crash_as_failure(tmp_path, profiles):
    server = FakeServer("run-1", [{"task_id": "t-1", "title": "Flaky"}])

    async def executor(inv):
        raise PlatformError(ErrorKind.ISOLATION_UNAVAILABLE, "worker process exited")

    bridge = build_bridge(tmp_path, profiles, server, executor, run_id="run-1")
    report = await bridge.run_ready()

    assert report.completed == []
    assert report.failed == ["t-1"]
    assert "worker process exited" in server.failures["t-1"]
    # The runtime never faked a success for the crashed attempt.
    assert "t-1" not in server.submissions


async def test_bridge_ignores_other_runs(tmp_path, profiles):
    server = FakeServer("run-1", [{"task_id": "t-1", "title": "Mine"}])
    # A second run's ready task must not be claimed by this bridge.
    server.tasks["other-1"] = {
        "task_id": "other-1",
        "title": "Not mine",
        "run_id": "other-run",
        "status": "pending",
        "depends_on": [],
    }

    async def executor(inv):
        return NodeOutcome(result={}, summary="ok")

    bridge = build_bridge(tmp_path, profiles, server, executor, run_id="run-1")
    report = await bridge.run_ready()

    assert report.completed == ["t-1"]
    assert "other-1" not in server.claims


async def test_bridge_stops_when_no_progress(tmp_path, profiles):
    """A ready set the bridge already handled must not spin forever."""

    class StickyServer(FakeServer):
        async def list_ready_tasks(self, *, limit: int = 20):
            return [{"task_id": "t-1", "run_id": "run-1", "title": "X"}]

    sticky = StickyServer("run-1", [{"task_id": "t-1", "title": "X"}])

    async def terminal_executor(inv):
        return NodeOutcome(result={}, summary="ok")

    bridge = build_bridge(tmp_path, profiles, sticky, terminal_executor, run_id="run-1")
    report = await bridge.run_ready()
    # Executed exactly once, then the loop stops (no infinite spin).
    assert report.completed == ["t-1"]
    assert len(sticky.claims) == 1


def test_graph_from_run_spec_matches_server_payload():
    graph = graph_from_run_spec(
        [
            {"title": "A"},
            {"title": "B", "depends_on": [0]},
        ]
    )
    assert isinstance(graph, TaskGraph)
    assert graph.nodes[1].depends_on == (0,)
    ready = graph.ready_ids()
    assert len(ready) == 1  # only A is claimable


def test_graph_from_run_spec_rejects_cycle():
    with pytest.raises(PlatformError):
        graph_from_run_spec([{"title": "A", "depends_on": [1]}, {"title": "B", "depends_on": [0]}])


def test_single_task_graph_and_payload_helpers():
    graph = single_task_graph("t-9", "Title", metadata={"role": "developer"})
    assert graph.nodes[0].id == "t-9"
    assert graph.nodes[0].status is TaskStatus.PENDING
    assert graph.claimable("t-9")[0] is True

    from agent_runtime.runner import NodeResult

    completed = NodeResult(task_id="t-9", status=TaskStatus.COMPLETED, result={"a": 1}, summary="s")
    assert submission_payload(completed) == {"a": 1, "summary": "s"}

    failed = NodeResult(
        task_id="t-9",
        status=TaskStatus.FAILED,
        error={"error_code": "X", "message": "boom"},
        summary="",
    )
    assert failure_reason(failed) == "boom"
    assert BridgeReport(completed=["a"]).to_dict() == {
        "completed": ["a"],
        "failed": [],
        "skipped": [],
    }
