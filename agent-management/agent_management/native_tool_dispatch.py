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
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Mapping

from shared.attempt_fence import AttemptFenceDenied, TrustedSqliteAttemptFence

from .errors import ToolPolicyDenied
from .scoped_fs import ScopedFilesystemExecutor
from .trusted_https import TrustedHTTPSExecutor
from .tool_ledger import SqliteToolLedger
from .trusted_process_tools import TrustedReadOnlyProcessTools
from .trusted_https_get import TrustedHttpsGet

_CALL_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_TOOL_NAMES = frozenset({"read_file", "write_file"})
_ARG_FIELDS = {
    "read_file": frozenset({"path"}),
    "write_file": frozenset({"path", "content"}),
    "http_get": frozenset({"url"}),
    "git_status": frozenset(),
    "shell_list": frozenset(),
    "http_get": frozenset({"url"}),
}


def _require_control_file_outside_workspace(
    path: str | os.PathLike[str], root: str, inside_message: str,
) -> None:
    """Deny aliases/symlinked ancestors into model-writable workspace.

    Resolve the real path, not a lexical name supplied by an untrusted tree.
    Symlinked ancestors are disallowed even when the current target is
    outside the workspace: a mutable alias must never locate control state.
    Trusted deployment must also keep parent directories non-agent-writable.
    """
    try:
        p = Path(path)
        if p.is_symlink() or any(parent.is_symlink() for parent in p.parents):
            raise ToolPolicyDenied("Control-plane storage symlink denied")
        actual = p.resolve(strict=True)
        workspace = Path(root).resolve(strict=True)
        if os.path.commonpath((str(actual), str(workspace))) == str(workspace):
            raise ToolPolicyDenied(inside_message)
    except (OSError, ValueError) as exc:
        raise ToolPolicyDenied("Control-plane storage location unavailable") from exc


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
    An optional trusted attempt guard may fail closed immediately before tool
    I/O; it is NOT an atomic cross-process fence or a cancellation mechanism.
    """

    def __init__(
        self,
        filesystem: ScopedFilesystemExecutor,
        *,
        ledger: SqliteToolLedger | None = None,
        execution_scope: str | None = None,
        attempt_active: Callable[[], bool] | None = None,
        attempt_fence: TrustedSqliteAttemptFence | None = None,
        process_tools: TrustedReadOnlyProcessTools | None = None,
        https_get: TrustedHttpsGet | None = None,
        pinned_https: TrustedHTTPSExecutor | None = None,
    ) -> None:
        if not isinstance(filesystem, ScopedFilesystemExecutor):
            raise TypeError("A trusted scoped filesystem executor is required")
        if ledger is not None:
            if not isinstance(ledger, SqliteToolLedger) or not isinstance(execution_scope, str):
                raise TypeError("Durable ledger requires a trusted execution scope")
            _require_control_file_outside_workspace(
                ledger.path, filesystem.root,
                "Execution ledger cannot live inside agent workspace",
            )
        elif execution_scope is not None:
            raise ValueError("Execution scope requires a durable ledger")
        if attempt_active is not None:
            if not callable(attempt_active):
                raise TypeError("Trusted attempt guard must be callable")
            if ledger is None:
                raise ValueError("Attempt guard requires a durable execution ledger")
        if attempt_fence is not None:
            if not isinstance(attempt_fence, TrustedSqliteAttemptFence):
                raise TypeError("Trusted SQLite attempt fence required")
            if ledger is None or execution_scope != attempt_fence.execution_scope:
                raise ValueError("Attempt fence requires a matching durable scope and ledger")
            _require_control_file_outside_workspace(
                attempt_fence.path, filesystem.root,
                "Orchestration state cannot live inside agent workspace",
            )
        if https_get is not None:
            raise ValueError("HTTPS model dispatch requires a cancellable total deadline")
        if process_tools is not None:
            if ledger is None or attempt_fence is None:
                raise ValueError("Extended tools require durable ledger and attempt fencing")
            if Path(ledger.path).resolve(strict=True) == Path(attempt_fence.path).resolve(strict=True):
                raise ValueError("Execution ledger and orchestration fence must be separate")
            if process_tools is not None and (
                not isinstance(process_tools, TrustedReadOnlyProcessTools)
                or str(process_tools.workspace) != filesystem.root
            ):
                raise ValueError("Process executor workspace must match the assigned workspace")
        if pinned_https is not None:
            if not isinstance(pinned_https, TrustedHTTPSExecutor):
                raise TypeError("Trusted pinned HTTPS executor required")
            if ledger is None or attempt_fence is None:
                raise ValueError("HTTPS dispatch requires durable ledger and attempt fencing")
            if Path(ledger.path).resolve(strict=True) == Path(attempt_fence.path).resolve(strict=True):
                raise ValueError("Execution ledger and orchestration fence must be separate")
        self._pinned_https = pinned_https
        self._process_tools = process_tools
        self._enabled_tools = (
            _TOOL_NAMES
            | (frozenset({"git_status", "shell_list"}) if process_tools is not None else frozenset())
            | (frozenset({"http_get"}) if pinned_https is not None else frozenset())
        )
        self._attempt_fence = attempt_fence
        self._attempt_active = attempt_active
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

    def available_tools_schema(self) -> list[dict[str, Any]]:
        """Only advertise enabled, control-plane configured operations."""
        result = self.tools_schema()
        for name in ("git_status", "shell_list", "http_get"):
            if name not in self._enabled_tools:
                continue
            fields: dict[str, Any] = {"url": {"type": "string"}} if name == "http_get" else {}
            result.append({"type": "function", "function": {
                "name": name,
                "description": "Restricted policy-checked trusted operation.",
                "parameters": {
                    "type": "object", "properties": fields,
                    "required": list(fields), "additionalProperties": False,
                },
            }})
        return result

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
        safe_name = name if name in self._enabled_tools else "<unsupported>"
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

        if name not in self._enabled_tools:
            # Unknown model-supplied names must not appear in audit/log output.
            return self._deny(call_id, "<unsupported>", "UNKNOWN_TOOL")
        if (
            not isinstance(arguments, dict)
            or set(arguments) != _ARG_FIELDS[name]
            or not all(isinstance(value, str) for value in arguments.values())
        ):
            return self._deny(call_id, name, "INVALID_ARGUMENTS")

        # The guard is supplied by the trusted executor, never model output.
        # A revoked/unavailable attempt may not START a new filesystem action.
        # This check is not atomic with the I/O; the full worker generation
        # lease + quiescence barrier is a separate #38/#33 prerequisite.
        if self._attempt_active is not None:
            try:
                permitted = self._attempt_active()
            except Exception:
                # A transport/lease exception can contain secrets or paths.
                # Keep both the model response and audit detail sanitized.
                return self._deny(call_id, name, "ATTEMPT_FENCED")
            if permitted is not True:
                return self._deny(call_id, name, "ATTEMPT_FENCED")

        try:
            # This SQLite transaction remains open across actual tool I/O;
            # a concurrent server recovery cannot commit its revocation
            # until the filesystem operation has returned.
            gate = self._attempt_fence.operation() if self._attempt_fence else nullcontext()
            with gate:
                if name == "read_file":
                    text = self._filesystem.read_text(arguments["path"])
                elif name == "write_file":
                    self._filesystem.write_text(arguments["path"], arguments["content"])
                    text = "File written"
                elif name in ("git_status", "shell_list"):
                    assert self._process_tools is not None
                    result = self._process_tools.execute(name)
                    if not result.ok:
                        return self._deny(call_id, name, result.error_code or "TOOL_IO_ERROR")
                    text = result.output
                elif name == "http_get":
                    assert self._pinned_https is not None
                    # Exact URL allowlist, policy, DNS validation and pinned TLS
                    # are enforced inside the trusted executor before network IO.
                    outcome = self._pinned_https.get_bounded(arguments["url"])
                    text = outcome.content.decode("utf-8", errors="strict")
                else:
                    raise ToolPolicyDenied("Unsupported native tool")
        except AttemptFenceDenied:
            return self._deny(call_id, name, "ATTEMPT_FENCED")
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
