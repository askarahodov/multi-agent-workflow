"""Durable at-most-once claim ledger for native tool execution.

The DB path and execution scope are provided exclusively by the trusted
control plane. Never put this file inside an agent-visible workspace.
A crash after claim but before result keeps CLAIMED; recovery MUST NOT replay
the operation automatically. This prevents duplicate side effects at the cost
of manual reconciliation of ambiguous executions.
"""
from __future__ import annotations

import os
import re
import sqlite3
import stat
from pathlib import Path

from .errors import ToolPolicyDenied

_SCOPE_PATTERN = re.compile(r"[A-Za-z0-9_./:-]{1,192}\Z")
_STATES = frozenset({"SUCCEEDED", "DENIED"})


class SqliteToolLedger:
    """Cross-process claim storage. No tool arguments or content are persisted."""

    def __init__(self, database_path: str | os.PathLike[str]) -> None:
        if not isinstance(database_path, (str, os.PathLike)):
            raise TypeError("Trusted database path is required")
        target = Path(database_path)
        if not target.is_absolute():
            raise ValueError("Ledger path must be absolute and control-plane-owned")
        if not target.parent.is_dir():
            raise ValueError("Ledger parent directory must exist")
        if target.is_symlink():
            raise ToolPolicyDenied("Ledger cannot be a symbolic link")
        self.path = target.resolve(strict=False)
        # The trusted parent and database must not be writable by the agent.
        if self.path.exists():
            self._verify_file()
        else:
            try:
                fd = os.open(
                    str(self.path),
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except FileExistsError:
                self._verify_file()
            else:
                os.close(fd)
        self._verify_file()
        try:
            with self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS tool_execution (
                      scope TEXT NOT NULL,
                      call_id TEXT NOT NULL,
                      name TEXT NOT NULL,
                      state TEXT NOT NULL CHECK (
                        state IN ('CLAIMED', 'SUCCEEDED', 'DENIED')
                      ),
                      PRIMARY KEY (scope, call_id)
                    )
                """)
        except sqlite3.Error as exc:
            raise ToolPolicyDenied("Tool execution ledger unavailable") from exc

    def _verify_file(self) -> None:
        try:
            st = os.lstat(self.path)
        except OSError as exc:
            raise ToolPolicyDenied("Tool execution ledger unavailable") from exc
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
            raise ToolPolicyDenied("Ledger file must be private and regular")

    def _connect(self) -> sqlite3.Connection:
        self._verify_file()
        return sqlite3.connect(str(self.path), timeout=5.0, isolation_level=None)

    @staticmethod
    def _validate(scope: str, call_id: str) -> None:
        if (
            not isinstance(scope, str)
            or not _SCOPE_PATTERN.fullmatch(scope)
            or not isinstance(call_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", call_id)
        ):
            raise ToolPolicyDenied("Invalid trusted execution ledger identity")

    def claim(self, scope: str, call_id: str, name: str) -> bool:
        """Durably reserve the ID BEFORE any operation is attempted."""
        self._validate(scope, call_id)
        if not isinstance(name, str) or len(name) > 64:
            raise ToolPolicyDenied("Invalid ledger tool name")
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    conn.execute(
                        "INSERT INTO tool_execution (scope, call_id, name, state) "
                        "VALUES (?, ?, ?, 'CLAIMED')",
                        (scope, call_id, name),
                    )
                except sqlite3.IntegrityError:
                    conn.rollback()
                    return False
                conn.commit()
                return True
        except sqlite3.Error as exc:
            raise ToolPolicyDenied("Tool execution ledger unavailable") from exc

    def finalize(self, scope: str, call_id: str, *, ok: bool) -> None:
        """Finalize an existing claim; never make a new claim implicitly."""
        self._validate(scope, call_id)
        state = "SUCCEEDED" if ok else "DENIED"
        assert state in _STATES
        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                updated = conn.execute(
                    "UPDATE tool_execution SET state = ? "
                    "WHERE scope = ? AND call_id = ? AND state = 'CLAIMED'",
                    (state, scope, call_id),
                )
                if updated.rowcount != 1:
                    conn.rollback()
                    raise ToolPolicyDenied("Tool ledger claim no longer active")
                conn.commit()
        except sqlite3.Error as exc:
            raise ToolPolicyDenied("Tool execution ledger unavailable") from exc

    def state(self, scope: str, call_id: str) -> str | None:
        """Trusted recovery inspection only; CLAIMED requires reconciliation."""
        self._validate(scope, call_id)
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT state FROM tool_execution WHERE scope = ? AND call_id = ?",
                    (scope, call_id),
                ).fetchone()
                return row[0] if row else None
        except sqlite3.Error as exc:
            raise ToolPolicyDenied("Tool execution ledger unavailable") from exc
