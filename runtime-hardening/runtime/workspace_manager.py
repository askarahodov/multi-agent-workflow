"""Workspace lifecycle management (ADR-004).

Immutable base + ephemeral scratch + atomic lifecycle + reaper cleanup. All
operations are idempotent and converge to a consistent state, so they are safe
to re-run after a crash or partial allocation.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from runtime.models import Snapshot, ValidationCheck, Workspace, WorkspaceSpec, WorkspaceState


class WorkspaceError(RuntimeError):
    """Base error for workspace operations."""


class WorkspaceNotFound(WorkspaceError):
    """Raised when a workspace id does not exist."""


class ChecksumMismatch(WorkspaceError):
    """Raised when a snapshot fails checksum validation."""


META_FILE = "meta.json"
SCRATCH_SUBDIRS = (".work", ".agent-state", ".artifacts", ".logs")


def tree_checksum(root: Path, algorithm: str = "sha256") -> str:
    """Return a deterministic checksum over every file under ``root``.

    Files are visited in sorted relative-path order; both the path and the
    contents are folded into the digest so renames are detected.
    """
    digest = hashlib.new(algorithm)
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def file_checksum(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class WorkspaceManager:
    """Provision, snapshot, promote and reap agent workspaces."""

    root: Path = Path("/var/lib/agent-runtime/workspaces")
    durable_root: Path = Path("/var/lib/agent-runtime/durable")
    snapshots_root: Path = Path("/var/lib/agent-runtime/snapshots")
    grace_seconds: int = 30
    checksum_algorithm: str = "sha256"
    mount_overlay: bool = False
    _sleep: Callable[[float], None] = field(default=time.sleep)
    _states: dict[str, WorkspaceState] = field(default_factory=dict)

    # -- paths ---------------------------------------------------------------- #
    def workspace_path(self, ws_id: str) -> Path:
        if not ws_id or "/" in ws_id:
            raise WorkspaceError(f"invalid workspace id {ws_id!r}")
        return self.root / ws_id

    def scratch_path(self, ws_id: str) -> Path:
        return self.workspace_path(ws_id) / "scratch"

    def durable_path(self, ws_id: str) -> Path:
        return self.workspace_path(ws_id) / "durable"

    # -- lifecycle ------------------------------------------------------------ #
    def create(self, spec: WorkspaceSpec, ws_id: str | None = None) -> Workspace:
        """Atomically create a workspace, rolling back on any failure.

        Idempotent: a second call for an existing, valid workspace returns it.
        """
        wid = ws_id or spec.id or f"ws-{uuid.uuid4().hex[:12]}"
        final = self.workspace_path(wid)
        if final.exists():
            existing = self._load_meta(wid)
            if existing is not None and existing.state == WorkspaceState.READY:
                return existing
            # Partial/legacy state → recreate from base.
            self._force_remove(final)

        self.root.mkdir(parents=True, exist_ok=True)
        staging = self.root / f".staging-{wid}-{uuid.uuid4().hex[:8]}"
        try:
            self._stage(staging, wid, spec)
            self._validate_staging(staging)
            os.replace(staging, final)  # atomic commit
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            self._force_remove(final)
            raise
        self._states[wid] = WorkspaceState.READY
        return self._load_meta(wid) or self._synthesize(wid, spec, WorkspaceState.READY)

    def _stage(self, staging: Path, wid: str, spec: WorkspaceSpec) -> None:
        scratch = staging / "scratch"
        scratch.mkdir(parents=True)
        for sub in SCRATCH_SUBDIRS:
            (scratch / sub).mkdir()
        (staging / "base").mkdir()
        (staging / "base" / ".base-image").write_text(spec.baseImage or "scratch", encoding="utf-8")
        if spec.durable:
            (staging / "durable").mkdir()
        self._write_meta(
            staging,
            Workspace(
                id=wid,
                state=WorkspaceState.CREATING,
                baseImage=spec.baseImage,
                overlayLower=str(staging / "base"),
                overlayUpper=str(scratch),
                durablePath=str(staging / "durable") if spec.durable else None,
            ),
        )

    def _validate_staging(self, staging: Path) -> None:
        scratch = staging / "scratch"
        missing = [sub for sub in SCRATCH_SUBDIRS if not (scratch / sub).is_dir()]
        if missing:
            raise WorkspaceError(f"staging incomplete, missing {missing}")
        if not (staging / META_FILE).is_file():
            raise WorkspaceError("staging incomplete, missing meta.json")

    def _synthesize(self, wid: str, spec: WorkspaceSpec, state: WorkspaceState) -> Workspace:
        return Workspace(
            id=wid,
            state=state,
            baseImage=spec.baseImage,
            overlayLower=str(self.workspace_path(wid) / "base"),
            overlayUpper=str(self.scratch_path(wid)),
        )

    def get(self, ws_id: str) -> Workspace:
        ws = self._load_meta(ws_id)
        if ws is None:
            raise WorkspaceNotFound(ws_id)
        return ws

    def list_all(self) -> list[Workspace]:
        if not self.root.exists():
            return []
        out: list[Workspace] = []
        for entry in sorted(self.root.iterdir()):
            if entry.is_dir() and not entry.name.startswith(".staging-"):
                ws = self._load_meta(entry.name)
                if ws is not None:
                    out.append(ws)
        return out

    def validate(self, ws_id: str) -> list[ValidationCheck]:
        """Idempotent consistency check of the on-disk workspace."""
        path = self.workspace_path(ws_id)
        checks: list[ValidationCheck] = []
        checks.append(ValidationCheck(name="exists", ok=path.is_dir()))
        scratch = path / "scratch"
        for sub in SCRATCH_SUBDIRS:
            checks.append(ValidationCheck(name=f"scratch/{sub}", ok=(scratch / sub).is_dir()))
        checks.append(ValidationCheck(name="meta", ok=(path / META_FILE).is_file()))
        return checks

    # -- snapshot / restore --------------------------------------------------- #
    def snapshot(self, ws_id: str) -> Snapshot:
        """Best-effort snapshot of the scratch overlay with a checksum."""
        ws = self.get(ws_id)
        if ws.state not in (WorkspaceState.READY, WorkspaceState.DEGRADED):
            raise WorkspaceError(f"cannot snapshot workspace in state {ws.state}")
        self.snapshots_root.mkdir(parents=True, exist_ok=True)
        snap_id = f"snap-{ws_id}-{uuid.uuid4().hex[:10]}"
        archive = self.snapshots_root / f"{snap_id}.tar"
        with tarfile.open(archive, "w") as tar:
            tar.add(self.scratch_path(ws_id), arcname="scratch")
        checksum = file_checksum(archive, self.checksum_algorithm)
        snap = Snapshot(
            id=snap_id,
            workspaceId=ws_id,
            checksum=checksum,
            sizeBytes=archive.stat().st_size,
        )
        ws.lastSnapshotId = snap_id
        self._write_meta(self.workspace_path(ws_id), ws)
        return snap

    def restore(self, ws_id: str, snapshot_id: str) -> Workspace:
        """Restore scratch from a snapshot after checksum validation.

        On any failure the workspace is recreated fresh from base (ADR-004).
        """
        ws = self.get(ws_id)
        archive = self.snapshots_root / f"{snapshot_id}.tar"
        if not archive.is_file():
            raise WorkspaceNotFound(snapshot_id)
        expected = file_checksum(archive, self.checksum_algorithm)
        if self._snapshot_checksum(snapshot_id) not in (None, expected):
            raise ChecksumMismatch(f"checksum mismatch for {snapshot_id}")

        self._states[ws_id] = WorkspaceState.RESTORING
        try:
            scratch = self.scratch_path(ws_id)
            if scratch.exists():
                shutil.rmtree(scratch)
            with tarfile.open(archive, "r") as tar:
                tar.extractall(self.workspace_path(ws_id), filter="data")  # noqa: S202
            if not (scratch / ".agent-state").is_dir():
                raise WorkspaceError("restored snapshot missing scratch layout")
        except Exception:
            self.create(WorkspaceSpec(id=ws_id, baseImage=ws.baseImage), ws_id)
            raise
        ws.state = WorkspaceState.READY
        self._write_meta(self.workspace_path(ws_id), ws)
        self._states[ws_id] = WorkspaceState.READY
        return ws

    def _snapshot_checksum(self, snapshot_id: str) -> str | None:
        marker = self.snapshots_root / f"{snapshot_id}.checksum"
        if marker.is_file():
            return marker.read_text(encoding="utf-8").strip()
        return None

    # -- promote -------------------------------------------------------------- #
    def promote(self, ws_id: str, paths: list[str]) -> list[dict[str, str]]:
        """Copy scratch artifacts into the durable volume with checksums."""
        ws = self.get(ws_id)
        if ws.durablePath is None:
            raise WorkspaceError(f"workspace {ws_id} has no durable volume")
        durable = Path(ws.durablePath)
        durable.mkdir(parents=True, exist_ok=True)
        promoted: list[dict[str, str]] = []
        for rel in paths:
            src = self.scratch_path(ws_id) / rel
            if not src.is_file():
                raise WorkspaceError(f"artifact not found: {rel}")
            dst = durable / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".tmp")
            shutil.copy2(src, tmp)
            os.replace(tmp, dst)  # atomic rename
            promoted.append({"path": rel, "checksum": file_checksum(dst, self.checksum_algorithm)})
        return promoted

    # -- cleanup -------------------------------------------------------------- #
    def cleanup(self, ws_id: str, grace_seconds: int | None = None, *, force: bool = False) -> None:
        """Remove a workspace. Idempotent (safe to call repeatedly)."""
        path = self.workspace_path(ws_id)
        if not path.exists():
            self._states.pop(ws_id, None)
            return
        grace = self.grace_seconds if grace_seconds is None else grace_seconds
        self._states[ws_id] = WorkspaceState.CLEANING
        if not force and grace > 0:
            self._sleep(grace)
        self._force_remove(path)
        self._states[ws_id] = WorkspaceState.GONE

    @staticmethod
    def _force_remove(path: Path) -> None:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    # -- recovery / reaper ---------------------------------------------------- #
    def recover(self, ws_id: str, spec: WorkspaceSpec | None = None) -> Workspace:
        """Converge a workspace to a usable state after a crash.

        A workspace stuck in ``creating``/``restoring`` is recreated from base.
        """
        ws = self._load_meta(ws_id)
        if ws is not None and ws.state in (WorkspaceState.READY, WorkspaceState.DEGRADED):
            return ws
        return self.create(
            spec or WorkspaceSpec(id=ws_id, baseImage=ws.baseImage if ws else None), ws_id
        )

    def reap_orphans(self) -> list[str]:
        """Remove leftover staging directories from crashed creations."""
        reaped: list[str] = []
        if not self.root.exists():
            return reaped
        for entry in self.root.iterdir():
            if entry.is_dir() and entry.name.startswith(".staging-"):
                shutil.rmtree(entry, ignore_errors=True)
                reaped.append(entry.name)
        return reaped

    # -- meta helpers --------------------------------------------------------- #
    def _write_meta(self, workspace_dir: Path, ws: Workspace) -> None:
        workspace_dir.mkdir(parents=True, exist_ok=True)
        (workspace_dir / META_FILE).write_text(ws.model_dump_json(indent=2), encoding="utf-8")

    def _load_meta(self, ws_id: str) -> Workspace | None:
        meta = self.workspace_path(ws_id) / META_FILE
        if not meta.is_file():
            return None
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return Workspace.model_validate(data)
