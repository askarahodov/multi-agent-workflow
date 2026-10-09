"""Unit tests for health probes and metrics/observability (ADR-005)."""

from __future__ import annotations

import json
import logging

from runtime.health import (
    ControlPlaneHealth,
    HealthChecker,
    Probes,
    aggregate_status,
    probe_result,
)
from runtime.metrics import (
    JsonFormatter,
    MetricsCollector,
    OTelHooks,
    configure_logging,
    get_correlation_id,
    new_correlation_id,
    set_correlation_id,
)
from runtime.models import HealthProbeResult


def test_health_checker_all_pass() -> None:
    checker = HealthChecker(
        subject="a",
        probes=Probes(liveness=lambda: True, readiness=lambda: True, startup=lambda: True),
    )
    status = checker.check()
    assert status.liveness == HealthProbeResult.PASS
    assert checker.ready() is True


def test_health_checker_failing_probe_records_detail() -> None:
    checker = HealthChecker(
        subject="a", probes=Probes(liveness=lambda: True, readiness=lambda: False)
    )
    status = checker.check()
    assert status.readiness == HealthProbeResult.FAIL
    assert status.detail is not None and "readiness" in status.detail
    assert checker.ready() is False


def test_health_checker_probe_exception_is_failure() -> None:
    def boom() -> bool:
        raise RuntimeError("nope")

    checker = HealthChecker(subject="a", probes=Probes(liveness=boom))
    assert checker.check().liveness == HealthProbeResult.FAIL


def test_health_checker_unknown_when_unconfigured() -> None:
    checker = HealthChecker(subject="a", probes=Probes())
    assert checker.check().liveness == HealthProbeResult.UNKNOWN


def test_health_transition_timestamp_changes() -> None:
    state = {"ok": True}
    checker = HealthChecker(subject="a", probes=Probes(readiness=lambda: state["ok"]))
    first = checker.check()
    state["ok"] = False
    second = checker.check()
    assert second.lastTransition is not None
    assert first.lastTransition is not None
    assert second.lastTransition >= first.lastTransition


def test_control_plane_health() -> None:
    cp = ControlPlaneHealth()
    assert cp.liveness() and cp.startup() and cp.readiness()
    cp.register_dependency("db", lambda: False)
    assert cp.readiness() is False
    cp.register_dependency("db", lambda: True)
    assert cp.readiness() is True


def test_aggregate_status() -> None:
    assert (
        aggregate_status([HealthProbeResult.PASS, HealthProbeResult.PASS]) == HealthProbeResult.PASS
    )
    assert (
        aggregate_status([HealthProbeResult.PASS, HealthProbeResult.FAIL]) == HealthProbeResult.FAIL
    )
    assert (
        aggregate_status([HealthProbeResult.PASS, HealthProbeResult.UNKNOWN])
        == HealthProbeResult.UNKNOWN
    )


def test_probe_result_helper() -> None:
    assert probe_result(True) == HealthProbeResult.PASS
    assert probe_result(False) == HealthProbeResult.FAIL
    assert probe_result("unknown") == HealthProbeResult.UNKNOWN


def test_metrics_render_contains_expected_series() -> None:
    metrics = MetricsCollector()
    metrics.record_agent_state("running")
    metrics.set_degradation_mode("a1", "throttled")
    metrics.set_circuit_breaker_state("a1", "open")
    metrics.set_resource_usage("a1", "memory", 123.0)
    metrics.record_workspace_op("create", "success")
    metrics.record_memory_event("a1", "oom_kill")
    metrics.set_pressure("a1", "memory", 1.5)
    metrics.record_limit_adjustment("cpu", "down")
    metrics.observe_startup("runc", 0.42)
    metrics.record_oom_kill("runc", "a1")
    metrics.set_retry_budget_ratio("a1", 0.5)
    text = metrics.render()
    assert "agent_runtime_agents_total" in text
    assert 'agent_runtime_degradation_mode{agent_id="a1",mode="throttled"} 1.0' in text
    assert 'agent_runtime_circuit_breaker_state{agent_id="a1",state="open"} 1.0' in text
    assert "container_startup_duration_seconds_count" in text


def test_metrics_isolated_registries() -> None:
    first = MetricsCollector()
    second = MetricsCollector()
    first.record_agent_state("running")
    assert "running" in first.render()
    # A second collector must not raise duplicate-registration errors.
    assert second.render() is not None


def test_json_formatter_includes_correlation_id() -> None:
    formatter = JsonFormatter(service="test")
    record = logging.LogRecord("n", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    set_correlation_id("cid-123")
    payload = json.loads(formatter.format(record))
    assert payload["message"] == "hello world"
    assert payload["correlationId"] == "cid-123"
    assert payload["service"] == "test"


def test_configure_logging() -> None:
    logger = configure_logging(level="DEBUG", service="svc")
    assert logger.name == "svc"
    assert logging.getLogger().level == logging.DEBUG


def test_correlation_id_helpers() -> None:
    set_correlation_id("x")
    assert get_correlation_id() == "x"
    assert len(new_correlation_id()) == 32


def test_otel_hooks_noop_when_disabled() -> None:
    hooks = OTelHooks(enabled=False)
    assert hooks.available is False
    with hooks.span("op", {"k": "v"}) as span:
        assert span is None
