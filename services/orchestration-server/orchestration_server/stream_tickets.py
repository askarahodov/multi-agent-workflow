"""Durable one-time stream ticket storage for opt-in HTTP/WS routes.

Tickets are opaque bearer capabilities. Only SHA-256 digests enter SQLite.
Each operation uses an independent SQLite connection and BEGIN IMMEDIATE for
atomic redemption across processes using the same database file.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import stat
from contextlib import closing
import sqlite3
import time
from pathlib import Path
from typing import Callable, Literal

Transport = Literal["sse", "websocket"]


class StreamTicketRateLimited(Exception):
    """Issuance budget exhausted."""


class StreamTicketStoragePermissionError(PermissionError):
    """Unsafe ticket-store permissions; not an RBAC authorization failure."""


class StreamTicketStore:
    """Issue and atomically redeem run/transport/principal-scoped tickets.

    This is a storage primitive, not an authorization decision. Callers MUST
    authorize issuance against the target run and recheck current permission
    during redemption. Do not use this store as a process-local cache.
    """

    def __init__(
        self, database_path: str | Path, *, now: Callable[[], float] = time.time
    ) -> None:
        self.database_path = str(Path(database_path).absolute())
        self._now = now
        # Pin the original store identity for this process. An operator or
        # attacker replacing the file must not reset one-time tickets/quotas.
        self._file_identity: tuple[int, int] | None = None
        self._ensure_private_file()
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

            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_stream_tickets_expires "
                "ON stream_tickets (expires_at)"
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS stream_ticket_limits (
                    principal TEXT PRIMARY KEY,
                    window_start REAL NOT NULL,
                    count INTEGER NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_stream_ticket_limits_window "
                "ON stream_ticket_limits (window_start)"
            )

    def _ensure_private_file(self) -> None:
        """Create owner-only storage; reject exposed files and symlinks.

        Worker processes must use a trusted parent directory and the same
        service account. Do not silently chmod an operator-managed file.
        """
        flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.database_path, flags, 0o600)
        except FileExistsError:
            pass  # Another worker may have created it concurrently.
        else:
            os.close(fd)
        metadata = self._assert_private_file()
        self._file_identity = (metadata.st_dev, metadata.st_ino)

    def _assert_private_file(self) -> os.stat_result:
        """Reject removal, symlink substitution or permission drift after startup."""
        try:
            metadata = os.lstat(self.database_path)
        except FileNotFoundError:
            # Preserve the existing store-outage error contract while never
            # opening sqlite3 in its implicit CREATE mode.
            raise sqlite3.OperationalError("stream ticket database unavailable") from None
        except PermissionError:
            # An unsearchable/restricted parent directory is unavailable
            # storage, not a caller's missing READ authorization.
            raise StreamTicketStoragePermissionError(
                "stream ticket database unavailable"
            ) from None
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("stream ticket database must be a regular file")
        if os.name == "posix":
            if metadata.st_mode & 0o077:
                raise StreamTicketStoragePermissionError(
                    "stream ticket database must be owner-only (0600)"
                )
            if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
                raise StreamTicketStoragePermissionError(
                    "stream ticket database must belong to the service account"
                )
        identity = (metadata.st_dev, metadata.st_ino)
        if self._file_identity is not None and identity != self._file_identity:
            raise StreamTicketStoragePermissionError(
                "stream ticket database identity changed; operator recovery required"
            )
        return metadata

    def _connect(self) -> sqlite3.Connection:
        # The default sqlite3.connect(path) silently creates a replacement DB
        # if an operator unmounts/removes the live store. That new file may be
        # world-readable under the process umask and has no ticket tables.
        # Every operation must instead fail closed until an operator restores
        # the original, private file. SQLite URI mode=rw forbids recreation.
        self._assert_private_file()
        uri = f"{Path(self.database_path).as_uri()}?mode=rw"
        connection = sqlite3.connect(uri, uri=True, timeout=10, isolation_level=None)
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
            connection.execute("BEGIN IMMEDIATE")
            try:
                now = self._now()
                # Expired tickets (including consumed tickets) are no longer
                # usable and must not grow the durable store indefinitely.
                connection.execute(
                    "DELETE FROM stream_tickets WHERE expires_at <= ?", (now,)
                )
                connection.execute("DELETE FROM stream_ticket_limits WHERE window_start <= ?", (now - 60.0,))
                row = connection.execute("SELECT count FROM stream_ticket_limits WHERE principal = ?", (principal,)).fetchone()
                if row is not None and row[0] >= 60:
                    raise StreamTicketRateLimited()
                if row is None:
                    connection.execute("INSERT INTO stream_ticket_limits (principal, window_start, count) VALUES (?, ?, 1)", (principal, now))
                else:
                    connection.execute("UPDATE stream_ticket_limits SET count = count + 1 WHERE principal = ?", (principal,))
                connection.execute(
                    """INSERT INTO stream_tickets
                       (digest, principal, run_id, transport, expires_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (self._digest(ticket), principal, run_id, transport, now + ttl_seconds),
                )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise
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


    def principal_for_ticket(
        self, ticket: str, *, run_id: str, transport: Transport
    ) -> str | None:
        """Read the bound identity without consuming the capability.

        The caller MUST check that identity against current authentication
        policy and run authorization before invoking redeem().
        """
        if not ticket or not run_id or transport not in ("sse", "websocket"):
            return None
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT principal FROM stream_tickets
                   WHERE digest = ? AND run_id = ? AND transport = ?
                     AND consumed_at IS NULL AND expires_at > ?""",
                (self._digest(ticket), run_id, transport, self._now()),
            ).fetchone()
        return row[0] if row else None

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
