"""FastAPI application exposing the platform-owned orchestration REST API.

Every mutation flows through :class:`orchestration_server.engine.OrchestrationEngine`,
which owns the state machine and contract verification. Error responses are RFC
9457 Problem Details documents (see :class:`ProblemDetail`).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from . import __version__
from .config import Settings, get_settings
from .db import build_engine, build_session_factory, create_all
from .engine import OrchestrationEngine
from .errors import OrchestrationError
from .queries import OrchestrationQueries
from .schemas import (
    AgentRegister,
    AgentResponse,
    ApiStatus,
    AttemptResponse,
    BlockRequest,
    ClaimRequest,
    ContractCreate,
    ContractResponse,
    FailRequest,
    ProblemDetail,
    ProjectCreate,
    ProjectResponse,
    RunCreate,
    RunResponse,
    SubmitRequest,
    TaskResponse,
    WorkspaceCreate,
    WorkspaceResponse,
)

# Documented error responses, shared by the route decorators so the generated
# OpenAPI contract matches the runtime Problem Details behaviour.
ERROR_RESPONSES = {
    400: {"model": ProblemDetail, "description": "Validation error"},
    404: {"model": ProblemDetail, "description": "Resource not found"},
    409: {"model": ProblemDetail, "description": "Conflict (duplicate or concurrent update)"},
    422: {"model": ProblemDetail, "description": "Business rule violation"},
}


def build_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    state: dict = {}

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

    @app.get("/health", response_model=ApiStatus, tags=["meta"])
    async def health():
        return ApiStatus(status="ok")

    # ---------- projects / workspaces ----------
    @app.post(
        "/projects",
        response_model=ProjectResponse,
        status_code=201,
        tags=["projects"],
        responses=ERROR_RESPONSES,
    )
    async def create_project(body: ProjectCreate):
        return await eng().create_project(body.name, body.description, body.settings)

    @app.get("/projects", response_model=List[ProjectResponse], tags=["projects"])
    async def list_projects():
        return await quer().list_projects()

    @app.post(
        "/workspaces",
        response_model=WorkspaceResponse,
        status_code=201,
        tags=["workspaces"],
        responses=ERROR_RESPONSES,
    )
    async def create_workspace(body: WorkspaceCreate):
        return await eng().create_workspace(
            body.project_id, body.name, body.path, body.settings
        )

    @app.get(
        "/workspaces", response_model=List[WorkspaceResponse], tags=["workspaces"]
    )
    async def list_workspaces(project_id: Optional[str] = Query(default=None)):
        return await quer().list_workspaces(project_id)

    # ---------- contracts ----------
    @app.post(
        "/contracts",
        response_model=ContractResponse,
        status_code=201,
        tags=["contracts"],
        responses=ERROR_RESPONSES,
    )
    async def create_contract(body: ContractCreate):
        return await eng().create_contract(
            body.name, body.schema_, body.project_id, body.description
        )

    @app.get("/contracts", response_model=List[ContractResponse], tags=["contracts"])
    async def list_contracts():
        return await quer().list_contracts()

    # ---------- agents ----------
    @app.post(
        "/agents/register",
        response_model=AgentResponse,
        status_code=201,
        tags=["agents"],
        responses=ERROR_RESPONSES,
    )
    async def register_agent(body: AgentRegister):
        return await eng().register_agent(body.name, body.metadata)

    @app.get("/agents", response_model=List[AgentResponse], tags=["agents"])
    async def list_agents():
        return await quer().list_agents()

    # ---------- workflow runs ----------
    @app.post(
        "/workflows/runs",
        response_model=RunResponse,
        status_code=201,
        tags=["runs"],
        responses=ERROR_RESPONSES,
    )
    async def launch_run(body: RunCreate):
        return await eng().launch_run(
            body.project_id,
            body.name,
            [t.model_dump() for t in body.tasks],
            body.workspace_id,
            body.triggered_by,
            body.input_data,
            body.retry_policy,
        )

    @app.get("/workflows/runs", response_model=List[RunResponse], tags=["runs"])
    async def list_runs(
        project_id: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None),
    ):
        return await quer().list_runs(project_id, status)

    @app.get(
        "/workflows/runs/{run_id}",
        response_model=RunResponse,
        tags=["runs"],
        responses=ERROR_RESPONSES,
    )
    async def get_run(run_id: str):
        return await quer().get_run(run_id)

    @app.get(
        "/workflows/runs/{run_id}/tasks",
        response_model=List[TaskResponse],
        tags=["runs"],
    )
    async def list_tasks(run_id: str):
        return await quer().list_tasks(run_id)

    # ---------- tasks / attempts ----------
    @app.get(
        "/tasks/{task_id}",
        response_model=TaskResponse,
        tags=["tasks"],
        responses=ERROR_RESPONSES,
    )
    async def get_task(task_id: str):
        return await quer().get_task(task_id)

    @app.get(
        "/tasks/{task_id}/attempts",
        response_model=List[AttemptResponse],
        tags=["tasks"],
    )
    async def list_attempts(task_id: str):
        return await quer().list_attempts(task_id)

    @app.post(
        "/tasks/{task_id}/claim",
        response_model=AttemptResponse,
        status_code=201,
        tags=["tasks"],
        responses=ERROR_RESPONSES,
    )
    async def claim_task(task_id: str, body: ClaimRequest):
        return await eng().claim_task(task_id, body.agent_id)

    @app.post(
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
    ):
        if agent_id is None:
            raise HTTPException(status_code=400, detail="agent_id query parameter is required")
        return await eng().submit(task_id, attempt_id, agent_id, body.output)

    @app.post(
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
    ):
        if agent_id is None:
            raise HTTPException(status_code=400, detail="agent_id query parameter is required")
        return await eng().fail_attempt(task_id, attempt_id, agent_id, body.error)

    @app.post(
        "/tasks/{task_id}/block",
        response_model=TaskResponse,
        tags=["tasks"],
        responses=ERROR_RESPONSES,
    )
    async def block_task(
        task_id: str,
        body: BlockRequest,
        agent_id: Optional[str] = Query(default=None),
    ):
        if agent_id is None:
            raise HTTPException(status_code=400, detail="agent_id query parameter is required")
        return await eng().block_task(task_id, agent_id, body.reason)

    # ---------- maintenance ----------
    @app.post("/workflows/tick", response_model=dict, tags=["maintenance"])
    async def tick():
        return {"promoted": await eng().tick()}

    @app.post("/admin/recover", response_model=ApiStatus, tags=["maintenance"])
    async def admin_recover():
        result = await eng().recover()
        return ApiStatus(status="recovered", **result)

    return app
