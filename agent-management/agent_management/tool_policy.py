"""Tool policy enforcement for agent instances.

A tool policy is a JSON document describing which filesystem / Git / shell / network
operations an agent is permitted to perform, for example::

    {
      "fs_read":  ["/workspace/**"],
      "fs_write": ["/workspace/out/**"],
      "git":      ["status", "diff", "log", "add", "commit"],
      "shell":    ["pytest", "python", "npm", "ls", "cat"],
      "network":  ["https://api.example.com/**"]
    }

The checker exposes ``allow`` (returns bool) and ``enforce`` (raises
:class:`ToolPolicyDenied`) so call sites can either test-then-act or fail fast.
The secure default is deny-all: an action with an empty allow-list is refused.
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any, Dict

from .errors import ToolPolicyDenied, ValidationError

VALID_KINDS = ("fs_read", "fs_write", "git", "shell", "network")


def normalize_policy(permissions: Dict[str, Any]) -> Dict[str, list]:
    """Validate and normalize a permissions dict into allowed-kind → pattern lists."""
    clean: Dict[str, list] = {}
    unknown = set(permissions) - set(VALID_KINDS)
    if unknown:
        raise ValidationError(
            f"Unknown permission kinds: {sorted(unknown)}. Valid: {list(VALID_KINDS)}"
        )
    for kind in VALID_KINDS:
        raw = permissions.get(kind, [])
        if raw is None:
            clean[kind] = []
            continue
        if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
            raise ValidationError(f"Permission kind '{kind}' must be a list of strings")
        clean[kind] = list(raw)
    return clean


def _match(pattern: str, value: str) -> bool:
    pattern = (pattern or "").strip()
    if not pattern:
        return False
    if pattern == "*":
        return True
    return fnmatch.fnmatchcase(value, pattern) or value.startswith(pattern.rstrip("*"))


class ToolPolicyEngine:
    """Checks actions against a normalized tool-policy permissions mapping."""

    @staticmethod
    def allow(
        permissions: Dict[str, Any], action: str, resource: str = ""
    ) -> bool:
        """Return True when the action+resource is permitted by the policy."""
        if action not in VALID_KINDS:
            # Unknown action kinds are denied by default.
            return False
        clean = normalize_policy(permissions)
        patterns = clean[action]
        if not patterns:
            return False
        if "*" in patterns:
            return True
        if not resource:
            return False
        return any(_match(p, resource) for p in patterns)

    @classmethod
    def enforce(cls, permissions: Dict[str, Any], action: str, resource: str = "") -> None:
        if not cls.allow(permissions, action, resource):
            raise ToolPolicyDenied(
                f"Tool action {action!r} denied by policy"
                + (f" for resource {resource!r}" if resource else "")
            )

    @staticmethod
    def classify_fs(path: str) -> str:
        """Return the permission kind ('fs_read'/'fs_write') implied by a path.

        Raises ValidationError when no side is deducible.
        """
        if not path:
            raise ValidationError("Filesystem action requires a path")
        # Non-existence of a parent component's write markers:
        # a conservative classifier keeps fast/correct defaults for tests.
        normalized = os.path.normpath(path)
        if normalized.startswith(("/tmp", os.sep + "tmp")):
            return "fs_write"
        if os.path.exists(path) and os.access(path, os.W_OK):
            return "fs_write"
        return "fs_read"


#: A permissive development policy used only when no explicit default is configured.
DEFAULT_PERMISSIVE_POLICY = {
    "fs_read": ["**"],
    "fs_write": ["**"],
    "git": ["*"],
    "shell": ["*"],
    "network": ["*"],
}