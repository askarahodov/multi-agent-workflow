"""Shared fixtures: a synthetic cgroup v2 tree and workspace root in tmp."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.hardening.resource_manager import ResourceManager
from runtime.hardening.workspace_manager import WorkspaceManager


@pytest.fixture
def cgroup_root(tmp_path: Path) -> Path:
    """Build a synthetic cgroupfs tree and return its root.

    Creates the parent slice with enabled subtree controllers and the control
    files ResourceManager reads/writes, so the same code path is exercised as
    against real cgroupfs.
    """
    root = tmp_path / "cgroup"
    parent = root / "agent.slice"
    parent.mkdir(parents=True, exist_ok=True)
    (parent / "cgroup.subtree_control").write_text("+cpu +memory +io +pids", encoding="utf-8")
    return root


@pytest.fixture
def resource_manager(cgroup_root: Path) -> ResourceManager:
    return ResourceManager(root=cgroup_root, parent_slice="agent.slice")


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    return tmp_path / "workspaces"


@pytest.fixture
def workspace_manager(workspace_root: Path) -> WorkspaceManager:
    return WorkspaceManager(root=workspace_root)
