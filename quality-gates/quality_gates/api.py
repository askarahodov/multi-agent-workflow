"""FastAPI application exposing the quality-gates pipeline.

Endpoints (all under ``/api/v1`` unless noted):

* ``GET  /health``                      liveness probe
* ``GET  /api/v1/gates``                list registered gates
* ``POST /api/v1/runs``                 run a gate against a task/workspace
* ``GET  /api/v1/tasks/{task_id}/runs`` all runs for a task (evidence trail)
* ``GET  /api/v1/tasks/{task_id}/runs/{run_id}`` one run + its evidence
* ``GET  /api/v1/tasks/{task_id}/gates``         per-gate status + enforcement verdict
* ``POST /api/v1/tasks/{task_id}/transition``    gate-enforced transition
* ``POST /api/v1/tasks/{task_id}/releases``      create release candidate (awaiting_approval)
* ``GET  /api/v1/releases``                      list release candidates
* ``POST /api/v1/releases/{id}/approve``         human approval gate
* ``POST /api/v1/releases/{id}/reject``          human rejection
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import auth_middleware as auth_policy
from shared.auth_middleware import (
    AuthContext,
    AuthMiddleware,
    require_admin,
    require_read,
    require_write,
)
from shared.security_middleware import add_security_middleware

from .config import Settings
from .errors import (
    GateFailedError,
    GateNotFoundError,
    QualityGateError,
    ReleaseNotAwaitingApprovalError,
    TransitionForbiddenError,
)
from .gates.base import GATE_REGISTRY
from .pipeline import GatePipeline
from shared.qa_attestation import QaAttestationRejected


def build_app(
    settings: Settings | None = None,
    sf: async_sessionmaker | None = None,
) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Quality Gates API", version="0.1.0")
    # Authenticate every endpoint (SEC-001). Health remains exempt inside
    # AuthMiddleware; role checks below enforce read/write/admin on the rest.
    app.add_middleware(AuthMiddleware)
    # Add HSTS + HTTP->HTTPS redirect middleware when TLS is enabled (SEC-002)
    add_security_middleware(app, tls_enabled=settings.tls_enabled)

    # The pipeline is bound to app.state either at build time (when a session
    # factory is supplied) or later by the caller via ``app.state.pipeline = ...``.
    if sf is not None:
        app.state.pipeline = GatePipeline(sf, settings=settings)

    def _pipeline(request: Request) -> GatePipeline:
        pipeline: GatePipeline | None = getattr(request.app.state, "pipeline", None)
        if pipeline is None:
            raise HTTPException(status_code=500, detail="pipeline not initialised")
        return pipeline

    @app.get("/health")
    async def health(_auth: AuthContext = Depends(require_read)) -> dict[str, Any]:
        return {"status": "ok", "service": "quality-gates"}

    @app.get("/api/v1/gates")
    async def list_gates(_auth: AuthContext = Depends(require_read)) -> list[dict[str, str]]:
        return [
            {"name": name, "description": GATE_REGISTRY.get(name).description}
            for name in GATE_REGISTRY.names()
        ]

    @app.post("/api/v1/runs")
    async def create_run(
        payload: dict[str, Any],
        request: Request,
        _auth: AuthContext = Depends(require_admin),
    ) -> dict[str, Any]:
        pipeline = _pipeline(request)
        task_id = payload.get("task_id")
        workspace = payload.get("workspace")
        gate_name = payload.get("gate")
        if not task_id or not workspace or not gate_name:
            raise HTTPException(status_code=422, detail="task_id, workspace and gate are required")
        if ("attempt_id" in payload) != ("commit_sha" in payload):
            raise HTTPException(status_code=422, detail="Scoped QA requires attempt and commit")
        try:
            return await pipeline.run_gate(
                task_id, workspace, gate_name, payload.get("context"),
                qa_attempt_id=payload.get("attempt_id"),
                qa_commit_sha=payload.get("commit_sha"),
            )
        except GateNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except GateFailedError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/tasks/{task_id}/qa-attestation")
    async def issue_independent_qa(
        task_id: str, payload: dict[str, Any], request: Request,
        auth: AuthContext = Depends(require_admin),
    ) -> dict[str, Any]:
        # A WRITE-privileged AI worker cannot issue or receive this receipt.
        # Development-only all-role auth is not an independent QA identity.
        if not auth_policy.AUTH_ENABLED or auth.subject == "development":
            raise HTTPException(status_code=403, detail="Authenticated QA administrator required")
        key = settings.qa_attestation_key
        if not key:
            raise HTTPException(status_code=503, detail="QA attestation disabled")
        if set(payload) != {"attempt_id", "commit_sha"}:
            raise HTTPException(status_code=422, detail="Exact QA attempt and commit required")
        try:
            return await _pipeline(request).issue_qa_attestation(
                task_id, payload["attempt_id"], payload["commit_sha"],
                issued_by=auth.subject, signing_key=key,
            )
        except (QaAttestationRejected, GateFailedError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/v1/tasks/{task_id}/runs")
    async def task_runs(
        task_id: str, request: Request, _auth: AuthContext = Depends(require_read)
    ) -> list[dict[str, Any]]:
        pipeline = _pipeline(request)
        return await pipeline.runs_for_task(task_id)

    @app.get("/api/v1/tasks/{task_id}/runs/{run_id}")
    async def run_detail(
        task_id: str, run_id: str, request: Request, _auth: AuthContext = Depends(require_read)
    ) -> dict[str, Any]:
        pipeline = _pipeline(request)
        try:
            return await pipeline.get_run(task_id, run_id)
        except GateFailedError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/v1/tasks/{task_id}/gates")
    async def task_gates(
        task_id: str, request: Request, _auth: AuthContext = Depends(require_read)
    ) -> dict[str, Any]:
        pipeline = _pipeline(request)
        return await pipeline.required_gates_passed(task_id)

    @app.post("/api/v1/tasks/{task_id}/transition")
    async def transition(
        task_id: str,
        payload: dict[str, Any],
        request: Request,
        _auth: AuthContext = Depends(require_admin),
    ) -> dict[str, Any]:
        pipeline = _pipeline(request)
        target = payload.get("to")
        if not target:
            raise HTTPException(status_code=422, detail="'to' target status required")
        try:
            return await pipeline.transition(task_id, target)
        except TransitionForbiddenError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/api/v1/tasks/{task_id}/releases")
    async def create_release(
        task_id: str,
        payload: dict[str, Any],
        request: Request,
        _auth: AuthContext = Depends(require_admin),
    ) -> dict[str, Any]:
        pipeline = _pipeline(request)
        workspace = payload.get("workspace")
        version = payload.get("version")
        if not workspace or not version:
            raise HTTPException(status_code=422, detail="workspace and version are required")
        try:
            return await pipeline.create_release_candidate(task_id, workspace, version)
        except QualityGateError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/api/v1/releases")
    async def list_releases(
        request: Request, _auth: AuthContext = Depends(require_read)
    ) -> list[dict[str, Any]]:
        pipeline = _pipeline(request)
        return await pipeline.list_release_candidates()

    @app.post("/api/v1/releases/{release_id}/approve")
    async def approve_release(
        release_id: str,
        payload: dict[str, Any],
        request: Request,
        _auth: AuthContext = Depends(require_admin),
    ) -> dict[str, Any]:
        pipeline = _pipeline(request)
        # The worker WRITE key is not a human release approval capability.
        # Never accept an approver identity from a caller-controlled JSON body.
        # Development mode grants every role and cannot authenticate a human.
        if not auth_policy.AUTH_ENABLED or _auth.subject in ("development", "exempt-path"):
            raise HTTPException(status_code=403, detail="Authenticated administrator required for release approval")
        try:
            return await pipeline.approve_release_candidate(release_id, _auth.subject)
        except (ReleaseNotAwaitingApprovalError, QualityGateError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/releases/{release_id}/reject")
    async def reject_release(
        release_id: str,
        payload: dict[str, Any],
        request: Request,
        _auth: AuthContext = Depends(require_admin),
    ) -> dict[str, Any]:
        pipeline = _pipeline(request)
        if not auth_policy.AUTH_ENABLED or _auth.subject in ("development", "exempt-path"):
            raise HTTPException(status_code=403, detail="Authenticated administrator required for release rejection")
        try:
            return await pipeline.reject_release_candidate(release_id, _auth.subject)
        except (ReleaseNotAwaitingApprovalError, QualityGateError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app
