"""Durable server-owned attempt capability lifecycle (no LLM/provider calls).

A grant is minted only after a trusted claim, persisted as a hash, and
returned ONCE to the claiming HTTP client. Lost grants cannot be reissued:
operator recovery/quarantine is required, not unsafe automatic replay.

Validation/renewal alone does NOT fence side effects already in flight. A
trusted SQLite tool executor may additionally hold shared.attempt_fence's
transaction barrier. Remote/PostgreSQL tool gateways need their own barrier.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

from .errors import ConflictError
from .models import Agent, AttemptLease, Task, TaskAttempt, WorkflowRun


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def active_attempt_sql(agent_id: str):
    """Correlated DB predicate used *inside* guarded UPDATE transactions.

    Checking an ORM snapshot before a write is not sufficient: another
    process may have blocked/recovered an attempt in the meantime. This
    predicate is evaluated while acquiring the lease write fence.
    """
    return (
        select(TaskAttempt.id)
        .join(Task, Task.id == TaskAttempt.task_id)
        .join(WorkflowRun, WorkflowRun.id == Task.workflow_run_id)
        .join(Agent, Agent.id == TaskAttempt.agent_id)
        .where(
            TaskAttempt.id == AttemptLease.attempt_id,
            TaskAttempt.status == "running",
            TaskAttempt.agent_id == agent_id,
            TaskAttempt.attempt_number == AttemptLease.generation,
            Task.status == "in_progress",
            Task.assigned_agent_id == agent_id,
            Task.attempt_count == AttemptLease.generation,
            Agent.status == "busy",
            WorkflowRun.status == "running",
        )
        .exists()
    )


async def acquire_lease_write_fence(session, attempt_id: str) -> None:
    """Acquire the SQLite writer / PostgreSQL row lock BEFORE reading the clock.

    A SELECT FOR UPDATE does not lock SQLite, so use a conditional no-op
    UPDATE in both databases. The lock lasts until commit or rollback.
    A later lease expiry comparison cannot use a timestamp captured while
    waiting for another writer to finish.
    """
    locked = await session.execute(
        update(AttemptLease)
        .where(AttemptLease.attempt_id == attempt_id)
        .values(state=AttemptLease.state)
        .execution_options(synchronize_session=False)
    )
    if locked.rowcount != 1:
        raise ConflictError("Attempt lease missing or unavailable")


@dataclass(frozen=True)
class LeaseGrant:
    """Opaque token is deliberately never stored in model rows or logs."""

    token: str
    expires_at: datetime
    generation: int


class AttemptLeaseService:
    """Fail-closed, opt-in capability issuance and renewal."""

    def __init__(
        self, session_factory: async_sessionmaker, *,
        ttl_seconds: int = 60,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(ttl_seconds, int) or not 5 <= ttl_seconds <= 300:
            raise ValueError("Attempt lease TTL must be between 5 and 300 seconds")
        self._sf = session_factory
        self._ttl = ttl_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self) -> datetime:
        return utc(self._clock())

    async def _active(self, session, attempt_id: str, agent_id: str) -> TaskAttempt:
        attempt = await session.get(TaskAttempt, attempt_id)
        if attempt is None or attempt.agent_id != agent_id or attempt.status != "running":
            raise ConflictError("Attempt is not active")
        task = await session.get(Task, attempt.task_id)
        if (
            task is None or task.status != "in_progress"
            or task.assigned_agent_id != agent_id
            or attempt.attempt_number != task.attempt_count
        ):
            raise ConflictError("Attempt is no longer assigned")
        agent = await session.get(Agent, agent_id)
        if agent is None or agent.status != "busy":
            raise ConflictError("Agent is no longer active")
        run = await session.get(WorkflowRun, task.workflow_run_id)
        if run is None or run.status != "running":
            raise ConflictError("Workflow run is not active")
        return attempt

    async def issue(self, attempt_id: str, agent_id: str) -> LeaseGrant:
        """Mint only once; original secret never materializes in database."""
        secret = secrets.token_urlsafe(32)
        digest = hashlib.sha256(secret.encode("ascii")).hexdigest()
        async with self._sf() as session:
            try:
                # Acquire the writer/row lock BEFORE checking current state
                # or sampling the TTL. SELECT FOR UPDATE does not lock SQLite.
                # The attempt row exists even though its lease does not yet.
                locked = await session.execute(
                    update(TaskAttempt)
                    .where(
                        TaskAttempt.id == attempt_id,
                        TaskAttempt.agent_id == agent_id,
                        TaskAttempt.status == "running",
                    )
                    .values(status=TaskAttempt.status)
                    .execution_options(synchronize_session=False)
                )
                if locked.rowcount != 1:
                    raise ConflictError("Attempt is not active")
                attempt = await self._active(session, attempt_id, agent_id)
                if await session.get(AttemptLease, attempt_id) is not None:
                    raise ConflictError("Attempt lease already issued")
                # If a prior writer stalled issuance, issue a FRESH TTL.
                now = self._now()
                session.add(AttemptLease(
                    attempt_id=attempt_id, agent_id=agent_id,
                    generation=attempt.attempt_number, token_sha256=digest,
                    state="active", issued_at=now,
                    expires_at=now + timedelta(seconds=self._ttl),
                ))
                await session.commit()
            except (IntegrityError, OperationalError) as exc:
                await session.rollback()
                raise ConflictError("Attempt lease cannot be issued") from exc
        return LeaseGrant(secret, now + timedelta(seconds=self._ttl), attempt.attempt_number)

    async def validate(
        self, attempt_id: str, agent_id: str, token: str,
    ) -> bool:
        """Read-only capability test. NEVER a replacement for a tool I/O barrier."""
        if not isinstance(token, str) or not 20 <= len(token) <= 128:
            return False
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        async with self._sf() as session:
            lease = await session.get(AttemptLease, attempt_id)
            if (
                lease is None or lease.agent_id != agent_id
                or lease.state != "active" or utc(lease.expires_at) <= self._now()
                or not hmac.compare_digest(lease.token_sha256, digest)
            ):
                return False
            try:
                attempt = await self._active(session, attempt_id, agent_id)
            except ConflictError:
                return False
            return attempt.attempt_number == lease.generation

    async def renew(
        self, attempt_id: str, agent_id: str, token: str, *,
        task_id: str | None = None,
    ) -> LeaseGrant:
        """Renew only BEFORE expiry; an expired/revoked token cannot revive."""
        if not isinstance(token, str) or not 20 <= len(token) <= 128:
            raise ConflictError("Attempt lease invalid or expired")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        async with self._sf() as session:
            lease = await session.get(AttemptLease, attempt_id, with_for_update=True)
            if lease is None:
                raise ConflictError("Attempt lease invalid or expired")
            await acquire_lease_write_fence(session, attempt_id)
            now = self._now()
            if (
                lease.agent_id != agent_id
                or lease.state != "active"
                or utc(lease.expires_at) <= now
                or not hmac.compare_digest(lease.token_sha256, digest)
            ):
                raise ConflictError("Attempt lease invalid or expired")
            attempt = await self._active(session, attempt_id, agent_id)
            if task_id is not None and task_id != attempt.task_id:
                raise ConflictError("Attempt does not belong to this task")
            if lease.generation != attempt.attempt_number:
                raise ConflictError("Attempt generation invalid")
            # Compare-and-swap in SQL: a concurrent terminal submission,
            # admin revoke or another renewal must serialize with this write.
            expires = now + timedelta(seconds=self._ttl)
            changed = await session.execute(
                update(AttemptLease)
                .where(
                    AttemptLease.attempt_id == attempt_id,
                    AttemptLease.agent_id == agent_id,
                    AttemptLease.state == "active",
                    AttemptLease.token_sha256 == digest,
                    AttemptLease.generation == attempt.attempt_number,
                    AttemptLease.expires_at > now,
                    active_attempt_sql(agent_id),
                )
                .values(expires_at=expires, renewed_at=now)
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise ConflictError("Attempt lease invalid or expired")
            try:
                await session.commit()
            except (IntegrityError, OperationalError) as exc:
                await session.rollback()
                raise ConflictError("Attempt lease renewal unavailable") from exc
            return LeaseGrant(token, expires, lease.generation)

    async def revoke(self, attempt_id: str) -> bool:
        """Trusted control-plane action, idempotent; never requeues a task."""
        async with self._sf() as session:
            changed = await session.execute(
                update(AttemptLease)
                .where(
                    AttemptLease.attempt_id == attempt_id,
                    AttemptLease.state == "active",
                )
                .values(state="revoked")
                .execution_options(synchronize_session=False)
            )
            await session.commit()
            return changed.rowcount == 1
