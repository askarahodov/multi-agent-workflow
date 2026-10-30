"""Read/write access to the local Hermes Kanban board (``kanban.db``).

The sync uses this to (a) learn a card's assignee/status/branch for routing and
publishing, and (b) deliver GitHub-originated information to the owning card as a
comment plus a ``task_events`` row (the "observable confirmation of delivery"
required by Issue #192).

Only the board's own tables are touched (``tasks``, ``task_comments``,
``task_events``); no other profile's database or worktree is ever written.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from .config import _kanban_home


def _now_epoch() -> int:
    return int(time.time())


class KanbanBoard:
    def __init__(self, db_path: str | Path | None = None, *, author: str = "github-kanban-sync"):
        self.path = str(db_path) if db_path else str(_kanban_home() / "kanban.db")
        self.author = author
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.execute("PRAGMA journal_mode=WAL")

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "KanbanBoard":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- reads -------------------------------------------------------------
    def task(self, task_id: str) -> Optional[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchall()
        return dict(rows[0]) if rows else None

    def tasks(self, *, status: Optional[str] = None) -> list[dict[str, Any]]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE status=? ORDER BY created_at", (status,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM tasks ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]

    def events_since(self, event_id: int, *, task_id: Optional[str] = None) -> list[dict[str, Any]]:
        if task_id:
            rows = self.conn.execute(
                "SELECT * FROM task_events WHERE id>? AND task_id=? ORDER BY id",
                (event_id, task_id),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM task_events WHERE id>? ORDER BY id", (event_id,)
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if d.get("payload"):
                try:
                    d["payload"] = json.loads(d["payload"])
                except (ValueError, TypeError):
                    pass
            out.append(d)
        return out

    def comments(self, task_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM task_comments WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def has_comment_marker(self, task_id: str, marker: str) -> bool:
        rows = self.conn.execute(
            "SELECT 1 FROM task_comments WHERE task_id=? AND body LIKE ?",
            (task_id, f"%{marker}%"),
        ).fetchall()
        return bool(rows)

    def latest_run(self, task_id: str) -> Optional[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 1", (task_id,)
        ).fetchall()
        if not rows:
            return None
        run = dict(rows[0])
        meta = run.get("metadata")
        if meta:
            try:
                run["metadata"] = json.loads(meta)
            except (ValueError, TypeError):
                run["metadata"] = {}
        return run

    # -- writes ------------------------------------------------------------
    def add_comment(self, task_id: str, body: str, *, author: Optional[str] = None) -> int:
        """Append a comment to a card and a matching ``comment.added`` event."""
        who = author or self.author
        cur = self.conn.execute(
            "INSERT INTO task_comments(task_id, author, body, created_at) VALUES (?,?,?,?)",
            (task_id, who, body, _now_epoch()),
        )
        self.conn.execute(
            "INSERT INTO task_events(task_id, run_id, kind, payload, created_at)"
            " VALUES (?,?,?,?,?)",
            (task_id, None, "comment.added",
             json.dumps({"author": who, "body": body}), _now_epoch()),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)

    def record_event(self, task_id: str, kind: str, payload: dict[str, Any]) -> int:
        cur = self.conn.execute(
            "INSERT INTO task_events(task_id, run_id, kind, payload, created_at)"
            " VALUES (?,?,?,?,?)",
            (task_id, None, kind, json.dumps(payload), _now_epoch()),
        )
        self.conn.commit()
        return int(cur.lastrowid or 0)
