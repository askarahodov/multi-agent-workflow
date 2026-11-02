"""Metrics, tracing and structured logging (ADR-005).

* :class:`MetricsCollector` — Prometheus exposition of the metric set defined in
  ADR-005 (agent state, degradation mode, circuit-breaker state, resource usage,
  PSI pressure, workspace operations, container startup/OOM).
* :class:`OTelHooks` — OpenTelemetry instrumentation hooks; no-ops when the SDK
  is not installed so the runtime keeps working without it.
* :class:`JsonFormatter` — structured JSON log records correlated by ID.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

_otel_trace: Any = None
try:  # pragma: no cover - depends on optional extra
    import opentelemetry.trace as _otel_mod

    _otel_trace = _otel_mod
    _HAS_OTEL = True
except Exception:  # noqa: BLE001
    _HAS_OTEL = False


# --------------------------------------------------------------------------- #
# Correlation IDs / structured logging
# --------------------------------------------------------------------------- #
CORRELATION_ID: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def new_correlation_id() -> str:
    """Return a fresh correlation id."""
    return uuid.uuid4().hex


def set_correlation_id(value: str) -> None:
    CORRELATION_ID.set(value)


def get_correlation_id() -> str | None:
    return CORRELATION_ID.get()


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON with a correlation id."""

    def __init__(self, service: str = "agent-runtime") -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service,
        }
        correlation_id = get_correlation_id()
        if correlation_id:
            payload["correlationId"] = correlation_id
        for key in ("agentId", "workspaceId", "event"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", service: str = "agent-runtime") -> logging.Logger:
    """Configure the root logger with the JSON formatter and return the logger."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service=service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    return logging.getLogger(service)


# --------------------------------------------------------------------------- #
# OpenTelemetry hooks
# --------------------------------------------------------------------------- #
@dataclass
class OTelHooks:
    """Optional OpenTelemetry span helpers; transparent no-ops when unavailable."""

    enabled: bool = field(default_factory=lambda: _HAS_OTEL)
    tracer_name: str = "agent-runtime"

    @property
    def available(self) -> bool:
        return self.enabled and _HAS_OTEL

    @contextmanager
    def span(self, name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any | None]:
        if not self.available:
            yield None
            return
        tracer = _otel_trace.get_tracer(self.tracer_name)
        with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
            yield span


# --------------------------------------------------------------------------- #
# Prometheus metrics
# --------------------------------------------------------------------------- #
@dataclass
class MetricsCollector:
    """Prometheus metric registry mirroring ADR-005 instrumentation points."""

    service: str = "agent-runtime"
    registry: CollectorRegistry = field(default_factory=CollectorRegistry)

    def __post_init__(self) -> None:
        r = self.registry
        self.agents_total = Counter(
            "agent_runtime_agents_total", "Agent lifecycle transitions", ["state"], registry=r
        )
        self.resource_usage = Gauge(
            "agent_runtime_resource_usage",
            "Current resource usage per agent",
            ["agent_id", "resource"],
            registry=r,
        )
        self.degradation_mode = Gauge(
            "agent_runtime_degradation_mode",
            "Agent degradation mode (1 = active)",
            ["agent_id", "mode"],
            registry=r,
        )
        self.circuit_breaker_state = Gauge(
            "agent_runtime_circuit_breaker_state",
            "Agent circuit-breaker state (1 = active)",
            ["agent_id", "state"],
            registry=r,
        )
        self.workspace_operations_total = Counter(
            "agent_runtime_workspace_operations_total",
            "Workspace lifecycle operations",
            ["op", "status"],
            registry=r,
        )
        self.memory_events_total = Counter(
            "cgroup_memory_events_total",
            "cgroup v2 memory.events counter",
            ["agent_id", "event"],
            registry=r,
        )
        self.pressure_seconds = Gauge(
            "cgroup_pressure_seconds_total",
            "PSI stall time (seconds) by resource",
            ["agent_id", "resource"],
            registry=r,
        )
        self.limit_adjustments_total = Counter(
            "resource_limit_adjustments_total",
            "Resource limit adjustments",
            ["resource", "direction"],
            registry=r,
        )
        self.container_startup_duration = Histogram(
            "container_startup_duration_seconds",
            "Container startup duration",
            ["runtime"],
            registry=r,
        )
        self.container_oom_kills_total = Counter(
            "container_oom_kills_total",
            "Container OOM kills",
            ["runtime", "agent_id"],
            registry=r,
        )
        self.retry_budget_ratio = Gauge(
            "agent_runtime_retry_budget_ratio",
            "Remaining retry budget ratio",
            ["agent_id"],
            registry=r,
        )

    # -- recording helpers ---------------------------------------------------- #
    def record_agent_state(self, state: str) -> None:
        self.agents_total.labels(state=state).inc()

    def set_resource_usage(self, agent_id: str, resource: str, value: float) -> None:
        self.resource_usage.labels(agent_id=agent_id, resource=resource).set(value)

    def set_degradation_mode(self, agent_id: str, mode: str) -> None:
        for candidate in ("full", "throttled", "read_only", "paused", "terminated"):
            self.degradation_mode.labels(agent_id=agent_id, mode=candidate).set(
                1 if candidate == mode else 0
            )

    def set_circuit_breaker_state(self, agent_id: str, state: str) -> None:
        for candidate in ("closed", "open", "half_open"):
            self.circuit_breaker_state.labels(agent_id=agent_id, state=candidate).set(
                1 if candidate == state else 0
            )

    def record_workspace_op(self, op: str, status: str) -> None:
        self.workspace_operations_total.labels(op=op, status=status).inc()

    def record_memory_event(self, agent_id: str, event: str, count: int = 1) -> None:
        self.memory_events_total.labels(agent_id=agent_id, event=event).inc(count)

    def set_pressure(self, agent_id: str, resource: str, seconds: float) -> None:
        self.pressure_seconds.labels(agent_id=agent_id, resource=resource).set(seconds)

    def record_limit_adjustment(self, resource: str, direction: str) -> None:
        self.limit_adjustments_total.labels(resource=resource, direction=direction).inc()

    def observe_startup(self, runtime: str, seconds: float) -> None:
        self.container_startup_duration.labels(runtime=runtime).observe(seconds)

    def record_oom_kill(self, runtime: str, agent_id: str) -> None:
        self.container_oom_kills_total.labels(runtime=runtime, agent_id=agent_id).inc()

    def set_retry_budget_ratio(self, agent_id: str, ratio: float) -> None:
        self.retry_budget_ratio.labels(agent_id=agent_id).set(ratio)

    def render(self) -> str:
        """Return the Prometheus text exposition format."""
        return generate_latest(self.registry).decode("utf-8")
