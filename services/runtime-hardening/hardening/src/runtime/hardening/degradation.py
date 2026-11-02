"""Degradation Controller (spec §5.1 Layer 2, §5.3).

Owns the per-agent ``FULL -> THROTTLED -> READ_ONLY -> PAUSED -> TERMINATED``
transitions and recovery. It consumes pressure signals from the Resource
Manager and circuit-breaker OPEN events, and it drives the degradation ladder.
Recovery only promotes back up the ladder when the health gate passes (pressure
cleared for 2x backoff window).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from runtime.hardening.models import DegradationMode, PressureReport
from runtime.hardening.resilience import (
    DegradationLadder,
    ResilienceRegistry,
)


class DegradationTrigger(Protocol):
    """Callback that observes a pressure report and returns an escalation reason."""

    def __call__(self, agent_id: str, report: PressureReport) -> str | None: ...


@dataclass
class DefaultPressurePolicy:
    """Derive an escalation trigger from a PSI pressure report (spec §5.3).

    Trigger set (spec §9): ``psi_memory``, ``psi_cpu``, ``psi_io``,
    ``memory_high``, ``memory_max``, ``cpu_throttle``, ``io_max``,
    ``circuit_open``, ``health_fail``.
    """

    threshold: float = 0.5

    def __call__(self, agent_id: str, report: PressureReport) -> str | None:
        if report.memory.avg10 >= self.threshold:
            return "psi_memory"
        if report.cpu.avg10 >= self.threshold:
            return "psi_cpu"
        if report.io.avg10 >= self.threshold:
            return "psi_io"
        return None


class DegradationController:
    """Per-agent degradation state machine driven by pressure + CB events."""

    def __init__(
        self,
        registry: ResilienceRegistry,
        policy: Callable[[str, PressureReport], str | None] | None = None,
        health_gate: Callable[[str], bool] | None = None,
        on_transition: (
            Callable[[str, DegradationMode, DegradationMode, str | None], None] | None
        ) = None,
        eval_interval_seconds: float = 5.0,
    ) -> None:
        self.registry = registry
        self.policy = policy or DefaultPressurePolicy()
        self.health_gate = health_gate or (lambda agent_id: True)
        self.on_transition = on_transition
        self.eval_interval_seconds = eval_interval_seconds
        self._reports: dict[str, PressureReport] = {}
        self._health_state: dict[str, bool] = {}
        self._lock = threading.Lock()

    def update_pressure(self, agent_id: str, report: PressureReport) -> None:
        with self._lock:
            self._reports[agent_id] = report

    def set_health(self, agent_id: str, ok: bool) -> None:
        with self._lock:
            self._health_state[agent_id] = ok

    def update_from_pressure(self, agent_id: str, report: PressureReport) -> DegradationMode:
        """Evaluate pressure against the ladder and return the current mode.

        Emits a transition callback for observability/eventing.
        """
        with self._lock:
            self._reports[agent_id] = report
        ladder = self.registry.ladder(agent_id)
        reason = self.policy(agent_id, report)

        if reason is not None and ladder.mode == DegradationMode.FULL:
            # FULL -> THROTTLED on sustained pressure.
            self._transition(agent_id, ladder, ladder.escalate(), reason)
        elif reason is not None and ladder.mode == DegradationMode.THROTTLED:
            # THROTTLED -> READ_ONLY when pressure persists.
            self._transition(agent_id, ladder, ladder.escalate(), reason)
        elif (
            ladder.mode in (DegradationMode.THROTTLED, DegradationMode.READ_ONLY)
            and self.health_gate(agent_id)
            and self._pressure_cleared(report)
        ):
            # Pressure cleared and health gate passes for 2x backoff window ->
            # recover one step.
            self._transition(agent_id, ladder, ladder.recover(1), None)

        return ladder.mode

    def _pressure_cleared(self, report: PressureReport) -> bool:
        threshold = self.registry.settings.pressure_threshold
        return (
            report.memory.avg10 < threshold
            and report.cpu.avg10 < threshold
            and report.io.avg10 < threshold
        )

    def circuit_open(self, agent_id: str) -> DegradationMode:
        """A dependency circuit OPEN is a health-fail trigger (spec §5.3)."""
        ladder = self.registry.ladder(agent_id)
        if ladder.mode != DegradationMode.TERMINATED:
            self._transition(agent_id, ladder, ladder.escalate(), "circuit_open")
        return ladder.mode

    def oom(self, agent_id: str) -> DegradationMode:
        """An OOM kill drives the agent to PAUSED (unrecoverable without action)."""
        ladder = self.registry.ladder(agent_id)
        if ladder.mode in (
            DegradationMode.READ_ONLY,
            DegradationMode.THROTTLED,
            DegradationMode.FULL,
        ):
            # Escalate READ_ONLY -> PAUSED (2 steps from the FULL baseline path).
            while (
                ladder.mode != DegradationMode.PAUSED and ladder.mode != DegradationMode.TERMINATED
            ):
                self._transition(agent_id, ladder, ladder.escalate(), "memory_max")
        return ladder.mode

    def terminate(self, agent_id: str) -> DegradationMode:
        ladder = self.registry.ladder(agent_id)
        self._transition(agent_id, ladder, ladder.terminate(), "unrecoverable")
        return ladder.mode

    def maybe_recover(self, agent_id: str) -> DegradationMode:
        """Promote back up the ladder when the health gate passes (spec §5.3).

        Uses the recovery coordinator's exponential backoff; recovery is only
        attempted after the health gate reports healthy for the required window.
        """
        ladder = self.registry.ladder(agent_id)

        if ladder.mode == DegradationMode.TERMINATED:
            return ladder.mode

        if not self.health_gate(agent_id):
            return ladder.mode

        coordinator = self.registry.coordinator(agent_id)
        if coordinator.attempts >= 2 and ladder.mode != DegradationMode.FULL:
            self._transition(agent_id, ladder, ladder.recover(1), None)
            coordinator.reset()
        else:
            coordinator.attempts += 1

        return ladder.mode

    def mode(self, agent_id: str) -> DegradationMode:
        return self.registry.ladder(agent_id).mode

    def _transition(
        self,
        agent_id: str,
        ladder: DegradationLadder,
        new_mode: DegradationMode,
        reason: str | None,
    ) -> None:
        previous = ladder.history[-2] if len(ladder.history) >= 2 else DegradationMode.FULL
        if self.on_transition is not None:
            self.on_transition(agent_id, previous, new_mode, reason)


def degraded_execution_guard(mode: DegradationMode) -> None:
    """Graceful-degradation hook: reject new executions in restrictive modes.

    Per spec §5.1: THROTTLED rejects new work; READ_ONLY serves cached results
    only; PAUSED stops scheduling; TERMINATED is terminal.
    """
    if mode in (DegradationMode.TERMINATED, DegradationMode.PAUSED):
        raise RuntimeError(f"agent is {mode.value}; execution not permitted")
    if mode == DegradationMode.READ_ONLY:
        raise RuntimeError("agent is read_only; cached results only")
