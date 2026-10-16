"""Pipeline orchestrator: runs the gate set for a task, persists evidence, and
enforces the transition gate.

Acceptance-criterion mapping:

* "gates are enforced"          -> :meth:`GatePipeline.transition` refuses any
   advance unless every required gate has a passing run recorded for the task.
* "evidence is stored/auditable"-> every run persists immutable, checksummed
   evidence via :class:`EvidenceStore` and records rows in ``gate_runs`` /
   ``evidence_items``.
* "release prep ... awaiting human approval" -> handled by the release agent
   and the ``release_prep`` gate; the pipeline only advances a task whose
   release gate produced a verifiable candidate.
"""

from __future__ import annotations

import time
import hashlib
import json
import re
import subprocess
from pathlib import Path
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .config import Settings
from .errors import (
    GateFailedError,
    GateNotFoundError,
    TaskNotFoundError,
    TransitionForbiddenError,
)
from .evidence import EvidenceStore
from .gates.base import GateResult, GATE_REGISTRY
from .models import EvidenceItem, GateRun, ReleaseCandidate
from .gates.release_prep import ReleasePrepAgent


class GatePipeline:
    """Runs gates, persists evidence, and enforces transition gates per task."""

    def __init__(
        self,
        sf: async_sessionmaker[AsyncSession],
        settings: Settings | None = None,
    ) -> None:
        self.sf = sf
        self.settings = settings or Settings()
        self.settings.ensure_dirs()
        self.evidence_store = EvidenceStore(self.settings.evidence_root)
        self.release_agent = ReleasePrepAgent(
            self.settings.artifact_root, evidence_store=self.evidence_store
        )

    # --- gate execution ---------------------------------------------------------
    async def run_gate(
        self,
        task_id: str,
        workspace: str,
        gate_name: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a single gate, persist its run + evidence, and return the run row.

        Raises :class:`GateNotFoundError` for unknown gates. A failing gate does
        *not* raise -- it persists a ``failed`` run and returns it, so callers can
        aggregate across gates; :meth:`transition` uses those runs to enforce the
        block.
        """
        if gate_name not in GATE_REGISTRY.names():
            raise GateNotFoundError(f"unknown gate: {gate_name}")

        # Only a trusted operator may supply qa_subject via the ADMIN-only API.
        # The Git checkout must be exactly the claimed commit and clean both
        # before and after running the gate, otherwise the report is unbound.
        subject = (context or {}).get("qa_subject")
        if subject is not None:
            if (
                not isinstance(subject, dict)
                or set(subject) != {"attempt_id", "commit_sha"}
                or not isinstance(subject["attempt_id"], str)
                or not re.fullmatch(r"[0-9a-f-]{36}", subject["attempt_id"])
                or not isinstance(subject["commit_sha"], str)
                or not re.fullmatch(r"[0-9a-f]{40}", subject["commit_sha"])
            ):
                raise GateFailedError("Invalid trusted Git QA subject")
            self._assert_clean_git(workspace, subject["commit_sha"])

        gate_cls = GATE_REGISTRY.get(gate_name)
        # release_prep needs the shared agent to place candidates; others are stateless.
        gate = gate_cls(release_agent=self.release_agent) if gate_name == "release_prep" else gate_cls()

        run_id = None
        result: GateResult | None = None
        try:
            async with self.sf() as session:
                run = GateRun(task_id=task_id, gate_name=gate_name, status="running")
                session.add(run)
                await session.flush()
                run_id = run.id
                # Flush before long-running checks so the run is visible/auditable.
                await session.commit()

            result = gate.execute(workspace, context)
            if subject is not None:
                self._assert_clean_git(workspace, subject["commit_sha"])

            async with self.sf() as session:
                run = await session.get(GateRun, run_id)
                run.status = "passed" if result.passed else "failed"
                run.summary = result.summary
                run.duration_ms = result.duration_ms
                run.finished_at = _utcnow()
                # A zero-finding "passed" runner must not qualify as QA proof.
                if subject is not None and (not result.findings or not all(f.passed for f in result.findings)):
                    run.status = "failed"
                if subject is not None:
                    meta = self.evidence_store.store(task_id, run_id, "subject", "git-identity", subject)
                    session.add(EvidenceItem(
                        run_id=run_id, category="subject", key="git-identity",
                        value=subject, checksum=meta["checksum"],
                    ))
                # Persist each finding as immutable evidence.
                for f in result.findings:
                    meta = self.evidence_store.store(
                        task_id, run_id, f.category, f.key, f.as_evidence()
                    )
                    session.add(
                        EvidenceItem(
                            run_id=run_id,
                            category=f.category,
                            key=f.key,
                            value=f.as_evidence(),
                            checksum=meta["checksum"],
                        )
                    )
                run.report_path = self._report_relative(run_id)
                await session.commit()
        except Exception as exc:  # pragma: no cover - defensive
            raise GateFailedError(f"gate {gate_name} could not be completed: {exc}") from exc

        return await self.get_run(task_id, run_id)

    @staticmethod
    def _assert_clean_git(workspace: str, sha: str) -> None:
        """Avoid self-declared SHA for arbitrary mutable workspace content."""
        try:
            head = subprocess.run(
                ["git", "-C", workspace, "rev-parse", "--verify", "HEAD"],
                capture_output=True, text=True, timeout=10, check=True,
            ).stdout.strip()
            dirty = subprocess.run(
                ["git", "-C", workspace, "status", "--porcelain", "--untracked-files=all"],
                capture_output=True, text=True, timeout=10, check=True,
            ).stdout
        except (OSError, subprocess.SubprocessError) as exc:
            raise GateFailedError("QA requires a real readable Git checkout") from exc
        if head != sha or dirty:
            raise GateFailedError("QA checkout must be clean and match subject Git SHA")

    async def qa_proof(self, task_id: str, attempt_id: str, commit_sha: str) -> dict:
        """Re-check disk evidence; newest matching test/review/security must pass."""
        if (
            not re.fullmatch(r"[0-9a-f-]{36}", attempt_id)
            or not re.fullmatch(r"[0-9a-f]{40}", commit_sha)
        ):
            raise GateFailedError("Invalid QA proof subject")
        selected = {}
        async with self.sf() as session:
            runs = list((await session.scalars(
                select(GateRun).where(
                    GateRun.task_id == task_id,
                    GateRun.gate_name.in_(("tester", "reviewer", "security")),
                ).order_by(GateRun.started_at.desc(), GateRun.id.desc()).limit(150)
            )).all())
            for run in runs:
                items = list((await session.scalars(
                    select(EvidenceItem).where(EvidenceItem.run_id == run.id)
                )).all())
                subject = next((e for e in items if e.category == "subject" and e.key == "git-identity"), None)
                if subject is None or subject.value != {"attempt_id": attempt_id, "commit_sha": commit_sha}:
                    continue
                if run.gate_name in selected:
                    continue
                if run.status != "passed" or len(items) < 2:
                    raise GateFailedError("Latest matching QA gate is not a verified pass")
                checksums = []
                for item in items:
                    relative = f"{task_id}/{run.id}/{item.category}_{self._safe_key(item.key)}.json"
                    doc = self.evidence_store.read(relative)
                    if (
                        doc is None or doc.get("_checksum") != item.checksum
                        or {k: v for k, v in doc.items() if k != "_checksum"} != item.value
                    ):
                        raise GateFailedError("QA evidence checksum mismatch or missing document")
                    if item.category != "subject" and item.value.get("passed") is not True:
                        raise GateFailedError("QA evidence contains a failing finding")
                    checksums.append(item.checksum)
                selected[run.gate_name] = {"run_id": run.id, "evidence": sorted(checksums)}
        if set(selected) != {"tester", "reviewer", "security"}:
            raise GateFailedError("Missing independently executed QA gate runs")
        manifest = {
            "task_id": task_id, "attempt_id": attempt_id,
            "commit_sha": commit_sha, "runs": selected,
        }
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return {
            "passed": True, "task_id": task_id, "attempt_id": attempt_id,
            "commit_sha": commit_sha, "evidence_sha256": digest,
            "evidence_ref": f"qg://{task_id}/{attempt_id}/{digest}",
        }

    @staticmethod
    def _safe_key(key: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", key).strip("_") or "evidence"

    def _report_relative(self, run_id: str) -> str:
        return f"{run_id}/report.json"

    # --- queries ------------------------------------------------------------------
    async def get_run(self, task_id: str, run_id: str) -> dict[str, Any]:
        async with self.sf() as session:
            run = await session.get(GateRun, run_id)
            if run is None:
                raise GateFailedError("run not found")
            items = (
                await session.execute(
                    select(EvidenceItem).where(EvidenceItem.run_id == run_id)
                )
            ).scalars().all()
            return _run_to_dict(run, items)

    async def runs_for_task(self, task_id: str) -> list[dict[str, Any]]:
        async with self.sf() as session:
            runs = (
                await session.execute(
                    select(GateRun)
                    .where(GateRun.task_id == task_id)
                    .order_by(GateRun.started_at.desc())
                )
            ).scalars().all()
            return [_run_to_dict(r, []) for r in runs]

    # --- transition enforcement ----------------------------------------------------
    async def required_gates_passed(self, task_id: str) -> dict[str, Any]:
        """Return which required gates have a passing run for ``task_id``.

        Enforces that every gate in ``settings.required_gates`` has at least one
        run with status ``passed``. Returns both the raw gate-run status map and
        the boolean verdict.
        """
        async with self.sf() as session:
            runs = (
                await session.execute(select(GateRun).where(GateRun.task_id == task_id))
            ).scalars().all()
        # Keep the newest run's status per gate (runs sorted newest-first).
        statuses: dict[str, str] = {}
        for run in sorted(runs, key=lambda r: r.started_at, reverse=True):
            statuses.setdefault(run.gate_name, run.status)
        missing = [g for g in self.settings.required_gates if statuses.get(g) != "passed"]
        verdict = not missing
        return {
            "passed": verdict,
            "per_gate": statuses,
            "missing": missing,
        }

    async def transition(self, task_id: str, target_status: str) -> dict[str, Any]:
        """Model a Kanban transition.

        Raises :class:`TransitionForbiddenError` unless every required gate has a
        passing run for the task -- i.e. a task cannot advance without passing all
        gates. Returns a record of the enforced check.
        """
        check = await self.required_gates_passed(task_id)
        if not check["passed"]:
            raise TransitionForbiddenError(
                f"transition to '{target_status}' blocked: required gates not all passed "
                f"(missing: {', '.join(check['missing']) or 'none-but-incomplete'})"
            )
        return {
            "task_id": task_id,
            "target_status": target_status,
            "allowed": True,
            "gates": check["per_gate"],
            "message": "all required gates passed; transition permitted",
        }

    # --- release lifecycle ---------------------------------------------------------
    async def create_release_candidate(
        self,
        task_id: str,
        workspace: str,
        version: str,
        approver: str | None = None,
    ) -> dict[str, Any]:
        """Assemble a release candidate and persist it in ``awaiting_approval``.

        Approval is never automatic: the candidate is created only in
        ``awaiting_approval`` and the human gate is enforced in
        :meth:`approve_release_candidate`.
        """
        candidate = self.release_agent.assemble(
            workspace, version, task_id=task_id
        )
        async with self.sf() as session:
            row = ReleaseCandidate(
                task_id=task_id,
                version=version,
                status="awaiting_approval",
                release_notes=candidate["release_notes"],
                artifact_path=candidate["artifact_path"],
                artifact_checksum=candidate["artifact_checksum"],
            )
            session.add(row)
            await session.flush()
            candidate_id = row.id
            await session.commit()
        return {**candidate, "id": candidate_id}

    async def approve_release_candidate(self, candidate_id: str, approver: str) -> dict[str, Any]:
        """Enforce the human gate: approve an awaiting_approval candidate."""
        async with self.sf() as session:
            row = await session.get(ReleaseCandidate, candidate_id)
            if row is None:
                from .errors import ReleaseNotFoundError

                raise ReleaseNotFoundError("release candidate not found")
            if row.status != "awaiting_approval":
                from .errors import ReleaseNotAwaitingApprovalError

                raise ReleaseNotAwaitingApprovalError(
                    f"candidate status is {row.status}, expected awaiting_approval"
                )
            if not approver:
                from .errors import QualityGateError

                raise QualityGateError("approval requires an approver identity")
            if approver.lower() in {"release_prep", "release_prep_agent"}:
                from .errors import QualityGateError

                raise QualityGateError("release prep agent cannot approve its own candidate")
            row.status = "approved"
            row.approved_at = _utcnow()
            row.approved_by = approver
            await session.commit()
            return _candidate_to_dict(row)

    async def reject_release_candidate(self, candidate_id: str, approver: str) -> dict[str, Any]:
        async with self.sf() as session:
            row = await session.get(ReleaseCandidate, candidate_id)
            if row is None:
                from .errors import ReleaseNotFoundError

                raise ReleaseNotFoundError("release candidate not found")
            if row.status != "awaiting_approval":
                from .errors import ReleaseNotAwaitingApprovalError

                raise ReleaseNotAwaitingApprovalError(
                    f"candidate status is {row.status}, expected awaiting_approval"
                )
            row.status = "rejected"
            row.approved_by = approver
            await session.commit()
            return _candidate_to_dict(row)

    async def list_release_candidates(self, task_id: str | None = None) -> list[dict[str, Any]]:
        async with self.sf() as session:
            q = select(ReleaseCandidate)
            if task_id:
                q = q.where(ReleaseCandidate.task_id == task_id)
            rows = (await session.execute(q.order_by(ReleaseCandidate.created_at.desc()))).scalars().all()
            return [_candidate_to_dict(r) for r in rows]


# --- serialization helpers ----------------------------------------------------------
def _utcnow():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _run_to_dict(run: GateRun, items: list[EvidenceItem]) -> dict[str, Any]:
    return {
        "id": run.id,
        "task_id": run.task_id,
        "gate": run.gate_name,
        "status": run.status,
        "summary": run.summary,
        "duration_ms": run.duration_ms,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "report_path": run.report_path,
        "evidence": [
            {
                "id": it.id,
                "category": it.category,
                "key": it.key,
                "value": it.value,
                "checksum": it.checksum,
            }
            for it in items
        ],
    }


def _candidate_to_dict(row: ReleaseCandidate) -> dict[str, Any]:
    return {
        "id": row.id,
        "task_id": row.task_id,
        "version": row.version,
        "status": row.status,
        "release_notes": row.release_notes,
        "artifact_path": row.artifact_path,
        "artifact_checksum": row.artifact_checksum,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "approved_by": row.approved_by,
    }
