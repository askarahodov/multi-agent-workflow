"""Shared fixtures for the agent-runtime test suite."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_runtime.limits import Budget
from agent_runtime.permissions import ToolPolicy
from agent_runtime.spec import (
    AgentDefinition,
    AgentInstance,
    ConfigStore,
    ModelProfile,
    ProfileManager,
    RetryPolicy,
    Role,
)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """An initialised git repo with one commit (for worktree provisioning tests)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "test@example.com", cwd=repo)
    _git("config", "user.name", "Test", cwd=repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    return repo


def build_store(*, capabilities=("fs.read", "fs.write", "code.run"), permissions=None,
                budget=None, max_turns=50) -> ConfigStore:
    """A small but complete configuration plane for tests."""
    store = ConfigStore()
    policy = ToolPolicy(
        name="dev",
        permissions=permissions
        if permissions is not None
        else {
            "fs_read": ["workspace/**", "project/**"],
            "fs_write": ["workspace/**"],
            "shell": ["python", "pytest", "git"],
        },
        requires_approval=(),
    )
    store.add_tool_policy(policy)
    store.add_model_profile(
        ModelProfile(
            id="mp-1",
            provider_id="prov-1",
            model_id="openrouter/openai/gpt-4o",
            context_window=8192,
            retry_policy=RetryPolicy(max_attempts=3, base_delay_ms=1),
            budget=Budget(max_steps=10, max_tokens=10_000, max_cost_usd=1.0, max_wall_time_ms=60_000),
        )
    )
    store.add_definition(
        AgentDefinition(
            id="def-1",
            name="developer",
            system_prompt="You are a careful engineer.",
            default_model_profile_id="mp-1",
            default_tool_policy_id="dev",
            capabilities=("fs.read", "fs.write", "code.run", "agent.spawn"),
        )
    )
    store.add_instance(
        AgentInstance(
            id="inst-1",
            definition_id="def-1",
            model_profile_id="mp-1",
            tool_policy_id="dev",
            config={"max_turns": max_turns, "resource_tier": "medium"},
        )
    )
    store.add_role(
        Role(
            name="default",
            default_definition_id="def-1",
            allowed_capabilities=tuple(capabilities),
        )
    )
    return store


@pytest.fixture
def store() -> ConfigStore:
    return build_store()


@pytest.fixture
def profiles(store: ConfigStore) -> ProfileManager:
    return ProfileManager(store)
