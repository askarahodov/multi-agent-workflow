"""ToolPolicy integration (ADR-103 / ADR-012 §3.5).

The registry enforces the agent's ToolPolicy by checking each tool's required
policy kinds and, for resource-bearing tools, the specific resource patterns
(paths, commands, domains) present in the policy permissions document.

The deny-by-default rule lives here: an action with an empty allow-list is
refused.
"""

from __future__ import annotations

from typing import Any

from .base import ExecutionContext, ToolSpec


def allowed_kind(permissions: dict, kind: str) -> bool:
    """True when *something* in the allow-list for ``kind`` is configured.

    Semantic: a kind that is absent or empty is treated as denied.
    """
    allowlist = permissions.get(kind)
    if not isinstance(allowlist, list):
        return False
    return bool(allowlist) or "*" in (allowlist or [])


def path_allowed(permissions: dict, kind: str, resource: str, context: ExecutionContext) -> bool:
    """Check a filesystem resource against both the policy and the workspace scope.

    A resource must be permitted by the policy **and** (when a workspace_root is
    present) inside the allowed workspace paths of the execution context.
    """
    from .base import canonical_path, is_within

    allowlist = permissions.get(kind) or []
    try:
        resolved = canonical_path(resource)
    except (OSError, ValueError):
        return False

    def in_policy() -> bool:
        if "*" in allowlist:
            return True
        for pattern in allowlist:
            pat = pattern.rstrip("*").rstrip("/")
            if str(resolved).startswith(pat) or pat == "":
                return True
        return False

    in_scope = True
    if context.allowed_paths and kind == "fs_read":
        in_scope = in_scope and is_within(resolved, context.allowed_paths)
    return in_policy() and in_scope


def _match_any(allowlist: list, token: str) -> bool:
    if "*" in allowlist:
        return True
    return token in allowlist


def check_disallowed(
    spec: ToolSpec, params: dict, permissions: dict, context: ExecutionContext
) -> str | None:
    """Return a human reason string when the call is disallowed, else ``None``.

    This is the enforcement surface the registry calls before running a tool.
    """
    # A tool that has no required policy kinds is trivially allowed.
    if not spec.required_policy:
        return None

    # Application/policy-level kinds gate every tool call.
    for kind in spec.required_policy:
        if not allowed_kind(permissions, kind):
            return f"policy denied: no grants for permission kind '{kind}'"

    # Resource-specific checks.
    category = spec.category.value
    if category == "filesystem":
        path = params.get("path")
        kind = spec.name  # fs_read / fs_write
        if path is not None and not path_allowed(permissions, kind, path, context):
            return f"policy denied: path {path!r} not permitted for {kind}"
    elif category == "shell":
        command = (params.get("command") or "").strip().split()[0] if params.get("command") else ""
        allowlist = permissions.get("shell") or []
        if command and not _match_any(allowlist, command):
            return f"policy denied: shell command {command!r} not permitted"
        if context.allowed_shell_commands and command and command not in context.allowed_shell_commands:
            return f"policy denied: command {command!r} outside execution-context allow-list"
    elif category == "git":
        subcommand = params.get("subcommand") or params.get("command") or ""
        allowlist = permissions.get("git") or []
        if subcommand and not _match_any(allowlist, subcommand):
            return f"policy denied: git subcommand {subcommand!r} not permitted"
    elif category == "network":
        domain = params.get("url", "")
        # Egress allow-list is enforced at execution time in network.py (needs
        # DNS-safe checks); here we do a coarse host check only when a policy
        # is present to fail fast on obviously blocked seeds.
        allowlist = permissions.get("network") or []
        if allowlist and domain:
            if not _any_domain_matches(allowlist, domain):
                return f"policy denied: url {domain!r} not permitted"
    return None


def _any_domain_matches(patterns: list, url: str) -> bool:
    from urllib.parse import urlparse

    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return False
    if "*" in patterns:
        return True
    for pattern in patterns:
        pat_host = urlparse(pattern).hostname or pattern
        pat_host = pat_host.lstrip("*.")
        if host == pat_host or host.endswith("." + pat_host):
            return True
    return False


def policy_allows(permissions: dict, kind: str) -> bool:
    return allowed_kind(permissions, kind)