"""Shared fixtures for the tools package tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure repo root is importable so ``import tools`` works regardless of cwd.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def workspace(tmp_path: Path):
    """A fresh scoped workspace directory."""
    return tmp_path


@pytest.fixture
def ctx(workspace: Path):
    """A minimal ExecutionContext rooted at the workspace."""
    from tools.registry import ExecutionContext

    return ExecutionContext(
        run_id="run-1",
        agent_instance_id="agent-1",
        task_id="task-1",
        workspace_root=workspace,
        cwd=workspace,
        allowed_paths=(str(workspace.resolve()),),
        allowed_shell_commands=("ls", "python", "pytest", "echo"),
        allowed_git_commands=("status", "diff", "log", "add", "commit"),
        allowed_domains=("https://example.com", "https://api.example.com"),
    )