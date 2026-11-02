"""AgentSpec resolution and context minimisation (ADR-108)."""

from __future__ import annotations

import pytest

from agent_runtime.errors import ErrorKind, PlatformError
from agent_runtime.permissions import ToolPolicy
from agent_runtime.spec import (
    AgentDefinition,
    ConfigStore,
    ProfileManager,
    Role,
    build_model_context,
    compute_spec_version,
)


def test_resolve_returns_immutable_spec_with_intersection_capabilities(profiles):
    spec = profiles.resolve("default", instance_id="inst-1")
    # role allows fs.read/fs.write/code.run; definition also has agent.spawn,
    # which the role does not grant -> intersection excludes it.
    assert spec.capabilities == ("fs.read", "fs.write", "code.run")
    assert spec.model_profile.model_id == "openrouter/openai/gpt-4o"
    assert spec.tool_policy.name == "dev"
    assert spec.budget.max_steps == 10


def test_spec_version_is_deterministic_and_changes_with_config(store):
    pm = ProfileManager(store)
    first = pm.resolve("default", instance_id="inst-1")
    second = pm.resolve("default", instance_id="inst-1")
    assert first.spec_version == second.spec_version

    store.add_tool_policy(ToolPolicy(name="dev", permissions={"fs_read": ["workspace/**"]}, version=2))
    third = pm.resolve("default", instance_id="inst-1")
    assert third.spec_version != first.spec_version


def test_unknown_role_raises_config_error(profiles):
    with pytest.raises(PlatformError) as exc:
        profiles.resolve("nope")
    assert exc.value.kind is ErrorKind.CONFIG_ERROR


def test_missing_model_profile_fails_closed():
    store = ConfigStore()
    store.add_definition(AgentDefinition(id="def-x", name="x", default_model_profile_id=None))
    store.add_role(Role(name="default", default_definition_id="def-x"))
    with pytest.raises(PlatformError) as exc:
        ProfileManager(store).resolve("default")
    assert exc.value.kind is ErrorKind.CONFIG_ERROR
    assert "model profile" in exc.value.message


def test_missing_policy_resolves_to_deny_all(store):
    store.add_definition(
        AgentDefinition(id="def-nopolicy", name="np", default_model_profile_id="mp-1")
    )
    store.add_role(Role(name="nopolicy", default_definition_id="def-nopolicy"))
    spec = ProfileManager(store).resolve("nopolicy")
    assert spec.tool_policy.permissions == {}


def test_build_model_context_excludes_forbidden_keys(profiles):
    spec = profiles.resolve("default", instance_id="inst-1")
    messages = build_model_context(
        spec,
        task_title="Implement X",
        task_description="Do the thing",
        task_input={"api_key": "sk-secret", "nested": {"token": "t"}, "keep": "visible"},
        upstream=[{"prev_task_id": "t0", "summary": "prior work"}],
    )
    serialized = str(messages)
    assert "sk-secret" not in serialized
    assert "keep" in serialized
    assert "prior work" in serialized
    assert messages[0]["role"] == "system"


def test_build_model_context_bounds_upstream_summary(profiles):
    spec = profiles.resolve("default", instance_id="inst-1")
    big = "x" * 10_000
    messages = build_model_context(spec, task_title="t", upstream=[{"prev_task_id": "t0", "summary": big}])
    user = messages[-1]["content"]
    assert big not in user
    assert spec.context_policy.max_upstream_summary_chars < 10_000


def test_compute_spec_version_is_order_insensitive():
    a = compute_spec_version({"a": 1, "b": 2})
    b = compute_spec_version({"b": 2, "a": 1})
    assert a == b
