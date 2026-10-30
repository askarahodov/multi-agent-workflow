"""Task dependency graph: DAG validation, deterministic claimability, result
passing (ADR-109).

The graph is the single source of ordering truth. A ``pending`` task may only be
claimed when *every* prerequisite is ``completed``; the model can never grant
itself claimability. Results move downstream only through the service-owned
``_maw_upstream`` handoff, injected atomically on completion — never through a
shared mutable file and never via user-supplied input (ADR-109 §3.5).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Sequence

from .errors import ErrorKind, PlatformError, claim_denied, validation_error

#: Service-generated handoff key. User input carrying this key is rejected.
MAW_UPSTREAM_KEY = "_maw_upstream"

#: Per-task dependency bound (ADR-109 §3.1 rule 1).
MAX_DEPENDENCIES = 16


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class TaskNode:
    id: str
    index: int
    title: str
    depends_on: tuple[int, ...] = ()
    contract_id: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    input_data: dict[str, Any] = field(default_factory=dict)
    upstream: list[dict[str, Any]] = field(default_factory=list)
    result: Optional[dict[str, Any]] = None
    summary: str = ""
    error: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "depends_on": list(self.depends_on),
            "contract_id": self.contract_id,
            "status": self.status.value,
            "summary": self.summary,
            "error": self.error,
        }


class TaskGraph:
    """A validated, acyclic set of :class:`TaskNode` with deterministic scheduling."""

    def __init__(self, nodes: Sequence[TaskNode], *, require_contract: bool = False) -> None:
        self.nodes: list[TaskNode] = list(nodes)
        self.require_contract = require_contract
        self._by_id: dict[str, TaskNode] = {n.id: n for n in self.nodes}
        self._by_index: dict[int, TaskNode] = {n.index: n for n in self.nodes}
        self._validate()

    # -- construction ------------------------------------------------------
    @classmethod
    def from_spec(
        cls,
        tasks: Sequence[Mapping[str, Any]],
        *,
        require_contract: bool = False,
    ) -> "TaskGraph":
        """Build a graph from a ``POST /workflows/runs`` ``tasks[]`` payload.

        Validation is atomic: any error raises before a graph is returned, so a
        rejected graph commits nothing (ADR-109 §3.1 rule 2).
        """
        if not isinstance(tasks, (list, tuple)) or not tasks:
            raise validation_error("tasks must be a non-empty list")
        nodes: list[TaskNode] = []
        for index, raw in enumerate(tasks):
            if not isinstance(raw, Mapping):
                raise validation_error(f"task[{index}] must be an object")
            title = raw.get("title")
            if not isinstance(title, str) or not title.strip():
                raise validation_error(f"task[{index}].title is required")
            depends_on = tuple(raw.get("depends_on", ()) or ())
            contract_id = raw.get("contract_id")
            input_data = dict(raw.get("input_data", {}) or {})
            if MAW_UPSTREAM_KEY in input_data:
                raise validation_error(
                    f"task[{index}].input_data must not contain the reserved key "
                    f"{MAW_UPSTREAM_KEY!r}"
                )
            nodes.append(
                TaskNode(
                    id=str(raw.get("id") or f"task-{index}-{uuid.uuid4().hex[:8]}"),
                    index=index,
                    title=title,
                    depends_on=depends_on,
                    contract_id=str(contract_id) if contract_id else None,
                    input_data=input_data,
                    metadata=dict(raw.get("metadata", {}) or {}),
                )
            )
        graph = cls(nodes, require_contract=require_contract)
        graph._validate_atomic_scope(tasks)
        return graph

    # -- validation --------------------------------------------------------
    def _validate(self) -> None:
        if len(self._by_id) != len(self.nodes):
            raise validation_error("duplicate task ids in graph")
        if sorted(self._by_index) != list(range(len(self.nodes))):
            raise validation_error("task indices must be contiguous from 0")
        for node in self.nodes:
            deps = list(node.depends_on)
            if len(deps) > MAX_DEPENDENCIES:
                raise validation_error(
                    f"task {node.title!r} has {len(deps)} dependencies "
                    f"(max {MAX_DEPENDENCIES})"
                )
            if len(set(deps)) != len(deps):
                raise validation_error(f"task {node.title!r} has duplicate dependencies")
            for dep in deps:
                if not isinstance(dep, int) or dep < 0 or dep >= len(self.nodes):
                    raise validation_error(
                        f"task {node.title!r} dependency index {dep!r} out of range"
                    )
                if dep >= node.index:
                    raise validation_error(
                        f"task {node.title!r} depends on a non-earlier task index {dep} "
                        "(cycles and forward edges are rejected)"
                    )
        self._assert_acyclic()

    def _assert_acyclic(self) -> None:
        WHITE, GREY, BLACK = 0, 1, 2
        colour: dict[str, int] = {n.id: WHITE for n in self.nodes}

        def visit(node: TaskNode, stack: list[str]) -> None:
            colour[node.id] = GREY
            stack.append(node.title)
            for dep_index in node.depends_on:
                dep = self._by_index[dep_index]
                if colour[dep.id] == GREY:
                    raise validation_error("cycle detected: " + " -> ".join(stack + [dep.title]))
                if colour[dep.id] == WHITE:
                    visit(dep, stack)
            stack.pop()
            colour[node.id] = BLACK

        for node in self.nodes:
            if colour[node.id] == WHITE:
                visit(node, [])

    def _validate_atomic_scope(self, raw_tasks: Sequence[Mapping[str, Any]]) -> None:
        if self.require_contract:
            for node in self.nodes:
                if not node.contract_id:
                    raise validation_error(
                        f"stage {node.title!r} is missing a contract_id "
                        "(contract-less stages are rejected at launch)"
                    )

    # -- scheduling --------------------------------------------------------
    def node(self, task_id: str) -> TaskNode:
        try:
            return self._by_id[task_id]
        except KeyError as exc:
            raise PlatformError(ErrorKind.NOT_FOUND, f"unknown task {task_id!r}") from exc

    def node_by_index(self, index: int) -> TaskNode:
        return self._by_index[index]

    def is_terminal(self, task_id: str) -> bool:
        return self.node(task_id).status in (TaskStatus.COMPLETED, TaskStatus.FAILED)

    def prerequisites(self, task_id: str) -> list[TaskNode]:
        node = self.node(task_id)
        return [self._by_index[i] for i in node.depends_on]

    def ready_ids(self) -> list[str]:
        """Task ids that are ``pending`` with every prerequisite ``completed``."""
        ready: list[str] = []
        for node in self.nodes:
            if node.status is not TaskStatus.PENDING:
                continue
            if self._prereqs_completed(node):
                ready.append(node.id)
        return ready

    def _prereqs_completed(self, node: TaskNode) -> bool:
        return all(
            self._by_index[i].status is TaskStatus.COMPLETED for i in node.depends_on
        )

    def claimable(self, task_id: str) -> tuple[bool, str]:
        """Deterministic claimability check (ADR-109 §3.2).

        Returns ``(True, "")`` when the task may be claimed, else ``(False, reason)``.
        A refused claim never increments attempts.
        """
        node = self.node(task_id)
        if node.status is TaskStatus.COMPLETED:
            return False, "task already completed"
        if node.status is TaskStatus.FAILED:
            return False, "task failed"
        if node.status is TaskStatus.RUNNING:
            return False, "task already running"
        open_deps = [
            self._by_index[i]
            for i in node.depends_on
            if self._by_index[i].status is not TaskStatus.COMPLETED
        ]
        if open_deps:
            titles = ", ".join(f"{d.title}({d.status.value})" for d in open_deps)
            return False, f"prerequisites not completed: {titles}"
        return True, ""

    def claim(self, task_id: str) -> TaskNode:
        """Claim a task or raise ``CLAIM_DENIED`` (refused claims bump no attempts)."""
        ok, reason = self.claimable(task_id)
        if not ok:
            raise claim_denied(task_id, reason)
        node = self.node(task_id)
        node.status = TaskStatus.RUNNING
        return node

    # -- completion & result passing --------------------------------------
    def complete(self, task_id: str, result: Optional[Mapping[str, Any]] = None, *, summary: str = "") -> None:
        node = self.node(task_id)
        if node.status is TaskStatus.COMPLETED:
            return
        node.status = TaskStatus.COMPLETED
        node.result = dict(result) if result is not None else None
        node.summary = summary
        self._propagate_handoff(node)

    def fail(self, task_id: str, *, error: Optional[Mapping[str, Any]] = None, summary: str = "") -> None:
        node = self.node(task_id)
        node.status = TaskStatus.FAILED
        node.error = dict(error) if error is not None else None
        if summary:
            node.summary = summary

    def block(self, task_id: str, *, reason: str) -> None:
        node = self.node(task_id)
        node.status = TaskStatus.BLOCKED
        node.error = {"reason": reason}

    def _propagate_handoff(self, node: TaskNode) -> None:
        """Append a bounded upstream entry to every direct dependent's input."""
        for dependent in self.nodes:
            if node.index in dependent.depends_on:
                dependent.upstream.append(
                    {"prev_task_id": node.id, "summary": node.summary}
                )

    def mark_running(self, task_id: str) -> None:
        self.node(task_id).status = TaskStatus.RUNNING

    # -- introspection -----------------------------------------------------
    def all_terminal(self) -> bool:
        return all(n.status in (TaskStatus.COMPLETED, TaskStatus.FAILED) for n in self.nodes)

    def topological_order(self) -> list[str]:
        order: list[str] = []
        for node in sorted(self.nodes, key=lambda n: n.index):
            order.append(node.id)
        return order

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "ready": self.ready_ids(),
        }
