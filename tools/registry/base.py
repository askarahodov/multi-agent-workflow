"""Core types for the Tool Registry (ADR-012).

A *tool* is a single named capability an agent can invoke (``fs_read``,
``shell_exec``, ``git_read`` ...). The registry holds :class:`ToolSpec` metadata
for every tool, validates parameters/results against JSON Schema, enforces the
agent's ToolPolicy (ADR-103) and executes the tool inside a scoped
:class:`ExecutionContext`.

The registry is deliberately a **library** — tool execution happens in the
agent's container context (via runtime-hardening). It is not a network service.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

import jsonschema

# ---------------------------------------------------------------------------
# Tool categories (PRD §13)
# ---------------------------------------------------------------------------


class ToolCategory(str, Enum):
    FILESYSTEM = "filesystem"
    SHELL = "shell"
    GIT = "git"
    NETWORK = "network"
    MEMORY = "memory"
    TASK = "task"
    ARTIFACT = "artifact"
    SPAWN = "agent_spawn"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """Base class for all tool-registry errors."""


class ToolNotFoundError(ToolError):
    """Raised when an unknown tool name is resolved."""


class ToolParamError(ToolError):
    """Raised when tool parameters fail JSON Schema validation."""


class ToolResultError(ToolError):
    """Raised when a tool result fails its result schema."""


class ToolPolicyDeniedError(ToolError):
    """Raised when a tool action is denied by the agent ToolPolicy."""


class ToolExecutionError(ToolError):
    """Raised when the underlying tool implementation fails."""


class ToolTimeoutError(ToolError):
    """Raised when a tool exceeds its configured timeout."""


# ---------------------------------------------------------------------------
# Execution context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionContext:
    """What a tool may touch during one call.

    Permissions are resolved *before* the call (from the agent's ToolPolicy plus
    workspace scoping) and baked into the context — the registry never falls
    back to a permissive default.
    """

    run_id: str
    agent_instance_id: str
    task_id: Optional[str] = None
    workspace_root: Optional[Path] = None
    cwd: Optional[Path] = None
    allowed_paths: tuple = ()  # tuple[str] absolute path prefixes (canonicalized)
    allowed_shell_commands: tuple = ()  # tuple[str] command prefixes
    allowed_git_commands: tuple = ()  # tuple[str] subcommands e.g. ("status", "diff")
    allowed_domains: tuple = ()  # tuple[str] egress allow-list (network tool)
    memory_level: str = "agent"
    parent_run_id: Optional[str] = None  # set for spawn_agent children
    metadata: dict = field(default_factory=dict)  # correlation ids, timings

    def child_for_spawn(self, child_run_id: str) -> "ExecutionContext":
        """Produce a strictly-narrower context for a spawned agent child.

        A child can never expand the parent's rights: it inherits the same
        allowed lists (subset semantics are enforced by the spawn tool).
        """
        return ExecutionContext(
            run_id=child_run_id,
            agent_instance_id=self.agent_instance_id,
            task_id=self.task_id,
            workspace_root=self.workspace_root,
            cwd=self.cwd,
            allowed_paths=self.allowed_paths,
            allowed_shell_commands=self.allowed_shell_commands,
            allowed_git_commands=self.allowed_git_commands,
            allowed_domains=self.allowed_domains,
            memory_level=self.memory_level,
            parent_run_id=self.run_id,
            metadata=self.metadata,
        )


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


class ToolStatus(str, Enum):
    SUCCESS = "success"
    DENIED = "denied"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class ToolResult:
    """Uniform, structured result for every tool call (PRD §13)."""

    status: ToolStatus
    data: Any = None
    error: Optional[str] = None
    duration_ms: int = 0
    tool: Optional[str] = None
    params_hash: Optional[str] = None

    @classmethod
    def success(cls, data: Any, tool: Optional[str] = None, duration_ms: int = 0) -> "ToolResult":
        return cls(
            status=ToolStatus.SUCCESS,
            data=data,
            tool=tool,
            duration_ms=duration_ms,
        )

    @classmethod
    def denied(cls, reason: str, tool: Optional[str] = None) -> "ToolResult":
        return cls(status=ToolStatus.DENIED, error=reason, tool=tool)

    @classmethod
    def error(cls, message: str, tool: Optional[str] = None, duration_ms: int = 0) -> "ToolResult":
        return cls(status=ToolStatus.ERROR, error=message, tool=tool, duration_ms=duration_ms)

    @classmethod
    def timeout(cls, tool: Optional[str] = None, duration_ms: int = 0) -> "ToolResult":
        return cls(status=ToolStatus.TIMEOUT, error="tool timeout", tool=tool, duration_ms=duration_ms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "data": self.data,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "tool": self.tool,
            "params_hash": self.params_hash,
        }


# ---------------------------------------------------------------------------
# Tool specification
# ---------------------------------------------------------------------------


class ToolSpec:
    """Metadata + policies for a single tool.

    ``required_policy`` lists the ToolPolicy permission kind(s) that gate the
    tool (ADR-103). The registry refuses to run a tool whose policy kinds are
    not all satisfied — deny-by-default.
    """

    def __init__(
        self,
        name: str,
        category: ToolCategory,
        description: str,
        params_schema: dict,
        result_schema: Optional[dict] = None,
        required_policy: Optional[list[str]] = None,
        default_timeout_ms: int = 30000,
        max_retries: int = 0,
        is_destructive: bool = False,
        handler: Optional[Callable] = None,
    ) -> None:
        self.name = name
        self.category = category if isinstance(category, ToolCategory) else ToolCategory(category)
        self.description = description
        self.params_schema = params_schema or {"type": "object"}
        self.result_schema = result_schema
        self.required_policy = required_policy or [name]
        self.default_timeout_ms = default_timeout_ms
        self.max_retries = max_retries
        self.is_destructive = is_destructive
        self.handler = handler

    def validate_params(self, params: dict) -> None:
        try:
            jsonschema.validate(instance=params, schema=self.params_schema)
        except jsonschema.ValidationError as exc:
            raise ToolParamError(f"params for '{self.name}' invalid: {exc.message}") from exc

    def validate_result(self, data: Any) -> None:
        if self.result_schema is None:
            return
        try:
            jsonschema.validate(instance=data, schema=self.result_schema)
        except jsonschema.ValidationError as exc:
            raise ToolResultError(f"result from '{self.name}' invalid: {exc.message}") from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def canonical_path(path: str | os.PathLike) -> Path:
    """Return a canonicalized (resolved, normalised) path.

    This is the first line of defense against path traversal / symlink escape:
    everything the filesystem tools compare against must be produced here.
    """
    return Path(path).expanduser().resolve()


def is_within(path: Path, allowed_prefixes) -> bool:
    """True when ``path`` is inside at least one allowed prefix.

    Both arguments must already be canonicalized (see :func:`canonical_path`).
    """
    for prefix in allowed_prefixes:
        prefix_path = Path(prefix)
        try:
            path.relative_to(prefix_path)
            return True
        except ValueError:
            continue
    return False


def stable_hash(*parts: Any) -> str:
    """A stable, non-cryptographic digest for audit/correlation purposes."""
    import hashlib

    blob = json.dumps(parts, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


def new_id() -> str:
    return str(uuid.uuid4())


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default