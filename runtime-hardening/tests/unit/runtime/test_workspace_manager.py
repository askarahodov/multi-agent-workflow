"""Unit tests for the workspace lifecycle manager (ADR-004)."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.models import WorkspaceSpec, WorkspaceState
from runtime.workspace_manager import (
    ChecksumMismatch,
    WorkspaceError,
    WorkspaceManager,
    WorkspaceNotFound,
    file_checksum,
    tree_checksum,
)


@pytest.fixture
def manager(tmp_path: Path) -> WorkspaceManager:
    return WorkspaceManager(
        root=tmp_path / "ws",
        durable_root=tmp_path / "durable",
        snapshots_root=tmp_path / "snap",
        grace_seconds=0,
        _sleep=lambda _s: None,
    )


def test_create_layout(manager: WorkspaceManager) -> None:
    ws = manager.create(WorkspaceSpec(baseImage="alpine"), "ws1")
    assert ws.state == WorkspaceState.READY
    scratch = manager.scratch_path("ws1")
    for sub in (".work", ".agent-state", ".artifacts", ".logs"):
        assert (scratch / sub).is_dir()
    assert manager.validate("ws1")[0].ok


def test_create_returns_same_id_when_ready(manager: WorkspaceManager) -> None:
    first = manager.create(WorkspaceSpec(id="ws1"), "ws1")
    second = manager.create(WorkspaceSpec(id="ws1"), "ws1")
    assert first.id == second.id
    assert second.state == WorkspaceState.READY


def test_create_durable_volume(manager: WorkspaceManager) -> None:
    ws = manager.create(WorkspaceSpec(baseImage="img", durable=True), "ws1")
    assert ws.durablePath is not None
    assert Path(ws.durablePath).is_dir()


def test_get_missing_raises(manager: WorkspaceManager) -> None:
    with pytest.raises(WorkspaceNotFound):
        manager.get("nope")


def test_list_workspaces(manager: WorkspaceManager) -> None:
    manager.create(WorkspaceSpec(), "ws1")
    manager.create(WorkspaceSpec(), "ws2")
    ids = {ws.id for ws in manager.list_all()}
    assert ids == {"ws1", "ws2"}


def test_snapshot_and_restore(manager: WorkspaceManager) -> None:
    manager.create(WorkspaceSpec(), "ws1")
    artifact = manager.scratch_path("ws1") / ".artifacts" / "out.txt"
    artifact.write_text("v1", encoding="utf-8")
    snap = manager.snapshot("ws1")
    assert snap.checksum
    assert snap.sizeBytes > 0

    artifact.write_text("v2", encoding="utf-8")
    restored = manager.restore("ws1", snap.id)
    assert restored.state == WorkspaceState.READY
    assert artifact.read_text(encoding="utf-8") == "v1"


def test_restore_checksum_mismatch(manager: WorkspaceManager) -> None:
    manager.create(WorkspaceSpec(), "ws1")
    snap = manager.snapshot("ws1")
    # Record a bogus checksum marker so validation fails.
    (manager.snapshots_root / f"{snap.id}.checksum").write_text("deadbeef", encoding="utf-8")
    with pytest.raises(ChecksumMismatch):
        manager.restore("ws1", snap.id)


def test_restore_missing_snapshot(manager: WorkspaceManager) -> None:
    manager.create(WorkspaceSpec(), "ws1")
    with pytest.raises(WorkspaceNotFound):
        manager.restore("ws1", "snap-missing")


def test_snapshot_requires_ready(manager: WorkspaceManager) -> None:
    manager.create(WorkspaceSpec(), "ws1")
    (manager.workspace_path("ws1") / "meta.json").unlink()
    with pytest.raises(WorkspaceNotFound):
        manager.snapshot("ws1")


def test_promote_artifacts(manager: WorkspaceManager) -> None:
    manager.create(WorkspaceSpec(durable=True), "ws1")
    (manager.scratch_path("ws1") / ".artifacts" / "a.txt").write_text("hello", encoding="utf-8")
    promoted = manager.promote("ws1", [".artifacts/a.txt"])
    assert promoted[0]["path"] == ".artifacts/a.txt"
    dst = Path(manager.get("ws1").durablePath) / ".artifacts" / "a.txt"
    assert dst.read_text(encoding="utf-8") == "hello"
    assert promoted[0]["checksum"] == file_checksum(dst)


def test_promote_without_durable_raises(manager: WorkspaceManager) -> None:
    manager.create(WorkspaceSpec(), "ws1")
    with pytest.raises(WorkspaceError):
        manager.promote("ws1", ["x"])


def test_promote_missing_artifact(manager: WorkspaceManager) -> None:
    manager.create(WorkspaceSpec(durable=True), "ws1")
    with pytest.raises(WorkspaceError):
        manager.promote("ws1", ["nope.txt"])


def test_cleanup_idempotent(manager: WorkspaceManager) -> None:
    manager.create(WorkspaceSpec(), "ws1")
    manager.cleanup("ws1", force=True)
    assert not manager.workspace_path("ws1").exists()
    manager.cleanup("ws1", force=True)  # no error


def test_cleanup_grace_uses_sleep(tmp_path: Path) -> None:
    slept: list[float] = []
    manager = WorkspaceManager(
        root=tmp_path / "ws",
        durable_root=tmp_path / "d",
        snapshots_root=tmp_path / "s",
        grace_seconds=5,
        _sleep=lambda s: slept.append(s),
    )
    manager.create(WorkspaceSpec(), "ws1")
    manager.cleanup("ws1")
    assert slept == [5]


def test_recover_partial_state(manager: WorkspaceManager) -> None:
    manager.create(WorkspaceSpec(baseImage="alpine"), "ws1")
    # Simulate a crash that left the metafile in "creating".
    meta = manager.workspace_path("ws1") / "meta.json"
    meta.write_text(
        '{"id": "ws1", "state": "creating", "createdAt": "2026-01-01T00:00:00Z"}',
        encoding="utf-8",
    )
    recovered = manager.recover("ws1")
    assert recovered.state == WorkspaceState.READY


def test_reap_orphans(manager: WorkspaceManager) -> None:
    manager.root.mkdir(parents=True, exist_ok=True)
    (manager.root / ".staging-orphan-1234").mkdir()
    reaped = manager.reap_orphans()
    assert reaped == [".staging-orphan-1234"]
    assert not (manager.root / ".staging-orphan-1234").exists()


def test_tree_checksum_detects_change(manager: WorkspaceManager, tmp_path: Path) -> None:
    d = tmp_path / "tree"
    (d / "a").mkdir(parents=True)
    (d / "a" / "f.txt").write_text("one", encoding="utf-8")
    first = tree_checksum(d)
    (d / "a" / "f.txt").write_text("two", encoding="utf-8")
    assert tree_checksum(d) != first


def test_invalid_workspace_id(manager: WorkspaceManager) -> None:
    with pytest.raises(WorkspaceError):
        manager.workspace_path("bad/id")
