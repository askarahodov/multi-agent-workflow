"""Shared SQLite persistence layer (task item (d)).

A small, dependency-free persistence facade used by the shared tooling and
platform services when a local SQLite store is sufficient. It provides:

* :class:`SQLiteStore` — a thread-safe ``sqlite3`` wrapper with WAL mode and
  JSON serialisation.
* :class:`MemoryStore` — the agent Memory subsystem (ADR-013 §2.2) backed by
  SQLite, with levels (agent/task/project/workflow/global), versioning and
  keyword search. When the bundled ``sqlite3`` exposes FTS5 a full-text virtual
  table is used; otherwise search degrades to a LIKE scan.

The orchestration server already persists its own domain models through
SQLAlchemy (see ``orchestration-server/orchestration_server/``); this module is
the *shared-tooling* persistence surface (agent memory, run state), so it has
no SQLAlchemy dependency and runs anywhere the platform tooling runs.

Security note: the memory store intentionally does **not** rank content above
the agent's standing instructions — instruction-order is the caller's
responsibility; this layer only stores and retrieves entries.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

# Memory levels (ADR-013 §2.2).
MEMORY_LEVELS = ("agent", "task", "project", "workflow", "global")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory_entries (
    id          TEXT PRIMARY KEY,
    level       TEXT NOT NULL,
    scope_id    TEXT,
    key         TEXT NOT NULL,
    value_json  TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    tags_json   TEXT NOT NULL DEFAULT '[]',
    created_by  TEXT,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_memory_scope ON memory_entries (level, scope_id);
CREATE INDEX IF NOT EXISTS ix_memory_key    ON memory_entries (key);
CREATE TABLE IF NOT EXISTS memory_history (
    entry_id   TEXT NOT NULL,
    version    INTEGER NOT NULL,
    value_json TEXT NOT NULL,
    changed_at REAL NOT NULL,
    PRIMARY KEY (entry_id, version)
);
"""


def _now_ts() -> float:
    return time.time()


class StorageError(Exception):
    """Base class for storage-layer errors."""


class LevelError(StorageError):
    """Raised when an invalid memory level is supplied."""


class SQLiteStore:
    """Thin, thread-safe ``sqlite3`` wrapper with JSON and WAL mode.

    A single persistent connection is held for the store's lifetime — required
    for ``:memory:`` stores (each ``sqlite3.connect(":memory:")`` call yields a
    brand-new, empty database) — and guarded by a lock so concurrent callers do
    not trample each other on a single host.
    """

    def __init__(self, path: str | Path | None = None, *, busy_timeout_ms: int = 5000) -> None:
        self.path = str(path) if path else ":memory:"
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = self._connect(check_same_thread=False)

    def _connect(self, *, check_same_thread: bool = True) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.path, timeout=5000 / 1000, check_same_thread=check_same_thread
        )
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _configure(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self._conn
            self._configure(conn)
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params))

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(raw: Any) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


class MemoryStore:
    """Agent Memory subsystem (ADR-013 §2.2) on SQLite.

    Entries are keyed by ``(level, scope_id, key)``; every write to an existing
    key bumps ``version`` and appends the prior state to a history table.
    Search uses FTS5 when available, falling back to a LIKE scan otherwise.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.store = SQLiteStore(path)
        with self.store.write() as conn:
            conn.executescript(_SCHEMA)
        self._fts5 = self._try_enable_fts5()

    def _try_enable_fts5(self) -> bool:
        with self.store.write() as conn:
            try:
                conn.executescript(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS memory_search USING fts5(key, value);"
                )
                conn.execute("SELECT 1 FROM memory_search LIMIT 0")
                return True
            except sqlite3.OperationalError:
                return False

    # -- helpers ----------------------------------------------------------------
    @staticmethod
    def _check_level(level: str) -> str:
        if level not in MEMORY_LEVELS:
            raise LevelError(
                f"invalid memory level {level!r}; expected one of {MEMORY_LEVELS}"
            )
        return level

    # -- writes -----------------------------------------------------------------
    def write(
        self,
        level: str,
        key: str,
        value: Any,
        *,
        scope_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        created_by: Optional[str] = None,
    ) -> dict[str, Any]:
        """Create or overwrite a memory entry (overwrites bump the version)."""
        level = self._check_level(level)
        ts = _now_ts()
        value_json = _dumps(value)
        tags_json = _dumps(tags or [])
        with self.store.write() as conn:
            row = conn.execute(
                "SELECT id, value_json, version FROM memory_entries WHERE level=? AND scope_id IS ? AND key=?",
                (level, scope_id, key),
            ).fetchone()
            if row is not None:
                entry_id = row["id"]
                # Snapshot the prior state into history before mutating.
                conn.execute(
                    "INSERT INTO memory_history(entry_id, version, value_json, changed_at)"
                    " VALUES (?,?,?,?)",
                    (entry_id, row["version"], row["value_json"], ts),
                )
                conn.execute(
                    "UPDATE memory_entries SET value_json=?, version=version+1, tags_json=?,"
                    " created_by=?, updated_at=? WHERE id=?",
                    (value_json, tags_json, created_by, ts, entry_id),
                )
            else:
                entry_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO memory_entries(id, level, scope_id, key, value_json, version,"
                    " tags_json, created_by, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,1,?,?,?,?)",
                    (entry_id, level, scope_id, key, value_json, tags_json, created_by, ts, ts),
                )
        self._sync_fts()
        rows = self.store.query("SELECT * FROM memory_entries WHERE id=?", (entry_id,))
        return self._row_to_entry(rows[0])

    def _sync_fts(self) -> None:
        """Rebuild the FTS index from the source table (simple and correct)."""
        if not self._fts5:
            return
        with self.store.write() as c:
            c.execute("DELETE FROM memory_search")
            rows = c.execute("SELECT rowid, key, value_json FROM memory_entries").fetchall()
            c.executemany(
                "INSERT INTO memory_search(rowid, key, value) VALUES (?,?,?)",
                [(r["rowid"], r["key"], r["value_json"]) for r in rows],
            )

    # -- reads -------------------------------------------------------------------
    def get(
        self, level: str, key: str, *, scope_id: Optional[str] = None
    ) -> Optional[dict[str, Any]]:
        self._check_level(level)
        rows = self.store.query(
            "SELECT * FROM memory_entries WHERE level=? AND scope_id IS ? AND key=?",
            (level, scope_id, key),
        )
        return self._row_to_entry(rows[0]) if rows else None

    def search(
        self,
        query: str,
        *,
        level: Optional[str] = None,
        scope_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if level is not None:
            self._check_level(level)
        if not query.strip():
            return []
        if self._fts5:
            return self._fts_search(query, level=level, scope_id=scope_id, limit=limit)
        return self._like_search(query, level=level, scope_id=scope_id, limit=limit)

    def _fts_search(self, query, *, level, scope_id, limit) -> list[dict[str, Any]]:
        where = []
        params: list[Any] = [query]
        if level is not None:
            where.append("e.level = ?")
            params.append(level)
        if scope_id is not None:
            where.append("e.scope_id = ?")
            params.append(scope_id)
        sql = (
            "SELECT e.* FROM memory_search m JOIN memory_entries e ON e.rowid = m.rowid"
            " WHERE m.memory_search MATCH ?"
        )
        if where:
            sql += " AND " + " AND ".join(where)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        rows = self.store.query(sql, (*params,))
        return [self._row_to_entry(r) for r in rows]

    def _like_search(self, query, *, level, scope_id, limit) -> list[dict[str, Any]]:
        where = ["(key LIKE ? OR value_json LIKE ?)"]
        params: list[Any] = [f"%{query}%", f"%{query}%"]
        if level is not None:
            where.append("level = ?")
            params.append(level)
        if scope_id is not None:
            where.append("scope_id = ?")
            params.append(scope_id)
        params.append(limit)
        rows = self.store.query(
            "SELECT * FROM memory_entries WHERE " + " AND ".join(where) + " ORDER BY updated_at DESC LIMIT ?",
            (*params,),
        )
        return [self._row_to_entry(r) for r in rows]

    def delete(self, level: str, key: str, *, scope_id: Optional[str] = None) -> bool:
        self._check_level(level)
        with self.store.write() as conn:
            cur = conn.execute(
                "DELETE FROM memory_entries WHERE level=? AND scope_id IS ? AND key=?",
                (level, scope_id, key),
            )
            deleted = cur.rowcount > 0
        if deleted:
            self._sync_fts()
        return deleted

    def versions(self, entry_id: str) -> list[dict[str, Any]]:
        rows = self.store.query(
            "SELECT * FROM memory_history WHERE entry_id=? ORDER BY version DESC",
            (entry_id,),
        )
        return [
            {
                "entry_id": r["entry_id"],
                "version": r["version"],
                "value": _loads(r["value_json"]),
                "changed_at": r["changed_at"],
            }
            for r in rows
        ]

    @staticmethod
    def _row_to_entry(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "level": row["level"],
            "scope_id": row["scope_id"],
            "key": row["key"],
            "value": _loads(row["value_json"]),
            "version": row["version"],
            "tags": _loads(row["tags_json"]),
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def close(self) -> None:
        """Release the underlying SQLite connection."""
        self.store.close()