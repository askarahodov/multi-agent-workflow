"""The agent execution engine (ADR-011 / ADR-107 / ADR-109).

:class:`AgentRuntime` is the single entry point that ties the whole autonomy
framework together:

* resolve an immutable :class:`AgentSpec` (role/tool/model/context/permission),
* provision an isolated workspace per task,
* execute a task DAG with bounded parallelism and contract-gated result passing,
* enforce tool permissions, budgets and quality gates (fail-closed),
* retry transient failures, persist turn checkpoints and resume after a crash,
* emit structured logs, events and metrics at every step.

The engine is deliberately transport-agnostic: the model turn loop and the
actual tool side effects are injected, so the framework is unit-testable without
network, Docker or a provider.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

from .errors import (
    ErrorKind,
    ErrorRecord,
    PlatformError,
    budget_exhausted,
    policy_denied,
)
from .graph import TaskGraph, TaskNode, TaskStatus
from .limits import (
    Budget,
    BudgetState,
    GateConfig,
    GateRunner,
    GateStatus,
)
from .observability import Event, EventBus, MetricsRegistry, StructuredLogger, correlation, new_id
from .permissions import PermissionEvaluator, ToolPolicy
from .retry import AgentRunState, CheckpointStore, RunStatus, retry_async, with_timeout
from .spec import AgentSpec, ProfileManager, build_model_context
from .workspace import Workspace, WorkspaceKind, WorkspaceManager

# Injected side-effect executor: (action, resource, params, workspace) -> dict
ToolExecutor = Callable[[str, str, Mapping[str, Any], Workspace], Awaitable[Any]]


@dataclass
class NodeInvocation:
    """Everything an agent turn loop needs to execute one task node."""

    node: TaskNode
    spec: AgentSpec
    workspace: Workspace
    run: AgentRunState
    permissions: PermissionEvaluator
    budget_state: BudgetState
    messages: list[dict[str, Any]]
    execute_tool: Callable[..., Awaitable[Any]]
    logger: StructuredLogger
    bus: EventBus
    checkpoints: CheckpointStore


@dataclass
class NodeOutcome:
    result: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    tokens: int = 0
    cost_usd: float = 0.0
    steps: int = 0
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


#: Injected agent turn loop: executes one node and returns its outcome.
AgentExecutor = Callable[[NodeInvocation], Awaitable[NodeOutcome]]


@dataclass
class NodeResult:
    task_id: str
    status: TaskStatus
    result: Optional[dict[str, Any]] = None
    summary: str = ""
    error: Optional[dict[str, Any]] = None
    steps: int = 0
    workspace_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "summary": self.summary,
            "error": self.error,
            "steps": self.steps,
            "workspace_id": self.workspace_id,
        }


@dataclass
class GraphRunResult:
    nodes: dict[str, NodeResult] = field(default_factory=dict)

    @property
    def completed(self) -> list[str]:
        return [k for k, v in self.nodes.items() if v.status is TaskStatus.COMPLETED]

    @property
    def failed(self) -> list[str]:
        return [k for k, v in self.nodes.items() if v.status is TaskStatus.FAILED]

    @property
    def blocked(self) -> list[str]:
        return [k for k, v in self.nodes.items() if v.status is TaskStatus.BLOCKED]

    def to_dict(self) -> dict[str, Any]:
        return {k: v.to_dict() for k, v in self.nodes.items()}


def _unexpected_executor_error(exc: BaseException) -> PlatformError:
    """Wrap an unexpected executor exception as a terminal :class:`PlatformError`.

    Injected executors are untrusted code; anything outside the platform error
    taxonomy is a terminal failure of that node, never a reason to leave it
    ``running`` or to cancel its DAG siblings.
    """
    return PlatformError(
        ErrorKind.WORKER_CRASH,
        f"executor raised unexpected {type(exc).__name__}: {exc}",
        retryable=False,
        context={"exception_type": type(exc).__name__},
    )


class AgentRuntime:
    """Executes task DAGs under the platform's autonomy controls."""

    def __init__(
        self,
        *,
        profiles: ProfileManager,
        workspaces: WorkspaceManager,
        tool_executor: ToolExecutor,
        service: str = "agent-runtime",
        gates: Optional[GateRunner] = None,
        gate_config: Optional[GateConfig | Callable[[TaskNode], GateConfig]] = None,
        checkpoints: Optional[CheckpointStore] = None,
        logger: Optional[StructuredLogger] = None,
        bus: Optional[EventBus] = None,
        metrics: Optional[MetricsRegistry] = None,
        role_resolver: Optional[Callable[[TaskNode], str]] = None,
        workspace_kind: WorkspaceKind = WorkspaceKind.WORKTREE,
        default_timeout_s: float = 30.0,
    ) -> None:
        self.profiles = profiles
        self.workspaces = workspaces
        self.tool_executor = tool_executor
        self.gates = gates or GateRunner()
        self.gate_config = gate_config
        self.checkpoints = checkpoints or CheckpointStore()
        self.logger = logger or StructuredLogger(service)
        self.bus = bus or EventBus()
        self.metrics = metrics or MetricsRegistry()
        self.role_resolver = role_resolver or (lambda node: str(node.metadata.get("role", "default")))
        self.workspace_kind = workspace_kind
        self.default_timeout_s = default_timeout_s

    # ------------------------------------------------------------------
    # DAG execution
    # ------------------------------------------------------------------
    async def run_graph(
        self,
        graph: TaskGraph,
        executor: AgentExecutor,
        *,
        max_parallelism: int = 4,
        trace_id: Optional[str] = None,
    ) -> GraphRunResult:
        """Execute the DAG with bounded parallelism and result passing.

        Independent ready tasks run concurrently (up to ``max_parallelism``); a
        dependent task becomes ready only after all its prerequisites complete.
        """
        if max_parallelism < 1:
            raise ValueError("max_parallelism must be >= 1")
        result = GraphRunResult()
        tid = trace_id or new_id("trace")
        semaphore = asyncio.Semaphore(max_parallelism)
        self.bus.publish("graph.started", {"trace_id": tid, "size": len(graph.nodes)})

        with correlation(trace_id=tid):
            while True:
                ready = graph.ready_ids()
                if not ready:
                    break
                tasks = [
                    asyncio.create_task(self._run_guarded(graph, task_id, executor, semaphore, tid))
                    for task_id in ready
                ]
                node_results = await asyncio.gather(*tasks, return_exceptions=True)
                for task_id, node_result in zip(ready, node_results):
                    if isinstance(node_result, asyncio.CancelledError):
                        raise node_result
                    if isinstance(node_result, BaseException):
                        # Defensive containment: an unexpected node-level crash
                        # fails that node instead of cancelling its siblings or
                        # leaving it stuck in status ``running``.
                        node_result = self._contain_crash(graph, task_id, node_result)
                    result.nodes[node_result.task_id] = node_result

            # Anything still not terminal after the ready set drains is blocked.
            for node in graph.nodes:
                if node.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                    node.status = TaskStatus.BLOCKED
                    node.error = node.error or {"reason": "prerequisites unmet (deadlock)"}
                    result.nodes.setdefault(
                        node.id,
                        NodeResult(task_id=node.id, status=TaskStatus.BLOCKED, error=node.error),
                    )
                    graph.block(node.id, reason="prerequisites unmet (deadlock)")
        self.bus.publish("graph.finished", {"trace_id": tid, "completed": result.completed})
        return result

    async def _run_guarded(
        self,
        graph: TaskGraph,
        task_id: str,
        executor: AgentExecutor,
        semaphore: asyncio.Semaphore,
        trace_id: str,
    ) -> NodeResult:
        async with semaphore:
            with correlation(trace_id=trace_id, span_id=new_id("span")):
                return await self.run_node(graph, task_id, executor)

    # ------------------------------------------------------------------
    # Single node
    # ------------------------------------------------------------------
    async def run_node(self, graph: TaskGraph, task_id: str, executor: AgentExecutor) -> NodeResult:
        """Claim, provision, execute and finalise exactly one task node."""
        node = graph.node(task_id)
        graph.claim(task_id)  # raises CLAIM_DENIED when prerequisites unmet
        self.metrics.inc("agent_runtime_tasks_total", status="claimed")
        self.bus.publish("task.claimed", {"task_id": task_id, "title": node.title})

        role = self.role_resolver(node)
        instance_id = node.metadata.get("agent_instance_id")
        try:
            spec = self.profiles.resolve(role, instance_id=instance_id)
        except PlatformError as exc:
            return self._fail(graph, node, exc, workspace=None)

        workspace: Optional[Workspace] = None
        try:
            workspace = self.workspaces.provision(task_id, kind=self.workspace_kind)
        except PlatformError as exc:
            # Fail-closed: no workspace, no execution (ADR-107 §3.4.4).
            return self._fail(graph, node, exc, workspace=None)

        self.bus.publish(
            "workspace.provisioned",
            {"task_id": task_id, "workspace_id": workspace.workspace_id, "path": str(workspace.path)},
        )

        budget = spec.budget
        budget_state = BudgetState()
        run = self.checkpoints.create(task_id, spec.agent_instance_id, spec_version=spec.spec_version)
        evaluator = PermissionEvaluator(spec.capabilities, spec.tool_policy)
        messages = build_model_context(
            spec,
            task_title=node.title,
            task_description=str(node.metadata.get("description", "")),
            task_input=node.input_data,
            upstream=node.upstream,
        )

        self.logger.info(
            "agent_runtime.runner",
            "resolved agent spec",
            task_id=task_id,
            role=role,
            spec_version=spec.spec_version,
        )
        self.bus.publish(
            "agent.run.started",
            {"task_id": task_id, "run_id": run.run_id, "spec_version": spec.spec_version},
        )
        self.metrics.inc("agent_runtime_runs_total", status="started")

        async def _execute_tool(
            action: str, resource: str, params: Optional[Mapping[str, Any]] = None
        ) -> Any:
            return await self._execute_tool(
                evaluator, budget, budget_state, workspace, run, node, action, resource, params or {}
            )

        invocation = NodeInvocation(
            node=node,
            spec=spec,
            workspace=workspace,
            run=run,
            permissions=evaluator,
            budget_state=budget_state,
            messages=messages,
            execute_tool=_execute_tool,
            logger=self.logger,
            bus=self.bus,
            checkpoints=self.checkpoints,
        )

        try:
            outcome = await self._run_executor_with_retry(executor, invocation, spec)
        except PlatformError as exc:
            self.checkpoints.save(_set_status(run, RunStatus.FAILED, exc))
            return self._fail(graph, node, exc, workspace)
        except Exception as exc:  # noqa: BLE001 - contain executor crashes
            # An executor is injected code: an unexpected exception must fail the
            # node, never escape ``run_node`` and strand it in status ``running``
            # (which would orphan the server-side claim).
            wrapped = _unexpected_executor_error(exc)
            self.checkpoints.save(_set_status(run, RunStatus.FAILED, wrapped))
            return self._fail(graph, node, wrapped, workspace)

        # ---- budget accounting for the node's steps -----------------------
        budget_state.record_usage(
            tokens=outcome.tokens,
            cost_usd=outcome.cost_usd,
            step=True,
            elapsed_ms=0,
        )
        check = budget_state.check(budget)
        if not check.ok:
            exc = budget_exhausted(list(check.violations))
            self.metrics.inc("agent_runtime_budget_exhausted_total", violation=check.violations[0])
            self.checkpoints.save(_set_status(run, RunStatus.TERMINATED, exc))
            return self._fail(graph, node, exc, workspace)

        # ---- quality gates (fail-closed, block rather than complete) ------
        gate_config = self._gate_config_for(node)
        if gate_config and gate_config.required_gates:
            node.metadata.setdefault("run_id", run.run_id)
            ok, gate_results = self.gates.check_submission(gate_config)
            for gate_result in gate_results:
                self.bus.publish("gate.evaluated", gate_result.to_dict())
                self.metrics.inc(
                    "agent_runtime_gate_evaluations_total",
                    gate=gate_result.gate,
                    result=gate_result.status.value,
                )
            if not ok:
                reason = "; ".join(
                    f"{r.gate}:{r.status.value}" for r in gate_results if r.status is not GateStatus.PASSED
                )
                exc = PlatformError(
                    ErrorKind.CONTRACT_VERIFICATION_FAILED,
                    f"required gates did not pass: {reason}",
                    context={"gates": [r.to_dict() for r in gate_results]},
                )
                self.checkpoints.save(_set_status(run, RunStatus.BLOCKED, exc))
                self.bus.publish("task.blocked", {"task_id": task_id, "reason": reason})
                graph.block(task_id, reason=reason)
                self.metrics.inc("agent_runtime_tasks_total", status="blocked")
                self._release(workspace)
                return NodeResult(
                    task_id=task_id,
                    status=TaskStatus.BLOCKED,
                    summary="blocked by quality gates",
                    error=exc.to_dict(),
                    steps=outcome.steps,
                    workspace_id=workspace.workspace_id,
                )

        # ---- finalise ------------------------------------------------------
        self.checkpoints.save(_set_status(run, RunStatus.COMPLETED, None))
        graph.complete(task_id, outcome.result, summary=outcome.summary)
        self.bus.publish(
            "task.finalized",
            {"task_id": task_id, "status": "completed", "summary": outcome.summary},
        )
        self.metrics.inc("agent_runtime_tasks_total", status="completed")
        self._release(workspace)
        return NodeResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            result=outcome.result,
            summary=outcome.summary,
            steps=outcome.steps,
            workspace_id=workspace.workspace_id,
        )

    async def _run_executor_with_retry(
        self, executor: AgentExecutor, invocation: NodeInvocation, spec: AgentSpec
    ) -> NodeOutcome:
        retry_policy = spec.model_profile.retry_policy

        def _on_retry(attempt: int, exc: BaseException, delay_s: float) -> None:
            self.bus.publish(
                "agent.run.retry",
                {"task_id": invocation.node.id, "attempt": attempt, "delay_s": round(delay_s, 4)},
            )
            self.metrics.inc("agent_runtime_retries_total")

        return await retry_async(
            lambda: executor(invocation),
            max_attempts=max(1, retry_policy.max_attempts),
            base_delay_s=max(0.0, retry_policy.base_delay_ms / 1000.0),
            on_retry=_on_retry,
        )

    # ------------------------------------------------------------------
    # Tool execution (permission + budget + retry + timeout + logging)
    # ------------------------------------------------------------------
    async def _execute_tool(
        self,
        evaluator: PermissionEvaluator,
        budget: Budget,
        budget_state: BudgetState,
        workspace: Workspace,
        run: AgentRunState,
        node: TaskNode,
        action: str,
        resource: str,
        params: Mapping[str, Any],
    ) -> Any:
        decision = evaluator.evaluate(action, resource)
        if not decision.allow:
            self.bus.publish("tool.call", {"tool": action, "allowed": False, "reason": decision.reason})
            self.metrics.inc("agent_runtime_tool_calls_total", tool=action, result="denied")
            raise policy_denied(action, resource, decision.reason)

        self.bus.publish("tool.call", {"tool": action, "resource": resource, "allowed": True})

        async def _invoke() -> Any:
            result = await self.tool_executor(action, resource, params, workspace)
            return result

        try:
            result = await retry_async(
                lambda: with_timeout(
                    _invoke(), timeout_s=self.default_timeout_s, operation=f"tool:{action}"
                ),
                max_attempts=2,
            )
        except PlatformError as exc:
            budget_state.record_usage(step=True)
            self.metrics.inc("agent_runtime_tool_calls_total", tool=action, result="error")
            self.bus.publish(
                "tool.result",
                {"tool": action, "status": "error", "error": exc.to_dict()},
            )
            raise
        except Exception as exc:  # noqa: BLE001 - contain unexpected tool crashes
            # The injected tool executor is untrusted code. Convert any
            # unexpected exception into the platform taxonomy so it cannot
            # bypass the structured failure path.
            wrapped = PlatformError(
                ErrorKind.TOOL_CONTAINER_CRASH,
                f"tool {action!r} raised {type(exc).__name__}: {exc}",
                retryable=False,
                context={"tool": action, "exception_type": type(exc).__name__},
            )
            budget_state.record_usage(step=True)
            self.metrics.inc("agent_runtime_tool_calls_total", tool=action, result="error")
            self.bus.publish(
                "tool.result",
                {"tool": action, "status": "error", "error": wrapped.to_dict()},
            )
            raise wrapped from exc
        budget_state.record_usage(step=True)
        self.metrics.inc("agent_runtime_tool_calls_total", tool=action, result="success")
        self.bus.publish("tool.result", {"tool": action, "status": "success"})
        if budget_state.warning(budget):
            self.bus.publish("budget.warning", {"run_id": run.run_id, **budget_state.to_dict()})
        check = budget_state.check(budget)
        if not check.ok:
            self.metrics.inc("agent_runtime_budget_exhausted_total", violation=check.violations[0])
            raise budget_exhausted(list(check.violations))
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _gate_config_for(self, node: TaskNode) -> Optional[GateConfig]:
        if self.gate_config is None:
            return None
        if callable(self.gate_config):
            return self.gate_config(node)
        return self.gate_config

    def _fail(
        self,
        graph: TaskGraph,
        node: TaskNode,
        exc: PlatformError,
        workspace: Optional[Workspace],
    ) -> NodeResult:
        record = ErrorRecord.from_exception(exc)
        graph.fail(node.id, error=record.to_dict(), summary=exc.message)
        self.logger.error(
            "agent_runtime.runner",
            "task failed",
            task_id=node.id,
            error_code=record.code,
        )
        self.bus.publish("task.failed", {"task_id": node.id, **record.to_dict()})
        self.metrics.inc("agent_runtime_tasks_total", status="failed")
        if workspace is not None:
            self._release(workspace)
        return NodeResult(
            task_id=node.id,
            status=TaskStatus.FAILED,
            summary=exc.message,
            error=record.to_dict(),
            workspace_id=workspace.workspace_id if workspace else None,
        )

    def _contain_crash(
        self, graph: TaskGraph, task_id: str, exc: BaseException
    ) -> NodeResult:
        """Mark a node failed after an unexpected crash and return its result."""
        wrapped = _unexpected_executor_error(exc)
        record = ErrorRecord.from_exception(wrapped)
        node = graph.node(task_id)
        graph.fail(task_id, error=record.to_dict(), summary=wrapped.message)
        self.logger.error(
            "agent_runtime.runner",
            "task crashed",
            task_id=node.id,
            error_code=record.code,
        )
        self.bus.publish("task.failed", {"task_id": node.id, **record.to_dict()})
        self.metrics.inc("agent_runtime_tasks_total", status="failed")
        return NodeResult(
            task_id=node.id,
            status=TaskStatus.FAILED,
            summary=wrapped.message,
            error=record.to_dict(),
        )

    def _release(self, workspace: Workspace) -> None:
        try:
            self.workspaces.release(workspace.workspace_id)
        except PlatformError:  # pragma: no cover - release is best-effort
            pass

    # ------------------------------------------------------------------
    # Crash recovery
    # ------------------------------------------------------------------
    async def resume_node(
        self,
        graph: TaskGraph,
        task_id: str,
        run_id: str,
        executor: AgentExecutor,
    ) -> NodeResult:
        """Resume a previously started run from its last completed turn.

        Reconstructs the checkpointed :class:`AgentRunState`, verifies the budget
        is not exhausted, marks the task running again and delegates to the
        executor (which is responsible for continuing from ``last_completed_turn``).
        """
        node = graph.node(task_id)
        run = self.checkpoints.load(run_id)
        from .retry import restore_budget, resume_point

        next_turn = resume_point(run)  # raises if status is not resumable
        restored = restore_budget(run)

        role = self.role_resolver(node)
        spec = self.profiles.resolve(role, instance_id=node.metadata.get("agent_instance_id"))
        if not restored.check(spec.budget).ok:
            return self._fail(graph, node, budget_exhausted(list(restored.check(spec.budget).violations)), None)

        workspace = self.workspaces.active_for_task(task_id)
        if workspace is None:
            workspace = self.workspaces.provision(task_id, kind=self.workspace_kind)

        node.status = TaskStatus.RUNNING
        evaluator = PermissionEvaluator(spec.capabilities, spec.tool_policy)
        messages = build_model_context(
            spec,
            task_title=node.title,
            task_description=str(node.metadata.get("description", "")),
            task_input=node.input_data,
            upstream=node.upstream,
        )
        self.bus.publish("agent.run.resumed", {"task_id": task_id, "run_id": run_id, "turn": next_turn})

        async def _execute_tool(
            action: str, resource: str, params: Optional[Mapping[str, Any]] = None
        ) -> Any:
            return await self._execute_tool(
                evaluator, spec.budget, restored, workspace, run, node, action, resource, params or {}
            )

        invocation = NodeInvocation(
            node=node,
            spec=spec,
            workspace=workspace,
            run=run,
            permissions=evaluator,
            budget_state=restored,
            messages=messages,
            execute_tool=_execute_tool,
            logger=self.logger,
            bus=self.bus,
            checkpoints=self.checkpoints,
        )
        try:
            outcome = await self._run_executor_with_retry(executor, invocation, spec)
        except PlatformError as exc:
            self.checkpoints.save(_set_status(run, RunStatus.FAILED, exc))
            return self._fail(graph, node, exc, workspace)
        except Exception as exc:  # noqa: BLE001 - contain executor crashes
            wrapped = _unexpected_executor_error(exc)
            self.checkpoints.save(_set_status(run, RunStatus.FAILED, wrapped))
            return self._fail(graph, node, wrapped, workspace)

        self.checkpoints.save(_set_status(run, RunStatus.COMPLETED, None))
        graph.complete(task_id, outcome.result, summary=outcome.summary)
        self.bus.publish("task.finalized", {"task_id": task_id, "status": "completed"})
        self._release(workspace)
        return NodeResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            result=outcome.result,
            summary=outcome.summary,
            steps=outcome.steps,
            workspace_id=workspace.workspace_id,
        )


def _set_status(run: AgentRunState, status: RunStatus, exc: Optional[PlatformError]) -> AgentRunState:
    run.status = status
    run.error = ErrorRecord.from_exception(exc).to_dict() if exc is not None else None
    return run
