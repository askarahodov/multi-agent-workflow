"""Release Preparation agent.

Assembles a release candidate: bumps/selects a version, generates release notes
from the changelog, builds a verifiable artifact (tar.gz + SHA-256), and stores
it in a ``release_candidates`` row with status ``awaiting_approval``.

Crucially the agent **stops at the human gate**: it can create a candidate and
place it in ``awaiting_approval``, but only an explicit, separately-authenticated
human approval (``approve_candidate``) can move it to ``approved``. The agent
itself can never approve its own output, and a candidate can only be released
after approval -- this is the enforced human checkpoint.
"""

from __future__ import annotations

import io
import json
import re
import tarfile
import time
from pathlib import Path
from typing import Any

from .base import Finding, Gate, GateResult, GATE_REGISTRY
from .walk import iter_files
from ..evidence import checksum_file

CHANGELOG_NAME = "CHANGELOG.md"


def _read_changelog_entries(root: Path) -> list[str]:
    changelog = root / CHANGELOG_NAME
    if not changelog.exists():
        return []
    text = changelog.read_text(encoding="utf-8", errors="replace")
    # naive section split on "## vX.Y.Z" style headers
    entries = re.split(r"^##\s+", text, flags=re.MULTILINE)
    return [e.strip() for e in entries if e.strip()]


class ReleasePrepAgent:
    """Coordinates release-candidate assembly against the persistence layer.

    The pure gate logic (what to put in the candidate) lives in
    :class:`ReleasePrepGate`; this service owns artifact building and the DB
    transitions (create / approve / reject) so it can be wired to the API.
    """

    def __init__(self, artifact_root: Path, evidence_store=None) -> None:
        self.artifact_root = Path(artifact_root)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.evidence_store = evidence_store

    def assemble(
        self,
        workspace: str,
        version: str,
        *,
        task_id: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a release artifact + notes and return a candidate dict (no DB yet)."""
        workspace_path = Path(workspace)
        notes = self._generate_notes(workspace_path, version)
        artifact_path = self._build_artifact(workspace_path, version)
        checksum = checksum_file(artifact_path)
        return {
            "task_id": task_id,
            "version": version,
            "status": "awaiting_approval",
            "release_notes": notes,
            "artifact_path": str(artifact_path),
            "artifact_checksum": checksum,
            "extra": extra or {},
        }

    def _generate_notes(self, workspace: Path, version: str) -> str:
        entries = _read_changelog_entries(workspace)
        if entries:
            body = "\n\n".join(f"## {e}" for e in entries[:5])
        else:
            body = f"Release candidate {version} prepared; no changelog entries found."
        return f"# Release {version}\n\n{body}"

    def _build_artifact(self, workspace: Path, version: str) -> Path:
        out = self.artifact_root / f"release-{version}.tar.gz"
        with tarfile.open(out, "w:gz") as tf:
            # Only include tracked-ish source: skip VCS and caches.
            for path in iter_files(workspace):
                if path.is_file():
                    tf.add(path, arcname=str(path.relative_to(workspace)))
        return out

    # --- lifecycle transitions (the human gate lives here) ---------------------
    def validate_approval(self, candidate: dict[str, Any], approver: str) -> dict[str, Any]:
        """Enforce the human gate: only an approved-by-human candidate proceeds."""
        if candidate.get("status") != "awaiting_approval":
            from ..errors import ReleaseNotAwaitingApprovalError

            raise ReleaseNotAwaitingApprovalError(
                f"candidate {candidate.get('id')} status is "
                f"{candidate.get('status')}, expected awaiting_approval"
            )
        if not approver:
            from ..errors import QualityGateError

            raise QualityGateError("approval requires a human approver identity")
        if approver.lower() == "release_prep":
            from ..errors import QualityGateError

            raise QualityGateError("the release prep agent cannot approve its own candidate")
        return candidate


class ReleasePrepGate:
    """Gate-shaped view of release prep for pipeline consistency.

    Running this gate as part of the pipeline ensures that a workspace can
    produce a verifiable release candidate; the gate *passes* only if the
    artifact builds and its checksum verifies.
    """

    name = "release_prep"
    description = "Assembles release candidates and generates release notes (human gate for approval)."

    def __init__(
        self,
        agent: ReleasePrepAgent | None = None,
        release_agent: ReleasePrepAgent | None = None,
    ) -> None:
        # ``release_agent`` is accepted as an alias so the pipeline can construct
        # every gate uniformly as ``gate_cls(release_agent=shared_agent)``.
        self.agent = agent or release_agent

    def execute(self, workspace: str, context: dict[str, Any] | None = None) -> GateResult:
        ctx = context or {}
        started = time.perf_counter()
        version = ctx.get("version") or "0.1.0-rc"
        agent = self.agent or ReleasePrepAgent(Path(ctx.get("artifact_root") or "release_artifacts"))
        try:
            candidate = agent.assemble(workspace, version, task_id=ctx.get("task_id") or "task")
            # verify the artifact checksum
            artifact = Path(candidate["artifact_path"])
            valid = artifact.exists() and checksum_file(artifact) == candidate["artifact_checksum"]
        except Exception as exc:  # noqa: BLE001
            return GateResult(
                gate=self.name,
                passed=False,
                summary=f"release candidate assembly failed: {exc}",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
        finding = Finding(
            category="release",
            key=f"candidate:{version}",
            passed=valid,
            summary=f"release candidate {version} artifact {'verifies' if valid else 'FAILED checksum'}",
            detail={
                "artifact_path": candidate["artifact_path"],
                "artifact_checksum": candidate["artifact_checksum"],
                "verifies": valid,
                "release_notes_excerpt": candidate["release_notes"][:500],
            },
        )
        duration_ms = (time.perf_counter() - started) * 1000
        return GateResult(
            gate=self.name,
            passed=valid,
            summary=f"release candidate {version} ready and verifiable" if valid else "release artifact invalid",
            findings=[finding],
            duration_ms=duration_ms,
        )


GATE_REGISTRY.register(ReleasePrepGate)
