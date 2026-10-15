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

import os
import re
import sqlite3
import stat
from contextlib import closing, contextmanager
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
        self.timeout_seconds = timeout_seconds
        self._verify_path()

    def _verify_path(self) -> None:
        try:
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
                    yield
                finally:
                    # No changes are made here. Releasing the transaction only
                    # AFTER the operation returns establishes the fence barrier.
                    conn.rollback()
        except sqlite3.Error as exc:
            raise AttemptFenceDenied("Trusted attempt state unavailable") from exc
