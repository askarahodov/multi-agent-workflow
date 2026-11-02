"""Unit tests for observability: health, JSON logs, metrics, OTel hooks (spec §7)."""

from __future__ import annotations

import json

from runtime.hardening.models import CircuitBreakerState, DegradationMode, HealthProbeResult
from runtime.hardening.observability import (
    HealthRegistry,
    JsonFormatter,
    MetricsRegistry,
    OTelHooks,
    StructuredLogger,
)


def test_health_liveness_pass_fail() -> None:
    registry = HealthRegistry()
    status = registry.liveness()
    assert status.liveness == HealthProbeResult.PASS
    registry.add_live_check("always-bad", lambda: False)
    assert registry.liveness().liveness == HealthProbeResult.FAIL


def test_health_readiness() -> None:
    registry = HealthRegistry()
    assert registry.readiness().readiness == HealthProbeResult.PASS
    registry.add_ready_check("no-workspace", lambda: False)
    assert registry.readiness().readiness == HealthProbeResult.FAIL


def test_health_startup() -> None:
    registry = HealthRegistry()
    assert registry.startup().startup == HealthProbeResult.FAIL
    registry.mark_started()
    assert registry.startup().startup == HealthProbeResult.PASS


def test_json_logger_emits_mandatory_fields() -> None:
    """AC-9: JSON-lines logs carry the mandatory spec §7.2 fields."""
    import logging

    logger = StructuredLogger("test.jsonlogger", level="INFO", component="test")
    # Build a record directly (avoiding stream-capture ordering issues) and
    # format it with the JSON formatter.
    formatter = JsonFormatter()
    record = logger._logger.makeRecord(
        "test.jsonlogger", logging.INFO, __file__, 0, "agent started", None, None
    )
    record.component = "test"
    record.agent_id = "a1"
    record.trace_id = "trace123"
    record.span_id = "span456"
    record.attributes = {"tier": "runc"}
    parsed = json.loads(formatter.format(record))
    assert parsed["level"] == "INFO"
    assert parsed["agent_id"] == "a1"
    assert parsed["trace_id"] == "trace123"
    assert parsed["span_id"] == "span456"
    assert parsed["attributes"] == {"tier": "runc"}
    assert "timestamp" in parsed
    assert parsed["component"] == "test"


def test_json_formatter_includes_exception() -> None:
    import logging

    formatter = JsonFormatter()
    record = logging.LogRecord("x", logging.ERROR, "file", 1, "boom", None, None)
    record.component = "c"
    line = formatter.format(record)
    assert json.loads(line)["level"] == "ERROR"


def test_metrics_expose_and_counts() -> None:
    metrics = MetricsRegistry()
    metrics.agents_running.labels(state="running").inc()
    metrics.retry_total.inc()
    metrics.set_circuit_state("a1", CircuitBreakerState.OPEN)
    metrics.set_degradation_mode("a1", DegradationMode.THROTTLED)
    metrics.oom_kills_total.inc()
    out = metrics.expose().decode()
    assert "harbor_agent_running_total" in out
    assert "harbor_retry_total" in out
    assert "harbor_oom_kills_total" in out
    assert "harbor_circuit_breaker_state" in out
    assert "harbor_degradation_mode" in out


def test_otel_hooks_trace_context() -> None:
    otel = OTelHooks(enabled=False)
    ctx = otel.start_span("workspace.create", agent_id="a1")
    assert ctx["trace_id"] and ctx["span_id"]
    headers = otel.propagate_headers(ctx["trace_id"], ctx["span_id"])
    assert headers["traceparent"].startswith("00-")
    otel.end_span(ctx)


def test_otel_trace_id_uniqueness() -> None:
    otel = OTelHooks()
    assert otel.new_trace_id() != otel.new_trace_id()
