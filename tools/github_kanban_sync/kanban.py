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
import re
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

from .config import _kanban_home

# The sync's own GitHub->Kanban delivery marker. Used to recognise (and never
# duplicate) a comment the tool already wrote to a card.
INGEST_MARKER_PREFIX = "gks:v1"
INGEST_MARKER_CHANNEL = "channel=ingest"
_INGEST_MARKER_RE = re.compile(r"<!--\s*gks:v1\b[^>]*channel=ingest\b[^>]*-->")


def _now_epoch() -> int:
    return int(time.time())


def is_ingest_comment(body: Optional[str]) -> bool:
    """True when ``body`` carries the sync's ``channel=ingest`` marker."""
    return bool(_INGEST_MARKER_RE.search(body or ""))


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
        """Exact-substring check for a marker in any comment on ``task_id``.

        Uses ``instr`` rather than ``LIKE`` so a marker containing SQL wildcard
        characters (``_`` / ``%``) — the ``source_event_id`` embeds both — is
        matched literally, never as a pattern.
        """
        rows = self.conn.execute(
            "SELECT 1 FROM task_comments WHERE task_id=? AND instr(body, ?)>0 LIMIT 1",
            (task_id, marker),
        ).fetchall()
        return bool(rows)

    def ingest_comments(self, task_id: str) -> list[dict[str, Any]]:
        """All GitHub->Kanban ingest comments currently on ``task_id`` (by id)."""
        return [c for c in self.comments(task_id) if is_ingest_comment(c.get("body"))]

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

    # -- cleanup -----------------------------------------------------------
    def remove_comment(self, comment_id: int) -> bool:
        """Delete a single comment row (used by the duplicate cleanup)."""
        cur = self.conn.execute("DELETE FROM task_comments WHERE id=?", (comment_id,))
        self.conn.commit()
        return bool(cur.rowcount)

    def _prune_comment_events(self, task_id: str, removed_bodies: list[str]) -> int:
        """Drop surplus ``comment.added`` events for bodies whose comments we removed.

        Keeps ``task_comments`` and ``task_events`` consistent: for a body removed
        ``n`` times we delete the ``n`` most recent matching events.
        """
        removed = Counter(removed_bodies)
        if not removed:
            return 0
        rows = self.conn.execute(
            "SELECT id, payload FROM task_events WHERE task_id=? AND kind='comment.added'"
            " ORDER BY id",
            (task_id,),
        ).fetchall()
        by_body: dict[Any, list[int]] = defaultdict(list)
        for row in rows:
            try:
                payload = json.loads(row["payload"] or "{}")
            except (ValueError, TypeError):
                continue
            by_body[payload.get("body")].append(row["id"])
        deleted = 0
        for body, ids in by_body.items():
            n = removed.get(body, 0)
            if n:
                for event_id in ids[-n:]:
                    self.conn.execute("DELETE FROM task_events WHERE id=?", (event_id,))
                    deleted += 1
        return deleted

    def dedupe_ingest_comments(self, task_id: str, *, keep: str = "first") -> dict[str, Any]:
        """Remove duplicate GitHub->Kanban ingest comments from a card.

        ``keep="first"`` keeps the earliest comment for each distinct body and
        removes later copies; ``keep="none"`` removes every ingest comment (a
        clean re-delivery). ``task_comments`` and the matching ``comment.added``
        events are pruned together and an audit ``comments.deduped`` event is
        appended, so the card is left consistent. Idempotent: a second run on an
        already-clean card removes nothing.
        """
        if keep not in ("first", "none"):
            raise ValueError("keep must be 'first' or 'none'")
        ingest = self.ingest_comments(task_id)
        seen: set[str] = set()
        kept: list[int] = []
        removed: list[int] = []
        removed_bodies: list[str] = []
        for comment in ingest:
            body = comment.get("body") or ""
            if keep == "none" or body in seen:
                removed.append(int(comment["id"]))
                removed_bodies.append(body)
            else:
                seen.add(body)
                kept.append(int(comment["id"]))
        if not removed:
            return {"task_id": task_id, "removed": [], "kept": kept,
                    "duplicates_removed": 0}
        for comment_id in removed:
            self.conn.execute("DELETE FROM task_comments WHERE id=?", (comment_id,))
        events_pruned = self._prune_comment_events(task_id, removed_bodies)
        audit = {"removed": removed, "kept": kept, "events_pruned": events_pruned}
        self.conn.execute(
            "INSERT INTO task_events(task_id, run_id, kind, payload, created_at)"
            " VALUES (?,?,?,?,?)",
            (task_id, None, "comments.deduped", json.dumps(audit), _now_epoch()),
        )
        self.conn.commit()
        return {"task_id": task_id, "removed": removed, "kept": kept,
                "duplicates_removed": len(removed), "events_pruned": events_pruned}
