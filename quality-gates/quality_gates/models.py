"""SQLAlchemy ORM models for the quality-gates subsystem.

Persistence is deliberately focused on what the acceptance criteria require:

* ``gate_runs``      -- one row per execution of a gate against a task/workspace.
* ``evidence_items`` -- auditable, immutable evidence produced by a run. Each
   item stores its SHA-256 checksum and is append-only; existing rows are never
   mutated, so the audit trail is tamper-evident.
* ``release_candidates`` -- verifiable release artifacts awaiting human approval.

The schema is SQLite/PostgreSQL-compatible (no SQLite-only column types used
beyond the standard ones), matching the other subsystems in this repository.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base shared by all quality-gates models."""


class GateRun(Base):
    __tablename__ = "gate_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    gate_name: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/running/passed/failed/blocked
    summary: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Serialized reference to where the full run report lives (evidence_root).
    report_path: Mapped[str | None] = mapped_column(String(500), nullable=True)


class EvidenceItem(Base):
    __tablename__ = "evidence_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("gate_runs.id"), index=True)
    category: Mapped[str] = mapped_column(String(32), index=True)  # unit/integration/lint/style/arch/dep/secret/release
    key: Mapped[str] = mapped_column(String(120))
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Immutability guard: evidence rows are write-once. Construction sets each
    # column once; any later assignment to a column that already has a value is
    # refused so the audit trail cannot be silently rewritten.
    def __setattr__(self, name: str, value: object) -> None:
        if name.startswith("_"):
            return super().__setattr__(name, value)
        if name in {"id", "created_at"}:
            # id/created_at have DB defaults; allow assignment but keep it simple.
            return super().__setattr__(name, value)
        # Block re-assignment of columns that already hold a value.
        try:
            existing = getattr(self, name)
        except Exception:
            existing = None
        if existing is not None:
            raise AttributeError(
                f"EvidenceItem.{name} is immutable after creation (audit trail)"
            )
        super().__setattr__(name, value)


class ReleaseCandidate(Base):
    __tablename__ = "release_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="draft")  # draft/awaiting_approval/approved/rejected
    release_notes: Mapped[str] = mapped_column(Text, default="")
    artifact_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    artifact_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
