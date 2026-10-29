"""Cost budgets, resource quotas and quality gates (ADR-105).

Three controls live side by side because they share one property: **fail-closed
defaults**. A missing budget is zero, a missing limit is minimal, and a gate that
cannot be evaluated blocks (never passes).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable, Mapping, Optional

from .errors import ErrorKind, PlatformError, gate_unavailable

# ---------------------------------------------------------------------------
# Cost budgets (ADR-105 §3.1)
# ---------------------------------------------------------------------------

#: Pricing per 1k tokens, keyed by model id. Unknown models fall back to
#: ``DEFAULT_PRICING`` which is deliberately expensive (fail-closed).
MODEL_PRICING: dict[str, dict[str, float]] = {
    "openrouter/anthropic/claude-3.5-sonnet": {"input_per_1k": 0.003, "output_per_1k": 0.015},
    "openrouter/openai/gpt-4o": {"input_per_1k": 0.005, "output_per_1k": 0.015},
}
DEFAULT_PRICING: dict[str, float] = {"input_per_1k": 0.01, "output_per_1k": 0.03}


def calculate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model_id, DEFAULT_PRICING)
    return (input_tokens / 1000.0) * pricing["input_per_1k"] + (
        output_tokens / 1000.0
    ) * pricing["output_per_1k"]


@dataclass(frozen=True)
class Budget:
    """Hard per-run limits. Defaults are zero (fail-closed, ADR-105 §3.4)."""

    max_steps: int = 0
    max_tokens: int = 0
    max_cost_usd: float = 0.0
    max_wall_time_ms: int = 0

    @classmethod
    def zero(cls) -> "Budget":
        return cls()

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_steps": self.max_steps,
            "max_tokens": self.max_tokens,
            "max_cost_usd": self.max_cost_usd,
            "max_wall_time_ms": self.max_wall_time_ms,
        }


@dataclass(frozen=True)
class BudgetCheck:
    ok: bool
    violations: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "violations": list(self.violations)}


@dataclass
class BudgetState:
    """Mutable consumption counters for one run (ADR-105 §3.1)."""

    steps_used: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    time_elapsed_ms: int = 0
    _warning_emitted: bool = field(default=False, repr=False)

    def check(self, budget: Budget) -> BudgetCheck:
        violations: list[str] = []
        if self.steps_used >= budget.max_steps:
            violations.append("max_steps")
        if self.tokens_used >= budget.max_tokens:
            violations.append("max_tokens")
        if self.cost_usd >= budget.max_cost_usd:
            violations.append("max_cost_usd")
        if self.time_elapsed_ms >= budget.max_wall_time_ms:
            violations.append("max_wall_time_ms")
        return BudgetCheck(ok=len(violations) == 0, violations=tuple(violations))

    def record_usage(
        self,
        *,
        tokens: int = 0,
        cost_usd: float = 0.0,
        step: bool = False,
        elapsed_ms: int = 0,
    ) -> None:
        if step:
            self.steps_used += 1
        self.tokens_used += max(0, tokens)
        self.cost_usd += max(0.0, cost_usd)
        self.time_elapsed_ms += max(0, elapsed_ms)

    def warning(self, budget: Budget, threshold: float = 0.8) -> bool:
        """Return True the first time a dimension crosses *threshold* (ADR-105 §3.5)."""
        if self._warning_emitted:
            return False
        dims = (
            (self.steps_used, budget.max_steps),
            (self.tokens_used, budget.max_tokens),
            (self.cost_usd, budget.max_cost_usd),
            (self.time_elapsed_ms, budget.max_wall_time_ms),
        )
        crossed = any(limit > 0 and used / limit >= threshold for used, limit in dims)
        if crossed:
            self._warning_emitted = True
        return crossed

    def to_dict(self) -> dict[str, Any]:
        return {
            "steps_used": self.steps_used,
            "tokens_used": self.tokens_used,
            "cost_usd": round(self.cost_usd, 6),
            "time_elapsed_ms": self.time_elapsed_ms,
        }


# ---------------------------------------------------------------------------
# Resource quotas (ADR-105 §3.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResourceLimits:
    cpu_quota_us: int = 10_000
    cpu_period_us: int = 100_000
    memory_max_bytes: int = 64 * 1024 * 1024
    memory_swap_max_bytes: int = 64 * 1024 * 1024
    pids_max: int = 16
    disk_quota_bytes: int = 10 * 1024 * 1024
    network_egress_bps: int = 0  # 0 = no egress

    def to_cgroup(self) -> dict[str, Any]:
        return {
            "cpu.max": f"{self.cpu_quota_us} {self.cpu_period_us}",
            "memory.max": self.memory_max_bytes,
            "memory.swap.max": self.memory_swap_max_bytes,
            "pids.max": self.pids_max,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_quota_us": self.cpu_quota_us,
            "cpu_period_us": self.cpu_period_us,
            "memory_max_bytes": self.memory_max_bytes,
            "memory_swap_max_bytes": self.memory_swap_max_bytes,
            "pids_max": self.pids_max,
            "disk_quota_bytes": self.disk_quota_bytes,
            "network_egress_bps": self.network_egress_bps,
        }


TIER_LIMITS: dict[str, ResourceLimits] = {
    "low": ResourceLimits(cpu_quota_us=50_000, memory_max_bytes=256 * 1024 * 1024, pids_max=32),
    "medium": ResourceLimits(
        cpu_quota_us=200_000,
        memory_max_bytes=1024 * 1024 * 1024,
        pids_max=128,
        disk_quota_bytes=100 * 1024 * 1024,
        network_egress_bps=10 * 1024 * 1024,
    ),
    "high": ResourceLimits(
        cpu_quota_us=500_000,
        memory_max_bytes=2048 * 1024 * 1024,
        pids_max=256,
        disk_quota_bytes=500 * 1024 * 1024,
        network_egress_bps=50 * 1024 * 1024,
    ),
}
DEFAULT_MINIMAL_LIMITS = ResourceLimits()


def limits_for_tier(tier: str) -> ResourceLimits:
    try:
        return TIER_LIMITS[tier]
    except KeyError as exc:  # fail-closed: unknown tier never widens limits
        raise PlatformError(
            ErrorKind.CONFIG_ERROR,
            f"unknown resource tier {tier!r}",
            context={"valid_tiers": sorted(TIER_LIMITS)},
        ) from exc


# ---------------------------------------------------------------------------
# Quality gates (ADR-105 §3.3)
# ---------------------------------------------------------------------------


class GateStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class GateResult:
    gate: str
    status: GateStatus
    findings: tuple[str, ...] = ()
    evidence_ref: str = ""

    @property
    def passed(self) -> bool:
        return self.status is GateStatus.PASSED

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "status": self.status.value,
            "passed": self.passed,
            "findings": list(self.findings),
            "evidence_ref": self.evidence_ref,
        }


@dataclass(frozen=True)
class GateConfig:
    """Required gates for a task type (ADR-105 §3.3)."""

    task_type: str = "default"
    required_gates: tuple[str, ...] = ()
    gate_params: Mapping[str, Any] = field(default_factory=dict)
    fix_loop_max: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "required_gates": list(self.required_gates),
            "gate_params": dict(self.gate_params),
            "fix_loop_max": self.fix_loop_max,
        }


#: A gate callable returns a GateResult. Raising is treated as UNAVAILABLE.
GateCallable = Callable[[str, Mapping[str, Any]], GateResult]


class GateRunner:
    """Runs the required gates for a task and fails closed (ADR-105 §3.3, §3.4).

    * an unknown/unregistered gate ⇒ ``UNAVAILABLE`` (block), never pass;
    * a gate that raises ⇒ ``UNAVAILABLE`` (block);
    * any ``FAILED`` gate makes the whole evaluation fail.
    """

    def __init__(self, gates: Mapping[str, GateCallable] | None = None) -> None:
        self._gates: dict[str, GateCallable] = dict(gates or {})

    def register(self, name: str, gate: GateCallable) -> None:
        self._gates[name] = gate

    def evaluate(self, config: GateConfig) -> list[GateResult]:
        results: list[GateResult] = []
        for gate_name in config.required_gates:
            gate = self._gates.get(gate_name)
            if gate is None:
                results.append(GateResult(gate_name, GateStatus.UNAVAILABLE, ("gate not registered",)))
                continue
            try:
                result = gate(gate_name, config.gate_params)
            except Exception as exc:  # noqa: BLE001 - fail closed on any gate error
                results.append(
                    GateResult(gate_name, GateStatus.UNAVAILABLE, (f"gate raised: {exc}",))
                )
                continue
            if not isinstance(result, GateResult):
                results.append(
                    GateResult(gate_name, GateStatus.UNAVAILABLE, ("gate returned invalid result",))
                )
                continue
            results.append(result)
        return results

    def check_submission(self, config: GateConfig) -> tuple[bool, list[GateResult]]:
        """Evaluate all required gates; ``(all_passed, results)``.

        ``all_passed`` is True only when every gate PASSED. Any FAILED or
        UNAVAILABLE result blocks submission (ADR-105 §3.3).
        """
        results = self.evaluate(config)
        ok = all(r.status is GateStatus.PASSED for r in results)
        return ok, results

    def enforce(self, config: GateConfig) -> list[GateResult]:
        """Like :meth:`check_submission`, but raises on any non-pass (fail-closed)."""
        ok, results = self.check_submission(config)
        if ok:
            return results
        from .errors import gate_failed

        for result in results:
            if result.status is GateStatus.UNAVAILABLE:
                raise gate_unavailable(result.gate, "; ".join(result.findings))
        failed = [r for r in results if r.status is GateStatus.FAILED]
        raise gate_failed(failed[0].gate, list(failed[0].findings) if failed else [])


# ---------------------------------------------------------------------------
# Wall-clock stopwatch helper
# ---------------------------------------------------------------------------


class Stopwatch:
    """Monotonic stopwatch with injectable clock (testable)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._start = clock()

    def elapsed_ms(self) -> int:
        return int((self._clock() - self._start) * 1000)
