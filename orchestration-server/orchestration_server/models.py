"""SQLAlchemy async models for the orchestration server."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)

    workspaces = relationship("Workspace", back_populates="project")


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_workspace_project_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)

    project: Mapped["Project"] = relationship(back_populates="workspaces")


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (UniqueConstraint("project_id", "name", name="uq_contract_project_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema: Mapped[dict] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (CheckConstraint("status IN ('inactive','idle','busy','terminated')", name="ck_agent_status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle", server_default="idle")
    agent_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)


class WorkflowDefinition(Base):
    """Design-time workflow definition (the persisted editor document).

    Owned by the orchestration server (ADR-102: orchestration is the source of
    truth for design-time definitions, not the agent-management or runtime
    subsystems). ``definition`` holds the canonical workflow document
    (schema_version/metadata/nodes/edges) and ``version`` is an optimistic-lock
    revision counter bumped on every update. ``current_version_id`` points at
    the newest immutable :class:`WorkflowVersion` snapshot when one has been
    saved via the /versions API.
    """

    __tablename__ = "workflow_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    current_version_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc
    )

    versions = relationship(
        "WorkflowVersion",
        back_populates="definition",
        cascade="all, delete-orphan",
        order_by="WorkflowVersion.version_number",
    )


class WorkflowVersion(Base):
    """Immutable snapshot of a workflow definition at a point in time.

    Created through POST /workflows/definitions/{id}/versions. ``version_number``
    is a per-definition monotonic counter (1, 2, ...); ``definition_snapshot`` is
    the exact document bytes captured at save time (never mutated afterwards).
    """

    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_definition_id", "version_number", name="uq_wf_version_number"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_definition_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_definitions.id"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    changelog: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now()
    )

    definition: Mapped["WorkflowDefinition"] = relationship(back_populates="versions")


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (CheckConstraint("status IN ('pending','running','completed','failed','cancelled')", name="ck_run_status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    input_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    retry_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)

    tasks = relationship("Task", back_populates="run", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('pending','in_progress','completed','failed','blocked')", name="ck_task_status"),
        Index("ix_task_run_status", "workflow_run_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    workflow_run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), nullable=False, index=True)
    node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id"), nullable=True)
    input_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    retry_base_delay_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retry_max_delay_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)

    run: Mapped["WorkflowRun"] = relationship(back_populates="tasks")
    attempts = relationship("TaskAttempt", back_populates="task", cascade="all, delete-orphan")


class TaskDependency(Base):
    """Immutable per-run ordering edge. New table, no destructive migration.

    Edges are inserted only by the platform at launch; the model cannot
    modify the graph or choose which prerequisite was verified.
    """
    __tablename__ = "task_dependencies"
    __table_args__ = (
        UniqueConstraint("task_id", "prerequisite_task_id", name="uq_task_dependency"),
        CheckConstraint("task_id != prerequisite_task_id", name="ck_no_self_dependency"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    prerequisite_task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id"), nullable=False, index=True,
    )


class TaskAttempt(Base):
    __tablename__ = "task_attempts"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_number", name="uq_attempt_task_number"),
        CheckConstraint("status IN ('running','completed','failed','verification_failed','interrupted')", name="ck_attempt_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    input_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    verification_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, onupdate=now_utc)

    task: Mapped["Task"] = relationship(back_populates="attempts")




class TaskGitEvidence(Base):
    """Unverified-by-server SHA reported by a leased trusted worker.

    Do not use this as proof of independent QA or remote Git publication.
    The only verified server fact is the success of Contract Gate.
    """
    __tablename__ = "task_git_evidence"

    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("task_attempts.id"), primary_key=True,
    )
    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id"), nullable=False, index=True,
    )
    commit_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_paths: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    provenance: Mapped[str] = mapped_column(
        String(32), nullable=False, default="worker_reported",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc,
    )


class AttemptLease(Base):
    """Server-issued short-lived capability; only its SHA-256 digest is stored.

    Separate table avoids intrusive changes to old task_attempts schemas.
    Unique attempt_id and monotonic attempt_number prevent issuing two live
    credentials for the same attempt/generation.
    """

    __tablename__ = "attempt_leases"
    __table_args__ = (
        CheckConstraint("state IN ('active','revoked')", name="ck_attempt_lease_state"),
    )

    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("task_attempts.id"), primary_key=True,
    )
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), nullable=False)
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(12), nullable=False, default="active",
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    renewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )


class TaskReconciliation(Base):
    """One persisted operator decision per recovered task.

    UNKNOWN can be upgraded once to a confirmed result; the immutable SagaEvent
    history records every decision. This table NEVER makes a task runnable.
    """
    __tablename__ = "task_reconciliations"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('UNKNOWN','CONFIRMED_SIDE_EFFECT','CONFIRMED_NO_SIDE_EFFECT')",
            name="ck_task_reconciliation_decision",
        ),
    )

    task_id: Mapped[str] = mapped_column(
        ForeignKey("tasks.id"), primary_key=True,
    )
    decision: Mapped[str] = mapped_column(String(40), nullable=False)
    evidence_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    operator_subject: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now_utc,
    )



class SagaEvent(Base):
    __tablename__ = "saga_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc, server_default=func.now())