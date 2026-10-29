"""End-to-end engine tests: DAG execution, parallelism, gating, budgets, recovery."""

from __future__ import annotations

import asyncio

import pytest

from agent_runtime.errors import ErrorKind, PlatformError
from agent_runtime.graph import TaskGraph, TaskStatus
from agent_runtime.limits import GateConfig, GateResult, GateRunner, GateStatus
from agent_runtime.retry import CheckpointStore, RunStatus
from agent_runtime.runner import AgentRuntime, NodeOutcome
from agent_runtime.spec import AgentInstance, ProfileManager
from agent_runtime.workspace import WorkspaceKind, WorkspaceManager

from conftest import build_store as _build_store  # reuse the fixture builder


def make_runtime(tmp_path, profiles, tool_executor, *, gates=None, gate_config=None, kind=WorkspaceKind.SCRATCH, **kw):
    workspaces = WorkspaceManager(tmp_path / "ws")
    return AgentRuntime(
        profiles=profiles,
        workspaces=workspaces,
        tool_executor=tool_executor,
        gates=gates,
        gate_config=gate_config,
        workspace_kind=kind,
        **kw,
    )


async def _echo_tool(action, resource, params, workspace):
    return {"action": action, "resource": resource}


def _success_executor(order: list[str] | None = None):
    async def executor(inv):
        await inv.execute_tool("fs_read", "workspace/main.py")
        if order is not None:
            order.append(f"start:{inv.node.title}")
        return NodeOutcome(result={"ok": True}, summary=f"done {inv.node.title}", steps=1, tokens=5, cost_usd=0.01)

    return executor


async def test_chain_completes_and_passes_upstream(tmp_path, profiles):
    graph = TaskGraph.from_spec(
        [
            {"title": "Research"},
            {"title": "Architecture", "depends_on": [0]},
            {"title": "Implementation", "depends_on": [1]},
        ]
    )
    runtime = make_runtime(tmp_path, profiles, _echo_tool)
    result = await runtime.run_graph(graph, _success_executor())

    assert set(result.completed) == {n.id for n in graph.nodes}
    assert result.failed == [] and result.blocked == []
    # upstream handoff propagated to each dependent
    assert graph.nodes[1].upstream == [{"prev_task_id": graph.nodes[0].id, "summary": "done Research"}]
    assert graph.nodes[2].upstream[0]["summary"] == "done Architecture"


async def test_independent_tasks_run_in_parallel(tmp_path, profiles):
    graph = TaskGraph.from_spec([{"title": "A"}, {"title": "B"}, {"title": "C"}])
    runtime = make_runtime(tmp_path, profiles, _echo_tool)
    live = {"now": 0, "max": 0}

    async def executor(inv):
        live["now"] += 1
        live["max"] = max(live["max"], live["now"])
        await asyncio.sleep(0.05)
        live["now"] -= 1
        return NodeOutcome(result={}, summary="ok")

    result = await runtime.run_graph(graph, executor, max_parallelism=3)
    assert len(result.completed) == 3
    assert live["max"] >= 2  # genuinely concurrent


async def test_dependent_waits_for_prerequisite(tmp_path, profiles):
    graph = TaskGraph.from_spec([{"title": "Research"}, {"title": "Architecture", "depends_on": [0]}])
    runtime = make_runtime(tmp_path, profiles, _echo_tool)
    order: list[str] = []

    async def executor(inv):
        order.append(inv.node.title)
        await asyncio.sleep(0.01)
        return NodeOutcome(result={}, summary=f"done {inv.node.title}")

    await runtime.run_graph(graph, executor)
    assert order.index("Research") < order.index("Architecture")


async def test_permission_denied_fails_node(tmp_path, profiles):
    graph = TaskGraph.from_spec([{"title": "Bad"}])
    runtime = make_runtime(tmp_path, profiles, _echo_tool)

    async def executor(inv):
        # fs_write to /etc is outside the policy allow-list -> denied.
        await inv.execute_tool("fs_write", "/etc/passwd")
        return NodeOutcome()

    result = await runtime.run_graph(graph, executor)
    node_result = result.nodes[graph.nodes[0].id]
    assert node_result.status is TaskStatus.FAILED
    assert node_result.error["error_code"] == ErrorKind.TOOL_POLICY_DENIED.code
    assert any(e.type == "tool.call" and e.payload.get("allowed") is False for e in runtime.bus.events)


async def test_budget_exhaustion_fails_node(tmp_path):
    store = _build_store()
    store.add_instance(
        AgentInstance(
            id="inst-1",
            definition_id="def-1",
            model_profile_id="mp-1",
            tool_policy_id="dev",
            config={"budget": {"max_steps": 0, "max_tokens": 0, "max_cost_usd": 0, "max_wall_time_ms": 0}},
        )
    )
    from agent_runtime.spec import ProfileManager

    profiles = ProfileManager(store)
    graph = TaskGraph.from_spec([{"title": "T", "metadata": {"agent_instance_id": "inst-1"}}])
    runtime = make_runtime(tmp_path, profiles, _echo_tool)
    result = await runtime.run_graph(graph, _success_executor())
    node_result = result.nodes[graph.nodes[0].id]
    assert node_result.status is TaskStatus.FAILED
    assert node_result.error["error_code"] == ErrorKind.BUDGET_EXHAUSTED.code


async def test_quality_gate_failure_blocks_instead_of_completing(tmp_path, profiles):
    graph = TaskGraph.from_spec([{"title": "T"}])
    gates = GateRunner({"tester": lambda n, p: GateResult(n, GateStatus.FAILED, ("coverage low",))})
    runtime = make_runtime(
        tmp_path, profiles, _echo_tool, gates=gates, gate_config=GateConfig(required_gates=("tester",))
    )
    result = await runtime.run_graph(graph, _success_executor())
    node_result = result.nodes[graph.nodes[0].id]
    assert node_result.status is TaskStatus.BLOCKED
    assert graph.nodes[0].status is TaskStatus.BLOCKED
    assert any(e.type == "gate.evaluated" and e.payload["gate"] == "tester" for e in runtime.bus.events)


async def test_quality_gate_unavailable_blocks_fail_closed(tmp_path, profiles):
    graph = TaskGraph.from_spec([{"title": "T"}])
    runtime = make_runtime(
        tmp_path, profiles, _echo_tool, gate_config=GateConfig(required_gates=("security",))
    )
    result = await runtime.run_graph(graph, _success_executor())
    assert result.nodes[graph.nodes[0].id].status is TaskStatus.BLOCKED


async def test_transient_error_is_retried(tmp_path, profiles):
    graph = TaskGraph.from_spec([{"title": "T"}])
    runtime = make_runtime(tmp_path, profiles, _echo_tool)
    attempts = {"n": 0}

    async def executor(inv):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise PlatformError(ErrorKind.PROVIDER_SERVER, "upstream 500")
        return NodeOutcome(result={"ok": True}, summary="done")

    result = await runtime.run_graph(graph, executor)
    assert result.nodes[graph.nodes[0].id].status is TaskStatus.COMPLETED
    assert attempts["n"] == 2
    assert any(e.type == "agent.run.retry" for e in runtime.bus.events)


async def test_workspaces_are_released_after_run(tmp_path, profiles):
    graph = TaskGraph.from_spec([{"title": "T"}])
    runtime = make_runtime(tmp_path, profiles, _echo_tool)
    await runtime.run_graph(graph, _success_executor())
    assert runtime.workspaces.active_for_task(graph.nodes[0].id) is None


async def test_worktree_without_repo_fails_closed(tmp_path, profiles):
    graph = TaskGraph.from_spec([{"title": "T"}])
    runtime = make_runtime(tmp_path, profiles, _echo_tool, kind=WorkspaceKind.WORKTREE)
    result = await runtime.run_graph(graph, _success_executor())
    node_result = result.nodes[graph.nodes[0].id]
    assert node_result.status is TaskStatus.FAILED
    assert node_result.error["error_code"] == ErrorKind.ISOLATION_UNAVAILABLE.code


async def test_resume_node_continues_from_checkpoint(tmp_path, profiles):
    workspaces = WorkspaceManager(tmp_path / "ws")
    checkpoints = CheckpointStore(tmp_path / "ckpt")
    runtime = AgentRuntime(
        profiles=profiles,
        workspaces=workspaces,
        tool_executor=_echo_tool,
        checkpoints=checkpoints,
        workspace_kind=WorkspaceKind.SCRATCH,
    )
    graph = TaskGraph.from_spec([{"title": "T"}])
    run = checkpoints.create(graph.nodes[0].id, "inst-1")
    checkpoints.record_turn(run, messages=[{"role": "user", "content": "step 1"}])

    seen = {}

    async def executor(inv):
        seen["last_completed_turn"] = inv.run.last_completed_turn
        return NodeOutcome(result={"ok": True}, summary="resumed")

    result = await runtime.resume_node(graph, graph.nodes[0].id, run.run_id, executor)
    assert result.status is TaskStatus.COMPLETED
    assert seen["last_completed_turn"] == 1


async def test_run_node_refuses_unclaimable_task(tmp_path, profiles):
    graph = TaskGraph.from_spec([{"title": "A"}, {"title": "B", "depends_on": [0]}])
    runtime = make_runtime(tmp_path, profiles, _echo_tool)
    with pytest.raises(PlatformError) as exc:
        await runtime.run_node(graph, graph.nodes[1].id, _success_executor())
    assert exc.value.kind is ErrorKind.CLAIM_DENIED
