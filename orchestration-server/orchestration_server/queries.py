"""Read-only query helpers for the orchestration engine."""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import select

from sqlalchemy.ext.asyncio import async_sessionmaker

from .errors import NotFoundError, StateTransitionError

from .models import (
    Agent,
    Contract,
    Project,
    Task,
    TaskAttempt,
    TaskReconciliation,
    SagaEvent,
    WorkflowRun,
    Workspace,
)
from .services.cursor import apply_keyset_predicate, fetch_one_more, split_page


class OrchestrationQueries:
    """Thin read-only facade over the orchestration store."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory

    async def get_quarantined_attempts(self, task_id: str) -> tuple[Task, list[TaskAttempt]]:
        """Resolve scope ONLY from an actual quarantined task in the engine DB."""
        async with self._sf() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise NotFoundError("Task not found")
            if task.status != "blocked":
                raise StateTransitionError("Task is not a recovery quarantine")
            event = await session.scalar(
                select(SagaEvent.id).where(
                    SagaEvent.aggregate_type == "task",
                    SagaEvent.aggregate_id == task_id,
                    SagaEvent.event_type == "task.recovery_quarantined",
                ).limit(1)
            )
            if event is None:
                raise StateTransitionError("Task is not a recovery quarantine")
            attempts = (await session.scalars(
                select(TaskAttempt).where(
                    TaskAttempt.task_id == task_id,
                    TaskAttempt.status == "interrupted",
                ).order_by(TaskAttempt.attempt_number).limit(51)
            )).all()
            if not attempts or len(attempts) > 50:
                raise StateTransitionError("Recovery attempt count is invalid")
            return task, list(attempts)

    async def get_reconciliation(self, task_id: str) -> TaskReconciliation:
        async with self._sf() as session:
            record = await session.get(TaskReconciliation, task_id)
            if record is None:
                raise NotFoundError("Reconciliation not found")
            return record

    async def list_recovery_quarantine(self, limit: int = 100) -> List[Task]:
        """Admin-facing queue, only tasks actually blocked by restart."""
        if not 1 <= limit <= 200:
            raise ValueError("Invalid recovery queue limit")
        async with self._sf() as session:
            tasks = await session.scalars(
                select(Task).join(
                    SagaEvent,
                    (SagaEvent.aggregate_type == "task")
                    & (SagaEvent.aggregate_id == Task.id)
                    & (SagaEvent.event_type == "task.recovery_quarantined"),
                ).where(Task.status == "blocked")
                .order_by(Task.created_at, Task.id)
                .limit(limit)
            )
            return list(tasks.unique().all())

    async def get_project(self, project_id: str) -> Project:
        async with self._sf() as session:
            obj = await session.get(Project, project_id)
            if obj is None:
                raise NotFoundError(f"Project {project_id} not found")
            return obj

    async def get_run(self, run_id: str) -> WorkflowRun:
        async with self._sf() as session:
            obj = await session.get(WorkflowRun, run_id)
            if obj is None:
                raise NotFoundError(f"Run {run_id} not found")
            return obj

    async def get_contract(self, contract_id: str) -> Contract:
        async with self._sf() as session:
            obj = await session.get(Contract, contract_id)
            if obj is None:
                raise NotFoundError(f"Contract {contract_id} not found")
            return obj

    async def get_agent(self, agent_id: str) -> Agent:
        async with self._sf() as session:
            obj = await session.get(Agent, agent_id)
            if obj is None:
                raise NotFoundError(f"Agent {agent_id} not found")
            return obj

    async def get_task(self, task_id: str) -> Task:
        async with self._sf() as session:
            obj = await session.get(Task, task_id)
            if obj is None:
                raise NotFoundError(f"Task {task_id} not found")
            return obj

    async def list_projects(self) -> List[Project]:
        async with self._sf() as session:
            stmt = select(Project).order_by(Project.created_at.desc())
            rows = await session.scalars(stmt)
            return list(rows.all())

    async def list_runs(
        self, project_id: Optional[str] = None, status: Optional[str] = None
    ) -> List[WorkflowRun]:
        async with self._sf() as session:
            stmt = select(WorkflowRun)
            if project_id is not None:
                stmt = stmt.where(WorkflowRun.project_id == project_id)
            if status is not None:
                stmt = stmt.where(WorkflowRun.status == status)
            stmt = stmt.order_by(WorkflowRun.created_at.desc())
            rows = await session.scalars(stmt)
            return list(rows.all())

    async def list_runs_page(
        self,
        after: Optional[str] = None,
        limit: int = 50,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[list[WorkflowRun], Optional[str]]:
        """Cursor-paged variant of :meth:`list_runs` (ADR-101 CursorPage)."""
        async with self._sf() as session:
            stmt = select(WorkflowRun)
            if project_id is not None:
                stmt = stmt.where(WorkflowRun.project_id == project_id)
            if status is not None:
                stmt = stmt.where(WorkflowRun.status == status)
            stmt = apply_keyset_predicate(
                stmt, WorkflowRun.created_at, WorkflowRun.id, after
            )
            stmt = stmt.order_by(
                WorkflowRun.created_at.desc(), WorkflowRun.id.desc()
            )
            stmt = fetch_one_more(stmt, limit)
            rows = list((await session.scalars(stmt)).all())
            page, next_cursor = split_page(
                rows, limit, lambda r: (r.created_at, r.id)
            )
            for r in page:
                session.expunge(r)
            return page, next_cursor

    async def list_workspaces(self, project_id: Optional[str] = None) -> List[Workspace]:
        async with self._sf() as session:
            stmt = select(Workspace)
            if project_id is not None:
                stmt = stmt.where(Workspace.project_id == project_id)
            stmt = stmt.order_by(Workspace.created_at.desc())
            rows = await session.scalars(stmt)
            return list(rows.all())

    async def list_contracts(self) -> List[Contract]:
        async with self._sf() as session:
            stmt = select(Contract).order_by(Contract.created_at.desc())
            rows = await session.scalars(stmt)
            return list(rows.all())

    async def list_agents(self) -> List[Agent]:
        async with self._sf() as session:
            stmt = select(Agent).order_by(Agent.created_at.desc())
            rows = await session.scalars(stmt)
            return list(rows.all())

    async def list_tasks(self, run_id: str) -> List[Task]:
        async with self._sf() as session:
            stmt = select(Task)
            stmt = stmt.where(Task.workflow_run_id == run_id)
            stmt = stmt.order_by(Task.priority.desc(), Task.created_at)
            rows = await session.scalars(stmt)
            return list(rows.all())

    async def list_tasks_page(
        self, run_id: str, after: Optional[str] = None, limit: int = 50
    ) -> tuple[list[Task], Optional[str]]:
        """Cursor-paged variant of :meth:`list_tasks` (ADR-101 CursorPage)."""
        async with self._sf() as session:
            stmt = select(Task).where(Task.workflow_run_id == run_id)
            stmt = apply_keyset_predicate(stmt, Task.created_at, Task.id, after)
            stmt = stmt.order_by(Task.created_at.desc(), Task.id.desc())
            stmt = fetch_one_more(stmt, limit)
            rows = list((await session.scalars(stmt)).all())
            page, next_cursor = split_page(rows, limit, lambda t: (t.created_at, t.id))
            for r in page:
                session.expunge(r)
            return page, next_cursor

    async def list_attempts(self, task_id: str) -> List[TaskAttempt]:
        async with self._sf() as session:
            stmt = select(TaskAttempt)
            stmt = stmt.where(TaskAttempt.task_id == task_id)
            stmt = stmt.order_by(TaskAttempt.attempt_number)
            rows = await session.scalars(stmt)
            return list(rows.all())