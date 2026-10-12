"""Tool Registry (ADR-012).

A first-class, testable library implementing the PRD §13 tool registry:
param/result JSON Schema validation, ToolPolicy enforcement (ADR-103), timeout
and retry handling, structured per-call audit logging, and a set of MVP tools
(filesystem, shell, git, network, spawn).

Usage::

    from tools.registry import build_default_registry, ExecutionContext

    reg = build_default_registry()
    ctx = ExecutionContext(run_id="...", agent_instance_id="...",
                           workspace_root=Path("/workspace"), ...)
    result = await reg.execute("fs_list", {"path": "."}, ctx,
                               policy_permissions={...})
"""

from __future__ import annotations

from .base import (
    ExecutionContext,
    ToolCategory,
    ToolError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolParamError,
    ToolPolicyDeniedError,
    ToolResult,
    ToolResultError,
    ToolSpec,
    ToolStatus,
    ToolTimeoutError,
    canonical_path,
    is_within,
    stable_hash,
)
from .registry import ToolRegistry, get_tool_registry
from .policies import policy_allows

__all__ = [
    "ExecutionContext",
    "ToolCategory",
    "ToolError",
    "ToolExecutionError",
    "ToolNotFoundError",
    "ToolParamError",
    "ToolPolicyDeniedError",
    "ToolResult",
    "ToolResultError",
    "ToolSpec",
    "ToolStatus",
    "ToolTimeoutError",
    "ToolRegistry",
    "canonical_path",
    "get_tool_registry",
    "is_within",
    "policy_allows",
    "stable_hash",
]


def build_default_registry() -> ToolRegistry:
    """Return a :class:`ToolRegistry` with the standard MVP tool set registered."""
    from .filesystem import register_filesystem
    from .shell import register_shell
    from .git import register_git
    from .network import register_network
    from .spawn import register_spawn

    registry = ToolRegistry()
    register_filesystem(registry)
    register_shell(registry)
    register_git(registry)
    register_network(registry)
    register_spawn(registry)
    return registry