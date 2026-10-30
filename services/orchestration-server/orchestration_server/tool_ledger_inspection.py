"""Read-only, bounded status inspection of worker-owned SQLite tool claims.

The ledger path is a TRUSTED server deployment setting, never provided by
the requester/model. The scope derives exclusively from orchestration run
and interrupted attempt IDs. No raw tool call IDs, paths, arguments, prompts,
or tool contents are returned. Does not authorize task resumption.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .errors import BusinessRuleError

_CALL_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_UUID = re.compile(r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\Z")
_ALLOWED_TOOLS = frozenset({"read_file", "write_file"})
_ALLOWED_STATES = frozenset({"CLAIMED", "SUCCEEDED", "DENIED"})


@dataclass(frozen=True)
class LedgerEntry:
    call_ref: str  # non-reversible digest prefix, never model-controlled ID
    tool: str
    state: str


class TrustedToolLedgerReader:
    """Read worker ledger without opening in create/write mode.

    The immediate parent must be provisioned by the trusted control plane and
    not writable by untrusted workers. A cross-host worker needs a separate
    authenticated status transport: do NOT mount its writable DB into agents.
    """

    def __init__(self, ledger_path: str | os.PathLike[str], *, max_entries: int = 200) -> None:
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise ValueError("POSIX nofollow is required for ledger inspection")
        if not isinstance(ledger_path, (str, os.PathLike)):
            raise ValueError("Trusted ledger path required")
        path = Path(ledger_path)
        if not path.is_absolute() or path.is_symlink() or path.parent.is_symlink():
            raise ValueError("Trusted ledger must use an absolute, non-symlink path")
        if type(max_entries) is not int or not 1 <= max_entries <= 1000:
            raise ValueError("Ledger read limit must be 1..1000")
        # Revalidation is required at read time; the trusted parent must not
        # be writable by agents and must not be swapped by untrusted users.
        self.path = path
        self.max_entries = max_entries
        self._verify_path()

    def _verify_path(self) -> None:
        # Reject symlink ancestors, not just the immediate parent: an alias
        # above the ledger directory could redirect reads to an untrusted DB.
        ancestor = self.path.parent
        while ancestor != ancestor.parent:
            if ancestor.is_symlink():
                raise BusinessRuleError("Trusted tool ledger path is unsafe")
            ancestor = ancestor.parent
        try:
            parent = os.stat(self.path.parent, follow_symlinks=False)
            fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                info = os.fstat(fd)
            finally:
                os.close(fd)
        except OSError as exc:
            raise BusinessRuleError("Trusted tool ledger unavailable") from exc
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_mode & 0o022
            or not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_nlink != 1
            or (hasattr(os, "geteuid") and info.st_uid != os.geteuid())
        ):
            raise BusinessRuleError("Trusted tool ledger permissions are unsafe")

    @staticmethod
    def _scope(run_id: str, attempt_id: str) -> str:
        if (
            not isinstance(run_id, str) or not _UUID.fullmatch(run_id)
            or not isinstance(attempt_id, str) or not _UUID.fullmatch(attempt_id)
        ):
            raise BusinessRuleError("Invalid trusted attempt identity")
        # Matches the canonical native E2E/worker ledger scope convention.
        return f"run-{run_id}/attempt-{attempt_id}"

    def inspect(self, run_id: str, attempt_id: str) -> tuple[LedgerEntry, ...]:
        scope = self._scope(run_id, attempt_id)
        self._verify_path()
        # SQLite URI mode=ro prevents accidentally creating or writing ledger.
        # Percent-escape the trusted path, including '?', '#' and spaces.
        uri = "file:" + quote(str(self.path), safe="/") + "?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=3)) as conn:
                conn.execute("PRAGMA query_only = ON")
                rows = conn.execute(
                    "SELECT call_id, name, state FROM tool_execution "
                    "WHERE scope = ? ORDER BY call_id LIMIT ?",
                    (scope, self.max_entries + 1),
                ).fetchall()
        except sqlite3.Error as exc:
            raise BusinessRuleError("Trusted tool ledger unreadable") from exc
        if len(rows) > self.max_entries:
            raise BusinessRuleError("Tool ledger results exceed inspection limit")
        entries = []
        for call_id, name, state in rows:
            if (
                not isinstance(call_id, str)
                or not _CALL_ID.fullmatch(call_id)
                or not isinstance(name, str)
                or len(name) > 64
                or not isinstance(state, str)
                or state not in _ALLOWED_STATES
            ):
                raise BusinessRuleError("Invalid tool ledger record")
            digest = hashlib.sha256((scope + ":" + call_id).encode("utf-8")).hexdigest()
            entries.append(LedgerEntry(
                call_ref=digest[:16],
                tool=name if isinstance(name, str) and name in _ALLOWED_TOOLS else "<unsupported>",
                state=state,
            ))
        return tuple(entries)
