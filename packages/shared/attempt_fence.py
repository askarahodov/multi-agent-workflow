"""SQLite-only, cross-process fencing of native tool I/O against server state.

The control plane alone binds run/task/attempt/agent IDs from a successful
claim; none of these values may originate from a model tool call. BEGIN
IMMEDIATE holds the same database writer lock required by OrchestrationEngine
state changes until the filesystem action returns. Thus recovery cannot
COMMIT a revoked attempt while an action admitted by this gate is still
executing. This is NOT a remote/PostgreSQL lease, a sandbox, or a general
exactly-once protocol.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
import stat
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import quote

_SERVER_ID = re.compile(r"[A-Za-z0-9-]{1,64}\Z")


class AttemptFenceDenied(Exception):
    """Sanitized refusal: do not include SQL, paths, tokens or tool contents."""


class TrustedSqliteAttemptFence:
    """Hold the orchestration SQLite write barrier across one filesystem action.

    Only suitable for trusted, co-located executors with shared *local*
    SQLite locking. The database must be private (0600) and outside the
    model-writable workspace. Remote workers and PostgreSQL require a
    separately authenticated, privileged tool gateway and lease protocol.
    """

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        *,
        run_id: str,
        task_id: str,
        attempt_id: str,
        agent_id: str,
        timeout_seconds: float = 5.0,
        lease_token: str | None = None,
        require_lease: bool = False,
    ) -> None:
        if not isinstance(database_path, (str, os.PathLike)):
            raise TypeError("Trusted SQLite database path required")
        path = Path(database_path)
        if not path.is_absolute():
            raise ValueError("Trusted SQLite database path must be absolute")
        if not (0 < timeout_seconds <= 30):
            raise ValueError("Fencing lock timeout must be from 0 to 30 seconds")
        for identifier in (run_id, task_id, attempt_id, agent_id):
            if not isinstance(identifier, str) or not _SERVER_ID.fullmatch(identifier):
                raise ValueError("Invalid control-plane attempt identity")
        self.path = path
        self.run_id = run_id
        self.task_id = task_id
        self.attempt_id = attempt_id
        self.agent_id = agent_id
        self.execution_scope = f"run-{run_id}/attempt-{attempt_id}"
        if require_lease and not lease_token:
            raise ValueError("An active server-issued lease token is required")
        if lease_token is not None and (
            not isinstance(lease_token, str) or not 20 <= len(lease_token) <= 128
        ):
            raise ValueError("Invalid server-issued lease token")
        self.lease_token = lease_token
        self.require_lease = require_lease
        self.timeout_seconds = timeout_seconds
        self._verify_path()

    def _verify_path(self) -> None:
        try:
            # lstat() on the final component is NOT enough: a symlinked
            # ancestor could redirect SQLite into an agent-owned workspace.
            # Reject such aliases both on construction and each I/O gate.
            if any(parent.is_symlink() for parent in self.path.parents):
                raise AttemptFenceDenied("Trusted attempt state unavailable")
            st = os.lstat(self.path)
        except OSError as exc:
            raise AttemptFenceDenied("Trusted attempt state unavailable") from exc
        if (
            not stat.S_ISREG(st.st_mode)
            or st.st_nlink != 1
            or st.st_mode & 0o077
            or (hasattr(os, "geteuid") and st.st_uid != os.geteuid())
        ):
            raise AttemptFenceDenied("Trusted attempt state unavailable")

    @contextmanager
    def operation(self) -> Iterator[None]:
        """No attempt may be marked revoked while admitted I/O is in flight.

        SQLite BEGIN IMMEDIATE serializes against server recovery/submit/fail.
        Recovery must wait for an in-flight write before its transaction can
        commit. After recovery commits, no new write can pass this check.
        If acquiring the barrier fails or the DB is stale, fail closed.
        """
        self._verify_path()
        uri = "file:" + quote(str(self.path), safe="/") + "?mode=rw"
        try:
            with closing(sqlite3.connect(
                uri, uri=True, timeout=self.timeout_seconds,
                isolation_level=None,
            )) as conn:
                try:
                    conn.execute("BEGIN IMMEDIATE")
                    row = conn.execute(
                        "SELECT a.status, t.status, t.assigned_agent_id, "
                        "a.agent_id, g.status, r.status "
                        "FROM task_attempts a "
                        "JOIN tasks t ON t.id = a.task_id "
                        "JOIN agents g ON g.id = a.agent_id "
                        "JOIN workflow_runs r ON r.id = t.workflow_run_id "
                        "WHERE a.id = ? AND t.id = ? AND t.workflow_run_id = ? "
                        "AND a.attempt_number = t.attempt_count",
                        (self.attempt_id, self.task_id, self.run_id),
                    ).fetchone()
                    if row != (
                        "running", "in_progress", self.agent_id,
                        self.agent_id, "busy", "running",
                    ):
                        raise AttemptFenceDenied("Attempt lease is no longer active")
                    if self.require_lease or self.lease_token is not None:
                        # Token check and the actual I/O run under the SAME
                        # SQLite writer lock used by revoke/renew transitions.
                        # Never store or audit a plaintext lease credential.
                        current = conn.execute(
                            "SELECT l.state, l.agent_id, l.generation, "
                            "l.token_sha256, l.expires_at, a.attempt_number "
                            "FROM attempt_leases l "
                            "JOIN task_attempts a ON a.id = l.attempt_id "
                            "WHERE l.attempt_id = ?",
                            (self.attempt_id,),
                        ).fetchone()
                        if current is None or self.lease_token is None:
                            raise AttemptFenceDenied("Attempt lease is unavailable")
                        state, agent, generation, digest, expiration, attempt_no = current
                        try:
                            expires = datetime.fromisoformat(expiration)
                            if expires.tzinfo is None:
                                expires = expires.replace(tzinfo=timezone.utc)
                        except (ValueError, TypeError):
                            raise AttemptFenceDenied("Attempt lease is invalid") from None
                        expected = hashlib.sha256(self.lease_token.encode("utf-8")).hexdigest()
                        if (
                            state != "active" or agent != self.agent_id
                            or generation != attempt_no
                            or expires <= datetime.now(timezone.utc)
                            or not hmac.compare_digest(digest, expected)
                        ):
                            raise AttemptFenceDenied("Attempt lease is no longer active")
                    yield
                finally:
                    # No changes are made here. Releasing the transaction only
                    # AFTER the operation returns establishes the fence barrier.
                    conn.rollback()
        except sqlite3.Error as exc:
            raise AttemptFenceDenied("Trusted attempt state unavailable") from exc
