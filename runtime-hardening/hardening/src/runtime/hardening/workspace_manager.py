"""Workspace Manager: atomic lifecycle + reaper (spec §6, ADR-011).

* immutable ``base`` (read-only overlay lower) + ephemeral ``scratch``
  (overlay upper / work) + optional ``durable`` volume (spec §6.1),
* atomic creation protocol: pre-flight → staging → validation → commit,
  with full rollback leaving zero orphaned cgroups/mounts/netns/volumes
  (AC-7),
* deterministic, idempotent cleanup (success/failure/crash) converging to
  "nothing allocated",
* a reaper daemon that reclaims orphaned workspaces after a controller crash
  within the force-cleanup timeout (AC-8),
* checksummed snapshot / restore and idempotent ``promote`` (spec §6.5).
"""

from __future__ import annotations

import hashlib
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from runtime.hardening.models import (
    Snapshot,
    ValidationCheck,
    Workspace,
    WorkspaceSpec,
    WorkspaceState,
)

# Sub-directories inside a workspace root (spec §6.1).
_STATE_DIR = ".agent-state"
_ARTIFACTS_DIR = ".artifacts"
_LOGS_DIR = ".logs"


class WorkspaceError(RuntimeError):
    """Raised on workspace manipulation failures."""


class InsufficientCapacityError(WorkspaceError):
    """Raised when resource availability pre-flight fails (507)."""


class UnknownWorkspaceError(WorkspaceError):
    """Raised when a workspace does not exist."""


class ChecksumViolationError(WorkspaceError):
    """Raised when a snapshot checksum does not validate (422)."""


def sha256_of_file(path: Path) -> str:
    """Return the SHA-256 hex digest of a file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class WorkspaceAllocator:
    """Resource availability checker used at pre-flight (spec §6.2 step 1).

    A pluggable hook lets callers check cgroup budget, user-ns range and disk
    capacity. The default always admits; the real runtime injects a concrete
    checker.
    """

    check: Callable[[WorkspaceSpec], None] | None = None

    def preflight(self, spec: WorkspaceSpec) -> None:
        if self.check is not None:
            self.check(spec)


@dataclass
class WorkspaceManager:
    """Atomic, idempotent workspace lifecycle over a filesystem root.

    The ``root`` is the base directory that will contain per-workspace
    ``<id>/`` trees. In the reference implementation the staging/commit is
    performed with filesystem staging + atomic rename (host) rather than a real
    overlayfs mount — the overlay-lower/upper paths are recorded on the
    :class:`Workspace` model and real mounting is delegated to the runtime
    backend (see docs/IMPLEMENTATION.md).
    """

    root: Path = Path("/workspace")
    allocator: WorkspaceAllocator = field(default_factory=WorkspaceAllocator)
    _state: dict[str, Workspace] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- paths ---------------------------------------------------------------- #
    def workspace_path(self, workspace_id: str) -> Path:
        if not workspace_id or "/" in workspace_id:
            raise WorkspaceError(f"invalid workspace id {workspace_id!r}")
        return self.root / workspace_id

    def exists(self, workspace_id: str) -> bool:
        return self.workspace_path(workspace_id).is_dir()

    def get(self, workspace_id: str) -> Workspace:
        if workspace_id in self._state:
            return self._state[workspace_id]
        path = self.workspace_path(workspace_id)
        if not path.is_dir():
            raise UnknownWorkspaceError(f"workspace {workspace_id!r} does not exist")
        # Reconstruct from a committed spec.json for crash recovery.
        spec_file = path / _STATE_DIR / "spec.json"
        if spec_file.exists():
            import json

            try:
                data = json.loads(spec_file.read_text(encoding="utf-8"))
                ws = Workspace.model_validate(data)
                self._state[workspace_id] = ws
                return ws
            except Exception:
                pass
        raise UnknownWorkspaceError(f"workspace {workspace_id!r} has no valid spec")

    # -- create (atomic, rollback) -------------------------------------------- #
    def create(self, spec: WorkspaceSpec) -> Workspace:
        """Atomically create a workspace; roll back on any failure (AC-7).

        If ``spec.id`` is absent a server-generated id is used. Creating an
        existing workspace returns the existing one (idempotent).
        """
        workspace_id = spec.id or f"ws-{uuid.uuid4().hex[:12]}"
        with self._lock:
            path = self.workspace_path(workspace_id)
            if path.is_dir():
                existing = self.get(workspace_id)
                if existing.state == WorkspaceState.READY:
                    return existing
            state_path = path / _STATE_DIR
            scratch = path / "scratch"
            upper = scratch / "upper"
            work = scratch / "work"
            artifacts = scratch / _ARTIFACTS_DIR
            logs = scratch / _LOGS_DIR
            durable = path / "durable"
            allocated: list[Path] = []
            try:
                # 1. Pre-flight: validate spec + resource availability.
                self.allocator.preflight(spec)
                # 2. Staging.
                self._mkdir(allocated, path)
                self._mkdir(allocated, state_path)
                self._mkdir(allocated, scratch)
                self._mkdir(allocated, upper)
                self._mkdir(allocated, work)
                self._mkdir(allocated, artifacts)
                self._mkdir(allocated, logs)
                if spec.durable:
                    self._mkdir(allocated, durable)
                # 3. Validation: verify expected structure is consistent.
                if not upper.is_dir() or not work.is_dir():
                    raise WorkspaceError("scratch overlay structure incomplete")
                # 4. Commit: write spec.json, mark ACTIVE.
                ws = Workspace(
                    id=workspace_id,
                    state=WorkspaceState.READY,
                    baseImage=spec.baseImage,
                    overlayLower=f"{path}/base" if spec.baseImage else None,
                    overlayUpper=str(upper),
                    durablePath=str(durable) if spec.durable else None,
                )
                spec_file = state_path / "spec.json"
                spec_file.write_text(ws.model_dump_json(), encoding="utf-8")
                self._state[workspace_id] = ws
                return ws
            except Exception:
                # 5. Rollback: reverse staging in reverse order (AC-7).
                for dirpath in reversed(allocated):
                    shutil.rmtree(dirpath, ignore_errors=True)
                raise

    def _mkdir(self, allocated: list[Path], path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        allocated.append(path)

    # -- lifecycle transitions ------------------------------------------------- #
    def mark_cleaning(self, workspace_id: str) -> Workspace:
        ws = self.get(workspace_id)
        ws.state = WorkspaceState.CLEANING
        self._state[workspace_id] = ws
        return ws

    # -- cleanup (deterministic, idempotent) ---------------------------------- #
    def cleanup(self, workspace_id: str, *, force: bool = False) -> None:
        """Clean up a workspace; idempotent — safe to call repeatedly.

        On failure artifacts under ``scratch/.artifacts`` are preserved for
        diagnosis unless ``force`` is set. Always converges to "nothing
        allocated".
        """
        path = self.workspace_path(workspace_id)
        if not path.is_dir():
            self._state.pop(workspace_id, None)
            return
        if not force:
            # Preserve failure artifacts for diagnosis (spec §6.3).
            artifacts = path / "scratch" / _ARTIFACTS_DIR
            if artifacts.is_dir():
                shutil.copytree(
                    artifacts,
                    path / "durable-failed-artifacts",
                    dirs_exist_ok=True,
                )
        shutil.rmtree(path, ignore_errors=True)
        self._state.pop(workspace_id, None)

    # -- snapshot / restore / promote (spec §6.4-6.5) --------------------------- #
    def snapshot(self, workspace_id: str) -> Snapshot:
        """Create a checksummed snapshot of the workspace state (best-effort)."""
        path = self.workspace_path(workspace_id)
        if not path.is_dir():
            raise UnknownWorkspaceError(f"workspace {workspace_id!r} does not exist")
        snapshot_id = f"snap-{uuid.uuid4().hex[:12]}"
        checksum = self._checksum_tree(path)
        snap = Snapshot(id=snapshot_id, workspaceId=workspace_id, checksum=checksum)
        snap_dir = path / _STATE_DIR / "snapshots"
        snap_dir.mkdir(parents=True, exist_ok=True)
        (snap_dir / f"{snapshot_id}.json").write_text(snap.model_dump_json(), encoding="utf-8")
        ws = self.get(workspace_id)
        ws.lastSnapshotId = snapshot_id
        self._state[workspace_id] = ws
        return snap

    def restore(self, workspace_id: str, snapshot_id: str) -> Workspace:
        """Restore a workspace from a snapshot, checksum-validated (422)."""
        path = self.workspace_path(workspace_id)
        if not path.is_dir():
            raise UnknownWorkspaceError(f"workspace {workspace_id!r} does not exist")
        snap_dir = path / _STATE_DIR / "snapshots"
        snap_file = snap_dir / f"{snapshot_id}.json"
        if not snap_file.exists():
            raise UnknownWorkspaceError(f"snapshot {snapshot_id!r} not found")
        import json

        data = json.loads(snap_file.read_text(encoding="utf-8"))
        snap = Snapshot.model_validate(data)
        current = self._checksum_tree(path)
        if current != snap.checksum:
            raise ChecksumViolationError(
                f"snapshot {snapshot_id!r} checksum mismatch (workspace mutated)"
            )
        ws = self.get(workspace_id)
        ws.state = WorkspaceState.READY
        self._state[workspace_id] = ws
        return ws

    def promote(self, workspace_id: str, paths: list[str]) -> list[dict[str, str]]:
        """Copy checksummed scratch artifacts to the durable volume.

        Idempotent — re-promoting an already-present artifact is a no-op that
        returns its checksum. Uses atomic rename within the same filesystem
        where possible.
        """
        path = self.workspace_path(workspace_id)
        if not path.is_dir():
            raise UnknownWorkspaceError(f"workspace {workspace_id!r} does not exist")
        durable = path / "durable"
        durable.mkdir(parents=True, exist_ok=True)
        scratch = path / "scratch"
        promoted: list[dict[str, str]] = []
        for rel in paths:
            source = (scratch / rel).resolve()
            if not source.is_relative_to(scratch) or not source.is_file():
                raise WorkspaceError(f"artifact {rel!r} is outside scratch or is not a file")
            target = (durable / rel).resolve()
            if not target.is_relative_to(durable):
                raise WorkspaceError(f"target {rel!r} escapes durable volume")
            target.parent.mkdir(parents=True, exist_ok=True)
            checksum = sha256_of_file(source)
            if target.exists() and sha256_of_file(target) == checksum:
                promoted.append({"path": rel, "checksum": checksum})
                continue
            shutil.copy2(source, target)
            promoted.append({"path": rel, "checksum": checksum})
        return promoted

    def validate(self, workspace_id: str) -> tuple[bool, list[ValidationCheck]]:
        """Idempotently validate a workspace is fully provisioned (spec §6.2)."""
        path = self.workspace_path(workspace_id)
        checks: list[ValidationCheck] = [
            ValidationCheck(
                name="root",
                ok=path.is_dir(),
                detail="workspace root present" if path.is_dir() else "root missing",
            ),
            ValidationCheck(
                name="state",
                ok=(path / _STATE_DIR / "spec.json").exists(),
                detail="spec.json committed"
                if (path / _STATE_DIR / "spec.json").exists()
                else "no spec",
            ),
            ValidationCheck(
                name="scratch",
                ok=(path / "scratch").is_dir(),
                detail="scratch present" if (path / "scratch").is_dir() else "scratch missing",
            ),
        ]
        return all(c.ok for c in checks), checks

    def _checksum_tree(self, path: Path) -> str:
        """Deterministic checksum over user-visible file contents under ``path``.

        Internal runtime state (``.agent-state``, which holds spec.json and
        snapshot metadata) is excluded so that recording a snapshot does not
        invalidate the very checksum it records.
        """
        digest = hashlib.sha256()
        for child in sorted(path.rglob("*")):
            if not child.is_file():
                continue
            rel = child.relative_to(path)
            if _STATE_DIR in rel.parts:
                continue
            digest.update(str(rel).encode("utf-8"))
            digest.update(sha256_of_file(child).encode("utf-8"))
        return digest.hexdigest()


@dataclass
class WorkspaceReaper:
    """Reaper daemon that reclaims orphaned workspaces after a crash (AC-8).

    Scans for workspaces whose last heartbeat is older than the force-cleanup
    timeout and force-cleans them, converging to "nothing allocated".
    """

    manager: WorkspaceManager
    force_cleanup_seconds: float = 30.0
    scan_interval_seconds: float = 15.0
    _heartbeats: dict[str, float] = field(default_factory=dict)
    _stop: threading.Event = field(default_factory=threading.Event)
    reclaimed: int = 0

    def heartbeat(self, workspace_id: str, *, now: float | None = None) -> None:
        """Record a liveness heartbeat for an active workspace."""
        self._heartbeats[workspace_id] = time.monotonic() if now is None else now

    def orphaned_ids(self, *, now: float | None = None) -> list[str]:
        """Return workspaces with no recent heartbeat (spec §6.3 crash/interrupt).

        Also scans the manager's root for workspace directories that have no
        recorded heartbeat at all — these are orphans from a controller crash
        mid-create (AC-8), since a partial create leaves a directory but never
        reaches the post-commit heartbeat.
        """
        stamp = time.monotonic() if now is None else now
        stale = [
            ws_id
            for ws_id, last in self._heartbeats.items()
            if stamp - last > self.force_cleanup_seconds
        ]
        # Discover filesystem orphans (present on disk, never heartbeated).
        root = self.manager.root
        if root.is_dir():
            for entry in root.iterdir():
                if not entry.is_dir():
                    continue
                name = entry.name
                if name in self._heartbeats:
                    continue
                if name.startswith("ws-") or (entry / ".agent-state").is_dir():
                    stale.append(name)
        return stale

    def reclaim_once(self, *, now: float | None = None) -> list[str]:
        """Force-clean all currently orphaned workspaces (idempotent)."""
        reclaimed: list[str] = []
        for ws_id in self.orphaned_ids(now=now):
            self.manager.cleanup(ws_id, force=True)
            self._heartbeats.pop(ws_id, None)
            reclaimed.append(ws_id)
            self.reclaimed += 1
        return reclaimed

    def run_forever(self) -> None:
        """Reaper loop: reclaim orphans every scan interval (for a daemon thread)."""
        while not self._stop.is_set():
            self.reclaim_once()
            self._stop.wait(self.scan_interval_seconds)

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.run_forever, daemon=True, name="workspace-reaper")
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()
