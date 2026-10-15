"""FastAPI application exposing the platform-owned orchestration REST API.

Every mutation flows through :class:`orchestration_server.engine.OrchestrationEngine`,
which owns the state machine and contract verification. Error responses are RFC
9457 Problem Details documents (see :class:`ProblemDetail`).

Routing follows ADR-101: the canonical contract lives under ``/api/v1`` (the
value of ``Settings.api_prefix``). For backward compatibility with existing
clients and tests, every route is also registered at its unprefixed path, so
both ``/workflows/runs`` and ``/api/v1/workflows/runs`` resolve to the same
handler. List endpoints return the uniform ``CursorPage`` envelope
(``{items, next_cursor}``) with ``after``/``limit`` cursor params.

Authentication: API key based via shared auth middleware (X-API-Key header or Authorization: Bearer).
Configure via AUTH_ENABLED, ADMIN_API_KEYS, WRITE_API_KEYS, READ_API_KEYS environment variables.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from shared.auth_middleware import (
    AuthMiddleware,
    AuthContext,
    require_admin,
    require_write,
    require_read,
    Role,
)
from shared.security_middleware import add_security_middleware
from . import __version__
from .config import Settings, get_settings
from .db import build_engine, build_session_factory, create_all
from .engine import OrchestrationEngine
from .errors import OrchestrationError
from .queries import OrchestrationQueries
from .reconciliation_evidence import ReconciliationEvidenceVerifier
from .tool_ledger_inspection import TrustedToolLedgerReader
from .schemas import (
    AgentRegister,
    AgentResponse,
    ApiStatus,
    AttemptResponse,
    BlockRequest,
    ClaimRequest,
    ContractCreate,
    ContractResponse,
    CreateVersionRequest,
    CreateWorkflowRequest,
    CursorPage,
    FailRequest,
    ProblemDetail,
    ProjectCreate,
    ProjectResponse,
    ReconciliationRequest,
    ReconciliationResponse,
    RecoveryLedgerReport,
    InterruptedAttemptLedger,
    RedactedToolLedgerEntry,
    RunCreate,
    RunResponse,
    SubmitRequest,
    TaskResponse,
    UpdateWorkflowRequest,
    WorkflowDefinitionDTO,
    WorkflowVersionDTO,
    WorkspaceCreate,
    WorkspaceResponse,
)
from .services.workflow_service import WorkflowService

# Documented error responses, shared by the route decorators so the generated
# OpenAPI contract matches the runtime Problem Details behaviour.
ERROR_RESPONSES = {
    400: {"model": ProblemDetail, "description": "Validation error"},
    404: {"model": ProblemDetail, "description": "Resource not found"},
    409: {"model": ProblemDetail, "description": "Conflict (duplicate or concurrent update)"},
    422: {"model": ProblemDetail, "description": "Business rule violation"},
}

_CURSOR_AFTER = Query(default=None, description="Opaque cursor from the previous page's next_cursor")
_CURSOR_LIMIT = Query(default=50, ge=1, le=200, description="Maximum items per page")


def build_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    state: dict = {}
    evidence_verifier = (
        ReconciliationEvidenceVerifier(settings.reconciliation_evidence_root)
        if settings.reconciliation_evidence_root else None
    )
    ledger_reader = (
        TrustedToolLedgerReader(settings.reconciliation_tool_ledger_path)
        if settings.reconciliation_tool_ledger_path else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = build_engine(settings.database_url)
        sf = build_session_factory(engine)
        await create_all(engine)
        orch = OrchestrationEngine(sf)
        if settings.recover_on_startup:
            await orch.recover()
        state["engine"] = engine
        state["orch"] = orch
        state["queries"] = OrchestrationQueries(sf)
        state["workflows"] = WorkflowService(sf)
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="Orchestration Server",
        description=(
            "Platform-owned orchestration with durable execution and task "
            "lifecycle. Agents cannot self-declare completion; contract "
            "verification is enforced by the engine."
        ),
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    # Add authentication middleware
    app.add_middleware(AuthMiddleware)
    # Add HSTS + HTTP->HTTPS redirect middleware when TLS is enabled (SEC-002)
    add_security_middleware(app, tls_enabled=settings.tls_enabled)

    @app.exception_handler(OrchestrationError)
    async def on_orch_error(request: Request, exc: OrchestrationError):
        return JSONResponse(status_code=exc.status_code, content=exc.to_problem())

    def eng() -> OrchestrationEngine:
        orch = state.get("orch")
        if orch is None:
            raise HTTPException(status_code=503, detail="Engine not initialized")
        return orch

    def quer() -> OrchestrationQueries:
        q = state.get("queries")
        if q is None:
            raise HTTPException(status_code=503, detail="Queries not initialized")
        return q

    def workflows() -> WorkflowService:
        w = state.get("workflows")
        if w is None:
            raise HTTPException(status_code=503, detail="Workflow service not initialized")
        return w

    router = APIRouter()

    @router.get("/health", response_model=ApiStatus, tags=["meta"])
    async def health(_auth: AuthContext = Depends(require_read)):
        return ApiStatus(status="ok")

    # ---------- projects / workspaces ----------
    @router.post(
        "/projects",
        response_model=ProjectResponse,
        status_code=201,
        tags=["projects"],
        responses=ERROR_RESPONSES,
    )
    async def create_project(body: ProjectCreate, _auth: AuthContext = Depends(require_write)):
        return await eng().create_project(body.name, body.description, body.settings)

    @router.get("/projects", response_model=List[ProjectResponse], tags=["projects"])
    async def list_projects(_auth: AuthContext = Depends(require_read)):
        return await quer().list_projects()

    @router.post(
        "/workspaces",
        response_model=WorkspaceResponse,
        status_code=201,
        tags=["workspaces"],
        responses=ERROR_RESPONSES,
    )
    async def create_workspace(body: WorkspaceCreate, _auth: AuthContext = Depends(require_write)):
        return await eng().create_workspace(
            body.project_id, body.name, body.path, body.settings
        )

    @router.get(
        "/workspaces", response_model=List[WorkspaceResponse], tags=["workspaces"]
    )
    async def list_workspaces(
        project_id: Optional[str] = Query(default=None), _auth: AuthContext = Depends(require_read)
    ):
        return await quer().list_workspaces(project_id)

    # ---------- contracts ----------
    @router.post(
        "/contracts",
        response_model=ContractResponse,
        status_code=201,
        tags=["contracts"],
        responses=ERROR_RESPONSES,
    )
    async def create_contract(body: ContractCreate, _auth: AuthContext = Depends(require_write)):
        return await eng().create_contract(
            body.name, body.schema_, body.project_id, body.description
        )

    @router.get("/contracts", response_model=List[ContractResponse], tags=["contracts"])
    async def list_contracts(_auth: AuthContext = Depends(require_read)):
        return await quer().list_contracts()

    # ---------- agents ----------
    @router.post(
        "/agents/register",
        response_model=AgentResponse,
        status_code=201,
        tags=["agents"],
        responses=ERROR_RESPONSES,
    )
    async def register_agent(body: AgentRegister, _auth: AuthContext = Depends(require_write)):
        return await eng().register_agent(body.name, body.metadata)

    @router.get("/agents", response_model=List[AgentResponse], tags=["agents"])
    async def list_agents(_auth: AuthContext = Depends(require_read)):
        return await quer().list_agents()

    # ---------- workflow definitions / versions (design-time domain) ----------
    @router.get(
        "/workflows/definitions",
        response_model=CursorPage[WorkflowDefinitionDTO],
        tags=["workflow-definitions"],
        responses=ERROR_RESPONSES,
    )
    async def list_workflow_definitions(
        after: Optional[str] = _CURSOR_AFTER, limit: int = _CURSOR_LIMIT, _auth: AuthContext = Depends(require_read)
    ):
        items, next_cursor = await workflows().list_definitions(after=after, limit=limit)
        return CursorPage(items=items, next_cursor=next_cursor)

    @router.get(
        "/workflows/definitions/{definition_id}",
        response_model=WorkflowDefinitionDTO,
        tags=["workflow-definitions"],
        responses=ERROR_RESPONSES,
    )
    async def get_workflow_definition(definition_id: str, _auth: AuthContext = Depends(require_read)):
        return await workflows().get_definition(definition_id)

    @router.post(
        "/workflows/definitions",
        response_model=WorkflowDefinitionDTO,
        status_code=201,
        tags=["workflow-definitions"],
        responses=ERROR_RESPONSES,
    )
    async def create_workflow_definition(body: CreateWorkflowRequest, _auth: AuthContext = Depends(require_write)):
        return await workflows().create_definition(
            body.name, body.definition, body.description
        )

    @router.put(
        "/workflows/definitions/{definition_id}",
        response_model=WorkflowDefinitionDTO,
        tags=["workflow-definitions"],
        responses=ERROR_RESPONSES,
    )
    async def update_workflow_definition(
        definition_id: str, body: UpdateWorkflowRequest, _auth: AuthContext = Depends(require_write)
    ):
        return await workflows().update_definition(
            definition_id,
            name=body.name,
            description=body.description,
            definition=body.definition,
            is_active=body.is_active,
        )

    @router.get(
        "/workflows/definitions/{definition_id}/versions",
        response_model=CursorPage[WorkflowVersionDTO],
        tags=["workflow-definitions"],
        responses=ERROR_RESPONSES,
    )
    async def list_workflow_versions(
        definition_id: str,
        after: Optional[str] = _CURSOR_AFTER,
        limit: int = _CURSOR_LIMIT,
        _auth: AuthContext = Depends(require_read),
    ):
        items, next_cursor = await workflows().list_versions(
            definition_id, after=after, limit=limit
        )
        return CursorPage(items=items, next_cursor=next_cursor)

    @router.post(
        "/workflows/definitions/{definition_id}/versions",
        response_model=WorkflowVersionDTO,
        status_code=201,
        tags=["workflow-definitions"],
        responses=ERROR_RESPONSES,
    )
    async def create_workflow_version(
        definition_id: str, body: CreateVersionRequest, _auth: AuthContext = Depends(require_write)
    ):
        return await workflows().create_version(
            definition_id, body.definition_snapshot, body.changelog
        )

    # ---------- workflow runs ----------
    @router.post(
        "/workflows/runs",
        response_model=RunResponse,
        status_code=201,
        tags=["runs"],
        responses=ERROR_RESPONSES,
    )
    async def launch_run(body: RunCreate, _auth: AuthContext = Depends(require_write)):
        return await eng().launch_run(
            body.project_id,
            body.name,
            [t.model_dump() for t in body.tasks],
            body.workspace_id,
            body.triggered_by,
            body.input_data,
            body.retry_policy,
        )

    @router.get(
        "/workflows/runs",
        response_model=CursorPage[RunResponse],
        tags=["runs"],
        responses=ERROR_RESPONSES,
    )
    async def list_runs(
        project_id: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None),
        after: Optional[str] = _CURSOR_AFTER,
        limit: int = _CURSOR_LIMIT,
        _auth: AuthContext = Depends(require_read),
    ):
        items, next_cursor = await quer().list_runs_page(
            after=after, limit=limit, project_id=project_id, status=status
        )
        return CursorPage(items=items, next_cursor=next_cursor)

    @router.get(
        "/workflows/runs/{run_id}",
        response_model=RunResponse,
        tags=["runs"],
        responses=ERROR_RESPONSES,
    )
    async def get_run(run_id: str, _auth: AuthContext = Depends(require_read)):
        return await quer().get_run(run_id)

    @router.get(
        "/workflows/runs/{run_id}/tasks",
        response_model=CursorPage[TaskResponse],
        tags=["runs"],
        responses=ERROR_RESPONSES,
    )
    async def list_tasks(
        run_id: str,
        after: Optional[str] = _CURSOR_AFTER,
        limit: int = _CURSOR_LIMIT,
        _auth: AuthContext = Depends(require_read),
    ):
        items, next_cursor = await quer().list_tasks_page(run_id, after=after, limit=limit)
        return CursorPage(items=items, next_cursor=next_cursor)

    # ---------- tasks / attempts ----------
    @router.get(
        "/tasks/{task_id}",
        response_model=TaskResponse,
        tags=["tasks"],
        responses=ERROR_RESPONSES,
    )
    async def get_task(task_id: str, _auth: AuthContext = Depends(require_read)):
        return await quer().get_task(task_id)

    @router.get(
        "/tasks/{task_id}/attempts",
        response_model=List[AttemptResponse],
        tags=["tasks"],
    )
    async def list_attempts(task_id: str, _auth: AuthContext = Depends(require_read)):
        return await quer().list_attempts(task_id)

    @router.post(
        "/tasks/{task_id}/claim",
        response_model=AttemptResponse,
        status_code=201,
        tags=["tasks"],
        responses=ERROR_RESPONSES,
    )
    async def claim_task(task_id: str, body: ClaimRequest, _auth: AuthContext = Depends(require_write)):
        return await eng().claim_task(task_id, body.agent_id)

    @router.post(
        "/tasks/{task_id}/attempts/{attempt_id}/submit",
        response_model=AttemptResponse,
        tags=["tasks"],
        responses=ERROR_RESPONSES,
    )
    async def submit(
        task_id: str,
        attempt_id: str,
        body: SubmitRequest,
        agent_id: Optional[str] = Query(default=None),
        _auth: AuthContext = Depends(require_write),
    ):
        if agent_id is None:
            raise HTTPException(status_code=400, detail="agent_id query parameter is required")
        return await eng().submit(task_id, attempt_id, agent_id, body.output)

    @router.post(
        "/tasks/{task_id}/attempts/{attempt_id}/fail",
        response_model=AttemptResponse,
        tags=["tasks"],
        responses=ERROR_RESPONSES,
    )
    async def fail_attempt(
        task_id: str,
        attempt_id: str,
        body: FailRequest,
        agent_id: Optional[str] = Query(default=None),
        _auth: AuthContext = Depends(require_write),
    ):
        if agent_id is None:
            raise HTTPException(status_code=400, detail="agent_id query parameter is required")
        return await eng().fail_attempt(task_id, attempt_id, agent_id, body.error)

    @router.post(
        "/tasks/{task_id}/block",
        response_model=TaskResponse,
        tags=["tasks"],
        responses=ERROR_RESPONSES,
    )
    async def block_task(
        task_id: str,
        body: BlockRequest,
        agent_id: Optional[str] = Query(default=None),
        _auth: AuthContext = Depends(require_write),
    ):
        if agent_id is None:
            raise HTTPException(status_code=400, detail="agent_id query parameter is required")
        return await eng().block_task(task_id, agent_id, body.reason)

    # ---------- maintenance ----------
    @router.get(
        "/admin/recovery-quarantine",
        response_model=List[TaskResponse], tags=["maintenance"],
    )
    async def recovery_quarantine(
        limit: int = Query(default=100, ge=1, le=200),
        _auth: AuthContext = Depends(require_admin),
    ):
        return await quer().list_recovery_quarantine(limit=limit)

    @router.get(
        "/admin/tasks/{task_id}/tool-ledger",
        response_model=RecoveryLedgerReport, tags=["maintenance"],
        responses=ERROR_RESPONSES,
    )
    async def inspect_recovery_tool_ledger(
        task_id: str, _auth: AuthContext = Depends(require_admin),
    ):
        if ledger_reader is None:
            raise HTTPException(
                status_code=503, detail="Trusted tool ledger inspection is not configured",
            )
        task, attempts = await quer().get_quarantined_attempts(task_id)
        reports = []
        for attempt in attempts:
            entries = await asyncio.to_thread(
                ledger_reader.inspect, task.workflow_run_id, attempt.id,
            )
            reports.append(InterruptedAttemptLedger(
                attempt_id=attempt.id,
                record_status="RECORDS" if entries else "NO_RECORDS",
                entries=[RedactedToolLedgerEntry(
                    call_ref=entry.call_ref, tool=entry.tool, state=entry.state,
                ) for entry in entries],
            ))
        return RecoveryLedgerReport(
            task_id=task.id, ledger_status="AVAILABLE", attempts=reports,
        )

    @router.get(
        "/admin/tasks/{task_id}/reconciliation",
        response_model=ReconciliationResponse, tags=["maintenance"],
        responses=ERROR_RESPONSES,
    )
    async def get_reconciliation(
        task_id: str, _auth: AuthContext = Depends(require_admin),
    ):
        return await quer().get_reconciliation(task_id)

    @router.post(
        "/admin/tasks/{task_id}/reconciliation",
        response_model=ReconciliationResponse, tags=["maintenance"],
        responses=ERROR_RESPONSES,
    )
    async def attest_reconciliation(
        task_id: str,
        body: ReconciliationRequest,
        _auth: AuthContext = Depends(require_admin),
    ):
        # A confirmed result needs an independently verified evidence file
        # from the trusted service mount, not only an operator-supplied digest.
        # UNKNOWN can be attested without proof to keep ambiguous tasks blocked.
        if body.decision != "UNKNOWN":
            if evidence_verifier is None:
                raise HTTPException(
                    status_code=503, detail="Trusted evidence verification is not configured",
                )
            await asyncio.to_thread(
                evidence_verifier.verify, body.evidence_ref, body.evidence_sha256,
            )
            # The UI refuses a confirmed verdict without ledger inspection.
            # Enforce the same fail-closed rule at the API boundary; an admin
            # client must not bypass it by skipping the recovery console.
            if ledger_reader is None:
                raise HTTPException(
                    status_code=503, detail="Trusted tool ledger inspection is not configured",
                )
            task, attempts = await quer().get_quarantined_attempts(task_id)
            for attempt in attempts:
                await asyncio.to_thread(
                    ledger_reader.inspect, task.workflow_run_id, attempt.id,
                )
        # Operator comes from the authenticated principal; user-supplied
        # operator names and task states are ignored/not in request schema.
        return await eng().reconcile_quarantined_task(
            task_id, decision=body.decision,
            evidence_ref=body.evidence_ref,
            evidence_sha256=body.evidence_sha256,
            operator_subject=_auth.subject,
        )

    @router.post("/workflows/tick", response_model=dict, tags=["maintenance"])
    async def tick(_auth: AuthContext = Depends(require_write)):
        return {"promoted": await eng().tick()}

    @router.post("/admin/recover", response_model=ApiStatus, tags=["maintenance"])
    async def admin_recover(_auth: AuthContext = Depends(require_admin)):
        result = await eng().recover()
        return ApiStatus(status="recovered", **result)

    # Canonical /api/v1 contract (ADR-101) plus unprefixed aliases so existing
    # clients/tests keep working unchanged.
    app.include_router(router)
    if settings.api_prefix:
        app.include_router(router, prefix=settings.api_prefix)

    return app