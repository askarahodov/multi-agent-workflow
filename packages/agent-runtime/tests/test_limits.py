"""Budget, resource quota and quality-gate controls (ADR-105)."""

from __future__ import annotations

import pytest

from agent_runtime.errors import ErrorKind, PlatformError
from agent_runtime.limits import (
    DEFAULT_MINIMAL_LIMITS,
    Budget,
    BudgetState,
    GateConfig,
    GateResult,
    GateRunner,
    GateStatus,
    ResourceLimits,
    calculate_cost,
    limits_for_tier,
)


def test_budget_state_flags_every_violation():
    budget = Budget(max_steps=1, max_tokens=10, max_cost_usd=0.5, max_wall_time_ms=100)
    state = BudgetState(steps_used=1, tokens_used=10, cost_usd=0.5, time_elapsed_ms=100)
    check = state.check(budget)
    assert check.ok is False
    assert set(check.violations) == {"max_steps", "max_tokens", "max_cost_usd", "max_wall_time_ms"}


def test_budget_state_ok_when_within_limits():
    budget = Budget(max_steps=5, max_tokens=100, max_cost_usd=1.0, max_wall_time_ms=1000)
    state = BudgetState(steps_used=1, tokens_used=50, cost_usd=0.1, time_elapsed_ms=100)
    assert state.check(budget).ok is True


def test_budget_record_usage_accumulates_and_ignores_negatives():
    state = BudgetState()
    state.record_usage(tokens=10, cost_usd=0.1, step=True, elapsed_ms=5)
    state.record_usage(tokens=-5, cost_usd=-1.0, step=False)
    assert state.steps_used == 1
    assert state.tokens_used == 10
    assert state.cost_usd == pytest.approx(0.1)
    assert state.time_elapsed_ms == 5


def test_budget_warning_fires_once():
    budget = Budget(max_steps=10, max_tokens=0, max_cost_usd=0, max_wall_time_ms=0)
    state = BudgetState(steps_used=8)
    assert state.warning(budget) is True
    assert state.warning(budget) is False


def test_calculate_cost_uses_known_and_default_pricing():
    known = calculate_cost("openrouter/openai/gpt-4o", 1000, 1000)
    assert known == pytest.approx(0.005 + 0.015)
    default = calculate_cost("mystery/model", 1000, 0)
    assert default == pytest.approx(0.01)


def test_limits_for_known_and_unknown_tier():
    assert limits_for_tier("medium") is not DEFAULT_MINIMAL_LIMITS
    with pytest.raises(PlatformError) as exc:
        limits_for_tier("gigantic")
    assert exc.value.kind is ErrorKind.CONFIG_ERROR


def test_resource_limits_render_cgroup():
    limits = ResourceLimits(cpu_quota_us=50_000, cpu_period_us=100_000, memory_max_bytes=1024, pids_max=8)
    cg = limits.to_cgroup()
    assert cg["cpu.max"] == "50000 100000"
    assert cg["memory.max"] == 1024
    assert cg["pids.max"] == 8


def _gate(name, status, findings=()):
    return lambda _n, _p: GateResult(name, status, tuple(findings))


def test_gate_runner_passes_only_when_all_pass():
    runner = GateRunner({"tester": _gate("tester", GateStatus.PASSED)})
    ok, results = runner.check_submission(GateConfig(required_gates=("tester",)))
    assert ok is True
    assert all(r.passed for r in results)


def test_gate_runner_fails_closed_on_unregistered_gate():
    runner = GateRunner()
    ok, results = runner.check_submission(GateConfig(required_gates=("security",)))
    assert ok is False
    assert results[0].status is GateStatus.UNAVAILABLE
    with pytest.raises(PlatformError) as exc:
        runner.enforce(GateConfig(required_gates=("security",)))
    assert exc.value.kind is ErrorKind.GATE_UNAVAILABLE


def test_gate_runner_fails_closed_when_gate_raises():
    def boom(_name, _params):
        raise RuntimeError("gate down")

    runner = GateRunner({"tester": boom})
    ok, results = runner.check_submission(GateConfig(required_gates=("tester",)))
    assert ok is False
    assert results[0].status is GateStatus.UNAVAILABLE


def test_gate_runner_reports_failure():
    runner = GateRunner({"tester": _gate("tester", GateStatus.FAILED, ("coverage low",))})
    with pytest.raises(PlatformError) as exc:
        runner.enforce(GateConfig(required_gates=("tester",)))
    assert exc.value.kind is ErrorKind.GATE_FAILED
    assert "coverage low" in exc.value.context["findings"]
