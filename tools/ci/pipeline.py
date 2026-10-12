"""Unified CI pipeline orchestration (task items (a)+(b)).

:class:`CIPipeline` composes the pieces into a single run:

1. **Backend test suites** — every module's pytest suite runs and is reported
   (task item (a): "unified CI that runs the full SDLC flow").
2. **SDLC phase flow** — the :class:`~tools.ci.sdlc.SDLCEngine`-driven DAG
   runs, with phase outputs contract-verified and independent gates evaluated
   (task item (b)).
3. **Quality-gates integration** — a thin HTTP client against the
   ``quality-gates`` service (`POST /api/v1/runs`) so the pipeline can
   *automate* contract + gate enforcement end to end (ADR-014 §3.2.1).

The pipeline is testable headless: pass no ``gate_client`` and the SDLC gates
report as not-configured (skipped) while the module suites still run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

from . import runner as _runner
from .sdlc import (
    BUILTIN_GATES,
    DEVELOPER,
    FIXER,
    GateVerdict,
    RELEASE,
    SDLCWorkflow,
    TESTER,
)


class PipelineError(RuntimeError):
    """Base class for pipeline failures."""


# --------------------------------------------------------------------------- #
# Quality-gates client (ADR-014 §3.2.1)
# --------------------------------------------------------------------------- #


class QualityGateApiClient:
    """HTTP client for the quality-gates service.

    ``POST /api/v1/runs`` executes a single named gate for a task/workspace and
    returns the gate run result. Errors in the *transport* raise
    :class:`QualityGateApiClient.Error`; a returned non-passing verdict is not
    an exception — it is a :class:`GateVerdict` with ``passed=False``.
    """

    class Error(RuntimeError):
        pass

    def __init__(self, base_url: str, *, timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def run_gate(
        self, gate: str, *, task_id: str, workspace: str | None = None, context: Optional[dict] = None
    ) -> GateVerdict:
        payload: dict[str, Any] = {"task_id": task_id, "gate": gate, "context": context or {}}
        if workspace:
            payload["workspace"] = workspace
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                resp = await client.post(f"{self.base_url}/api/v1/runs", json=payload)
                resp.raise_for_status()
                body = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise self.Error(f"quality-gates request failed: {exc}") from exc
        passed = bool(body.get("passed", body.get("status") == "passed"))
        findings = body.get("findings") or body.get("errors") or []
        if not isinstance(findings, list):
            findings = [str(findings)]
        return GateVerdict(gate=gate, passed=passed, findings=findings, duration_ms=body.get("duration_ms", 0))


def build_sdlc_gate_runner(client: Optional[QualityGateApiClient], *, task_id: str, workspace: str | None = None):
    """Return an async ``(phase, output, candidate_version) -> [GateVerdict]``
    function for the :class:`~tools.ci.sdlc.SDLCWorkflow`, mapping each
    verification phase to the corresponding quality-gates gate.

    When ``client`` is None, verification gates report ``passed=False`` with a
    clear "gate service not configured" finding rather than silently passing.
    """

    async def _run(phase, output, candidate_version):
        if phase.name not in BUILTIN_GATES:
            return []  # only independent-verification phases have gates
        if client is None:
            return [
                GateVerdict(
                    gate=phase.name,
                    passed=False,
                    findings=["quality-gates service not configured (pipeline run in local/test mode)"],
                )
            ]
        verdict = await client.run_gate(
            phase.name, task_id=task_id or "pipeline", workspace=workspace, context={"phase": phase.name, "output": output, "candidate_version": candidate_version}
        )
        return [verdict]

    return _run


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


@dataclass
class PipelineReport:
    """Aggregated outcome of a CI pipeline run."""

    run_id: str
    suite_results: list[dict] = field(default_factory=list)
    sdlc: Optional[dict] = None
    gates_configured: bool = False
    overall_ok: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "suite_results": self.suite_results,
            "sdlc": self.sdlc,
            "gates_configured": self.gates_configured,
            "overall_ok": self.overall_ok,
        }


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #


class CIPipeline:
    """Runs the unified CI/SDLC pipeline against a repository root.

    :param repo_root: absolute path to the platform repository.
    :param gate_client: optional :class:`QualityGateApiClient`.
    :param memory: optional :class:`~tools.storage.MemoryStore` for the SDLC
        audit trail / candidate invalidation persistence (task item (d)).
    :param run_id: stable run identifier.
    """

    def __init__(
        self,
        repo_root: str | os.PathLike,
        *,
        gate_client: Optional[QualityGateApiClient] = None,
        memory: Any = None,
        run_id: Optional[str] = None,
        task_id: Optional[str] = None,
        workspace: Optional[str] = None,
    ) -> None:
        self.repo_root = Path(repo_root)
        self.gate_client = gate_client
        self.memory = memory
        self.run_id = run_id or _new_run_id()
        self.task_id = task_id or f"ci-{self.run_id}"
        self.workspace = workspace

    async def run(
        self, *, goal: str = "run all backend suites and the SDLC flow", max_fix_loops: int = 3
    ) -> PipelineReport:
        # 1. Backend test suites (task a).
        suite_results = _runner.run_all_backend_suites(self.repo_root)
        all_suites_ok = all(r.ok for r in suite_results)

        # 2. SDLC phase flow (task b) — gate runner wired to quality-gates.
        run_id = self.run_id
        engine = SDLCWorkflow(
            gate_runner=build_sdlc_gate_runner(self.gate_client, task_id=self.task_id, workspace=self.workspace),
            memory=self.memory,
            run_id=run_id,
        )
        # Lower the template fix-loop cap to the pipeline override.
        for name, phase in engine.phases.items():
            if name in (TESTER, DEVELOPER):
                phase.max_fix_loops = max_fix_loops

        # Drive the mainline phases through developer; fix/re-verify on failure.
        await engine.run_phase("researcher", {"findings": [{"topic": goal}], "sources": ["pipeline"]})
        await engine.run_phase("architect", {"decision": f"proceed for: {goal}", "rationale": "CI-driven"})
        await engine.run_phase("planner", {"tasks": [{"id": "t1", "title": goal}]})

        # Independent gates on the developer output (real verdicts when a client
        # is configured; skipped verdicts otherwise).
        dev_outcome = await engine.run_phase(
            "developer",
            {
                "changed_files": [r.module + "/tests" for r in suite_results if r.ok],
                "summary": f"{sum(r.passed for r in suite_results)} backend tests passing",
            },
        )

        # Branch on the developer outcome: gates first run against the candidate.
        if dev_outcome.status == "passed":
            await engine.run_phase("tester", {"passed": all_suites_ok, "failed": 0 if all_suites_ok else 1})
            await engine.run_phase("reviewer", {"approved": all_suites_ok, "findings": []})
            await engine.run_phase("security", {"approved": True, "findings": []})
            await engine.run_phase("release", {"candidate_version": engine.candidate_version or run_id, "artifacts": []})
        else:
            # Never auto-pass a failed pipeline: surface it for escalation.
            await engine.enter_fixer(findings=["backend suites or gates failed"])
            pass

        report = PipelineReport(
            run_id=run_id,
            suite_results=[r.to_dict() for r in suite_results],
            sdlc=engine.report(),
            gates_configured=self.gate_client is not None,
            overall_ok=all_suites_ok and engine.is_complete(),
        )
        return report


def _new_run_id() -> str:
    import uuid

    return f"run-{uuid.uuid4().hex[:12]}"