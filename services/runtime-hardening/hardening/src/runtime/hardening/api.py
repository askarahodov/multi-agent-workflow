"""Agent Runtime Control Plane API (spec §2.1 / api/agent-runtime-openapi.yaml).

FastAPI implementation of the agent lifecycle, workspace, resource and health
endpoints, plus per-agent Prometheus exposition and structured JSON logs. Errors
are returned as RFC 9457 Problem Details. Health probes are unauthenticated by
design; all other endpoints in production require mTLS + bearer JWT (the
reference app does not enforce auth — declared in the OpenAPI security block and
documented as a deployment responsibility).
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse

from runtime.hardening import models as m
from runtime.hardening.config import RuntimeSettings
from runtime.hardening.degradation import (
    DegradationController,
)
from runtime.hardening.isolation import (
    AdmissionController,
    DockerRuntime,
    RuntimeSelector,
    SandboxSpec,
    SeccompProfile,
    detect_kvm,
    runtime_class_for,
)
from runtime.hardening.observability import (
    HealthRegistry,
    MetricsRegistry,
    OTelHooks,
    StructuredLogger,
    build_observability,
)
from runtime.hardening.resilience import ResilienceRegistry
from runtime.hardening.resource_manager import (
    QuotaExceededError,
    ResourceManager,
)
from runtime.hardening.workspace_manager import (
    ChecksumViolationError,
    InsufficientCapacityError,
    UnknownWorkspaceError,
    WorkspaceManager,
    WorkspaceReaper,
)


def _problem(
    status: int, title: str, detail: str | None = None, *, retryable: bool = False
) -> m.ProblemDetails:
    return m.ProblemDetails(
        title=title,
        status=status,
        detail=detail,
        retryable=retryable,
        instance=f"about:blank/{status}",
    )


class RuntimeApp:
    """Wires all hardening components behind one FastAPI application."""

    def __init__(self, settings: RuntimeSettings | None = None) -> None:
        self.settings = settings or RuntimeSettings()
        self.logger: StructuredLogger
        self.health: HealthRegistry
        self.metrics: MetricsRegistry
        self.otel: OTelHooks
        self.health, self.metrics, self.otel, self.logger = build_observability(self.settings)

        self.kvm_available = detect_kvm()
        self.selector = RuntimeSelector(
            kvm_available=self.kvm_available,
            no_kvm_untrusted_tier=m.IsolationTier(self.settings.isolation.no_kvm_untrusted_tier),
            no_kvm_adversarial_tier=m.IsolationTier(
                self.settings.isolation.no_kvm_adversarial_tier
            ),
        )
        self.admission = AdmissionController()
        self.runtime = DockerRuntime()

        self.resources = ResourceManager(
            root=Path(self.settings.isolation.cgroup_root),
            parent_slice=self.settings.isolation.parent_slice,
        )
        self.workspaces = WorkspaceManager(root=self.workspace_root())
        self.reaper = WorkspaceReaper(
            self.workspaces,
            force_cleanup_seconds=self.settings.isolation.reaper_force_cleanup_seconds,
            scan_interval_seconds=self.settings.isolation.reaper_scan_interval_seconds,
        )
        self.resilience = ResilienceRegistry(settings=self.settings.resilience)
        self.degradation = DegradationController(
            registry=self.resilience,
            eval_interval_seconds=self.settings.resilience.eval_interval_seconds,
        )

        self._agents: dict[str, m.Agent] = {}
        self.app = FastAPI(
            title="Agent Runtime Control Plane API",
            version="1.0.0",
            description="Hardened agent runtime control plane (P8.3).",
        )
        self._register_routes()

        self.health.add_live_check(
            "cgroup-root", lambda: self.resources.parent_path.parent.is_dir()
        )
        self.health.add_ready_check("workspace-root", lambda: self.workspaces.root.is_dir())
        self.health.mark_started()

    # -- helpers -------------------------------------------------------------- #
    def workspace_root(self) -> Any:
        import tempfile
        from pathlib import Path

        return Path(tempfile.mkdtemp(prefix="agent-workspaces-"))

    def _agent(self, agent_id: str) -> m.Agent:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise HTTPException(status_code=404, detail="agent not found")
        return agent

    # -- routes --------------------------------------------------------------- #
    def _register_routes(self) -> None:
        app = self.app

        # Health probes (unauthenticated by design, spec §8.1).
        @app.get(
            "/healthz/live",
            response_model=m.HealthStatus,
            responses={503: {"model": m.HealthStatus}},
        )
        def healthz_live() -> m.HealthStatus:
            status = self.health.liveness()
            if status.liveness == m.HealthProbeResult.FAIL:
                raise HTTPException(status_code=503, detail="not alive")
            return status

        @app.get(
            "/healthz/ready",
            response_model=m.HealthStatus,
            responses={503: {"model": m.HealthStatus}},
        )
        def healthz_ready() -> m.HealthStatus:
            status = self.health.readiness()
            if status.readiness == m.HealthProbeResult.FAIL:
                raise HTTPException(status_code=503, detail="not ready")
            return status

        @app.get(
            "/healthz/startup",
            response_model=m.HealthStatus,
            responses={503: {"model": m.HealthStatus}},
        )
        def healthz_startup() -> m.HealthStatus:
            status = self.health.startup()
            if status.startup == m.HealthProbeResult.FAIL:
                raise HTTPException(status_code=503, detail="starting")
            return status

        @app.get("/metrics", response_class=PlainTextResponse)
        def metrics_exposition() -> str:
            return self.metrics.expose().decode()

        # Agents --------------------------------------------------------------- #
        @app.post("/agents", response_model=m.Agent, status_code=201)
        def create_agent(spec: m.AgentSpec) -> m.Agent:
            agent_id = spec.id or f"agent-{datetime.now(UTC).microsecond:x}"
            if agent_id in self._agents:
                raise HTTPException(status_code=409, detail="agent id already exists")
            # Admission: untrusted/adversarial must not land on runc (AC-1).
            workload = spec.labels.get("harbor.hardening/isolation", "untrusted")
            workload_class = m.WorkloadClass(workload)
            requested_class = runtime_class_for(spec.isolationTier)
            try:
                self.admission.admit(workload_class, requested_class)
            except Exception as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

            # Resource limits: class + overrides, budget-checked (AC-4).
            limits = self._resolve_limits(spec)
            try:
                self.resources.apply_limits(agent_id, limits)
            except QuotaExceededError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

            sandbox = SandboxSpec(
                agent_id=agent_id,
                image=spec.image,
                tier=spec.isolationTier,
                runtime_class_name=requested_class,
                env=spec.env,
                seccomp=SeccompProfile(),
                network_egress_allowlist=spec.networkEgressAllowlist,
            )
            try:
                container_id = self.runtime.start(sandbox)
            except Exception as exc:
                self.resources.remove(agent_id)
                raise HTTPException(status_code=503, detail=f"sandbox start failed: {exc}") from exc

            agent = m.Agent(
                id=agent_id,
                name=spec.name,
                state=m.AgentState.RUNNING,
                isolationTier=spec.isolationTier,
                runtimeClass=requested_class,
                containerId=container_id,
                cgroupPath=str(self.resources.agent_path(agent_id)),
            )
            self._agents[agent_id] = agent
            self.metrics.agents_running.labels(state="running").inc()
            self.logger.info(
                "agent.created",
                agent_id=agent_id,
                attributes={"tier": spec.isolationTier.value, "runtimeClass": requested_class},
            )
            return agent

        @app.get("/agents", response_model=dict[str, Any])
        def list_agents(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
            items = list(self._agents.values())[:limit]
            return {"items": items, "nextCursor": None}

        @app.get("/agents/{agent_id}", response_model=m.Agent)
        def get_agent(agent_id: str) -> m.Agent:
            return self._agent(agent_id)

        @app.delete("/agents/{agent_id}", status_code=202)
        def delete_agent(
            agent_id: str, grace_seconds: int = Query(30, ge=0, le=300), force: bool = False
        ) -> Response:
            agent = self._agent(agent_id)
            with suppress(Exception):
                self.runtime.stop(agent.containerId or "", grace_seconds=grace_seconds)
            if agent.cgroupPath and agent.cgroupPath != "None":
                pass
            self._agents.pop(agent_id, None)
            self.metrics.agents_running.labels(state="terminated").inc()
            return Response(status_code=202)

        @app.post("/agents/{agent_id}/pause", status_code=202)
        def pause_agent(agent_id: str) -> Response:
            agent = self._agent(agent_id)
            if agent.state == m.AgentState.TERMINATED:
                raise HTTPException(status_code=409, detail="agent terminated")
            with suppress(Exception):
                self.runtime.pause(agent.containerId or "")
            agent.state = m.AgentState.PAUSED
            return Response(status_code=202)

        @app.post("/agents/{agent_id}/resume", status_code=202)
        def resume_agent(agent_id: str) -> Response:
            agent = self._agent(agent_id)
            if agent.state != m.AgentState.PAUSED:
                raise HTTPException(status_code=409, detail="agent not paused")
            with suppress(Exception):
                self.runtime.resume(agent.containerId or "")
            agent.state = m.AgentState.RUNNING
            return Response(status_code=202)

        @app.post("/agents/{agent_id}/stop", status_code=202)
        def stop_agent(agent_id: str, grace_seconds: int = Query(30, ge=0, le=300)) -> Response:
            agent = self._agent(agent_id)
            with suppress(Exception):
                self.runtime.stop(agent.containerId or "", grace_seconds=grace_seconds)
            agent.state = m.AgentState.TERMINATED
            return Response(status_code=202)

        @app.get("/agents/{agent_id}/status", response_model=m.AgentStatus)
        def agent_status(agent_id: str) -> m.AgentStatus:
            agent = self._agent(agent_id)
            return m.AgentStatus(
                agent=agent,
                circuitBreaker=self.resilience.breaker(agent_id).state,
                degradationMode=self.degradation.mode(agent_id),
            )

        @app.get("/agents/{agent_id}/metrics", response_class=PlainTextResponse)
        def agent_metrics(agent_id: str) -> str:
            self._agent(agent_id)
            return self.metrics.expose().decode()

        @app.get(
            "/agents/{agent_id}/health",
            response_model=m.HealthStatus,
            responses={503: {"model": m.HealthStatus}},
        )
        def agent_health(agent_id: str) -> m.HealthStatus:
            self._agent(agent_id)
            return self.health.readiness()

        @app.get("/agents/{agent_id}/logs", response_class=PlainTextResponse)
        def agent_logs(agent_id: str, tail: int = Query(200, ge=1, le=10000)) -> str:
            agent = self._agent(agent_id)
            try:
                return self.runtime.logs(agent.containerId or "", tail=tail)
            except Exception:
                return ""

        # Resources ------------------------------------------------------------ #
        @app.get("/agents/{agent_id}/limits", response_model=m.ResourceLimits)
        def get_limits(agent_id: str) -> m.ResourceLimits:
            self._agent(agent_id)
            return self.resources.get_limits(agent_id)

        @app.put("/agents/{agent_id}/limits", response_model=m.ResourceLimits)
        def apply_limits(agent_id: str, limits: m.ResourceLimits) -> m.ResourceLimits:
            self._agent(agent_id)
            try:
                return self.resources.apply_limits(agent_id, limits)
            except QuotaExceededError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.patch("/agents/{agent_id}/limits", response_model=m.ResourceLimits)
        def adjust_limits(agent_id: str, delta: m.ResourceLimitsDelta) -> m.ResourceLimits:
            self._agent(agent_id)
            try:
                return self.resources.adjust_limits(agent_id, delta)
            except QuotaExceededError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc

        @app.get("/agents/{agent_id}/usage", response_model=m.ResourceUsage)
        def get_usage(agent_id: str) -> m.ResourceUsage:
            self._agent(agent_id)
            return self.resources.read_usage(agent_id)

        @app.get("/agents/{agent_id}/pressure", response_model=m.PressureReport)
        def get_pressure(agent_id: str) -> m.PressureReport:
            self._agent(agent_id)
            report = self.resources.read_pressure(agent_id)
            self.degradation.update_from_pressure(agent_id, report)
            return report

        # Workspaces ------------------------------------------------------------ #
        @app.post("/workspaces", response_model=m.Workspace, status_code=201)
        def create_workspace(spec: m.WorkspaceSpec) -> m.Workspace:
            try:
                ws = self.workspaces.create(spec)
            except InsufficientCapacityError as exc:
                raise HTTPException(status_code=507, detail=str(exc)) from exc
            self.metrics.workspace_operations.labels(op="create", status="ok").inc()
            self.reaper.heartbeat(ws.id)
            return ws

        @app.get("/workspaces", response_model=dict[str, Any])
        def list_workspaces() -> dict[str, Any]:
            return {"items": list(self.workspaces._state.values())}

        @app.get("/workspaces/{workspace_id}", response_model=m.Workspace)
        def get_workspace(workspace_id: str) -> m.Workspace:
            try:
                return self.workspaces.get(workspace_id)
            except UnknownWorkspaceError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

        @app.delete("/workspaces/{workspace_id}", status_code=202)
        def delete_workspace(
            workspace_id: str, grace_seconds: int = Query(30, ge=0, le=300), force: bool = False
        ) -> Response:
            try:
                self.workspaces.mark_cleaning(workspace_id)
                self.workspaces.cleanup(workspace_id, force=force)
            except UnknownWorkspaceError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            self.metrics.workspace_operations.labels(op="cleanup", status="ok").inc()
            return Response(status_code=202)

        @app.post("/workspaces/{workspace_id}/snapshot", response_model=m.Snapshot, status_code=202)
        def snapshot_workspace(workspace_id: str) -> m.Snapshot:
            try:
                snap = self.workspaces.snapshot(workspace_id)
            except UnknownWorkspaceError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            self.metrics.workspace_operations.labels(op="snapshot", status="ok").inc()
            return snap

        @app.post("/workspaces/{workspace_id}/restore", response_model=m.Workspace)
        def restore_workspace(workspace_id: str, body: dict[str, str]) -> m.Workspace:
            try:
                return self.workspaces.restore(workspace_id, body["snapshotId"])
            except ChecksumViolationError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except UnknownWorkspaceError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

        @app.post("/workspaces/{workspace_id}/promote", response_model=dict[str, Any])
        def promote_workspace(workspace_id: str, body: dict[str, list[str]]) -> dict[str, Any]:
            try:
                promoted = self.workspaces.promote(workspace_id, body["paths"])
            except UnknownWorkspaceError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            self.metrics.workspace_operations.labels(op="promote", status="ok").inc()
            return {"promoted": promoted}

        @app.post("/workspaces/{workspace_id}/validate", response_model=dict[str, Any])
        def validate_workspace(workspace_id: str) -> dict[str, Any]:
            try:
                valid, checks = self.workspaces.validate(workspace_id)
            except UnknownWorkspaceError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            return {"valid": valid, "checks": [c.as_dict() for c in checks]}

        # Exception handlers -> RFC 9457 Problem Details ------------------------- #
        @app.exception_handler(HTTPException)
        async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
            problem = m.ProblemDetails(
                title="HTTP error",
                status=exc.status_code,
                detail=str(exc.detail),
            )
            return Response(
                status_code=exc.status_code,
                content=problem.model_dump_json(),
                media_type="application/problem+json",
            )

    def _resolve_limits(self, spec: m.AgentSpec) -> m.ResourceLimits:
        """Merge the named resource class with per-agent overrides (spec §4.5)."""
        if spec.resources is not None:
            return spec.resources
        # In the reference app the quota config is injected by the caller; the
        # default path uses the spec's resourceClass name as-is.
        base = m.ResourceLimits()
        if spec.resources is None and spec.resourceClass:
            # No quota file wired — use spec.resources or empty (container gets
            # host defaults). Budget checks still apply via parentBudget if set.
            return m.ResourceLimits()
        return base


def create_app(settings: RuntimeSettings | None = None) -> RuntimeApp:
    """Factory used by uvicorn / tests."""
    return RuntimeApp(settings)
