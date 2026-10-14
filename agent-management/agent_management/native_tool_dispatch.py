"""Strict native tool-call dispatch for the first filesystem-only agent tools.

All values in a provider tool_call are untrusted. This module never imports
subprocess, Git, HTTP clients, or evaluates model-supplied code. A trusted
orchestrator constructs the scoped filesystem executor and owns its policy.
This is a staged boundary, not a sandbox or a complete native Agent Loop.
"""
from __future__ import annotations

import json
import os
import re
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Any, Mapping

from .errors import ToolPolicyDenied
from .scoped_fs import ScopedFilesystemExecutor
from .tool_ledger import SqliteToolLedger

_CALL_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TOOL_NAMES = frozenset({"read_file", "write_file"})
_ARG_FIELDS = {
    "read_file": frozenset({"path"}),
    "write_file": frozenset({"path", "content"}),
}


@dataclass(frozen=True)
class ToolOutcome:
    """Result compatible with OpenAI's next-turn tool message format."""

    tool_call_id: str
    name: str
    ok: bool
    content: str
    error_code: str | None = None

    def to_provider_message(self) -> dict[str, str]:
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            # Model sees a stable machine-readable failure, never raw OS errors.
            "content": self.content if self.ok else json.dumps(
                {"error": self.error_code}, separators=(",", ":"),
            ),
        }


@dataclass(frozen=True)
class ToolAudit:
    """Redacted in-memory event, not a substitute for durable journaling."""

    tool_call_id: str
    name: str
    outcome: str


class NativeFilesystemDispatcher:
    """Allow only exact read_file/write_file calls.

    The caller MUST provide a control-plane-initialized ScopedFilesystemExecutor.
    The model cannot nominate or replace workspace roots, permissions or tools.
    Duplicate IDs are rejected before execution, including attempts that failed.
    These at-most-once semantics apply ONLY to this dispatcher instance: a
    persistent task-level replay journal is required before production recovery.
    """

    def __init__(
        self,
        filesystem: ScopedFilesystemExecutor,
        *,
        ledger: SqliteToolLedger | None = None,
        execution_scope: str | None = None,
    ) -> None:
        if not isinstance(filesystem, ScopedFilesystemExecutor):
            raise TypeError("A trusted scoped filesystem executor is required")
        if ledger is not None:
            if not isinstance(ledger, SqliteToolLedger) or not isinstance(execution_scope, str):
                raise TypeError("Durable ledger requires a trusted execution scope")
            if os.path.commonpath((str(ledger.path), filesystem.root)) == filesystem.root:
                raise ToolPolicyDenied("Execution ledger cannot live inside agent workspace")
        elif execution_scope is not None:
            raise ValueError("Execution scope requires a durable ledger")
        self._filesystem = filesystem
        self._ledger = ledger
        self._scope = execution_scope
        self._handled: set[str] = set()
        self._lock = Lock()
        self._audit: deque[ToolAudit] = deque(maxlen=256)

    @staticmethod
    def tools_schema() -> list[dict[str, Any]]:
        """The ONLY function definitions offered to the LLM by this stage."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read an allowed UTF-8 file in the assigned workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "write_file",
                    "description": "Write an allowed UTF-8 file in the assigned workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["path", "content"],
                        "additionalProperties": False,
                    },
                },
            },
        ]

    def audit_snapshot(self) -> tuple[ToolAudit, ...]:
        """Small redacted trace for diagnostics; caller must persist if needed."""
        with self._lock:
            return tuple(self._audit)

    def dispatch(self, event: Mapping[str, Any]) -> ToolOutcome:
        """Consume one assembled streaming tool_call. Never execute unknown tools.

        Invalid input raises ToolPolicyDenied without touching underlying I/O.
        Well-shaped attempts return a safe outcome and are consumed once.
        """
        if not isinstance(event, Mapping) or event.get("type") != "tool_call":
            raise ToolPolicyDenied("Only assembled tool-call events are accepted")
        call_id = event.get("id")
        name = event.get("name")
        arguments = event.get("arguments")
        if not isinstance(call_id, str) or not _CALL_ID.fullmatch(call_id):
            raise ToolPolicyDenied("Invalid tool call identifier")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name):
            raise ToolPolicyDenied("Invalid tool name")

        # Never persist or audit unknown model-controlled function names.
        safe_name = name if name in _TOOL_NAMES else "<unsupported>"
        # Atomically claim the ID before validation and before any side effect.
        with self._lock:
            if call_id in self._handled:
                self._audit.append(ToolAudit(call_id, safe_name, "DUPLICATE"))
                return ToolOutcome(call_id, safe_name, False, "", "DUPLICATE_CALL")
            if self._ledger is not None:
                # Cross-process reservation commits before any filesystem I/O.
                if not self._ledger.claim(self._scope, call_id, safe_name):
                    self._audit.append(ToolAudit(call_id, safe_name, "DUPLICATE"))
                    return ToolOutcome(call_id, safe_name, False, "", "DUPLICATE_CALL")
            self._handled.add(call_id)

        if name not in _TOOL_NAMES:
            # Unknown model-supplied names must not appear in audit/log output.
            return self._deny(call_id, "<unsupported>", "UNKNOWN_TOOL")
        if (
            not isinstance(arguments, dict)
            or set(arguments) != _ARG_FIELDS[name]
            or not all(isinstance(value, str) for value in arguments.values())
        ):
            return self._deny(call_id, name, "INVALID_ARGUMENTS")

        try:
            path = arguments["path"]
            if name == "read_file":
                text = self._filesystem.read_text(path)
            else:
                self._filesystem.write_text(path, arguments["content"])
                text = "File written"
        except ToolPolicyDenied:
            return self._deny(call_id, name, "POLICY_DENIED")
        except (OSError, ValueError, UnicodeError, TypeError):
            # Do not expose paths, stack traces, environment or secret contents.
            return self._deny(call_id, name, "TOOL_IO_ERROR")
        return self._record(ToolOutcome(call_id, name, True, text))

    def _record(self, outcome: ToolOutcome) -> ToolOutcome:
        # If finalization fails after a side effect, CLAIMED remains in SQLite
        # and recovery refuses to replay; do not report a false success.
        if self._ledger is not None:
            self._ledger.finalize(self._scope, outcome.tool_call_id, ok=outcome.ok)
        with self._lock:
            self._audit.append(ToolAudit(
                outcome.tool_call_id, outcome.name,
                "OK" if outcome.ok else str(outcome.error_code),
            ))
        return outcome

    def _deny(self, call_id: str, name: str, code: str) -> ToolOutcome:
        return self._record(ToolOutcome(call_id, name, False, "", code))
