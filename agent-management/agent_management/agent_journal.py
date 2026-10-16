"""Durable, redacted native Agent Loop telemetry; no model-controlled text persisted."""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from .errors import ToolPolicyDenied

_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_KINDS = frozenset({"provider_turn", "usage", "tool_result", "final", "failure", "started"})
_DETAILS = frozenset({"started", "stop", "tool_calls", "unknown", "unverified", "OK",
                      "UNKNOWN_TOOL", "POLICY_DENIED", "INVALID_ARGUMENTS",
                      "DUPLICATE_CALL", "ATTEMPT_FENCED", "TOOL_IO_ERROR",
                      "PROCESS_FAILED", "HTTP_REJECTED", "HTTP_FAILED",
                      "HTTP_SIZE_DENIED", "HTTP_ENCODING_DENIED",
                      "HTTP_TYPE_DENIED", "error", "cancelled", "timeout",
                      "budget_exceeded", "provider_error", "loop_error"})


class AgentEventJournal:
    """SQLite append-only journal placed in trusted control-plane storage."""

    def __init__(self, path: str | os.PathLike[str], *, run_id: str, workspace: str | os.PathLike[str]) -> None:
        if type(run_id) is not str or not _ID.fullmatch(run_id):
            raise ValueError("Trusted run id required")
        db_path = Path(path)
        root = Path(workspace).resolve(strict=True)
        if not db_path.is_absolute() or db_path.is_symlink() or any(p.is_symlink() for p in db_path.parents):
            raise ToolPolicyDenied("Agent journal must be an absolute, non-symlinked control path")
        if db_path.resolve().is_relative_to(root):
            raise ToolPolicyDenied("Agent journal cannot be in model workspace")
        if not db_path.parent.is_dir():
            raise FileNotFoundError("Agent journal directory does not exist")
        self.path = db_path
        self.run_id = run_id
        with sqlite3.connect(str(self.path), timeout=10) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS agent_loop_events ("
                         "seq INTEGER PRIMARY KEY AUTOINCREMENT,"
                         "run_id TEXT NOT NULL, turn INTEGER NOT NULL,"
                         "kind TEXT NOT NULL, detail TEXT NOT NULL,"
                         "tokens INTEGER, cost TEXT NOT NULL DEFAULT 'UNKNOWN',"
                         "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            conn.execute("CREATE INDEX IF NOT EXISTS agent_loop_run_idx "
                         "ON agent_loop_events (run_id, seq)")

    def record(self, turn: int, kind: str, detail: str, *, tokens: int | None = None) -> None:
        if type(turn) is not int or not 0 <= turn <= 128:
            raise ValueError("Invalid journal turn")
        if kind not in _KINDS:
            raise ValueError("Invalid journal kind")
        # Never persist raw model text, paths, headers, credentials or provider errors.
        if detail not in _DETAILS:
            detail = "error" if kind == "failure" else "unknown"
        if tokens is not None and (type(tokens) is not int or not 0 <= tokens <= 10_000_000):
            raise ValueError("Invalid token count")
        with sqlite3.connect(str(self.path), timeout=10) as conn:
            conn.execute(
                "INSERT INTO agent_loop_events (run_id, turn, kind, detail, tokens, cost) "
                "VALUES (?, ?, ?, ?, ?, 'UNKNOWN')",
                (self.run_id, turn, kind, detail, tokens),
            )

    def snapshot(self) -> tuple[tuple[int, str, str, int | None, str], ...]:
        with sqlite3.connect(str(self.path), timeout=10) as conn:
            rows = conn.execute(
                "SELECT turn, kind, detail, tokens, cost FROM agent_loop_events "
                "WHERE run_id = ? ORDER BY seq", (self.run_id,),
            ).fetchall()
        return tuple(rows)
