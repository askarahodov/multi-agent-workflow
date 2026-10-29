"""Isolated workspace provisioning (ADR-107/109)."""

from __future__ import annotations

import subprocess

import pytest

from agent_runtime.errors import ErrorKind, PlatformError
from agent_runtime.workspace import WorkspaceKind, WorkspaceManager, WorkspaceStatus


def test_provision_worktree_creates_branch_and_isolated_dir(tmp_path, git_repo):
    manager = WorkspaceManager(tmp_path / "ws", repo=git_repo)
    ws = manager.provision("t-1", kind=WorkspaceKind.WORKTREE)

    assert ws.branch == "wt/t-1"
    assert ws.path.exists()
    assert (ws.path / "README.md").exists()

    listed = subprocess.run(
        ["git", "worktree", "list"], cwd=git_repo, capture_output=True, text=True, check=True
    ).stdout
    assert str(ws.path) in listed


def test_two_tasks_get_distinct_workspaces(tmp_path, git_repo):
    manager = WorkspaceManager(tmp_path / "ws", repo=git_repo)
    a = manager.provision("t-a", kind=WorkspaceKind.WORKTREE)
    b = manager.provision("t-b", kind=WorkspaceKind.WORKTREE)
    assert a.workspace_id != b.workspace_id
    assert a.path != b.path


def test_second_provision_for_same_task_fails_closed(tmp_path, git_repo):
    manager = WorkspaceManager(tmp_path / "ws", repo=git_repo)
    manager.provision("t-1", kind=WorkspaceKind.WORKTREE)
    with pytest.raises(PlatformError) as exc:
        manager.provision("t-1", kind=WorkspaceKind.WORKTREE)
    assert exc.value.kind is ErrorKind.ISOLATION_UNAVAILABLE


def test_workspace_id_collision_rejected(tmp_path):
    manager = WorkspaceManager(tmp_path / "ws")
    manager.provision("t-1", kind=WorkspaceKind.SCRATCH, workspace_id="ws-fixed")
    with pytest.raises(PlatformError) as exc:
        manager.provision("t-2", kind=WorkspaceKind.SCRATCH, workspace_id="ws-fixed")
    assert exc.value.kind is ErrorKind.ISOLATION_UNAVAILABLE


def test_unsafe_task_id_rejected(tmp_path):
    manager = WorkspaceManager(tmp_path / "ws")
    with pytest.raises(PlatformError) as exc:
        manager.provision("../escape", kind=WorkspaceKind.SCRATCH)
    assert exc.value.kind is ErrorKind.ISOLATION_UNAVAILABLE


def test_worktree_without_repo_fails_closed(tmp_path):
    manager = WorkspaceManager(tmp_path / "ws")  # no repo configured
    with pytest.raises(PlatformError) as exc:
        manager.provision("t-1", kind=WorkspaceKind.WORKTREE)
    assert exc.value.kind is ErrorKind.ISOLATION_UNAVAILABLE


def test_non_git_dir_fails_closed(tmp_path):
    not_repo = tmp_path / "notrepo"
    not_repo.mkdir()
    manager = WorkspaceManager(tmp_path / "ws", repo=not_repo)
    with pytest.raises(PlatformError) as exc:
        manager.provision("t-1", kind=WorkspaceKind.WORKTREE)
    assert exc.value.kind is ErrorKind.ISOLATION_UNAVAILABLE


def test_release_frees_task_slot(tmp_path):
    manager = WorkspaceManager(tmp_path / "ws")
    ws = manager.provision("t-1", kind=WorkspaceKind.SCRATCH)
    manager.release(ws.workspace_id, remove=True)
    assert manager.active_for_task("t-1") is None
    assert manager.get(ws.workspace_id).status is WorkspaceStatus.RELEASED
    # a new workspace may now be provisioned for the same task
    again = manager.provision("t-1", kind=WorkspaceKind.SCRATCH)
    assert again.workspace_id != ws.workspace_id


def test_is_within_workspace_scope(tmp_path):
    manager = WorkspaceManager(tmp_path / "ws")
    ws = manager.provision("t-1", kind=WorkspaceKind.SCRATCH)
    assert manager.is_within_workspace(ws.workspace_id, "src/main.py") is True
    assert manager.is_within_workspace(ws.workspace_id, str(ws.path / "a" / "b")) is True
    assert manager.is_within_workspace(ws.workspace_id, "/etc/passwd") is False
    assert manager.is_within_workspace("unknown", "x") is False


def test_release_removes_worktree(tmp_path, git_repo):
    manager = WorkspaceManager(tmp_path / "ws", repo=git_repo)
    ws = manager.provision("t-rm", kind=WorkspaceKind.WORKTREE)
    manager.release(ws.workspace_id, remove=True)
    listed = subprocess.run(
        ["git", "worktree", "list"], cwd=git_repo, capture_output=True, text=True, check=True
    ).stdout
    assert str(ws.path) not in listed
