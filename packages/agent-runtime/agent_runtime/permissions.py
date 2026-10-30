"""Deny-by-default permission evaluation (ADR-103 §3, ADR-108 §3.3).

The runtime never trusts a model to choose its own privileges. A tool action is
allowed only when **both** conditions hold:

1. the role's ``allowed_capabilities`` grant the capability the action requires
   (intersection, never a union), and
2. the effective ``ToolPolicy.permissions`` explicitly allow the action for the
   requested resource (missing action ⇒ denied).

Optional ``spawn`` permissions are handled with *subset* semantics: a child
policy may never be broader than its parent (ADR-108 §3.3 rule 2).
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from .errors import PlatformError, validation_error

#: Permission kinds recognised by the runtime (mirrors the Tool Registry categories).
VALID_ACTIONS: tuple[str, ...] = (
    "fs_read",
    "fs_write",
    "fs_search",
    "fs_list",
    "shell",
    "git",
    "network",
    "memory",
    "task",
    "artifact",
    "spawn",
)

#: Capability token an action requires. A capability not present in the role's
#: allow-list denies the action even when the policy grants it (ADR-108 §3.3).
ACTION_CAPABILITY: dict[str, str] = {
    "fs_read": "fs.read",
    "fs_search": "fs.read",
    "fs_list": "fs.read",
    "fs_write": "fs.write",
    "shell": "code.run",
    "git": "git.use",
    "network": "net.egress",
    "memory": "memory.use",
    "task": "task.read",
    "artifact": "artifact.use",
    "spawn": "agent.spawn",
}

#: Wildcard capability that grants every action family.
CAPABILITY_WILDCARD = "*"


@dataclass(frozen=True)
class ToolPolicy:
    """Immutable tool policy document (ADR-108 §3.3)."""

    name: str = "deny-all"
    permissions: Mapping[str, Any] = field(default_factory=dict)
    requires_approval: tuple[str, ...] = ()
    version: int = 1

    @classmethod
    def deny_all(cls, name: str = "deny-all") -> "ToolPolicy":
        """Fail-closed default: nothing permitted (ADR-105 §3.4)."""
        return cls(name=name, permissions={}, requires_approval=())

    def normalized(self) -> dict[str, list[str]]:
        return normalize_permissions(self.permissions)


@dataclass(frozen=True)
class PermissionDecision:
    allow: bool
    action: str
    resource: str = ""
    reason: str = ""
    capability: Optional[str] = None
    matched_pattern: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow": self.allow,
            "action": self.action,
            "resource": self.resource,
            "reason": self.reason,
            "capability": self.capability,
            "matched_pattern": self.matched_pattern,
        }


class PermissionEvaluator:
    """Evaluates ``(capabilities ∩ policy)`` for every tool action."""

    def __init__(
        self,
        capabilities: Iterable[str],
        policy: ToolPolicy,
        *,
        action_capability: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.capabilities = frozenset(capabilities)
        self.policy = policy
        self.action_capability = dict(action_capability or ACTION_CAPABILITY)
        self._normalized = policy.normalized()

    # -- capability side ---------------------------------------------------
    def _capability_allows(self, action: str) -> tuple[bool, Optional[str]]:
        capability = self.action_capability.get(action)
        if capability is None:
            return False, None
        if CAPABILITY_WILDCARD in self.capabilities:
            return True, capability
        return capability in self.capabilities, capability

    # -- policy side -------------------------------------------------------
    def _policy_allows(self, action: str, resource: str) -> tuple[bool, Optional[str]]:
        patterns = self._normalized.get(action)
        if not patterns:
            return False, None
        for pattern in patterns:
            if _match(pattern, resource):
                return True, pattern
        return False, None

    def evaluate(self, action: str, resource: str = "") -> PermissionDecision:
        if action not in VALID_ACTIONS:
            return PermissionDecision(
                allow=False,
                action=action,
                resource=resource,
                reason=f"unknown action {action!r} (deny-by-default)",
            )
        cap_ok, capability = self._capability_allows(action)
        if not cap_ok:
            return PermissionDecision(
                allow=False,
                action=action,
                resource=resource,
                reason=(
                    f"capability {capability!r} not granted to role"
                    if capability
                    else f"no capability mapping for action {action!r}"
                ),
                capability=capability,
            )
        policy_ok, pattern = self._policy_allows(action, resource)
        if not policy_ok:
            return PermissionDecision(
                allow=False,
                action=action,
                resource=resource,
                reason="action not permitted by tool policy (missing action or no pattern match)",
                capability=capability,
            )
        return PermissionDecision(
            allow=True,
            action=action,
            resource=resource,
            reason="capability ∩ policy allow",
            capability=capability,
            matched_pattern=pattern,
        )

    def allow(self, action: str, resource: str = "") -> bool:
        return self.evaluate(action, resource).allow

    def enforce(self, action: str, resource: str = "") -> None:
        """Raise :class:`PlatformError` (``TOOL_POLICY_DENIED``) when denied."""
        decision = self.evaluate(action, resource)
        if not decision.allow:
            from .errors import policy_denied

            raise policy_denied(action, resource, decision.reason)


def normalize_permissions(permissions: Mapping[str, Any]) -> dict[str, list[str]]:
    """Validate and normalise a raw permissions mapping.

    Unknown action kinds raise a :class:`PlatformError` so a malformed policy
    fails closed at config-resolution time rather than silently denying at run
    time. ``spawn`` is a structured value and is normalised to a list of
    allowed definition ids for subset comparison.
    """
    clean: dict[str, list[str]] = {}
    for kind in permissions:
        if kind not in VALID_ACTIONS:
            raise validation_error(
                f"unknown permission kind {kind!r}; valid: {list(VALID_ACTIONS)}",
                permission_kind=kind,
            )
    for kind in VALID_ACTIONS:
        raw = permissions.get(kind)
        if raw is None:
            clean[kind] = []
            continue
        if kind == "spawn":
            if isinstance(raw, Mapping):
                allowed = raw.get("allowed_definitions", [])
            elif isinstance(raw, (list, tuple)):
                allowed = list(raw)
            else:
                raise validation_error("permission 'spawn' must be a mapping or list")
            if not all(isinstance(x, str) for x in allowed):
                raise validation_error("permission 'spawn.allowed_definitions' must be strings")
            clean[kind] = list(allowed)
            continue
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple)) or not all(isinstance(x, str) for x in raw):
            raise validation_error(f"permission kind {kind!r} must be a list of strings")
        clean[kind] = list(raw)
    return clean


def _match(pattern: str, value: str) -> bool:
    pattern = (pattern or "").strip()
    if not pattern:
        return False
    if pattern == "*":
        return True
    if not value:
        return False
    # ``**`` matches across separators; fnmatch's ``*`` already crosses ``/``.
    return fnmatch.fnmatchcase(value, pattern)


def policy_subsumes(parent: ToolPolicy | Mapping[str, Any], child: ToolPolicy | Mapping[str, Any]) -> bool:
    """Return True when *child* grants nothing *parent* does not.

    Used to validate a spawned child's policy (``child_policy ⊆ parent_policy``).
    Subset semantics are per-action pattern containment: every child pattern must
    be covered by at least one parent pattern for the same action.
    """
    p_perms = normalize_permissions(parent.permissions if isinstance(parent, ToolPolicy) else parent)
    c_perms = normalize_permissions(child.permissions if isinstance(child, ToolPolicy) else child)
    for action in VALID_ACTIONS:
        parent_patterns = p_perms[action]
        child_patterns = c_perms[action]
        if not child_patterns:
            continue
        if action == "spawn":
            # A child's allowed definitions must be a subset of the parent's.
            if not set(child_patterns).issubset(set(parent_patterns)):
                return False
            continue
        for cpat in child_patterns:
            if not any(_pattern_covers(ppat, cpat) for ppat in parent_patterns):
                return False
    return True


def _pattern_covers(parent_pattern: str, child_pattern: str) -> bool:
    """Approximate containment: does *parent_pattern* cover *child_pattern*?

    A parent ``*``/``**`` covers everything. Otherwise containment is decided by
    testing the child pattern with its wildcards removed against the parent
    pattern; this is conservative (a false negative denies, never widens).
    """
    if parent_pattern in ("*", "**"):
        return True
    if child_pattern in ("*", "**"):
        return False  # child broader than a concrete parent
    probe = child_pattern.replace("*", "x")
    return _match(parent_pattern, probe)
