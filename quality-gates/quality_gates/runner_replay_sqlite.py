"""Persistent, atomic one-time runner execution IDs for a trusted verifier.

Opt-in local SQLite backend only. Caller must keep DB outside untrusted mounts.
This is not an authenticated transport or proof of runner provenance.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .isolated_tester import SandboxError
from .runner_result import validate_expected_runner_result

_ID = re.compile(r"[0-9a-f]{32}\Z")


class PersistentRunnerResults:
    def __init__(self, database: Path):
        path = Path(database)
        if not path.is_absolute() or path.is_symlink() or not path.parent.is_dir():
            raise SandboxError("Trusted absolute replay database required")
        self.database = path

    def consume(
        self, raw: bytes, *, run_id: str, expected_command_id: str,
        expected_exit_code: int,
    ) -> dict[str, object]:
        if type(run_id) is not str or not _ID.fullmatch(run_id):
            raise SandboxError("Invalid trusted execution ID")
        # Autocommit INSERT's unique constraint is atomic across independent
        # SQLite connections and processes, unlike an in-memory set.
        try:
            with sqlite3.connect(self.database, timeout=10, isolation_level=None) as db:
                db.execute("CREATE TABLE IF NOT EXISTS consumed (run_id TEXT PRIMARY KEY)")
                db.execute("INSERT INTO consumed (run_id) VALUES (?)", (run_id,))
        except sqlite3.IntegrityError as exc:
            raise SandboxError("Runner execution ID already consumed") from exc
        except sqlite3.Error as exc:
            raise SandboxError("Replay store unavailable; fail closed") from exc
        # Burn the ID first: malformed or mismatched evidence remains consumed.
        return validate_expected_runner_result(
            raw, expected_command_id=expected_command_id,
            expected_exit_code=expected_exit_code,
        )
