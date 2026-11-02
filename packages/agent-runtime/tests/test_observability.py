"""Structured logging, sanitisation, events and metrics (ADR-106)."""

from __future__ import annotations

import json

from agent_runtime.observability import (
    EventBus,
    MetricsRegistry,
    StructuredLogger,
    correlation,
    sanitize_context,
)


def test_sanitize_context_redacts_nested_secrets():
    clean = sanitize_context(
        {
            "api_key": "sk-123",
            "nested": {"token": "t", "keep": "ok"},
            "items": [{"password": "p"}, "plain"],
        }
    )
    assert clean["api_key"] == "***REDACTED***"
    assert clean["nested"]["token"] == "***REDACTED***"
    assert clean["nested"]["keep"] == "ok"
    assert clean["items"][0]["password"] == "***REDACTED***"
    assert clean["items"][1] == "plain"


def test_structured_logger_emits_valid_json_with_required_fields():
    lines: list[str] = []
    logger = StructuredLogger("agent-runtime", sink=lines.append)
    with correlation(correlation_id="req-1", trace_id="trace-9", span_id="span-3"):
        record = logger.info("agent_runtime.runner", "hi", api_key="sk-secret", task_id="t-1")

    payload = json.loads(lines[0])
    assert payload["service"] == "agent-runtime"
    assert payload["level"] == "INFO"
    assert payload["correlation_id"] == "req-1"
    assert payload["trace_id"] == "trace-9"
    assert payload["span_id"] == "span-3"
    assert payload["context"]["api_key"] == "***REDACTED***"
    assert "sk-secret" not in lines[0]
    assert record.to_dict()["message"] == "hi"


def test_event_bus_records_events_and_survives_bad_handler():
    bus = EventBus()
    seen: list[str] = []
    bus.subscribe(lambda e: seen.append(e.type))

    def boom(_event):
        raise RuntimeError("handler down")

    bus.subscribe(boom)
    event = bus.publish("task.claimed", {"task_id": "t-1", "token": "secret"})
    assert seen == ["task.claimed"]
    assert bus.types() == ["task.claimed"]
    assert event.payload["token"] == "secret"  # raw payload preserved in memory
    assert event.to_dict()["payload"]["token"] == "***REDACTED***"  # redacted on serialise
    assert bus.failed_handlers and bus.failed_handlers[0][0] == "task.claimed"


def test_metrics_registry_renders_prometheus_text():
    metrics = MetricsRegistry()
    metrics.inc("agent_runtime_tasks_total", status="completed")
    metrics.inc("agent_runtime_tasks_total", status="completed")
    metrics.inc("agent_runtime_tasks_total", status="failed")
    assert metrics.value("agent_runtime_tasks_total", status="completed") == 2
    rendered = metrics.render()
    assert 'agent_runtime_tasks_total{status="completed"} 2' in rendered
    assert 'agent_runtime_tasks_total{status="failed"} 1' in rendered
