"""Unit tests for the Workspace Manager + reaper (spec §6, AC-7/AC-8)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.hardening.models import WorkspaceSpec, WorkspaceState
from runtime.hardening.workspace_manager import (
    ChecksumViolationError,
    InsufficientCapacityError,
    UnknownWorkspaceError,
    WorkspaceAllocator,
    WorkspaceError,
    WorkspaceManager,
    WorkspaceReaper,
    sha256_of_file,
)


def test_create_workspace_ready(workspace_manager: WorkspaceManager) -> None:
    ws = workspace_manager.create(WorkspaceSpec(baseImage="img", scratchBytes=1024))
    assert ws.state == WorkspaceState.READY
    assert ws.overlayUpper is not None
    assert workspace_manager.exists(ws.id)


def test_create_idempotent_returns_existing(workspace_manager: WorkspaceManager) -> None:
    first = workspace_manager.create(WorkspaceSpec(id="ws-dup"))
    second = workspace_manager.create(WorkspaceSpec(id="ws-dup"))
    assert first.id == second.id
    assert first.state == WorkspaceState.READY


def test_create_durable_volume(workspace_manager: WorkspaceManager) -> None:
    ws = workspace_manager.create(WorkspaceSpec(durable=True, durabilityClass="persistent"))
    assert ws.durablePath is not None


def test_rollback_leaves_zero_orphans(workspace_manager: WorkspaceManager, tmp_path: Path) -> None:
    """AC-7: induced partial failure rolls back with zero orphaned resources."""
    root = tmp_path / "ws-root"
    manager = WorkspaceManager(root=root)

    def failing_check(spec: WorkspaceSpec) -> None:
        # Simulate a staging failure (e.g. cgroup budget exhausted mid-create).
        raise InsufficientCapacityError("no budget")

    manager.allocator = WorkspaceAllocator(check=failing_check)
    with pytest.raises(InsufficientCapacityError):
        manager.create(WorkspaceSpec())
    # Zero orphaned directories under root.
    assert not list(root.iterdir()) if root.exists() else True


def test_rollback_after_partial_staging(
    workspace_manager: WorkspaceManager, tmp_path: Path
) -> None:
    """AC-7: failure after some dirs staged leaves no orphans."""
    root = tmp_path / "ws2"
    manager = WorkspaceManager(root=root)
    spec = WorkspaceSpec()

    # Monkeypatch _mkdir to fail after creating the root dir.
    original = manager._mkdir
    calls: list[Path] = []

    def flaky_mkdir(allocated: list[Path], path: Path) -> None:
        original(allocated, path)
        calls.append(path)
        if len(calls) >= 3:
            raise OSError("simulated crash during staging")

    manager._mkdir = flaky_mkdir  # type: ignore[method-assign]
    with pytest.raises(OSError):
        manager.create(spec)
    assert not list(root.iterdir()) if root.exists() else True


def test_snapshot_and_restore_checksum(workspace_manager: WorkspaceManager) -> None:
    ws = workspace_manager.create(WorkspaceSpec())
    snap = workspace_manager.snapshot(ws.id)
    assert snap.checksum
    restored = workspace_manager.restore(ws.id, snap.id)
    assert restored.state == WorkspaceState.READY


def test_restore_checksum_violation(workspace_manager: WorkspaceManager) -> None:
    """AC: snapshot checksum violation returns 422 (ChecksumViolationError)."""
    ws = workspace_manager.create(WorkspaceSpec())
    snap = workspace_manager.snapshot(ws.id)
    # Mutate the workspace so the checksum no longer matches.
    scratch = workspace_manager.workspace_path(ws.id) / "scratch"
    (scratch / "mutated.txt").write_text("changed", encoding="utf-8")
    with pytest.raises(ChecksumViolationError):
        workspace_manager.restore(ws.id, snap.id)


def test_promote_artifacts(workspace_manager: WorkspaceManager) -> None:
    ws = workspace_manager.create(WorkspaceSpec(durable=True))
    scratch = workspace_manager.workspace_path(ws.id) / "scratch"
    (scratch / ".artifacts").mkdir(parents=True, exist_ok=True)
    (scratch / ".artifacts" / "out.txt").write_text("hello", encoding="utf-8")
    promoted = workspace_manager.promote(ws.id, [".artifacts/out.txt"])
    assert promoted[0]["path"] == ".artifacts/out.txt"
    assert promoted[0]["checksum"] == sha256_of_file(scratch / ".artifacts" / "out.txt")
    # Idempotent re-promote returns same checksum.
    again = workspace_manager.promote(ws.id, [".artifacts/out.txt"])
    assert again[0]["checksum"] == promoted[0]["checksum"]


def test_promote_rejects_escaping_path(workspace_manager: WorkspaceManager) -> None:
    ws = workspace_manager.create(WorkspaceSpec())
    with pytest.raises(WorkspaceError):
        workspace_manager.promote(ws.id, ["../etc/passwd"])


def test_validate(workspace_manager: WorkspaceManager) -> None:
    ws = workspace_manager.create(WorkspaceSpec())
    valid, checks = workspace_manager.validate(ws.id)
    assert valid is True
    assert len(checks) >= 3


def test_cleanup_idempotent(workspace_manager: WorkspaceManager) -> None:
    ws = workspace_manager.create(WorkspaceSpec())
    workspace_manager.cleanup(ws.id)
    assert not workspace_manager.exists(ws.id)
    workspace_manager.cleanup(ws.id)  # second call no-op


def test_get_unknown(workspace_manager: WorkspaceManager) -> None:
    with pytest.raises(UnknownWorkspaceError):
        workspace_manager.get("missing")


def test_reaper_reclaims_stale_heartbeat(workspace_manager: WorkspaceManager) -> None:
    ws = workspace_manager.create(WorkspaceSpec())
    reaper = WorkspaceReaper(workspace_manager, force_cleanup_seconds=1.0)
    reaper.heartbeat(ws.id, now=0.0)
    # After the force-cleanup timeout with no new heartbeat -> orphaned.
    assert ws.id in reaper.orphaned_ids(now=5.0)
    reclaimed = reaper.reclaim_once(now=5.0)
    assert ws.id in reclaimed
    assert not workspace_manager.exists(ws.id)


def test_reaper_reclaims_crash_mid_create(workspace_manager: WorkspaceManager) -> None:
    """AC-8: reaper reclaims a workspace orphaned by a controller crash mid-create."""
    root = workspace_manager.root
    orphan = root / "ws-orphan-crash"
    orphan.mkdir(parents=True, exist_ok=True)
    (orphan / ".agent-state").mkdir(parents=True, exist_ok=True)
    (orphan / ".agent-state" / "spec.json").write_text("{}", encoding="utf-8")
    (orphan / "scratch").mkdir(parents=True, exist_ok=True)

    reaper = WorkspaceReaper(workspace_manager, force_cleanup_seconds=1.0)
    assert "ws-orphan-crash" in reaper.orphaned_ids(now=0.0)
    reclaimed = reaper.reclaim_once(now=0.0)
    assert "ws-orphan-crash" in reclaimed
    assert not orphan.exists()


def test_spec_json_persisted(workspace_manager: WorkspaceManager) -> None:
    ws = workspace_manager.create(WorkspaceSpec(baseImage="img"))
    spec_file = workspace_manager.workspace_path(ws.id) / ".agent-state" / "spec.json"
    data = json.loads(spec_file.read_text(encoding="utf-8"))
    assert data["state"] == "ready"
