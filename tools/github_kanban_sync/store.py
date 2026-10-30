"""Local SQLite ledger for the GitHub <-> Kanban sync.

A *separate* database from ``kanban.db`` so that a corrupt or locked sync ledger
can never block the board. WAL mode + ``busy_timeout``; a single process holds
the writer connection, readers (the CLI, the health probe) open their own.

Tables
------
``issue_link``    the ID contract: ``repo + issue_number`` <-> ``board + task_id``
``coord_event``   dedup + audit keyed by ``source_event_id``
``delivery``      per-channel delivery journal (receipts / retries / errors)
``cursor``        incremental poll cursors + ETags per feed
``snapshot``      latest observed GitHub state
``claim``         active worktree -> owner -> changed paths (conflict detector)
``reservation``   exclusive path ownership (e.g. #182 migration reservation)
``rate``          per-scope publish rate limiting
``meta``          schema version
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS issue_link (
    repo            TEXT NOT NULL,
    issue_number    INTEGER NOT NULL,
    board           TEXT NOT NULL,
    task_id         TEXT NOT NULL,
    pr_number       INTEGER,
    branch          TEXT,
    base_sha        TEXT,
    head_sha        TEXT,
    owner           TEXT,
    changed_paths   TEXT NOT NULL DEFAULT '[]',
    status          TEXT,
    source_event_id TEXT,
    updated_at      TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (repo, issue_number),
    UNIQUE (board, task_id)
);
CREATE TABLE IF NOT EXISTS coord_event (
    source_event_id TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    repo_sha        TEXT,
    payload         TEXT NOT NULL,
    correlation_id  TEXT,
    first_seen      TEXT NOT NULL,
    delivered_at    TEXT,
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT
);
CREATE TABLE IF NOT EXISTS delivery (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_event_id TEXT NOT NULL,
    channel         TEXT NOT NULL,
    target          TEXT,
    status          TEXT NOT NULL,
    attempts        INTEGER NOT NULL DEFAULT 1,
    correlation_id  TEXT,
    detail          TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_delivery_event ON delivery(source_event_id);
CREATE TABLE IF NOT EXISTS cursor (
    feed       TEXT PRIMARY KEY,
    etag       TEXT,
    cursor     TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS snapshot (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at     TEXT NOT NULL,
    origin_main  TEXT,
    ci_state     TEXT,
    open_prs     INTEGER NOT NULL DEFAULT 0,
    payload      TEXT
);
CREATE TABLE IF NOT EXISTS claim (
    task_id        TEXT PRIMARY KEY,
    branch         TEXT,
    worktree       TEXT,
    owner          TEXT,
    changed_paths  TEXT NOT NULL DEFAULT '[]',
    base_sha       TEXT,
    updated_at     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reservation (
    scope       TEXT NOT NULL,
    issue_number INTEGER,
    task_id     TEXT,
    reason      TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (scope)
);
CREATE TABLE IF NOT EXISTS rate (
    scope        TEXT PRIMARY KEY,
    window_start REAL NOT NULL,
    count        INTEGER NOT NULL DEFAULT 0
);
"""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Store:
    """Thin, explicit SQLite access layer. All writes go through here."""

    def __init__(self, path: str | Path | None = None):
        self.path = str(path) if path and str(path) != ":memory:" else ":memory:"
        self._memory = str(path) == ":memory:"
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        with self._lock:
            self.conn.executescript(_SCHEMA)
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),),
            )
            self.conn.commit()

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _exec(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self.conn.execute(sql, params).fetchall())

    # -- events / dedup ----------------------------------------------------
    def record_event(
        self,
        source_event_id: str,
        kind: str,
        payload: dict[str, Any],
        *,
        repo_sha: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> bool:
        """Insert the event if new. Returns ``True`` when it is first seen.

        Idempotency is enforced by the ``source_event_id`` primary key; a
        duplicate is a no-op so a poll and a webhook converge.
        """
        try:
            self._exec(
                "INSERT INTO coord_event(source_event_id, kind, repo_sha, payload,"
                " correlation_id, first_seen, attempts) VALUES (?,?,?,?,?,?,0)",
                (source_event_id, kind, repo_sha, json.dumps(payload, sort_keys=True),
                 correlation_id, _now()),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def event_seen(self, source_event_id: str) -> bool:
        return bool(
            self._query("SELECT 1 FROM coord_event WHERE source_event_id=?", (source_event_id,))
        )

    def pending_events(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self._query(
            "SELECT * FROM coord_event WHERE delivered_at IS NULL ORDER BY first_seen LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    def mark_delivered(self, source_event_id: str) -> None:
        self._exec(
            "UPDATE coord_event SET delivered_at=? WHERE source_event_id=?",
            (_now(), source_event_id),
        )

    def bump_attempt(self, source_event_id: str, error: Optional[str] = None) -> None:
        self._exec(
            "UPDATE coord_event SET attempts=attempts+1, last_error=? WHERE source_event_id=?",
            (error, source_event_id),
        )

    # -- delivery journal --------------------------------------------------
    def record_delivery(
        self,
        source_event_id: str,
        channel: str,
        status: str,
        *,
        target: Optional[str] = None,
        correlation_id: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        self._exec(
            "INSERT INTO delivery(source_event_id, channel, target, status,"
            " correlation_id, detail, created_at) VALUES (?,?,?,?,?,?,?)",
            (source_event_id, channel, target, status, correlation_id, detail, _now()),
        )

    def delivery_journal(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._query(
            "SELECT * FROM delivery ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]

    # -- cursors -----------------------------------------------------------
    def get_cursor(self, feed: str) -> dict[str, Any]:
        rows = self._query("SELECT * FROM cursor WHERE feed=?", (feed,))
        return dict(rows[0]) if rows else {"feed": feed, "etag": None, "cursor": None}

    def set_cursor(self, feed: str, *, etag: Optional[str] = None,
                   cursor: Optional[str] = None) -> None:
        existing = self.get_cursor(feed)
        self._exec(
            "INSERT OR REPLACE INTO cursor(feed, etag, cursor, updated_at) VALUES (?,?,?,?)",
            (feed, etag if etag is not None else existing.get("etag"),
             cursor if cursor is not None else existing.get("cursor"), _now()),
        )

    # -- snapshot ----------------------------------------------------------
    def record_snapshot(self, snapshot: dict[str, Any]) -> int:
        cur = self._exec(
            "INSERT INTO snapshot(taken_at, origin_main, ci_state, open_prs, payload)"
            " VALUES (?,?,?,?,?)",
            (_now(), snapshot.get("origin_main"), snapshot.get("ci_state"),
             int(snapshot.get("open_prs", 0)), json.dumps(snapshot, sort_keys=True)),
        )
        return int(cur.lastrowid or 0)

    def last_snapshot(self) -> Optional[dict[str, Any]]:
        rows = self._query("SELECT * FROM snapshot ORDER BY id DESC LIMIT 1")
        return dict(rows[0]) if rows else None

    # -- claims ------------------------------------------------------------
    def upsert_claim(self, task_id: str, *, branch: Optional[str] = None,
                     worktree: Optional[str] = None, owner: Optional[str] = None,
                     changed_paths: Optional[Iterable[str]] = None,
                     base_sha: Optional[str] = None) -> None:
        self._exec(
            "INSERT OR REPLACE INTO claim(task_id, branch, worktree, owner,"
            " changed_paths, base_sha, updated_at) VALUES (?,?,?,?,?,?,?)",
            (task_id, branch, worktree, owner, json.dumps(sorted(set(changed_paths or []))),
             base_sha, _now()),
        )

    def claims(self) -> list[dict[str, Any]]:
        rows = self._query("SELECT * FROM claim")
        out = []
        for r in rows:
            d = dict(r)
            d["changed_paths"] = json.loads(d.get("changed_paths") or "[]")
            out.append(d)
        return out

    # -- reservations ------------------------------------------------------
    def reserve(self, scope: str, *, issue_number: Optional[int] = None,
                task_id: Optional[str] = None, reason: Optional[str] = None) -> None:
        self._exec(
            "INSERT OR REPLACE INTO reservation(scope, issue_number, task_id, reason,"
            " updated_at) VALUES (?,?,?,?,?)",
            (scope, issue_number, task_id, reason, _now()),
        )

    def reservations(self) -> list[dict[str, Any]]:
        return [dict(r) for r in self._query("SELECT * FROM reservation")]

    # -- rate limiting -----------------------------------------------------
    def allow(self, scope: str, min_interval: float, *, now: Optional[float] = None) -> bool:
        now = now if now is not None else time.time()
        rows = self._query("SELECT * FROM rate WHERE scope=?", (scope,))
        if not rows:
            return True
        return (now - float(rows[0]["window_start"])) >= min_interval

    def touch(self, scope: str, *, now: Optional[float] = None) -> None:
        now = now if now is not None else time.time()
        self._exec(
            "INSERT OR REPLACE INTO rate(scope, window_start, count) VALUES (?,?,1)", (scope, now)
        )

    def counts(self) -> dict[str, int]:
        def one(sql: str) -> int:
            return int(self._query(sql)[0][0])
        return {
            "links": one("SELECT COUNT(*) FROM issue_link"),
            "events": one("SELECT COUNT(*) FROM coord_event"),
            "pending": one("SELECT COUNT(*) FROM coord_event WHERE delivered_at IS NULL"),
            "deliveries": one("SELECT COUNT(*) FROM delivery"),
            "delivery_errors": one(
                "SELECT COUNT(*) FROM delivery WHERE status IN ('error','failed')"
            ),
        }
