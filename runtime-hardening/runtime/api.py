"""Agent Runtime control-plane API (OpenAPI / AsyncAPI).

Wires the container runtime, resource manager, workspace manager and resilience
layer into a FastAPI application exposing the endpoints defined in
``agent-runtime-openapi.yaml``. The :class:`RuntimeService` holds the in-memory
registry of agents and is independent of the HTTP layer, so it can be unit
tested directly.
"""

from __future__ import annotations

import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse

from shared.auth_middleware import (
    AuthContext,
    AuthMiddleware,
    require_admin,
    require_read,
    require_write,
)

from shared.security_middleware import add_security_middleware
from runtime.circuit_breaker import (
    BulkheadFull,
    CircuitOpen,
    ResilienceRegistry,
)
from runtime.config import RuntimeSettings, load_quota_config
from runtime.container_runtime import (
    ContainerRuntime,
    ContainerRuntimeError,
    IsolationBackend,
    RootlessConfig,
    SeccompProfileGenerator,
    build_runtime,
    kvm_available,
    select_isolation_backend,
)
from runtime.health import ControlPlaneHealth, HealthChecker, Probes
from runtime.metrics import MetricsCollector, OTelHooks, set_correlation_id
from runtime.models import (
    Agent,
    AgentSpec,
    AgentState,
    AgentStatus,
    HealthStatus,
    PressureReport,
    ProblemDetails,
    ResourceLimits,
    ResourceLimitsDelta,
    ResourceUsage,
    Snapshot,
    Workspace,
    WorkspaceSpec,
)
from runtime.resource_manager import (
    QuotaExceededError,
    ResourceManager,
    UnknownAgentError,
)
from runtime.workspace_manager import (
    ChecksumMismatch,
    WorkspaceError,
    WorkspaceManager,
    WorkspaceNotFound,
)


class AgentConflict(RuntimeError):
    """Raised when creating an agent whose id already exists."""


class AgentNotFound(RuntimeError):
    """Raised for unknown agent ids."""


class InvalidTransition(RuntimeError):
    """Raised for illegal agent state transitions."""


_ALLOWED_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.CREATED: {AgentState.RUNNING, AgentState.FAILED, AgentState.TERMINATED},
    AgentState.RUNNING: {
        AgentState.PAUSED,
        AgentState.DEGRADED,
        AgentState.FAILED,
        AgentState.TERMINATED,
    },
    AgentState.PAUSED: {AgentState.RUNNING, AgentState.TERMINATED},
    AgentState.DEGRADED: {
        AgentState.RUNNING,
        AgentState.PAUSED,
        AgentState.TERMINATED,
        AgentState.FAILED,
    },
    AgentState.FAILED: {AgentState.TERMINATED, AgentState.RUNNING},
    AgentState.TERMINATED: set(),
}


def _limits_from_quota(
    quota_config: Any, resource_class: str, overrides: ResourceLimits | None
) -> ResourceLimits:
    """Resolve a resource class (+optional overrides) into concrete limits."""
    if quota_config is None:
        return overrides or ResourceLimits()
    limits: ResourceLimits = quota_config.resourceClasses.get(resource_class)
    if limits is None:
        limits = quota_config.resourceClasses.get("default") or next(
            iter(quota_config.resourceClasses.values())
        )
    if overrides is not None:
        merged = limits.model_dump(exclude_none=True)
        for key, value in overrides.model_dump(exclude_none=True).items():
            merged.setdefault(key, {}).update(value)
        return ResourceLimits.model_validate(merged)
    return limits


def _limit_flags(limits: ResourceLimits) -> list[str]:
    """Translate cgroup limits into container-engine CLI flags."""
    flags: list[str] = []
    if limits.cpu and limits.cpu.quotaMicros not in (None, -1):
        cpus = limits.cpu.quotaMicros / limits.cpu.periodMicros
        flags += ["--cpus", f"{cpus:.4f}"]
        flags += ["--cpu-shares", str(limits.cpu.weight)]
    if limits.memory:
        if limits.memory.maxBytes is not None:
            flags += ["--memory", str(limits.memory.maxBytes)]
        if limits.memory.highBytes is not None:
            flags += ["--memory-reservation", str(limits.memory.highBytes)]
        flags += ["--memory-swap", str(limits.memory.maxBytes or 0)]
    if limits.pids and limits.pids.max is not None:
        flags += ["--pids-limit", str(limits.pids.max)]
    return flags


@dataclass
class RuntimeService:
    """Stateful orchestration of agents, workspaces and resources."""

    settings: RuntimeSettings = field(default_factory=RuntimeSettings)
    quota_config: Any = None
    container_runtime: ContainerRuntime | None = None
    manage_containers: bool = False
    resource_manager: ResourceManager = field(init=False)
    workspace_manager: WorkspaceManager = field(init=False)
    resilience: ResilienceRegistry = field(default_factory=ResilienceRegistry)
    metrics: MetricsCollector = field(default_factory=MetricsCollector)
    otel: OTelHooks = field(default_factory=OTelHooks)
    control_plane_health: ControlPlaneHealth = field(default_factory=ControlPlaneHealth)
    _agents: dict[str, Agent] = field(default_factory=dict)
    _specs: dict[str, AgentSpec] = field(default_factory=dict)
    _health: dict[str, HealthChecker] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.resource_manager = ResourceManager(
            root=self.settings.cgroup_root,
            parent_slice=self.settings.cgroup_parent_slice,
            parent_budget=self.quota_config.parentBudget if self.quota_config else None,
        )
        self.workspace_manager = WorkspaceManager(
            root=self.settings.workspace_root,
            durable_root=self.settings.durable_root,
            snapshots_root=self.settings.snapshots_root,
            grace_seconds=self.settings.cleanup_grace_seconds,
            checksum_algorithm=self.settings.snapshot_checksum_algorithm,
        )
        if self.container_runtime is None:
            self.container_runtime = build_runtime(self.settings.container_runtime)

    # -- helpers -------------------------------------------------------------- #
    def _backend_for(self, spec: AgentSpec) -> IsolationBackend:
        return select_isolation_backend(spec.isolationTier, kvm_available=kvm_available())

    def _resolve_limits(self, spec: AgentSpec) -> ResourceLimits:
        return _limits_from_quota(self.quota_config, spec.resourceClass, spec.resources)

    def _record_state(self, agent: Agent) -> None:
        self.metrics.record_agent_state(agent.state.value)
        self.metrics.set_degradation_mode(agent.id, agent.degradationMode.value)

    # -- agents --------------------------------------------------------------- #
    def create_agent(self, spec: AgentSpec) -> Agent:
        agent_id = spec.id or f"agent-{abs(hash(spec.name)) % 10**8:08d}"
        if agent_id in self._agents:
            raise AgentConflict(agent_id)

        backend = self._backend_for(spec)
        limits = self._resolve_limits(spec)

        if spec.workspace is not None:
            ws_spec = spec.workspace.model_copy(update={"id": agent_id})
            self.workspace_manager.create(ws_spec, agent_id)
            self.metrics.record_workspace_op("create", "success")

        cgroup_path: str | None = None
        container_id: str | None = None
        try:
            self.resource_manager.apply_limits(agent_id, limits)
            cgroup_path = str(self.resource_manager.agent_path(agent_id))
            if self.manage_containers and self.container_runtime is not None:
                container_id = self._start_container(spec, agent_id, backend, limits)
        except Exception:
            # Atomic rollback: release everything allocated so far.
            self._rollback(agent_id)
            raise

        agent = Agent(
            id=agent_id,
            name=spec.name,
            state=AgentState.RUNNING,
            isolationTier=spec.isolationTier,
            runtimeClass=backend.runtime_class,
            containerId=container_id,
            cgroupPath=cgroup_path,
        )
        self._agents[agent_id] = agent
        self._specs[agent_id] = spec
        self._health[agent_id] = HealthChecker(
            subject=agent_id,
            probes=Probes(
                liveness=lambda: agent.state != AgentState.TERMINATED,
                readiness=lambda: agent.state in (AgentState.RUNNING, AgentState.DEGRADED),
                startup=lambda: True,
            ),
        )
        self._record_state(agent)
        self.metrics.set_circuit_breaker_state(agent_id, "closed")
        return agent

    def _start_container(
        self,
        spec: AgentSpec,
        agent_id: str,
        backend: IsolationBackend,
        limits: ResourceLimits,
    ) -> str:
        assert self.container_runtime is not None
        seccomp: str | Path = self.settings.default_seccomp_profile
        if spec.seccompProfile not in ("RuntimeDefault", "unconfined"):
            profile = SeccompProfileGenerator().write(
                self.settings.workspace_root / agent_id / "seccomp.json"
            )
            seccomp = profile
        args = self.container_runtime.create_args(
            image=spec.image,
            name=f"agent-{agent_id}",
            backend=backend,
            rootless=RootlessConfig(enabled=self.settings.rootless),
            seccomp_profile=seccomp,
            limits=_limit_flags(limits),
            env=spec.env,
            network_egress_allowlist=spec.networkEgressAllowlist,
        )
        started = time.monotonic()
        info = self.container_runtime.create(args)
        self.metrics.observe_startup(backend.runtime_class, time.monotonic() - started)
        return info.container_id

    def get_agent(self, agent_id: str) -> Agent:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise AgentNotFound(agent_id)
        return agent

    def list_agents(
        self, state: AgentState | None = None, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[Agent], str | None]:
        agents = sorted(self._agents.values(), key=lambda a: a.createdAt)
        if state is not None:
            agents = [a for a in agents if a.state == state]
        start = 0
        if cursor is not None:
            for index, agent in enumerate(agents):
                if agent.id == cursor:
                    start = index + 1
                    break
        page = agents[start : start + limit]
        next_cursor = page[-1].id if len(page) == limit and start + limit < len(agents) else None
        return page, next_cursor

    def _transition(self, agent: Agent, target: AgentState) -> Agent:
        if target not in _ALLOWED_TRANSITIONS[agent.state]:
            raise InvalidTransition(f"{agent.state.value} -> {target.value}")
        agent.state = target
        from runtime.models import utcnow

        agent.updatedAt = utcnow()
        self._record_state(agent)
        return agent

    def pause_agent(self, agent_id: str) -> Agent:
        agent = self.get_agent(agent_id)
        runtime = self.container_runtime
        if (
            agent.state != AgentState.PAUSED
            and agent.containerId
            and runtime is not None
            and runtime.available()
        ):
            runtime.pause(agent.containerId)
        return self._transition(agent, AgentState.PAUSED)

    def resume_agent(self, agent_id: str) -> Agent:
        agent = self.get_agent(agent_id)
        runtime = self.container_runtime
        if (
            agent.state == AgentState.PAUSED
            and agent.containerId
            and runtime is not None
            and runtime.available()
        ):
            runtime.resume(agent.containerId)
        return self._transition(agent, AgentState.RUNNING)

    def stop_agent(self, agent_id: str, grace_seconds: int = 30) -> Agent:
        agent = self.get_agent(agent_id)
        if agent.containerId and self.container_runtime and self.container_runtime.available():
            self.container_runtime.stop(agent.containerId, grace_seconds)
        return self._transition(agent, AgentState.TERMINATED)

    def delete_agent(self, agent_id: str, grace_seconds: int = 30, force: bool = False) -> None:
        agent = self.get_agent(agent_id)
        if agent.containerId and self.container_runtime and self.container_runtime.available():
            self.container_runtime.remove(agent.containerId, force=force)
        if agent.state != AgentState.TERMINATED:
            try:
                self._transition(agent, AgentState.TERMINATED)
            except InvalidTransition:
                agent.state = AgentState.TERMINATED
        if self.workspace_manager.workspace_path(agent_id).exists():
            self.workspace_manager.cleanup(agent_id, grace_seconds, force=force)
        self._rollback(agent_id, cleanup_workspace=False)
        self._agents.pop(agent_id, None)
        self._specs.pop(agent_id, None)
        self._health.pop(agent_id, None)
        self.resilience.remove(agent_id)

    def _rollback(self, agent_id: str, *, cleanup_workspace: bool = True) -> None:
        with suppress(Exception):
            self.resource_manager.remove(agent_id)
        if cleanup_workspace and self.workspace_manager.workspace_path(agent_id).exists():
            self.workspace_manager.cleanup(agent_id, 0, force=True)

    # -- status / telemetry --------------------------------------------------- #
    def get_status(self, agent_id: str) -> AgentStatus:
        agent = self.get_agent(agent_id)
        usage = pressure = None
        if self.resource_manager.exists(agent_id):
            usage = self.resource_manager.read_usage(agent_id)
            pressure = self.resource_manager.read_pressure(agent_id)
        workspace = None
        if self.workspace_manager.workspace_path(agent_id).exists():
            try:
                workspace = self.workspace_manager.get(agent_id)
            except WorkspaceNotFound:
                workspace = None
        checker = self._health.get(agent_id)
        return AgentStatus(
            agent=agent,
            circuitBreaker=self.resilience.breaker(agent_id).state,
            degradationMode=self.resilience.ladder(agent_id).mode,
            health=checker.check() if checker else None,
            usage=usage,
            pressure=pressure,
            workspace=workspace,
        )

    def get_health(self, agent_id: str) -> HealthStatus:
        self.get_agent(agent_id)
        checker = self._health.get(agent_id)
        if checker is None:
            return HealthStatus()
        return checker.check()

    def get_logs(self, agent_id: str, tail: int = 200) -> str:
        agent = self.get_agent(agent_id)
        if agent.containerId and self.container_runtime and self.container_runtime.available():
            return self.container_runtime.logs(agent.containerId, tail)
        log_dir = self.workspace_manager.scratch_path(agent_id) / ".logs"
        if not log_dir.is_dir():
            return ""
        lines: list[str] = []
        for log_file in sorted(log_dir.glob("*")):
            lines.extend(log_file.read_text(encoding="utf-8").splitlines())
        return "\n".join(lines[-tail:])

    def get_limits(self, agent_id: str) -> ResourceLimits:
        self.get_agent(agent_id)
        return self.resource_manager.get_limits(agent_id)

    def apply_limits(self, agent_id: str, limits: ResourceLimits) -> ResourceLimits:
        self.get_agent(agent_id)
        return self.resource_manager.apply_limits(agent_id, limits)

    def adjust_limits(self, agent_id: str, delta: ResourceLimitsDelta) -> ResourceLimits:
        self.get_agent(agent_id)
        return self.resource_manager.adjust_limits(agent_id, delta)

    def get_usage(self, agent_id: str) -> ResourceUsage:
        self.get_agent(agent_id)
        return self.resource_manager.read_usage(agent_id)

    def get_pressure(self, agent_id: str) -> PressureReport:
        self.get_agent(agent_id)
        return self.resource_manager.read_pressure(agent_id)

    # -- workspaces ----------------------------------------------------------- #
    def create_workspace(self, spec: WorkspaceSpec) -> Workspace:
        ws = self.workspace_manager.create(spec)
        self.metrics.record_workspace_op("create", "success")
        return ws

    def list_workspaces(self) -> list[Workspace]:
        return self.workspace_manager.list_all()

    def get_workspace(self, ws_id: str) -> Workspace:
        return self.workspace_manager.get(ws_id)

    def delete_workspace(self, ws_id: str, grace_seconds: int = 30, force: bool = False) -> None:
        self.workspace_manager.cleanup(ws_id, grace_seconds, force=force)
        self.metrics.record_workspace_op("cleanup", "success")

    def snapshot_workspace(self, ws_id: str) -> Snapshot:
        snap = self.workspace_manager.snapshot(ws_id)
        self.metrics.record_workspace_op("snapshot", "success")
        return snap

    def restore_workspace(self, ws_id: str, snapshot_id: str) -> Workspace:
        ws = self.workspace_manager.restore(ws_id, snapshot_id)
        self.metrics.record_workspace_op("restore", "success")
        return ws

    def promote_workspace(self, ws_id: str, paths: list[str]) -> list[dict[str, str]]:
        promoted = self.workspace_manager.promote(ws_id, paths)
        self.metrics.record_workspace_op("promote", "success")
        return promoted

    def validate_workspace(self, ws_id: str) -> list[Any]:
        return self.workspace_manager.validate(ws_id)


# --------------------------------------------------------------------------- #
# FastAPI application
# --------------------------------------------------------------------------- #
def _problem(status: int, title: str, detail: str | None = None) -> JSONResponse:
    body = ProblemDetails(type="about:blank", title=title, status=status, detail=detail)
    return JSONResponse(status_code=status, content=body.model_dump(exclude_none=True))


def create_app(service: RuntimeService | None = None, **kwargs: Any) -> FastAPI:
    """Build the FastAPI control plane around a :class:`RuntimeService`."""
    svc = service or RuntimeService(**kwargs)
    app = FastAPI(title="Agent Runtime Control Plane", version="1.0.0")
    app.add_middleware(AuthMiddleware)
    # Add HSTS + HTTP->HTTPS redirect middleware when TLS is enabled (SEC-002)
    add_security_middleware(app, tls_enabled=svc.settings.tls_enabled)
    app.state.service = svc

    @app.exception_handler(AgentNotFound)
    async def _not_found(_: Any, exc: AgentNotFound) -> JSONResponse:
        return _problem(404, "Not Found", str(exc))

    @app.exception_handler(WorkspaceNotFound)
    async def _ws_not_found(_: Any, exc: WorkspaceNotFound) -> JSONResponse:
        return _problem(404, "Not Found", str(exc))

    @app.exception_handler(AgentConflict)
    async def _conflict(_: Any, exc: AgentConflict) -> JSONResponse:
        return _problem(409, "Conflict", str(exc))

    @app.exception_handler(InvalidTransition)
    async def _invalid(_: Any, exc: InvalidTransition) -> JSONResponse:
        return _problem(409, "Invalid state transition", str(exc))

    @app.exception_handler(QuotaExceededError)
    async def _quota(_: Any, exc: QuotaExceededError) -> JSONResponse:
        return _problem(409, "Quota exceeded", str(exc))

    @app.exception_handler(ChecksumMismatch)
    async def _checksum(_: Any, exc: ChecksumMismatch) -> JSONResponse:
        return _problem(422, "Checksum validation failed", str(exc))

    @app.exception_handler(CircuitOpen)
    async def _circuit(_: Any, exc: CircuitOpen) -> JSONResponse:
        return _problem(503, "Circuit open", str(exc))

    @app.exception_handler(BulkheadFull)
    async def _bulkhead(_: Any, exc: BulkheadFull) -> JSONResponse:
        return _problem(503, "Bulkhead full", str(exc))

    @app.exception_handler(ContainerRuntimeError)
    async def _runtime_error(_: Any, exc: ContainerRuntimeError) -> JSONResponse:
        return _problem(503, "Container runtime error", str(exc))

    @app.exception_handler(UnknownAgentError)
    async def _unknown_cgroup(_: Any, exc: UnknownAgentError) -> JSONResponse:
        return _problem(404, "Not Found", str(exc))

    @app.exception_handler(WorkspaceError)
    async def _workspace_error(_: Any, exc: WorkspaceError) -> JSONResponse:
        return _problem(400, "Workspace error", str(exc))

    # -- agents --------------------------------------------------------------- #
    @app.post("/agents", status_code=201, response_model=Agent)
    def create_agent(spec: AgentSpec, _auth: AuthContext = Depends(require_write)) -> Agent:
        return svc.create_agent(spec)

    @app.get("/agents")
    def list_agents(
        state: AgentState | None = None,
        limit: int = Query(default=50, ge=1, le=200),
        cursor: str | None = None,
        _auth: AuthContext = Depends(require_read),
    ) -> dict[str, Any]:
        items, next_cursor = svc.list_agents(state, limit, cursor)
        return {"items": items, "nextCursor": next_cursor}

    @app.get("/agents/{agent_id}", response_model=Agent)
    def get_agent(agent_id: str, _auth: AuthContext = Depends(require_read)) -> Agent:
        return svc.get_agent(agent_id)

    @app.delete("/agents/{agent_id}", status_code=202)
    def delete_agent(
        agent_id: str,
        graceSeconds: int = Query(default=30, ge=0, le=300),
        force: bool = False,
        _auth: AuthContext = Depends(require_admin),
    ) -> dict[str, str]:
        svc.delete_agent(agent_id, graceSeconds, force)
        return {"status": "terminated", "agentId": agent_id}

    @app.post("/agents/{agent_id}/pause", status_code=202)
    def pause_agent(agent_id: str, _auth: AuthContext = Depends(require_write)) -> dict[str, str]:
        return {"state": svc.pause_agent(agent_id).state.value}

    @app.post("/agents/{agent_id}/resume", status_code=202)
    def resume_agent(agent_id: str, _auth: AuthContext = Depends(require_write)) -> dict[str, str]:
        return {"state": svc.resume_agent(agent_id).state.value}

    @app.post("/agents/{agent_id}/stop", status_code=202)
    def stop_agent(
        agent_id: str,
        graceSeconds: int = Query(default=30, ge=0, le=300),
        _auth: AuthContext = Depends(require_write),
    ) -> dict[str, str]:
        return {"state": svc.stop_agent(agent_id, graceSeconds).state.value}

    @app.get("/agents/{agent_id}/status", response_model=AgentStatus)
    def get_agent_status(agent_id: str, _auth: AuthContext = Depends(require_read)) -> AgentStatus:
        return svc.get_status(agent_id)

    @app.get("/agents/{agent_id}/metrics")
    def get_agent_metrics(
        agent_id: str, _auth: AuthContext = Depends(require_read)
    ) -> PlainTextResponse:
        svc.get_agent(agent_id)
        return PlainTextResponse(svc.metrics.render(), media_type="text/plain")

    @app.get("/agents/{agent_id}/logs")
    def get_agent_logs(
        agent_id: str,
        tail: int = Query(default=200, ge=1, le=10000),
        since: str | None = None,
        _auth: AuthContext = Depends(require_read),
    ) -> PlainTextResponse:
        return PlainTextResponse(svc.get_logs(agent_id, tail), media_type="application/x-ndjson")

    @app.get("/agents/{agent_id}/health", response_model=HealthStatus)
    def get_agent_health(agent_id: str, _auth: AuthContext = Depends(require_read)) -> JSONResponse:
        status = svc.get_health(agent_id)
        code = 200 if status.readiness.value != "fail" else 503
        return JSONResponse(status_code=code, content=status.model_dump(mode="json"))

    # -- resources ------------------------------------------------------------ #
    @app.get("/agents/{agent_id}/limits", response_model=ResourceLimits)
    def get_limits(agent_id: str, _auth: AuthContext = Depends(require_read)) -> ResourceLimits:
        return svc.get_limits(agent_id)

    @app.put("/agents/{agent_id}/limits", response_model=ResourceLimits)
    def apply_limits(
        agent_id: str, limits: ResourceLimits, _auth: AuthContext = Depends(require_write)
    ) -> ResourceLimits:
        return svc.apply_limits(agent_id, limits)

    @app.patch("/agents/{agent_id}/limits", response_model=ResourceLimits)
    def adjust_limits(
        agent_id: str, delta: ResourceLimitsDelta, _auth: AuthContext = Depends(require_write)
    ) -> ResourceLimits:
        return svc.adjust_limits(agent_id, delta)

    @app.get("/agents/{agent_id}/usage", response_model=ResourceUsage)
    def get_usage(agent_id: str, _auth: AuthContext = Depends(require_read)) -> ResourceUsage:
        return svc.get_usage(agent_id)

    @app.get("/agents/{agent_id}/pressure", response_model=PressureReport)
    def get_pressure(agent_id: str, _auth: AuthContext = Depends(require_read)) -> PressureReport:
        return svc.get_pressure(agent_id)

    # -- workspaces ----------------------------------------------------------- #
    @app.post("/workspaces", status_code=201, response_model=Workspace)
    def create_workspace(spec: WorkspaceSpec, _auth: AuthContext = Depends(require_write)) -> Workspace:
        return svc.create_workspace(spec)

    @app.get("/workspaces")
    def list_workspaces(_auth: AuthContext = Depends(require_read)) -> dict[str, Any]:
        return {"items": svc.list_workspaces()}

    @app.get("/workspaces/{workspace_id}", response_model=Workspace)
    def get_workspace(workspace_id: str, _auth: AuthContext = Depends(require_read)) -> Workspace:
        return svc.get_workspace(workspace_id)

    @app.delete("/workspaces/{workspace_id}", status_code=202)
    def delete_workspace(
        workspace_id: str,
        graceSeconds: int = Query(default=30, ge=0, le=300),
        force: bool = False,
        _auth: AuthContext = Depends(require_admin),
    ) -> dict[str, str]:
        svc.delete_workspace(workspace_id, graceSeconds, force)
        return {"status": "cleaned", "workspaceId": workspace_id}

    @app.post("/workspaces/{workspace_id}/snapshot", status_code=202, response_model=Snapshot)
    def snapshot_workspace(
        workspace_id: str, _auth: AuthContext = Depends(require_write)
    ) -> Snapshot:
        return svc.snapshot_workspace(workspace_id)

    @app.post("/workspaces/{workspace_id}/restore", response_model=Workspace)
    def restore_workspace(
        workspace_id: str, body: dict[str, str], _auth: AuthContext = Depends(require_write)
    ) -> Workspace:
        snapshot_id = body.get("snapshotId")
        if not snapshot_id:
            raise HTTPException(status_code=422, detail="snapshotId is required")
        return svc.restore_workspace(workspace_id, snapshot_id)

    @app.post("/workspaces/{workspace_id}/promote")
    def promote_workspace(
        workspace_id: str, body: dict[str, list[str]], _auth: AuthContext = Depends(require_write)
    ) -> dict[str, Any]:
        paths = body.get("paths") or []
        return {"promoted": svc.promote_workspace(workspace_id, paths)}

    @app.post("/workspaces/{workspace_id}/validate")
    def validate_workspace(
        workspace_id: str, _auth: AuthContext = Depends(require_write)
    ) -> dict[str, Any]:
        checks = svc.validate_workspace(workspace_id)
        return {
            "valid": all(c.ok for c in checks),
            "checks": [c.model_dump() for c in checks],
        }

    # -- health / metrics ----------------------------------------------------- #
    @app.get("/healthz/live")
    def live(_auth: AuthContext = Depends(require_read)) -> JSONResponse:
        ok = svc.control_plane_health.liveness()
        return JSONResponse(
            status_code=200 if ok else 503, content={"status": "alive" if ok else "dead"}
        )

    @app.get("/healthz/ready")
    def ready(_auth: AuthContext = Depends(require_read)) -> JSONResponse:
        ok = svc.control_plane_health.readiness()
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"status": "ready" if ok else "not_ready"},
        )

    @app.get("/healthz/startup")
    def startup(_auth: AuthContext = Depends(require_read)) -> JSONResponse:
        ok = svc.control_plane_health.startup()
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"status": "started" if ok else "starting"},
        )

    @app.get("/metrics")
    def metrics(_auth: AuthContext = Depends(require_read)) -> PlainTextResponse:
        return PlainTextResponse(svc.metrics.render(), media_type="text/plain")

    # -- events (WebSocket) --------------------------------------------------- #
    @app.websocket("/agents/{agent_id}/events")
    async def agent_events(websocket: WebSocket, agent_id: str) -> None:
        await websocket.accept()
        try:
            agent = svc.get_agent(agent_id)
        except AgentNotFound:
            await websocket.send_json({"type": "error", "detail": "agent not found"})
            await websocket.close(code=1008)
            return
        await websocket.send_json(
            {
                "type": "state",
                "agentId": agent.id,
                "state": agent.state.value,
                "degradationMode": agent.degradationMode.value,
            }
        )
        try:
            while True:
                message = await websocket.receive_text()
                if message == "ping":
                    await websocket.send_json({"type": "pong"})
        except WebSocketDisconnect:
            return

    return app


def _build_default_service() -> RuntimeService:
    """Build a service from the environment, loading the quota config if present."""
    settings = RuntimeSettings()
    quota = None
    quota_path = getattr(settings, "quota_config_path", None)
    if quota_path:
        quota = load_quota_config(quota_path)
    return RuntimeService(settings=settings, quota_config=quota)


def app_factory() -> FastAPI:  # pragma: no cover - ASGI entrypoint
    """Uvicorn entrypoint: ``uvicorn runtime.api:app_factory --factory``."""
    set_correlation_id("boot")
    return create_app(_build_default_service())
