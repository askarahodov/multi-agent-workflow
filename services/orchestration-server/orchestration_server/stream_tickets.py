"""Durable one-time stream ticket storage (not wired into HTTP/WS routes).

Tickets are opaque bearer capabilities. Only SHA-256 digests enter SQLite.
Each operation uses an independent SQLite connection and BEGIN IMMEDIATE for
atomic redemption across processes using the same database file.
"""
from __future__ import annotations

import hashlib
import secrets
from contextlib import closing
import sqlite3
import time
from pathlib import Path
from typing import Callable, Literal

Transport = Literal["sse", "websocket"]


class StreamTicketStore:
    """Issue and atomically redeem run/transport/principal-scoped tickets.

    This is a storage primitive, not an authorization decision. Callers MUST
    authorize issuance against the target run and recheck current permission
    during redemption. Do not use this store as a process-local cache.
    """

    def __init__(
        self, database_path: str | Path, *, now: Callable[[], float] = time.time
    ) -> None:
        self.database_path = str(database_path)
        self._now = now
        with closing(self._connect()) as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS stream_tickets (
                    digest TEXT PRIMARY KEY,
                    principal TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    transport TEXT NOT NULL CHECK (transport IN ('sse', 'websocket')),
                    expires_at REAL NOT NULL,
                    consumed_at REAL
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @staticmethod
    def _digest(ticket: str) -> str:
        return hashlib.sha256(ticket.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate(principal: str, run_id: str, transport: str) -> None:
        if not principal or not run_id or transport not in ("sse", "websocket"):
            raise ValueError("valid principal, run_id and transport are required")

    def issue(
        self, *, principal: str, run_id: str, transport: Transport, ttl_seconds: int = 30
    ) -> str:
        self._validate(principal, run_id, transport)
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 0 < ttl_seconds <= 30:
            raise ValueError("ticket TTL must be between 1 and 30 seconds")
        ticket = secrets.token_urlsafe(32)
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO stream_tickets
                   (digest, principal, run_id, transport, expires_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (self._digest(ticket), principal, run_id, transport, self._now() + ttl_seconds),
            )
        return ticket

    def redeem(
        self, ticket: str, *, principal: str, run_id: str, transport: Transport
    ) -> bool:
        self._validate(principal, run_id, transport)
        if not ticket:
            return False
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                now = self._now()
                result = connection.execute(
                    """UPDATE stream_tickets SET consumed_at = ?
                       WHERE digest = ? AND principal = ? AND run_id = ?
                         AND transport = ? AND consumed_at IS NULL AND expires_at > ?""",
                    (now, self._digest(ticket), principal, run_id, transport, now),
                )
                connection.execute("COMMIT")
                return result.rowcount == 1
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    def revoke(self, *, principal: str, run_id: str | None = None) -> int:
        """Invalidate all unconsumed tickets for a principal or one run.

        This supports session/permission revocation by the owning auth layer;
        existing active streams still require their own authorization checks.
        """
        if not principal or run_id == "":
            raise ValueError("principal must be nonempty; run_id must be nonempty or None")
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if run_id is None:
                    result = connection.execute(
                        """DELETE FROM stream_tickets
                           WHERE principal = ? AND consumed_at IS NULL""", (principal,)
                    )
                else:
                    result = connection.execute(
                        """DELETE FROM stream_tickets
                           WHERE principal = ? AND run_id = ? AND consumed_at IS NULL""",
                        (principal, run_id),
                    )
                connection.execute("COMMIT")
                return result.rowcount
            except BaseException:
                connection.execute("ROLLBACK")
                raise
