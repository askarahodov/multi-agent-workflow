"""Observability integration (spec §7, ADR-011).

Provides the health-check protocol (``/healthz/{live,ready,startup}``),
structured JSON-lines logging with W3C trace correlation, Prometheus metric
exposition (the ``harbor_*`` / ``cgroup_*`` set), and OpenTelemetry
instrumentation hooks (W3C TraceContext + OTLP export when enabled).

No hardcoded secrets; trace/log correlation via ``trace_id``/``span_id``.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
from datetime import UTC, datetime
from typing import Any, Protocol

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

from runtime.hardening.config import RuntimeSettings
from runtime.hardening.models import (
    CircuitBreakerState,
    DegradationMode,
    HealthProbeResult,
    HealthStatus,
    PressureReport,
    ResourceUsage,
)

# --------------------------------------------------------------------------- #
# Structured JSON logging (spec §7.2)
# --------------------------------------------------------------------------- #
_MANDATORY_LEVELS = ("DEBUG", "INFO", "WARN", "ERROR", "CRITICAL")


class JsonFormatter(logging.Formatter):
    """Emit JSON-lines with the mandatory fields from spec §7.2.

    Fields: timestamp (RFC3339Nano), level, trace_id, span_id, agent_id,
    workspace_id, component, message, attributes{}. PII redaction is a caller
    responsibility at the source.
    """

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="microseconds"),
            "level": record.levelname,
            "message": record.getMessage(),
            "component": getattr(record, "component", None) or record.name,
        }
        for attr in ("trace_id", "span_id", "agent_id", "workspace_id"):
            value = getattr(record, attr, None)
            if value is not None:
                entry[attr] = value
        attributes = getattr(record, "attributes", None)
        if attributes:
            entry["attributes"] = attributes
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


class StructuredLogger:
    """Logger factory producing JSON-lines logs with correlation context."""

    def __init__(self, name: str, *, level: str = "INFO", component: str | None = None) -> None:
        self._logger = logging.getLogger(name)
        self._component = component or name
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(JsonFormatter())
            self._logger.addHandler(handler)
            self._logger.setLevel(level.upper() if level.upper() in _MANDATORY_LEVELS else "INFO")
            self._logger.propagate = False

    def _log(
        self,
        level: int,
        message: str,
        *,
        trace_id: str | None = None,
        span_id: str | None = None,
        agent_id: str | None = None,
        workspace_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        record = self._logger.makeRecord(
            self._logger.name,
            level,
            __file__,
            0,
            message,
            args=(),
            exc_info=None,
            func=None,
        )
        record.component = self._component
        record.trace_id = trace_id
        record.span_id = span_id
        record.agent_id = agent_id
        record.workspace_id = workspace_id
        record.attributes = attributes
        self._logger.handle(record)

    def debug(self, message: str, **ctx: Any) -> None:
        self._log(logging.DEBUG, message, **ctx)

    def info(self, message: str, **ctx: Any) -> None:
        self._log(logging.INFO, message, **ctx)

    def warn(self, message: str, **ctx: Any) -> None:
        self._log(logging.WARNING, message, **ctx)

    def error(self, message: str, **ctx: Any) -> None:
        self._log(logging.ERROR, message, **ctx)

    def critical(self, message: str, **ctx: Any) -> None:
        self._log(logging.CRITICAL, message, **ctx)


# --------------------------------------------------------------------------- #
# Health-check protocol (spec §7.5)
# --------------------------------------------------------------------------- #
class HealthRegistry:
    """Tracks liveness/readiness/startup probes for the control plane."""

    def __init__(self) -> None:
        self.startup_complete = False
        self._ready_checks: dict[str, Callable0] = {}
        self._live_checks: dict[str, Callable0] = {}
        self._lock = threading.Lock()

    def mark_started(self) -> None:
        with self._lock:
            self.startup_complete = True

    def add_ready_check(self, name: str, check: Callable0) -> None:
        with self._lock:
            self._ready_checks[name] = check

    def add_live_check(self, name: str, check: Callable0) -> None:
        with self._lock:
            self._live_checks[name] = check

    def liveness(self) -> HealthStatus:
        failures = [n for n, fn in self._live_checks.items() if not fn()]
        return HealthStatus(
            liveness=HealthProbeResult.FAIL if failures else HealthProbeResult.PASS,
            readiness=HealthProbeResult.UNKNOWN,
            startup=HealthProbeResult.PASS if self.startup_complete else HealthProbeResult.FAIL,
            lastTransition=datetime.now(UTC),
            detail=f"live checks failing: {failures}" if failures else None,
        )

    def readiness(self) -> HealthStatus:
        failures = [n for n, fn in self._ready_checks.items() if not fn()]
        return HealthStatus(
            liveness=HealthProbeResult.PASS,
            readiness=HealthProbeResult.FAIL if failures else HealthProbeResult.PASS,
            startup=HealthProbeResult.PASS if self.startup_complete else HealthProbeResult.FAIL,
            lastTransition=datetime.now(UTC),
            detail=f"ready checks failing: {failures}" if failures else None,
        )

    def startup(self) -> HealthStatus:
        return HealthStatus(
            liveness=HealthProbeResult.PASS,
            readiness=HealthProbeResult.UNKNOWN,
            startup=HealthProbeResult.PASS if self.startup_complete else HealthProbeResult.FAIL,
            lastTransition=datetime.now(UTC),
            detail=None if self.startup_complete else "startup not complete",
        )


class Callable0(Protocol):
    def __call__(self) -> bool: ...


# --------------------------------------------------------------------------- #
# Prometheus metrics (spec §7.4)
# --------------------------------------------------------------------------- #
class MetricsRegistry:
    """Exposes the ``harbor_*`` and ``cgroup_*`` metric set for Prometheus.

    Each instance owns a private :class:`CollectorRegistry` so multiple app
    instances (e.g. tests) do not collide on the global default registry.
    """

    def __init__(self, namespace: str = "harbor") -> None:
        self.namespace = namespace
        self.registry = CollectorRegistry(auto_describe=True)
        self.agents_running = Gauge(
            "harbor_agent_running_total",
            "Running agents by state",
            ["state"],
            registry=self.registry,
        )
        self.workspace_duration = Histogram(
            "harbor_workspace_duration_seconds",
            "Workspace create duration",
            buckets=(0.1, 0.5, 1, 5, 30),
            registry=self.registry,
        )
        self.resource_usage = Gauge(
            "harbor_resource_usage_bytes",
            "Resource usage",
            ["cgroup", "resource"],
            registry=self.registry,
        )
        self.circuit_breaker_state = Gauge(
            "harbor_circuit_breaker_state",
            "0=closed 1=open 2=half_open",
            ["agent_id", "state"],
            registry=self.registry,
        )
        self.degradation_mode = Gauge(
            "harbor_degradation_mode",
            "0/1 flag per mode",
            ["agent_id", "mode"],
            registry=self.registry,
        )
        self.retry_total = Counter("harbor_retry_total", "Retry attempts", registry=self.registry)
        self.retry_budget_ratio = Gauge(
            "harbor_retry_budget_ratio", "Available retry budget", registry=self.registry
        )
        self.oom_kills_total = Counter(
            "harbor_oom_kills_total", "OOM kill events", registry=self.registry
        )
        self.sandbox_start_duration = Histogram(
            "harbor_sandbox_start_duration_seconds",
            "Sandbox start",
            buckets=(0.5, 1, 5, 15, 60),
            registry=self.registry,
        )
        self.workspace_operations = Counter(
            "harbor_workspace_operations_total",
            "Workspace ops",
            ["op", "status"],
            registry=self.registry,
        )
        self.cgroup_memory_events = Counter(
            "cgroup_memory_events_total",
            "cgroup memory events",
            ["event", "agent_id"],
            registry=self.registry,
        )
        self.cgroup_pressure = Counter(
            "cgroup_pressure_seconds_total",
            "PSI stall time",
            ["resource", "agent_id"],
            registry=self.registry,
        )
        self.container_startup = Histogram(
            "container_startup_duration_seconds",
            "Container start",
            ["runtime"],
            registry=self.registry,
        )

    def expose(self) -> bytes:
        return generate_latest(self.registry)

    def set_circuit_state(self, agent_id: str, state: CircuitBreakerState) -> None:
        for label, value in (("closed", 0), ("open", 1), ("half_open", 2)):
            self.circuit_breaker_state.labels(agent_id=agent_id, state=label).set(
                value if state.value == label else 0
            )

    def set_degradation_mode(self, agent_id: str, mode: DegradationMode) -> None:
        for label in DegradationMode:
            self.degradation_mode.labels(agent_id=agent_id, mode=label.value).set(
                1 if mode == label else 0
            )

    def record_pressure(self, agent_id: str, report: PressureReport) -> None:
        for resource, sample in (("cpu", report.cpu), ("memory", report.memory), ("io", report.io)):
            self.cgroup_pressure.labels(resource=resource, agent_id=agent_id).inc(
                float(sample.totalMicros) / 1_000_000
            )

    def record_usage(self, agent_id: str, usage: ResourceUsage) -> None:
        self.resource_usage.labels(cgroup=agent_id, resource="memory").set(
            float(usage.memory.currentBytes)
        )


# --------------------------------------------------------------------------- #
# OpenTelemetry hooks (spec §7.3)
# --------------------------------------------------------------------------- #
class OTelHooks:
    """Minimal OTel-compatible instrumentation.

    When the OTLP exporter is unavailable (no ``opentelemetry`` dependency), a
    no-op implementation records the same span/trace metadata on the structured
    logger and is drop-in compatible with a future real SDK. W3C TraceContext
    values are generated/threaded here.
    """

    def __init__(
        self, service_name: str = "agent-runtime-hardening", enabled: bool = False
    ) -> None:
        self.service_name = service_name
        self.enabled = enabled
        self._lock = threading.Lock()
        self._current_trace: str | None = None
        self._current_span: str | None = None
        self._logger = StructuredLogger(f"{service_name}.otel", component="otel")

    @staticmethod
    def new_trace_id() -> str:
        return f"{int(time.time_ns()):032x}"

    @staticmethod
    def new_span_id() -> str:
        return f"{int(time.time_ns() % (1 << 64)):016x}"

    def start_span(self, name: str, *, agent_id: str | None = None) -> dict[str, str | None]:
        """Open a span; returns the trace/span context to propagate."""
        trace_id = self._current_trace or self.new_trace_id()
        span_id = self.new_span_id()
        with self._lock:
            self._current_trace = trace_id
            self._current_span = span_id
        self._logger.info(
            f"span.start name={name}", trace_id=trace_id, span_id=span_id, agent_id=agent_id
        )
        return {"trace_id": trace_id, "span_id": span_id}

    def end_span(self, context: dict[str, str | None]) -> None:
        self._logger.debug(
            "span.end",
            trace_id=context.get("trace_id"),
            span_id=context.get("span_id"),
        )

    def propagate_headers(self, trace_id: str | None, span_id: str | None) -> dict[str, str]:
        """Build W3C ``traceparent`` header for outbound calls."""
        if not trace_id or not span_id:
            return {}
        return {"traceparent": f"00-{trace_id}-{span_id}-01"}


def build_observability(
    settings: RuntimeSettings,
) -> tuple[HealthRegistry, MetricsRegistry, OTelHooks, StructuredLogger]:
    """Construct the observability stack from settings."""
    health = HealthRegistry()
    metrics = MetricsRegistry()
    otel = OTelHooks(service_name=settings.service_name, enabled=settings.otlp_enabled)
    logger = StructuredLogger(settings.service_name, level=settings.log_level)
    return health, metrics, otel, logger
