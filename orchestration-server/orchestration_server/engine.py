"""Platform-owned orchestration engine (durable state transitions).

The engine is the single authority over task and run lifecycle. Agents talk to
it only through the REST API and can never mark a task complete by themselves:
``submit`` runs contract verification and only the engine may move a task to
``completed``. Every transition is written to the ``saga_events`` journal in the
same transaction as the state change, so confirmed results are durable and a
restart (see :meth:`OrchestrationEngine.recover`) can re-queue incomplete work
without losing confirmed results.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import jsonschema
from jsonschema import Draft202012Validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.qa_attestation import QaAttestationRejected, verify_qa_attestation

from .attempt_leases import acquire_lease_write_fence, active_attempt_sql
from .errors import (
    BusinessRuleError,
    ConflictError,
    ContractVerificationError,
    DuplicateKeyError,
    NotFoundError,
    StateTransitionError,
)
from .models import (
    Agent,
    AttemptLease,
    Contract,
    Project,
    SagaEvent,
    Task,
    TaskDependency,
    TaskAttempt,
    TaskGitEvidence,
    TaskQaAttestation,
    TaskReconciliation,
    WorkflowRun,
    Workspace,
)

TERMINAL_TASK_STATUSES = ("completed", "failed", "blocked")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes from the DB; treat them as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


DEFAULT_RETRY = {
    "max_attempts": 3,
    "base_delay_seconds": 1.0,
    "max_delay_seconds": 300.0,
    "backoff_multiplier": 2.0,
}


class OrchestrationEngine:
    """Owns every durable transition of runs, tasks and attempts."""

    def __init__(
        self,
        session_factory: async_sessionmaker,
        default_retry: Optional[dict] = None,
        require_lease: bool = False,
        qa_attestation_key: str | None = None,
    ) -> None:
        if qa_attestation_key is not None and (
            not require_lease or type(qa_attestation_key) is not str
            or not qa_attestation_key.isascii()
            or not 32 <= len(qa_attestation_key) <= 128
        ):
            raise ValueError("Trusted QA requires a leased native engine and private signing key")
        self._sf = session_factory
        self._require_lease = require_lease
        self._qa_key = qa_attestation_key
        self._default_retry = {**DEFAULT_RETRY, **(default_retry or {})}

    async def _log(
        self,
        session,
        run_id: Optional[str],
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: Optional[dict] = None,
    ) -> None:
        session.add(
            SagaEvent(
                run_id=run_id,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                event_type=event_type,
                payload=payload,
            )
        )

    # ---------- scoping entities ----------
    async def create_project(
        self,
        name: str,
        description: Optional[str] = None,
        settings: Optional[dict] = None,
    ) -> Project:
        async with self._sf() as session:
            dup = await session.scalar(select(Project).where(Project.name == name))
            if dup is not None:
                raise DuplicateKeyError(f"Project {name!r} already exists")
            proj = Project(name=name, description=description, settings=settings)
            session.add(proj)
            await session.flush()
            await self._log(session, None, "project", proj.id, "project.created", {"name": name})
            await session.commit()
            return proj

    async def create_workspace(
        self,
        project_id: str,
        name: str,
        path: Optional[str] = None,
        settings: Optional[dict] = None,
    ) -> Workspace:
        async with self._sf() as session:
            pr = await session.get(Project, project_id)
            if pr is None:
                raise NotFoundError(f"Project {project_id} not found")
            dup = await session.scalar(
                select(Workspace).where(
                    Workspace.project_id == project_id, Workspace.name == name
                )
            )
            if dup is not None:
                raise DuplicateKeyError(f"Workspace {name!r} already exists in project")
            ws = Workspace(project_id=project_id, name=name, path=path, settings=settings)
            session.add(ws)
            await session.flush()
            await self._log(session, None, "workspace", ws.id, "workspace.created", {"name": name})
            await session.commit()
            return ws

    async def create_contract(
        self,
        name: str,
        schema: dict,
        project_id: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Contract:
        if not isinstance(schema, dict):
            raise BusinessRuleError("Contract schema must be a JSON object")
        try:
            Draft202012Validator.check_schema(schema)
        except jsonschema.SchemaError as exc:
            raise BusinessRuleError(f"Invalid JSON Schema: {exc}") from exc
        async with self._sf() as session:
            if project_id is not None:
                pr = await session.get(Project, project_id)
                if pr is None:
                    raise NotFoundError(f"Project {project_id} not found")
            dup = await session.scalar(
                select(Contract).where(
                    Contract.project_id == project_id, Contract.name == name
                )
            )
            if dup is not None:
                raise DuplicateKeyError(f"Contract {name!r} already exists")
            c = Contract(
                project_id=project_id, name=name, description=description, schema=schema
            )
            session.add(c)
            await session.flush()
            await self._log(session, None, "contract", c.id, "contract.created", {"name": name})
            await session.commit()
            return c

    async def register_agent(self, name: str, metadata: Optional[dict] = None) -> Agent:
        async with self._sf() as session:
            dup = await session.scalar(select(Agent).where(Agent.name == name))
            if dup is not None:
                raise DuplicateKeyError(f"Agent {name!r} already registered")
            agent = Agent(name=name, agent_metadata=metadata)
            session.add(agent)
            await session.flush()
            await self._log(session, None, "agent", agent.id, "agent.registered", {"name": name})
            await session.commit()
            return agent

    # ---------- run launch ----------
    async def launch_run(
        self,
        project_id: str,
        name: str,
        tasks: list,
        workspace_id: Optional[str] = None,
        triggered_by: Optional[str] = None,
        input_data: Optional[dict] = None,
        retry_policy: Optional[dict] = None,
    ) -> WorkflowRun:
        policy = {**self._default_retry, **(retry_policy or {})}
        if int(policy["max_attempts"]) < 1:
            raise BusinessRuleError("retry_policy.max_attempts must be >= 1")
        async with self._sf() as session:
            pr = await session.get(Project, project_id)
            if pr is None:
                raise NotFoundError(f"Project {project_id} not found")
            if workspace_id is not None:
                ws = await session.get(Workspace, workspace_id)
                if ws is None:
                    raise NotFoundError(f"Workspace {workspace_id} not found")
                if ws.project_id != project_id:
                    raise BusinessRuleError("Workspace does not belong to the workflow project")
            if not tasks:
                raise BusinessRuleError("A workflow run needs at least one task")
            run = WorkflowRun(
                project_id=project_id,
                workspace_id=workspace_id,
                name=name,
                status="running",
                input_data=input_data,
                triggered_by=triggered_by,
                retry_policy=policy,
                started_at=_now(),
            )
            session.add(run)
            await session.flush()
            await self._log(session, run.id, "run", run.id, "run.launched", {"name": name})
            created_tasks: list[Task] = []
            for index, spec in enumerate(tasks):
                predecessors = spec.get("depends_on") or []
                if (
                    not isinstance(predecessors, list) or len(predecessors) > 16
                    or len(predecessors) != len(set(
                        str(value) for value in predecessors
                    ))
                    or any(type(value) is not int or value < 0 or value >= index
                           for value in predecessors)
                ):
                    raise BusinessRuleError(
                        "Task dependencies must be unique indexes of earlier tasks"
                    )
                input_data = spec.get("input_data")
                if input_data is not None and (
                    not isinstance(input_data, dict)
                    or "_maw_upstream" in input_data
                ):
                    raise BusinessRuleError("Reserved SDLC upstream context cannot be supplied")
                title = spec.get("title")
                if not title:
                    raise BusinessRuleError("Every task needs a non-empty title")
                contract_id = spec.get("contract_id")
                if self._require_lease and contract_id is None:
                    raise BusinessRuleError("Native leased task requires an explicit contract")
                if contract_id is not None:
                    contract = await session.get(Contract, contract_id)
                    if contract is None:
                        raise NotFoundError(
                            f"Contract {contract_id} referenced by task {title!r} not found"
                        )
                    # Global contracts remain reusable; project-specific ones are isolated.
                    if contract.project_id not in (None, project_id):
                        raise BusinessRuleError("Contract does not belong to the workflow project")
                t = Task(
                    workflow_run_id=run.id,
                    node_id=spec.get("node_id"),
                    title=title,
                    description=spec.get("description"),
                    contract_id=contract_id,
                    input_data=spec.get("input_data"),
                    priority=int(spec.get("priority", 0) or 0),
                    max_attempts=int(policy["max_attempts"]),
                    retry_base_delay_seconds=float(policy["base_delay_seconds"]),
                    retry_max_delay_seconds=float(policy["max_delay_seconds"]),
                )
                session.add(t)
                await session.flush()
                await self._log(session, run.id, "task", t.id, "task.created", {"title": t.title})
                for before in predecessors:
                    session.add(TaskDependency(
                        task_id=t.id,
                        prerequisite_task_id=created_tasks[before].id,
                    ))
                created_tasks.append(t)
            await session.commit()
            return run

    async def get_qa_status(self, task_id: str) -> dict:
        """Read operator-verifiable QA state without exposing the HMAC proof."""
        async with self._sf() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise NotFoundError("Task not found")
            if self._qa_key is None:
                return {"task_id": task_id, "status": "disabled"}
            proof = await session.get(TaskQaAttestation, task_id)
            if proof is None:
                return {"task_id": task_id, "status": "pending"}
            return {
                "task_id": task_id, "status": "verified",
                "attempt_id": proof.attempt_id,
                "commit_sha": proof.commit_sha,
                "gate_run_ids": proof.gate_run_ids,
                "issued_by": proof.issued_by,
                "issued_at": proof.issued_at,
            }

    async def register_qa_attestation(
        self, task_id: str, receipt: dict,
    ) -> dict:
        """Accept only fresh QG-signed QA evidence for the completed Git attempt.

        This is called from an ADMIN-only API endpoint. Workers have no signing
        key and cannot independently attest their own results.
        """
        if self._qa_key is None:
            raise ConflictError("Independent QA attestation is disabled")
        try:
            proof = verify_qa_attestation(receipt, self._qa_key)
        except QaAttestationRejected as exc:
            raise ConflictError(str(exc)) from None
        if proof["task_id"] != task_id:
            raise ConflictError("QA receipt task mismatch")
        run_id = None
        async with self._sf() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise NotFoundError("QA task not found")
            attempt = await session.get(TaskAttempt, proof["attempt_id"])
            if (
                task.status != "completed"
                or attempt is None or attempt.task_id != task_id
                or attempt.status != "completed"
            ):
                raise ConflictError("QA requires a completed Contract Gate attempt")
            git = await session.get(TaskGitEvidence, attempt.id)
            if (
                git is None or git.task_id != task_id
                or git.commit_sha != proof["commit_sha"]
            ):
                raise ConflictError("QA evidence does not match persisted Git attempt")
            if await session.get(TaskQaAttestation, task_id) is not None:
                raise ConflictError("QA has already been attested for this task")
            session.add(TaskQaAttestation(
                task_id=task_id, attempt_id=attempt.id,
                commit_sha=proof["commit_sha"],
                gate_run_ids=proof["gate_run_ids"],
                issued_by=proof["issued_by"],
                issued_at=proof["issued_at"],
                signature=receipt["signature"],
            ))
            run_id = task.workflow_run_id
            await self._log(
                session, run_id, "task", task_id, "task.qa_attested",
                {"attempt_id": attempt.id, "commit_sha": git.commit_sha,
                 "gate_run_ids": proof["gate_run_ids"]},
            )
            await session.commit()
        if run_id is not None:
            await self._finalize_run(run_id)
        return {
            "task_id": task_id, "attempt_id": proof["attempt_id"],
            "commit_sha": proof["commit_sha"], "gate_run_ids": proof["gate_run_ids"],
            "issued_by": proof["issued_by"], "status": "verified",
        }

    # ---------- task claiming (concurrency-safe) ----------
    async def claim_task(self, task_id: str, agent_id: str) -> TaskAttempt:
        """Atomically claim a pending task for an agent.

        The claim is guarded by a conditional ``UPDATE ... WHERE status='pending'``
        so two workers racing for the same task cannot both win: exactly one
        observes ``rowcount == 1`` and creates the attempt, the loser receives a
        conflict. The same pattern guards agent exclusivity.
        """
        async with self._sf() as session:
            agent = await session.get(Agent, agent_id)
            if agent is None:
                raise NotFoundError(f"Agent {agent_id} not found")
            task = await session.get(Task, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found")
            if self._require_lease and task.contract_id is None:
                raise ConflictError("Native task requires an explicit contract")
            if task.status in TERMINAL_TASK_STATUSES:
                raise StateTransitionError(f"Task {task_id} is terminal ({task.status})")
            if task.status == "in_progress":
                raise ConflictError(f"Task {task_id} is already claimed")
            run = await session.get(WorkflowRun, task.workflow_run_id)
            if run is None or run.status != "running":
                raise ConflictError("Task's workflow run is not active")
            predecessors = list((await session.execute(
                select(Task.id, Task.status)
                .join(TaskDependency, Task.id == TaskDependency.prerequisite_task_id)
                .where(TaskDependency.task_id == task_id)
            )).all())
            if any(status != "completed" for _, status in predecessors):
                raise ConflictError("Task prerequisites not yet contract-verified")
            if self._qa_key is not None:
                for prerequisite_id, _ in predecessors:
                    if await session.get(TaskQaAttestation, prerequisite_id) is None:
                        raise ConflictError("Independent QA evidence required before next stage")
            retry_at = _aware(task.retry_at)
            if retry_at is not None and retry_at > _now():
                raise ConflictError(f"Task {task_id} is waiting for its retry window")
            run_id = task.workflow_run_id

            now = _now()
            try:
                claimed = await session.execute(
                    update(Task)
                    .where(Task.id == task_id, Task.status == "pending")
                    .values(
                        status="in_progress",
                        assigned_agent_id=agent_id,
                        started_at=now,
                        retry_at=None,
                        attempt_count=Task.attempt_count + 1,
                        version=Task.version + 1,
                    )
                    .execution_options(synchronize_session=False)
                )
                if claimed.rowcount != 1:
                    await session.rollback()
                    raise ConflictError(f"Task {task_id} was claimed concurrently")

                seized = await session.execute(
                    update(Agent)
                    .where(Agent.id == agent_id, Agent.status == "idle")
                    .values(status="busy", version=Agent.version + 1)
                    .execution_options(synchronize_session=False)
                )
                if seized.rowcount != 1:
                    await session.rollback()
                    raise ConflictError(f"Agent {agent_id} is not idle")

                last_no = await session.scalar(
                    select(func.max(TaskAttempt.attempt_number)).where(
                        TaskAttempt.task_id == task_id
                    )
                )
                attempt_no = int(last_no or 0) + 1
                attempt = TaskAttempt(
                    task_id=task_id,
                    attempt_number=attempt_no,
                    agent_id=agent_id,
                    status="running",
                    input_data=task.input_data,
                )
                session.add(attempt)
                await session.flush()
                await self._log(
                    session, run_id, "task", task_id, "task.claimed", {"agent": agent_id}
                )
                await self._log(
                    session,
                    run_id,
                    "attempt",
                    attempt.id,
                    "attempt.started",
                    {"number": attempt_no},
                )
                await session.commit()
            except (OperationalError, IntegrityError) as exc:
                # A database-level race (write lock contention or a unique
                # constraint on (task_id, attempt_number)) means another worker
                # won the claim; surface it as a domain conflict, not a 500.
                await session.rollback()
                raise ConflictError(
                    f"Task {task_id} was claimed concurrently"
                ) from exc
            return attempt

    def _retry_delay(self, task: Task, attempt_number: int) -> float:
        """Exponential backoff, capped at the task's max delay."""
        base = task.retry_base_delay_seconds
        multiplier = self._default_retry["backoff_multiplier"]
        cap = task.retry_max_delay_seconds
        delay = base * (multiplier ** (attempt_number - 1))
        return min(delay, cap)

    async def _schedule_retry(
        self, session, task: Task, attempt: TaskAttempt, reason: str
    ) -> None:
        """Platform-owned retry: re-queue if attempts remain, else fail the task."""
        if task.attempt_count >= task.max_attempts:
            task.status = "failed"
            task.completed_at = _now()
            task.assigned_agent_id = None
            task.version = task.version + 1
            await self._log(
                session,
                task.workflow_run_id,
                "task",
                task.id,
                "task.failed",
                {"reason": reason},
            )
        else:
            delay = self._retry_delay(task, attempt.attempt_number)
            task.status = "pending"
            task.retry_at = _now() + timedelta(seconds=delay)
            task.assigned_agent_id = None
            task.started_at = None
            task.version = task.version + 1
            await self._log(
                session,
                task.workflow_run_id,
                "task",
                task.id,
                "task.retry_scheduled",
                {"delay": delay},
            )

    async def _finalize_run(self, run_id: str) -> None:
        """Reconcile the parent run in its own transaction.

        Runs after the task transaction commits so concurrent completions each
        observe the latest task set; the terminal ``UPDATE ... WHERE status ==
        'running'`` makes finalization idempotent under races.
        """
        async with self._sf() as session:
            statuses = list(
                (
                    await session.scalars(
                        select(Task.status).where(Task.workflow_run_id == run_id)
                    )
                ).all()
            )
            if not statuses:
                return
            total = len(statuses)
            now = _now()
            if all(s == "completed" for s in statuses):
                if self._qa_key is not None:
                    attestations = await session.scalar(
                        select(func.count(TaskQaAttestation.task_id))
                        .join(Task, Task.id == TaskQaAttestation.task_id)
                        .where(Task.workflow_run_id == run_id)
                    )
                    # A completed model output is not a completed SDLC run.
                    # Independently signed QA is required even for the last stage.
                    if attestations != total:
                        return
                res = await session.execute(
                    update(WorkflowRun)
                    .where(WorkflowRun.id == run_id, WorkflowRun.status == "running")
                    .values(
                        status="completed",
                        completed_at=now,
                        output_data={"tasks_completed": total},
                        version=WorkflowRun.version + 1,
                    )
                    .execution_options(synchronize_session=False)
                )
                if res.rowcount == 1:
                    await self._log(
                        session,
                        run_id,
                        "run",
                        run_id,
                        "run.completed",
                        {"tasks_completed": total},
                    )
            elif any(s == "failed" for s in statuses):
                res = await session.execute(
                    update(WorkflowRun)
                    .where(WorkflowRun.id == run_id, WorkflowRun.status == "running")
                    .values(
                        status="failed",
                        completed_at=now,
                        version=WorkflowRun.version + 1,
                    )
                    .execution_options(synchronize_session=False)
                )
                if res.rowcount == 1:
                    await self._log(
                        session,
                        run_id,
                        "run",
                        run_id,
                        "run.failed",
                        {"tasks_failed": sum(1 for s in statuses if s == "failed")},
                    )
            await session.commit()

    async def _consume_terminal_lease(
        self, session, attempt: TaskAttempt, agent_id: str,
        lease_token: str | None,
    ) -> None:
        """Atomically fence a terminal transition against renew/revoke.

        This guarded UPDATE is the serialization point. A previously revoked,
        expired, wrong-generation or mismatched token cannot submit/fail. The
        consumed capability and task/attempt transitions COMMIT together.
        Never log the plaintext credential or expose it to model tools.
        """
        if not self._require_lease:
            return
        if (
            not isinstance(lease_token, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{40,128}", lease_token)
        ):
            raise ConflictError("Active attempt lease required")
        digest = hashlib.sha256(lease_token.encode("ascii")).hexdigest()
        await acquire_lease_write_fence(session, attempt.id)
        # This timestamp MUST be sampled after the lock is acquired. A
        # writer held up behind I/O fencing may wait beyond lease expiry.
        checked_at = _now()
        changed = await session.execute(
            update(AttemptLease)
            .where(
                AttemptLease.attempt_id == attempt.id,
                AttemptLease.agent_id == agent_id,
                AttemptLease.generation == attempt.attempt_number,
                AttemptLease.token_sha256 == digest,
                AttemptLease.state == "active",
                AttemptLease.expires_at > checked_at,
                active_attempt_sql(agent_id),
            )
            .values(state="revoked")
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise ConflictError("Attempt lease invalid, expired, or revoked")

    async def submit(
        self, task_id: str, attempt_id: str, agent_id: str, output: dict,
        *, lease_token: str | None = None,
        git_artifact: dict | None = None,
    ) -> TaskAttempt:
        """Submit an attempt result. Only the engine may complete a task.

        Contract verification runs here; a submission that fails verification is
        recorded as ``verification_failed`` and the platform applies its retry
        policy. An agent can never force ``completed`` by asserting success.
        """
        run_id: Optional[str] = None
        async with self._sf() as session:
            attempt = await session.get(TaskAttempt, attempt_id)
            if attempt is None:
                raise NotFoundError(f"Attempt {attempt_id} not found")
            if attempt.task_id != task_id:
                raise ConflictError("Attempt does not belong to that task")
            if attempt.status != "running":
                raise StateTransitionError(f"Attempt {attempt_id} is {attempt.status}")
            if attempt.agent_id != agent_id:
                raise ConflictError("Agent is not the owner of this attempt")
            task = await session.get(Task, task_id, with_for_update=True)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found")
            if task.status != "in_progress":
                raise StateTransitionError(f"Task {task_id} is {task.status}")
            if self._require_lease and task.contract_id is None:
                raise ConflictError("Native task requires an explicit contract")
            run_id = task.workflow_run_id
            if git_artifact is not None:
                if lease_token is None or not self._require_lease:
                    raise ConflictError("Git evidence requires a live leased native attempt")
                if (
                    type(git_artifact) is not dict
                    or set(git_artifact) != {"commit_sha", "changed_paths"}
                    or type(git_artifact["commit_sha"]) is not str
                    or re.fullmatch(r"[0-9a-f]{40,64}", git_artifact["commit_sha"]) is None
                    or type(git_artifact["changed_paths"]) is not list
                    or not 1 <= len(git_artifact["changed_paths"]) <= 64
                    or any(type(path) is not str for path in git_artifact["changed_paths"])
                    or len(set(git_artifact["changed_paths"])) != len(git_artifact["changed_paths"])
                    or any(
                        type(path) is not str or len(path) > 256
                        or not path.startswith("out/")
                        or chr(92) in path
                        or any(part in ("", ".", "..") for part in path.split("/"))
                        for path in git_artifact["changed_paths"]
                    )
                ):
                    raise ConflictError("Malformed worker Git evidence")
            await self._consume_terminal_lease(session, attempt, agent_id, lease_token)

            verification = {"valid": True, "errors": []}
            if task.contract_id:
                contract = await session.get(Contract, task.contract_id)
                if contract is None:
                    raise ContractVerificationError(
                        f"Task {task_id} references missing contract {task.contract_id}"
                    )
                validator = Draft202012Validator(contract.schema)
                errors = [
                    str(err.message)
                    for err in sorted(
                        validator.iter_errors(output), key=lambda e: list(e.path)
                    )
                ]
                if errors:
                    verification = {"valid": False, "errors": errors}

            if not verification["valid"]:
                attempt.status = "verification_failed"
                attempt.completed_at = _now()
                attempt.verification_result = verification
                attempt.output_data = output
                attempt.error = "; ".join(verification["errors"])
                await self._log(
                    session,
                    run_id,
                    "attempt",
                    attempt.id,
                    "attempt.verification_failed",
                    {"errors": verification["errors"]},
                )
                await self._schedule_retry(
                    session, task, attempt, "contract verification failed"
                )
            else:
                attempt.status = "completed"
                attempt.completed_at = _now()
                attempt.output_data = output
                attempt.verification_result = verification
                task.output_data = output
                task.status = "completed"
                task.completed_at = _now()
                task.assigned_agent_id = None
                task.version = task.version + 1
                await self._log(
                    session,
                    run_id,
                    "attempt",
                    attempt.id,
                    "attempt.completed",
                    {"valid": True},
                )
                await self._log(session, run_id, "task", task.id, "task.completed", {})
                if git_artifact is not None:
                    session.add(TaskGitEvidence(
                        task_id=task.id, attempt_id=attempt.id,
                        commit_sha=git_artifact["commit_sha"],
                        changed_paths=git_artifact["changed_paths"],
                        provenance="worker_reported",
                    ))
                    await self._log(
                        session, run_id, "attempt", attempt.id, "attempt.git_reported",
                        {"commit_sha": git_artifact["commit_sha"],
                         "provenance": "worker_reported"},
                    )
                # Handoff is platform-owned and committed atomically alongside
                # Contract Gate completion. A failed/unverified attempt cannot
                # create a downstream artifact or unlock a stage.
                successors = list((await session.scalars(
                    select(TaskDependency.task_id).where(
                        TaskDependency.prerequisite_task_id == task.id
                    )
                )).all())
                summary = output.get("summary")
                summary_text = summary[:120] if type(summary) is str else ""
                for next_id in successors:
                    next_task = await session.get(Task, next_id, with_for_update=True)
                    if next_task is None or next_task.workflow_run_id != run_id:
                        raise ConflictError("Invalid trusted SDLC dependency")
                    context = dict(next_task.input_data or {})
                    previous = list(context.get("_maw_upstream", []))
                    if any(item.get("task_id") == task.id for item in previous):
                        raise ConflictError("Duplicate upstream stage handoff")
                    previous.append({
                        "task_id": task.id,
                        "stage": task.title[:120],
                        "summary": summary_text,
                    })
                    context["_maw_upstream"] = previous
                    next_task.input_data = context
                    next_task.version += 1
                    await self._log(
                        session, run_id, "task", next_task.id,
                        "task.upstream_verified", {"predecessor_id": task.id},
                    )

            await session.execute(
                update(Agent)
                .where(Agent.id == attempt.agent_id)
                .values(status="idle", version=Agent.version + 1)
                .execution_options(synchronize_session=False)
            )
            await session.commit()
        if run_id is not None:
            await self._finalize_run(run_id)
        return attempt

    async def fail_attempt(
        self, task_id: str, attempt_id: str, agent_id: str, error: str,
        *, lease_token: str | None = None,
    ) -> TaskAttempt:
        run_id: Optional[str] = None
        async with self._sf() as session:
            attempt = await session.get(TaskAttempt, attempt_id)
            if attempt is None:
                raise NotFoundError(f"Attempt {attempt_id} not found")
            if attempt.task_id != task_id:
                raise ConflictError("Attempt does not belong to that task")
            if attempt.status != "running":
                raise StateTransitionError(f"Attempt {attempt_id} is {attempt.status}")
            if attempt.agent_id != agent_id:
                raise ConflictError("Agent is not the owner of this attempt")
            task = await session.get(Task, task_id, with_for_update=True)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found")
            run_id = task.workflow_run_id
            await self._consume_terminal_lease(session, attempt, agent_id, lease_token)
            attempt.status = "failed"
            attempt.completed_at = _now()
            attempt.error = error
            await self._log(
                session, run_id, "attempt", attempt.id, "attempt.failed", {"error": error}
            )
            await self._schedule_retry(session, task, attempt, error)
            await session.execute(
                update(Agent)
                .where(Agent.id == attempt.agent_id)
                .values(status="idle", version=Agent.version + 1)
                .execution_options(synchronize_session=False)
            )
            await session.flush()
            await session.commit()
        if run_id is not None:
            await self._finalize_run(run_id)
        return attempt

    async def block_task(self, task_id: str, agent_id: str, reason: str) -> Task:
        async with self._sf() as session:
            task = await session.get(Task, task_id, with_for_update=True)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found")
            if task.status in TERMINAL_TASK_STATUSES:
                raise StateTransitionError(f"Task {task_id} is terminal ({task.status})")
            task.status = "blocked"
            task.assigned_agent_id = None
            task.version = task.version + 1
            await self._log(
                session,
                task.workflow_run_id,
                "task",
                task.id,
                "task.blocked",
                {"reason": reason, "agent": agent_id},
            )
            await session.commit()
            return task

    # ---------- durability / recovery ----------
    async def reconcile_quarantined_task(
        self,
        task_id: str,
        *,
        decision: str,
        evidence_ref: str,
        evidence_sha256: str,
        operator_subject: str,
    ) -> TaskReconciliation:
        """Audit an administrator's evidence attestation; NEVER requeue work.

        Only tasks with an actual recovery_quarantined event and interrupted
        attempt are eligible. One row per task ensures at most one confirmed
        decision, including when competing admins race. UNKNOWN may be upgraded
        later, with immutable SagaEvents recording both decisions.
        """
        import re

        if decision not in (
            "UNKNOWN", "CONFIRMED_SIDE_EFFECT", "CONFIRMED_NO_SIDE_EFFECT",
        ):
            raise BusinessRuleError("Invalid reconciliation decision")
        if (
            not isinstance(evidence_ref, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,159}", evidence_ref)
            or not isinstance(evidence_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256)
        ):
            raise BusinessRuleError("Evidence reference and SHA-256 digest required")
        if (
            not isinstance(operator_subject, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", operator_subject)
        ):
            raise BusinessRuleError("Trusted operator subject required")

        async with self._sf() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise NotFoundError("Task not found")
            if task.status != "blocked":
                raise StateTransitionError("Only quarantined tasks can be reconciled")
            quarantine = await session.scalar(
                select(SagaEvent.id).where(
                    SagaEvent.aggregate_type == "task",
                    SagaEvent.aggregate_id == task_id,
                    SagaEvent.event_type == "task.recovery_quarantined",
                ).limit(1)
            )
            interrupted = await session.scalar(
                select(TaskAttempt.id).where(
                    TaskAttempt.task_id == task_id,
                    TaskAttempt.status == "interrupted",
                ).limit(1)
            )
            if quarantine is None or interrupted is None:
                raise StateTransitionError("Task is not a recovered quarantine")

            record = await session.get(TaskReconciliation, task_id)
            if record is None:
                record = TaskReconciliation(
                    task_id=task_id, decision=decision,
                    evidence_ref=evidence_ref, evidence_sha256=evidence_sha256,
                    operator_subject=operator_subject, decided_at=_now(),
                )
                session.add(record)
                try:
                    await session.flush()
                except IntegrityError as exc:
                    await session.rollback()
                    raise ConflictError("Reconciliation already recorded") from exc
            elif record.decision != "UNKNOWN":
                raise ConflictError("Reconciliation already confirmed")
            elif decision == "UNKNOWN":
                raise ConflictError("UNKNOWN attestation already recorded")
            else:
                result = await session.execute(
                    update(TaskReconciliation).where(
                        TaskReconciliation.task_id == task_id,
                        TaskReconciliation.decision == "UNKNOWN",
                    ).values(
                        decision=decision,
                        evidence_ref=evidence_ref,
                        evidence_sha256=evidence_sha256,
                        operator_subject=operator_subject,
                        decided_at=_now(),
                    ).execution_options(synchronize_session=False)
                )
                if result.rowcount != 1:
                    raise ConflictError("Concurrent reconciliation already confirmed")
                await session.refresh(record)

            await self._log(
                session, task.workflow_run_id, "task", task_id,
                "task.reconciliation_attested", {
                    "decision": decision,
                    "evidence_ref": evidence_ref,
                    "evidence_sha256": evidence_sha256,
                    "operator_subject": operator_subject,
                },
            )
            await session.commit()
            return record

    async def recover(self) -> dict:
        """Reconcile incomplete state after a server restart.

        Running attempts are interrupted and in-progress tasks are
        QUARANTINED as blocked, not requeued. A tool might have performed a
        side effect before the crash, and new model tool IDs do not prove
        replay safety. Agents previously marked busy become inactive rather
        than immediately claimable: external worker processes may still be
        running after the server restarts. An operator must reconcile the
        ledger, worker liveness and side effects before safely provisioning
        new worker identities. Terminal states remain unchanged. Repeated
        recovery is idempotent.
        """
        recovered_attempts = 0
        recovered_tasks = 0
        async with self._sf() as session:
            running = list(
                (
                    await session.scalars(
                        select(TaskAttempt).where(TaskAttempt.status == "running")
                    )
                ).all()
            )
            for attempt in running:
                attempt.status = "interrupted"
                attempt.completed_at = _now()
                attempt.error = "interrupted by server restart"
                await self._log(session, None, "attempt", attempt.id, "attempt.interrupted", {})
                recovered_attempts += 1
            in_progress = list(
                (
                    await session.scalars(
                        select(Task).where(Task.status == "in_progress")
                    )
                ).all()
            )
            for task in in_progress:
                task.status = "blocked"
                task.assigned_agent_id = None
                task.started_at = None
                task.retry_at = None
                task.version = task.version + 1
                await self._log(
                    session, task.workflow_run_id, "task", task.id,
                    "task.recovery_quarantined",
                    {"reason": "interrupted_attempt_requires_reconciliation"},
                )
                recovered_tasks += 1
            if self._require_lease:
                # Crash quarantine and capability revocation must COMMIT in
                # the same transaction: a stale submit/renew cannot revive
                # an interrupted attempt after recovery.
                await session.execute(
                    update(AttemptLease)
                    .where(AttemptLease.state == "active")
                    .values(state="revoked")
                    .execution_options(synchronize_session=False)
                )
            # A remote worker might survive a server restart; never make
            # its identity immediately eligible for another claim. Only an
            # explicitly provisioned idle agent can execute new work.
            await session.execute(
                update(Agent)
                .where(Agent.status == "busy")
                .values(status="inactive", version=Agent.version + 1)
                .execution_options(synchronize_session=False)
            )
            await session.commit()
        return {
            "recovered_attempts": recovered_attempts,
            "recovered_tasks": recovered_tasks,
        }

    async def ready_tasks(self, limit: int = 20) -> list[dict]:
        """Read-only native scheduler candidates; claim_task remains authority.

        Never mark a task running here. Dispatcher must atomically claim the
        selected ID; stale candidates are harmless under conditional UPDATE.
        """
        if type(limit) is not int or not 1 <= limit <= 100:
            raise BusinessRuleError("Ready task limit must be 1..100")
        async with self._sf() as session:
            pending = (await session.scalars(
                select(Task)
                .join(WorkflowRun, WorkflowRun.id == Task.workflow_run_id)
                .where(Task.status == "pending", WorkflowRun.status == "running")
                .order_by(Task.priority.desc(), Task.created_at, Task.id)
            )).all()
            result = []
            now = _now()
            for task in pending:
                if task.retry_at is not None and _aware(task.retry_at) > now:
                    continue
                dependencies = (await session.execute(
                    select(Task.id, Task.status)
                    .join(TaskDependency, Task.id == TaskDependency.prerequisite_task_id)
                    .where(TaskDependency.task_id == task.id)
                )).all()
                if any(status != "completed" for _, status in dependencies):
                    continue
                if self._qa_key is not None:
                    complete = True
                    for dependency_id, _ in dependencies:
                        if await session.get(TaskQaAttestation, dependency_id) is None:
                            complete = False
                            break
                    if not complete:
                        continue
                if self._require_lease and task.contract_id is None:
                    continue
                result.append({
                    "task_id": task.id,
                    "run_id": task.workflow_run_id,
                    "contract_id": task.contract_id,
                    "priority": task.priority,
                })
                if len(result) == limit:
                    break
            return result

    async def tick(self) -> int:
        """Advance due retries: pending tasks whose retry window has elapsed become claimable."""
        promoted = 0
        async with self._sf() as session:
            due = list(
                (
                    await session.scalars(
                        select(Task)
                        .where(Task.status == "pending")
                        .where(Task.retry_at.is_not(None))
                    )
                ).all()
            )
            now = _now()
            for task in [t for t in due if _aware(t.retry_at) <= now]:
                task.retry_at = None
                task.version = task.version + 1
                await self._log(
                    session,
                    task.workflow_run_id,
                    "task",
                    task.id,
                    "task.retry_window_opened",
                    {},
                )
                promoted += 1
            await session.commit()
        return promoted
