"""Durable one-time stream ticket storage (not wired into HTTP/WS routes).

Tickets are opaque bearer capabilities. Only SHA-256 digests enter SQLite.
Each operation uses an independent SQLite connection and BEGIN IMMEDIATE for
atomic redemption across processes using the same database file.
"""
from __future__ import annotations

import hashlib
import secrets
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
        with self._connect() as connection:
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
        if not 0 < ttl_seconds <= 30:
            raise ValueError("ticket TTL must be between 1 and 30 seconds")
        ticket = secrets.token_urlsafe(32)
        with self._connect() as connection:
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
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                result = connection.execute(
                    """UPDATE stream_tickets SET consumed_at = ?
                       WHERE digest = ? AND principal = ? AND run_id = ?
                         AND transport = ? AND consumed_at IS NULL AND expires_at > ?""",
                    (self._now(), self._digest(ticket), principal, run_id, transport, self._now()),
                )
                connection.execute("COMMIT")
                return result.rowcount == 1
            except BaseException:
                connection.execute("ROLLBACK")
                raise
