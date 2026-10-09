"""Tool policy enforcement: allow/enforce semantics, secure default deny-all,
path/command matching, and an integration check through the service layer.
"""

from __future__ import annotations

import pytest

from agent_management.errors import ToolPolicyDenied, ValidationError
from agent_management.tool_policy import ToolPolicyEngine
from tests.conftest import seed_definition, seed_policy, seed_profile, seed_provider


class TestPolicyEngine:
    def test_deny_all_by_default(self):
        assert ToolPolicyEngine.allow({}, "shell", "ls") is False

    def test_wildcard_allows_all(self):
        perms = {"shell": ["*"]}
        assert ToolPolicyEngine.allow(perms, "shell", "pytest") is True

    def test_kind_not_present_denied(self):
        perms = {"shell": ["pytest"]}
        assert ToolPolicyEngine.allow(perms, "fs_read", "/workspace/a.py") is False

    def test_path_globs(self):
        perms = {"fs_read": ["/workspace/**", "/tmp/**"], "fs_write": ["/workspace/out/**"]}
        assert ToolPolicyEngine.allow(perms, "fs_read", "/workspace/src/x.py") is True
        assert ToolPolicyEngine.allow(perms, "fs_read", "/etc/passwd") is False
        assert ToolPolicyEngine.allow(perms, "fs_write", "/workspace/out/report.md") is True
        assert ToolPolicyEngine.allow(perms, "fs_write", "/workspace/src/x.py") is False

    def test_unknown_kind_denied(self):
        assert ToolPolicyEngine.allow({}, "not_a_kind", "x") is False

    def test_enforce_raises_on_denial(self):
        perms = {"git": ["status", "diff"], "network": ["https://api.example.com/**"]}
        ToolPolicyEngine.enforce(perms, "git", "status")
        with pytest.raises(ToolPolicyDenied):
            ToolPolicyEngine.enforce(perms, "git", "push")
        ToolPolicyEngine.enforce(perms, "network", "https://api.example.com/v1/ping")
        with pytest.raises(ToolPolicyDenied):
            ToolPolicyEngine.enforce(perms, "network", "http://attacker.example.com/x")

    def test_empty_allow_list_is_deny(self):
        assert ToolPolicyEngine.allow({"fs_write": []}, "fs_write", "/tmp/x") is False

    def test_invalid_kind_raises_validation_error(self):
        with pytest.raises(ValidationError):
            ToolPolicyEngine.allow({"bogus": ["x"]}, "shell", "ls")


class TestPolicyServiceIntegration:
    async def test_definition_tool_policy_wired_to_instance(self, harness):
        p = await seed_provider(harness, name="tp-names")
        tp = await seed_policy(
            harness, name="restrictive",
            permissions={"shell": ["pytest"], "git": ["status", "diff"]},
        )
        d = await seed_definition(harness, name="guarded", tool_policy_id=tp.id)
        inst = await harness.service.agent_instances.create(
            {"agent_definition_id": d.id}
        )
        assert inst.tool_policy_id == tp.id

        policy = await harness.service.tool_policies.get(inst.tool_policy_id)
        assert ToolPolicyEngine.allow(policy.permissions, "shell", "pytest") is True
        with pytest.raises(ToolPolicyDenied):
            ToolPolicyEngine.enforce(policy.permissions, "shell", "rm -rf /")

    async def test_optimistic_update_of_policy(self, harness):
        tp = await seed_policy(harness, name="mut", permissions={"shell": ["ls"]})
        updated = await harness.service.tool_policies.update(
            tp.id, {"permissions": {"shell": ["ls", "cat"]}, "version": tp.version}
        )
        assert ToolPolicyEngine.allow(updated.permissions, "shell", "cat") is True