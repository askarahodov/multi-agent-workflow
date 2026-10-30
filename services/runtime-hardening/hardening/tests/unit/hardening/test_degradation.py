"""Unit tests for the degradation controller (spec §5.3)."""

from __future__ import annotations

from runtime.hardening.degradation import (
    DefaultPressurePolicy,
    DegradationController,
    degraded_execution_guard,
)
from runtime.hardening.models import DegradationMode, PressureReport, PressureSample
from runtime.hardening.resilience import ResilienceRegistry


def _report(**samples: float) -> PressureReport:
    def sample(avg10: float) -> PressureSample:
        return PressureSample(avg10=avg10, avg60=0.0, avg300=0.0)

    return PressureReport(
        cpu=sample(samples.get("cpu", 0.0)),
        memory=sample(samples.get("memory", 0.0)),
        io=sample(samples.get("io", 0.0)),
    )


def test_full_to_throttled_on_pressure() -> None:
    registry = ResilienceRegistry()
    controller = DegradationController(registry)
    mode = controller.update_from_pressure("a1", _report(memory=0.9))
    assert mode == DegradationMode.THROTTLED


def test_throttled_to_read_only_on_persistent_pressure() -> None:
    registry = ResilienceRegistry()
    controller = DegradationController(registry)
    controller.update_from_pressure("a1", _report(memory=0.9))
    mode = controller.update_from_pressure("a1", _report(memory=0.95))
    assert mode == DegradationMode.READ_ONLY


def test_recovers_when_pressure_cleared_and_health_gate_passes() -> None:
    registry = ResilienceRegistry()
    transitions: list[DegradationMode] = []
    controller = DegradationController(
        registry, on_transition=lambda a, p, n, r: transitions.append(n)
    )
    controller.update_from_pressure("a1", _report(memory=0.9))  # THROTTLED
    mode = controller.update_from_pressure("a1", _report(memory=0.0))  # cleared
    assert mode == DegradationMode.FULL


def test_circuit_open_escalates() -> None:
    registry = ResilienceRegistry()
    controller = DegradationController(registry)
    mode = controller.circuit_open("a1")
    assert mode == DegradationMode.THROTTLED


def test_oom_drives_to_paused() -> None:
    registry = ResilienceRegistry()
    controller = DegradationController(registry)
    controller.update_from_pressure("a1", _report(memory=0.9))  # -> THROTTLED
    controller.update_from_pressure("a1", _report(memory=0.95))  # -> READ_ONLY
    mode = controller.oom("a1")
    assert mode == DegradationMode.PAUSED


def test_terminate() -> None:
    registry = ResilienceRegistry()
    controller = DegradationController(registry)
    assert controller.terminate("a1") == DegradationMode.TERMINATED


def test_pressure_policy_triggers() -> None:
    policy = DefaultPressurePolicy(threshold=0.5)
    assert policy("a1", _report(memory=0.6)) == "psi_memory"
    assert policy("a1", _report(cpu=0.6)) == "psi_cpu"
    assert policy("a1", _report(io=0.6)) == "psi_io"
    assert policy("a1", _report()) is None


def test_degraded_execution_guard() -> None:
    try:
        degraded_execution_guard(DegradationMode.READ_ONLY)
    except RuntimeError:
        return
    raise AssertionError("expected RuntimeError for read_only execution")


def test_degraded_execution_guard_terminated() -> None:
    import pytest

    with pytest.raises(RuntimeError):
        degraded_execution_guard(DegradationMode.TERMINATED)
    # full/throttled permit execution.
    degraded_execution_guard(DegradationMode.FULL)
    degraded_execution_guard(DegradationMode.THROTTLED)
