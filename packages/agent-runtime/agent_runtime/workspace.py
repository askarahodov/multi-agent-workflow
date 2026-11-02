"""Isolated workspace provisioning per task (ADR-107, ADR-109 §3.4).

One task gets exactly one workspace, and no two concurrent runs may share a
``workspace_id``. The default kind is a git **worktree** at
``<repo>/.worktrees/<task-id>`` on branch ``wt/<task-id>``. Provisioning is
**fail-closed**: if a worktree cannot be created the caller gets an
``ISOLATION_UNAVAILABLE`` error and must not fall back to unshared execution
(ADR-107 §3.4.4).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from .errors import ErrorKind, PlatformError, isolation_unavailable

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkspaceKind(str, Enum):
    WORKTREE = "worktree"
    SCRATCH = "scratch"
    DIR = "dir"


class WorkspaceStatus(str, Enum):
    ACTIVE = "active"
    RELEASED = "released"


@dataclass
class Workspace:
    workspace_id: str
    task_id: str
    path: Path
    branch: Optional[str]
    kind: WorkspaceKind
    status: WorkspaceStatus = WorkspaceStatus.ACTIVE
    created_at: str = field(default_factory=_utcnow)
    released_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "path": str(self.path),
            "branch": self.branch,
            "kind": self.kind.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "released_at": self.released_at,
        }


def _validate_identifier(value: str, label: str) -> str:
    if not value or not _SAFE_ID.match(value):
        raise isolation_unavailable(
            f"unsafe {label} {value!r}: only [A-Za-z0-9_.-] allowed",
            **{label: value},
        )
    return value


class WorkspaceManager:
    """Provisions, tracks and releases per-task isolated workspaces."""

    def __init__(self, root: Path, *, repo: Optional[Path] = None) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo = Path(repo).resolve() if repo is not None else None
        self._by_id: dict[str, Workspace] = {}
        self._active_by_task: dict[str, str] = {}

    # -- queries -----------------------------------------------------------
    def get(self, workspace_id: str) -> Optional[Workspace]:
        return self._by_id.get(workspace_id)

    def active_for_task(self, task_id: str) -> Optional[Workspace]:
        workspace_id = self._active_by_task.get(task_id)
        return self._by_id.get(workspace_id) if workspace_id else None

    def active_workspaces(self) -> list[Workspace]:
        return [w for w in self._by_id.values() if w.status is WorkspaceStatus.ACTIVE]

    # -- provisioning ------------------------------------------------------
    def provision(
        self,
        task_id: str,
        *,
        kind: WorkspaceKind = WorkspaceKind.WORKTREE,
        workspace_id: Optional[str] = None,
    ) -> Workspace:
        """Provision a fresh workspace for *task_id* (1:1 with the task).

        Raises ``ISOLATION_UNAVAILABLE`` when the task already holds an active
        workspace, when a ``workspace_id`` is already bound, or when the
        requested kind cannot be realised.
        """
        _validate_identifier(task_id, "task_id")
        if task_id in self._active_by_task:
            raise isolation_unavailable(
                f"task {task_id!r} already holds an active workspace",
                task_id=task_id,
                workspace_id=self._active_by_task[task_id],
            )
        wid = workspace_id or f"ws-{uuid.uuid4().hex[:12]}"
        _validate_identifier(wid, "workspace_id")
        if wid in self._by_id:
            raise isolation_unavailable(
                f"workspace_id {wid!r} already in use (no two runs may share a workspace)",
                workspace_id=wid,
            )
        if kind is WorkspaceKind.WORKTREE:
            workspace = self._provision_worktree(task_id, wid)
        elif kind is WorkspaceKind.DIR:
            workspace = self._provision_dir(task_id, wid)
        elif kind is WorkspaceKind.SCRATCH:
            workspace = self._provision_scratch(task_id, wid)
        else:  # pragma: no cover - enum exhaustiveness
            raise isolation_unavailable(f"unsupported workspace kind {kind!r}")

        self._by_id[wid] = workspace
        self._active_by_task[task_id] = wid
        return workspace

    def _provision_worktree(self, task_id: str, workspace_id: str) -> Workspace:
        if self.repo is None:
            raise isolation_unavailable(
                "worktree workspace requested but no repo configured",
                task_id=task_id,
            )
        if not (self.repo / ".git").exists():
            raise isolation_unavailable(
                f"{self.repo} is not a git repository (fail-closed, no unshared fallback)",
                task_id=task_id,
            )
        path = self.root / _validate_identifier(task_id, "task_id")
        branch = f"wt/{task_id}"
        if path.exists():
            raise isolation_unavailable(f"workspace path already exists: {path}", path=str(path))
        _run_git(self.repo, "worktree", "add", "-b", branch, str(path), "HEAD")
        return Workspace(
            workspace_id=workspace_id,
            task_id=task_id,
            path=path,
            branch=branch,
            kind=WorkspaceKind.WORKTREE,
        )

    def _provision_dir(self, task_id: str, workspace_id: str) -> Workspace:
        path = self.root / _validate_identifier(task_id, "task_id")
        path.mkdir(parents=True, exist_ok=False)
        return Workspace(workspace_id, task_id, path, None, WorkspaceKind.DIR)

    def _provision_scratch(self, task_id: str, workspace_id: str) -> Workspace:
        path = self.root / _validate_identifier(task_id, "task_id")
        path.mkdir(parents=True, exist_ok=False)
        return Workspace(workspace_id, task_id, path, None, WorkspaceKind.SCRATCH)

    # -- release / cleanup -------------------------------------------------
    def release(self, workspace_id: str, *, remove: bool = False) -> None:
        workspace = self._by_id.get(workspace_id)
        if workspace is None:
            raise PlatformError(ErrorKind.NOT_FOUND, f"unknown workspace {workspace_id!r}")
        if workspace.status is WorkspaceStatus.RELEASED:
            return
        if remove:
            self._remove_workspace(workspace)
        workspace.status = WorkspaceStatus.RELEASED
        workspace.released_at = _utcnow()
        self._active_by_task.pop(workspace.task_id, None)

    def _remove_workspace(self, workspace: Workspace) -> None:
        if workspace.kind is WorkspaceKind.WORKTREE:
            if self.repo is not None and (self.repo / ".git").exists():
                _run_git(self.repo, "worktree", "remove", "--force", str(workspace.path))
                _run_git(self.repo, "branch", "-D", workspace.branch or "", check=False)
            elif workspace.path.exists():
                shutil.rmtree(workspace.path, ignore_errors=True)
        elif workspace.path.exists():
            shutil.rmtree(workspace.path, ignore_errors=True)

    def release_for_task(self, task_id: str, *, remove: bool = False) -> None:
        workspace_id = self._active_by_task.get(task_id)
        if workspace_id:
            self.release(workspace_id, remove=remove)

    # -- scoping -----------------------------------------------------------
    def is_within_workspace(self, workspace_id: str, candidate: str | os.PathLike) -> bool:
        workspace = self._by_id.get(workspace_id)
        if workspace is None:
            return False
        root = workspace.path.resolve()
        candidate_path = Path(candidate)
        if not candidate_path.is_absolute():
            candidate_path = root / candidate_path
        resolved = candidate_path.resolve()
        return resolved == root or root in resolved.parents


def _run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - environment dependent
        raise isolation_unavailable("git executable not found; cannot isolate workspace") from exc
    if check and result.returncode != 0:
        raise isolation_unavailable(
            f"git {' '.join(args)} failed: {result.stderr.strip()}",
            returncode=result.returncode,
        )
    return result
