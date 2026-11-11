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
import hashlib
import hmac
import json
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse, StreamingResponse

from shared import auth_middleware as auth_policy
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
from .attempt_leases import AttemptLeaseService
from .db import build_engine, build_session_factory, create_all
from .engine import OrchestrationEngine
from .errors import ConflictError, OrchestrationError
from .queries import OrchestrationQueries
from .reconciliation_evidence import ReconciliationEvidenceVerifier
from .tool_ledger_inspection import TrustedToolLedgerReader
from .schemas import (
    AgentRegister,
    AgentResponse,
    ApiStatus,
    AttemptResponse,
    AttemptLeaseRenewRequest,
    AttemptLeaseResponse,
    ClaimAttemptResponse,
    BlockRequest,
    ClaimRequest,
    ContractCreate,
    ContractResponse,
    CreateVersionRequest,
    CreateWorkflowRequest,
    PublishedRunCreate,
    CursorPage,
    FailRequest,
    GitEvidenceResponse,
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
    RunReleaseApprovalStatus,
    SubmitRequest,
    TaskResponse,
    UpdateWorkflowRequest,
    WorkflowDefinitionDTO,
    WorkflowVersionDTO,
    WorkspaceCreate,
    WorkspaceResponse,
)
from .services.workflow_service import WorkflowService
from .published_graph import compile_published_graph
from .published_preflight import inspect_published_run
from . import events as event_stream
from .stream_tickets import StreamTicketStore
from .stream_ticket_auth import active_stream_authorized, redeem_stream_ticket_principal
from .stream_ticket_issuer import StreamTicketIssuer
from .stream_ticket_router import create_stream_ticket_router

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


def _ws_read_authorized(websocket: WebSocket) -> bool:
    """Authorise a WebSocket handshake for read access.

    Browsers cannot attach custom headers to a ``new WebSocket(...)`` handshake,
    so the API key may be supplied as an ``api_key`` query parameter (or, for
    non-browser clients, in the usual header). The key sets and role semantics
    are shared with the HTTP middleware via ``resolve_api_key_roles`` so both
    transports agree on who may read.
    """
    if not auth_policy.AUTH_ENABLED:
        return True
    key = websocket.query_params.get("api_key")
    if not key:
        key = websocket.headers.get(auth_policy.API_KEY_HEADER_NAME)
    if not key:
        header = websocket.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            key = header[7:]
    if not key:
        return False
    return Role.READ in auth_policy.resolve_api_key_roles(key)


def build_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    state: dict = {}
    evidence_verifier = (
        ReconciliationEvidenceVerifier(settings.reconciliation_evidence_root)
        if settings.reconciliation_evidence_root else None
    )
    from .git_commit_verifier import TrustedGitCommitVerifier
    git_verifier = (
        TrustedGitCommitVerifier(
            settings.git_verification_repository,
            settings.git_verification_executable,
        ) if settings.git_verification_repository else None
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
        orch = OrchestrationEngine(
            sf, require_lease=settings.attempt_lease_enabled,
            qa_attestation_key=settings.qa_attestation_key,
            require_git_artifact=settings.require_git_artifact,
            git_commit_verifier=git_verifier,
            require_release_approval=settings.release_approval_key is not None,
        )
        if settings.recover_on_startup:
            await orch.recover()
        state["engine"] = engine
        state["orch"] = orch
        state["session_factory"] = sf
        state["queries"] = OrchestrationQueries(sf)
        state["workflows"] = WorkflowService(sf)
        state["lease_service"] = (
            AttemptLeaseService(sf, ttl_seconds=settings.attempt_lease_ttl_seconds)
            if settings.attempt_lease_enabled else None
        )
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
    app.state.stream_tickets_enabled = settings.stream_tickets_enabled
    app.state.stream_ticket_api_prefix = settings.api_prefix.rstrip("/")
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

    async def can_read_run(auth: AuthContext, run_id: str) -> bool:
        if Role.READ not in auth.roles:
            return False
        try:
            await quer().get_run(run_id)
        except OrchestrationError:
            return False
        return True

    ticket_store = (
        StreamTicketStore(settings.stream_ticket_database)
        if settings.stream_tickets_enabled else None
    )
    if ticket_store is not None:
        issuer = StreamTicketIssuer(ticket_store, can_read_run=can_read_run)
        router.include_router(create_stream_ticket_router(issuer))

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
            body.name, body.definition, body.description, body.project_id
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
            expected_version=body.expected_version,
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
            definition_id, body.definition_snapshot, body.changelog,
            expected_version=body.expected_version,
        )

    @router.get(
        "/workflows/definitions/{definition_id}/versions/{version_id}/preflight",
        tags=["workflow-definitions", "runs"],
        responses=ERROR_RESPONSES,
    )
    async def preflight_published_workflow(
        definition_id: str,
        version_id: str,
        project_id: str = Query(...),
        workspace_id: Optional[str] = Query(default=None),
        _auth: AuthContext = Depends(require_read),
    ):
        definition, version = await workflows().get_published_version(definition_id, version_id)
        return await inspect_published_run(
            state["session_factory"], definition, version,
            project_id=project_id, workspace_id=workspace_id,
        )

    @router.post(
        "/workflows/definitions/{definition_id}/versions/{version_id}/runs",
        response_model=RunResponse,
        status_code=201,
        tags=["workflow-definitions", "runs"],
        responses=ERROR_RESPONSES,
    )
    async def launch_published_workflow(
        definition_id: str,
        version_id: str,
        body: PublishedRunCreate,
        _auth: AuthContext = Depends(require_write),
    ):
        receipt = None
        if body.idempotency_key is not None:
            # Key stays out of run input_data, response, event logs and DB.
            # Principal/route/payload are bound to a digest, never a raw key.
            scope = json.dumps(
                ["published", _auth.subject, body.idempotency_key],
                separators=(",", ":"), ensure_ascii=True,
            )
            scope_hash = hashlib.sha256(scope.encode("utf-8")).hexdigest()
            request_payload = json.dumps({
                "definition_id": definition_id, "version_id": version_id,
                "body": body.model_dump(exclude={"idempotency_key"},
                                        exclude_none=True),
            }, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            request_hash = hashlib.sha256(request_payload.encode("utf-8")).hexdigest()
            receipt = (scope_hash, request_hash)
            existing = await eng().find_published_run(*receipt)
            if existing is not None:
                return existing
        definition, version = await workflows().get_published_version(definition_id, version_id)
        if definition.project_id not in (None, body.project_id):
            from .errors import BusinessRuleError
            raise BusinessRuleError("Workflow belongs to another project")
        # The client cannot submit a task list for this route. Recompile the
        # immutable server snapshot on every run, fail closed for unsupported
        # graph semantics, then let the engine verify contracts/project scope.
        preflight = await inspect_published_run(
            state["session_factory"], definition, version,
            project_id=body.project_id, workspace_id=body.workspace_id,
        )
        if not preflight["can_create_run"]:
            from .errors import BusinessRuleError
            blocked = [item["detail"] for item in preflight["checks"] if item["status"] == "block"]
            raise BusinessRuleError("Published workflow preflight blocked: " + "; ".join(blocked))
        compiled = compile_published_graph(version.definition_snapshot)
        context = dict(body.input_data or {})
        if any(key in context for key in ("_workflow_definition_id", "_workflow_version_id")):
            from .errors import ValidationError
            raise ValidationError("Reserved published workflow provenance keys")
        context.update({
            "_workflow_definition_id": definition_id,
            "_workflow_version_id": version_id,
        })
        return await eng().launch_run(
            body.project_id, body.name, compiled,
            workspace_id=body.workspace_id,
            triggered_by="published-workflow",
            input_data=context,
            published_graph=True,
            launch_receipt=receipt,
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

    # ---------- run event streaming (real-time UI) ----------
    @router.get(
        "/workflows/runs/{run_id}/events",
        tags=["runs"],
        responses=ERROR_RESPONSES,
        response_class=StreamingResponse,
    )
    async def stream_run_events(
        run_id: str,
        request: Request,
        after: int = Query(default=0, ge=0, description="Last saga event id already seen."),
        poll_interval: float = Query(
            default=event_stream.DEFAULT_POLL_INTERVAL,
            gt=0,
            le=event_stream.MAX_POLL_INTERVAL,
            description="Seconds between journal polls.",
        ),
        max_events: Optional[int] = Query(
            default=None, ge=1, le=10000, description="Close after N events (finite consumers)."
        ),
        idle_timeout: Optional[float] = Query(
            default=None, gt=0, le=3600, description="Close after N idle seconds."
        ),
        _auth: AuthContext = Depends(require_read),
    ):
        ticket_principal = None
        if ticket_store is not None:
            # Validate query shape here as well as in middleware: development
            # mode (AUTH_ENABLED=false) skips the middleware auth gate.
            query = request.query_params
            if (
                any(name.lower().replace("-", "_") == "api_key" for name in query.keys())
                or len(query.getlist("stream_ticket")) != 1
                or not query.get("stream_ticket")
            ):
                raise HTTPException(status_code=401, detail="Invalid stream credentials")
            ticket = query["stream_ticket"]
            try:
                ticket_principal = await redeem_stream_ticket_principal(
                    ticket_store, ticket, run_id=run_id,
                    transport="sse", can_read_run=can_read_run,
                )
            except Exception:
                # A lost/permission-downgraded shared store must fail closed
                # with a sanitized response, never a query-key fallback.
                raise HTTPException(
                    status_code=503, detail="Stream tickets unavailable",
                    headers={"Cache-Control": "no-store"},
                ) from None
            if ticket_principal is None:
                raise HTTPException(status_code=403, detail="Invalid stream ticket")
        # Resolve the run before opening the stream so an unknown id is a 404
        # problem document rather than an empty 200 stream.
        await quer().get_run(run_id)

        async def active_authorized() -> bool:
            return await active_stream_authorized(
                ticket_principal, run_id, can_read_run
            )

        async def event_source():
            # Reconnection needs a fresh short-lived ticket after revocation.
            try:
                yield "retry: 2000\n\n"
                async for kind, payload in event_stream.stream_events(
                    state["session_factory"],
                    run_id,
                    after_id=after,
                    poll_interval=poll_interval,
                    max_events=max_events,
                    idle_timeout=idle_timeout,
                    heartbeat_every=20,
                    authorize=active_authorized if ticket_principal is not None else None,
                ):
                    if kind == "ping" or payload is None:
                        yield ": ping\n\n"
                    else:
                        yield event_stream.format_sse(payload)
            except event_stream.StreamAuthorizationRevoked:
                return

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @router.websocket("/workflows/runs/{run_id}/ws")
    async def stream_run_events_ws(websocket: WebSocket, run_id: str) -> None:
        ticket_principal = None
        if ticket_store is not None:
            # Reject requests mixing long-lived and ephemeral URL credentials.
            query = websocket.query_params
            if (
                any(name.lower().replace("-", "_") == "api_key" for name in query.keys())
                or len(query.getlist("stream_ticket")) != 1
            ):
                await websocket.close(code=1008)
                return
            ticket = query.get("stream_ticket", "")
            try:
                ticket_principal = await redeem_stream_ticket_principal(
                    ticket_store, ticket, run_id=run_id,
                    transport="websocket", can_read_run=can_read_run,
                )
            except Exception:
                # A pre-accept close is an HTTP 403 handshake rejection under
                # ASGI, not an on-wire WebSocket 1011. Complete the handshake
                # (without sending events) to identify a store outage to the
                # client, then close with the server-error code.
                await websocket.accept()
                await websocket.close(code=1011)
                return
            if ticket_principal is None:
                await websocket.close(code=1008)
                return
        elif not _ws_read_authorized(websocket):
            await websocket.close(code=1008)
            return
        queries = state.get("queries")
        sf = state.get("session_factory")
        if queries is None or sf is None:
            await websocket.close(code=1011)
            return
        try:
            await queries.get_run(run_id)
        except OrchestrationError:
            await websocket.close(code=1008, reason="run not found")
            return

        def _int(name: str, default):
            raw = websocket.query_params.get(name)
            if raw is None:
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        def _float(name: str, default):
            raw = websocket.query_params.get(name)
            if raw is None:
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        after = max(_int("after", 0), 0)
        max_events = _int("max_events", None)
        if max_events is not None and max_events < 1:
            max_events = None
        poll_interval = _float("poll_interval", event_stream.DEFAULT_POLL_INTERVAL)
        idle_timeout = _float("idle_timeout", None)

        async def active_authorized() -> bool:
            return await active_stream_authorized(
                ticket_principal, run_id, can_read_run
            )

        await websocket.accept()
        try:
            async for kind, payload in event_stream.stream_events(
                sf,
                run_id,
                after_id=after,
                poll_interval=poll_interval,
                max_events=max_events,
                idle_timeout=idle_timeout,
                heartbeat_every=20,
                authorize=active_authorized if ticket_principal is not None else None,
            ):
                if kind == "ping" or payload is None:
                    await websocket.send_json({"type": "ping"})
                else:
                    await websocket.send_json({"type": "run_event", **payload})
        except event_stream.StreamAuthorizationRevoked:
            await websocket.close(code=1008)
            return
        except WebSocketDisconnect:
            return

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
        "/tasks/{task_id}/git-evidence",
        response_model=List[GitEvidenceResponse],
        tags=["tasks"],
    )
    async def list_git_evidence(task_id: str, _auth: AuthContext = Depends(require_read)):
        return await quer().get_git_evidence(task_id)

    @router.get(
        "/tasks/{task_id}/qa-attestation",
        response_model=dict, tags=["tasks"], responses=ERROR_RESPONSES,
    )
    async def get_independent_qa_status(
        task_id: str, _auth: AuthContext = Depends(require_read),
    ):
        return await eng().get_qa_status(task_id)

    @router.post(
        "/tasks/{task_id}/qa-attestation",
        response_model=dict, tags=["tasks"], responses=ERROR_RESPONSES,
    )
    async def register_independent_qa(
        task_id: str, payload: dict,
        auth: AuthContext = Depends(require_admin),
    ):
        # The worker has only WRITE; dev all-role auth is not an independent
        # QA principal. Never accept model output as a signed receipt.
        if not auth_policy.AUTH_ENABLED or auth.subject == "development":
            raise HTTPException(
                status_code=403, detail="Authenticated QA administrator required",
            )
        return await eng().register_qa_attestation(task_id, payload)

    @router.get(
        "/workflows/runs/{run_id}/release-approval",
        response_model=RunReleaseApprovalStatus,
        tags=["workflows"], responses=ERROR_RESPONSES,
    )
    async def read_native_release_approval(
        run_id: str, _auth: AuthContext = Depends(require_read),
    ):
        # READ clients see only existence/timestamp; neither the secret
        # operator credential nor hashed approver identity is disclosed.
        return await quer().get_run_release_approval(
            run_id, required=settings.release_approval_key is not None,
        )

    @router.post(
        "/workflows/runs/{run_id}/release-approval",
        response_model=dict, tags=["workflows"], responses=ERROR_RESPONSES,
    )
    async def approve_native_release(
        run_id: str, auth: AuthContext = Depends(require_admin),
    ):
        # QA administrators cannot approve their own receipts; only a
        # separate private operator credential may approve the release.
        if (
            not auth_policy.AUTH_ENABLED or auth.subject == "development"
            or settings.release_approval_key is None
            or not hmac.compare_digest(auth.api_key, settings.release_approval_key)
        ):
            raise HTTPException(status_code=403, detail="Dedicated release operator required")
        return await eng().approve_release(run_id, auth.subject)

    @router.get(
        "/tasks/{task_id}/attempts",
        response_model=List[AttemptResponse],
        tags=["tasks"],
    )
    async def list_attempts(task_id: str, _auth: AuthContext = Depends(require_read)):
        return await quer().list_attempts(task_id)

    @router.post(
        "/tasks/{task_id}/claim",
        response_model=ClaimAttemptResponse,
        status_code=201,
        tags=["tasks"],
        responses=ERROR_RESPONSES,
    )
    async def claim_task(
        task_id: str, body: ClaimRequest, response: Response,
        _auth: AuthContext = Depends(require_write),
    ):
        attempt = await eng().claim_task(task_id, body.agent_id)
        dto = ClaimAttemptResponse.model_validate(attempt)
        service = state.get("lease_service")
        if service is not None:
            # Issued after a committed claim. On failure the orphaned claim
            # is quarantined by normal recovery; never return a fake grant.
            grant = await service.issue(attempt.id, body.agent_id)
            dto.lease_token = grant.token
            dto.lease_generation = grant.generation
            dto.lease_expires_at = grant.expires_at
            response.headers["Cache-Control"] = "no-store"
        return dto

    @router.post(
        "/tasks/{task_id}/attempts/{attempt_id}/lease/renew",
        response_model=AttemptLeaseResponse,
        tags=["tasks"],
        responses=ERROR_RESPONSES,
    )
    async def renew_attempt_lease(
        task_id: str, attempt_id: str, body: AttemptLeaseRenewRequest,
        response: Response, _auth: AuthContext = Depends(require_write),
    ):
        service = state.get("lease_service")
        if service is None:
            raise ConflictError("Attempt leasing is disabled")
        grant = await service.renew(
            attempt_id, body.agent_id, body.lease_token, task_id=task_id,
        )
        response.headers["Cache-Control"] = "no-store"
        return AttemptLeaseResponse(
            generation=grant.generation, expires_at=grant.expires_at,
        )

    @router.post(
        "/tasks/{task_id}/attempts/{attempt_id}/lease/revoke",
        response_model=dict,
        tags=["maintenance"],
        responses=ERROR_RESPONSES,
    )
    async def revoke_attempt_lease(
        task_id: str, attempt_id: str,
        _auth: AuthContext = Depends(require_admin),
    ):
        service = state.get("lease_service")
        if service is None:
            raise ConflictError("Attempt leasing is disabled")
        # Verify scope from server-owned DB before mutating any capability.
        attempts = await quer().list_attempts(task_id)
        if not any(a.id == attempt_id for a in attempts):
            raise ConflictError("Attempt does not belong to this task")
        return {"revoked": await service.revoke(attempt_id)}

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
        lease_token: Optional[str] = Header(default=None, alias="X-Attempt-Lease"),
        _auth: AuthContext = Depends(require_write),
    ):
        if agent_id is None:
            raise HTTPException(status_code=400, detail="agent_id query parameter is required")
        return await eng().submit(
            task_id, attempt_id, agent_id, body.output, lease_token=lease_token,
            git_artifact=body.git_artifact.model_dump() if body.git_artifact else None,
        )

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
        lease_token: Optional[str] = Header(default=None, alias="X-Attempt-Lease"),
        _auth: AuthContext = Depends(require_write),
    ):
        if agent_id is None:
            raise HTTPException(status_code=400, detail="agent_id query parameter is required")
        return await eng().fail_attempt(
            task_id, attempt_id, agent_id, body.error, lease_token=lease_token,
        )

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
        run_id: Optional[str] = Query(default=None, min_length=1, max_length=128),
        _auth: AuthContext = Depends(require_admin),
    ):
        return await quer().list_recovery_quarantine(limit=limit, run_id=run_id)

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

    @router.get("/workflows/ready-tasks", response_model=list[dict], tags=["maintenance"])
    async def ready_tasks(
        limit: int = 20, _auth: AuthContext = Depends(require_read),
    ):
        return await eng().ready_tasks(limit)

    @router.post("/workflows/tick", response_model=dict, tags=["maintenance"])
    async def tick(_auth: AuthContext = Depends(require_write)):
        return {"promoted": await eng().tick()}

    @router.post(
        "/admin/recover",
        response_model=ProblemDetail,
        status_code=409,
        tags=["maintenance"],
        responses={409: {
            "model": ProblemDetail,
            "description": "Manual recovery disabled until trusted worker fencing is available",
        }},
    )
    async def admin_recover(_auth: AuthContext = Depends(require_admin)):
        # There is no trustworthy quiescence/fencing protocol for standalone
        # native workers yet. A live recover call could mark a still-executing
        # attempt interrupted and free its worker identity before side effects
        # finish. Even an empty DB scan races new claims. Fail closed until a
        # durable fencing barrier is deployed; startup recovery remains
        # separate and quarantines interrupted identities as inactive.
        raise ConflictError(
            "Live recovery disabled: worker quiescence and fencing are not verified"
        )

    # Canonical /api/v1 contract (ADR-101) plus unprefixed aliases so existing
    # clients/tests keep working unchanged.
    app.include_router(router)
    if settings.api_prefix:
        app.include_router(router, prefix=settings.api_prefix)

    return app