"""Permission intersection and deny-by-default semantics (ADR-103/108)."""

from __future__ import annotations

import pytest

from agent_runtime.errors import ErrorKind, PlatformError
from agent_runtime.permissions import (
    PermissionEvaluator,
    ToolPolicy,
    normalize_permissions,
    policy_subsumes,
)


def test_empty_policy_denies_everything():
    ev = PermissionEvaluator(capabilities=("fs.read",), policy=ToolPolicy.deny_all())
    decision = ev.evaluate("fs_read", "workspace/x")
    assert decision.allow is False
    assert "policy" in decision.reason


def test_unknown_action_is_denied():
    ev = PermissionEvaluator(capabilities=("fs.read",), policy=ToolPolicy(name="p", permissions={"fs_read": ["*"]}))
    assert ev.evaluate("rm_rf", "workspace").allow is False


def test_capability_intersection_denies_even_when_policy_grants():
    # policy grants shell, but the role lacks the code.run capability.
    policy = ToolPolicy(name="p", permissions={"shell": ["*"]})
    ev = PermissionEvaluator(capabilities=("fs.read",), policy=policy)
    decision = ev.evaluate("shell", "python")
    assert decision.allow is False
    assert "capability" in decision.reason


def test_allow_requires_capability_and_pattern_match():
    policy = ToolPolicy(name="p", permissions={"shell": ["python", "pytest"]})
    ev = PermissionEvaluator(capabilities=("code.run",), policy=policy)
    assert ev.evaluate("shell", "python").allow is True
    assert ev.evaluate("shell", "rm").allow is False


def test_wildcard_capability_grants_all_families():
    policy = ToolPolicy(name="p", permissions={"network": ["https://api.example.com/**"]})
    ev = PermissionEvaluator(capabilities=("*",), policy=policy)
    assert ev.evaluate("network", "https://api.example.com/v1").allow is True
    assert ev.evaluate("network", "https://evil.example.com/").allow is False


def test_enforce_raises_platform_error_with_policy_denied_code():
    ev = PermissionEvaluator(capabilities=("code.run",), policy=ToolPolicy(name="p", permissions={}))
    with pytest.raises(PlatformError) as exc:
        ev.enforce("shell", "python")
    assert exc.value.kind is ErrorKind.TOOL_POLICY_DENIED
    assert exc.value.retryable is False


def test_normalize_permissions_rejects_unknown_kind():
    with pytest.raises(PlatformError) as exc:
        normalize_permissions({"teleport": ["*"]})
    assert exc.value.kind is ErrorKind.VALIDATION_ERROR


def test_normalize_permissions_accepts_spawn_mapping():
    clean = normalize_permissions({"spawn": {"allowed_definitions": ["def-a"]}})
    assert clean["spawn"] == ["def-a"]


def test_policy_subsumes_checks_child_subset():
    parent = ToolPolicy(name="parent", permissions={"shell": ["python", "pytest"], "spawn": ["def-a", "def-b"]})
    narrower = ToolPolicy(name="child", permissions={"shell": ["python"], "spawn": ["def-a"]})
    wider = ToolPolicy(name="child", permissions={"shell": ["python", "rm"], "spawn": ["def-a"]})
    assert policy_subsumes(parent, narrower) is True
    assert policy_subsumes(parent, wider) is False


def test_policy_subsumes_wildcard_parent_covers_child():
    parent = ToolPolicy(name="parent", permissions={"fs_read": ["*"]})
    child = ToolPolicy(name="child", permissions={"fs_read": ["workspace/**"]})
    assert policy_subsumes(parent, child) is True


def test_policy_subsumes_concrete_parent_does_not_cover_child_wildcard():
    parent = ToolPolicy(name="parent", permissions={"fs_read": ["workspace/a"]})
    child = ToolPolicy(name="child", permissions={"fs_read": ["*"]})
    assert policy_subsumes(parent, child) is False
