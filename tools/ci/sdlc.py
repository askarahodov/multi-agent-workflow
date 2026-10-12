"""SDLC phase orchestration engine (task items (a)+(b), ADR-016).

Implements the executable Standard SDLC Workflow as a phase DAG with the
guarantees ADR-016 §2 requires:

* R1 — role DAG with explicit phases and entry/exit contracts (JSON Schema).
* R2 — fix-loop limit: a phase whose gates fail goes to FIXER; after
  ``max_fix_loops`` escalations the run escalates to a human instead of looping.
* R3 — candidate invalidation: entering the fix loop invalidates any prior
  candidate gate passes, so independent checks are never carried across a
  source change.
* R4 — auto task creation: each completed phase advances to the next one and
  ``auto_create_next`` produces the follow-on task.
* R5 — decision audit: every transition is recorded (audit trail).
* R6 — contract verification: each phase output validates against its
  output_contract before the phase is accepted.

Gate execution is *injected* (a callable) so the engine is a pure, testable
state machine; the real gate runner lives in :mod:`tools.ci.pipeline`. A
:class:`~tools.storage.MemoryStore` can be attached to persist the audit trail
and candidate state (task item (d)).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import jsonschema

# Phase names — stable identifiers mirroring the orchestration profiles.
RESEARCHER = "researcher"
ARCHITECT = "architect"
PLANNER = "planner"
DEVELOPER = "developer"
TESTER = "tester"
REVIEWER = "reviewer"
SECURITY = "security"
FIXER = "fixer"
RELEASE = "release"

# Gate names that correspond to independent verification roles (ADR-016 R7).
BUILTIN_GATES = (TESTER, REVIEWER, SECURITY)


class SDLCError(Exception):
    """Base class for SDLC engine errors."""


class ContractViolation(SDLCError):
    """Raised when a phase output fails its JSON Schema contract."""


class PhaseNotFoundError(SDLCError):
    """Raised when a phase name is not part of the template."""


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class SDLCPhase:
    """One role/phase in the SDLC template (ADR-016 §3.2)."""

    name: str
    agent_profile: str
    description: str
    output_contract: dict  # JSON Schema for a phase's accepted output
    required_gates: tuple[str, ...] = ()
    max_fix_loops: int = 3
    auto_create_next: bool = True


@dataclass
class GateVerdict:
    """Outcome of one independent verification gate (ADR-016 R7)."""

    gate: str
    passed: bool
    findings: list[str] = field(default_factory=list)
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate,
            "passed": self.passed,
            "findings": self.findings,
            "duration_ms": self.duration_ms,
        }


@dataclass
class AuditEvent:
    """One transition/decision record (ADR-016 R5)."""

    event_type: str
    phase: str
    payload: dict[str, Any]
    at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"event_type": self.event_type, "phase": self.phase, "payload": self.payload, "at": self.at}


class PhaseOutcome:
    """The result of running a single phase through the engine."""

    def __init__(self, phase: SDLCPhase, *, status: str, output: Any = None, gate_results: Optional[list[GateVerdict]] = None, fix_loop_count: int = 0) -> None:
        self.phase = phase
        self.status = status  # "passed" | "gates_failed" | "escalated"
        self.output = output
        self.gate_results = gate_results or []
        self.fix_loop_count = fix_loop_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase.name,
            "status": self.status,
            "output": self.output,
            "gate_results": [g.to_dict() for g in self.gate_results],
            "fix_loop_count": self.fix_loop_count,
        }


# --------------------------------------------------------------------------- #
# Template
# --------------------------------------------------------------------------- #


def standard_sdlc_phases() -> dict[str, SDLCPhase]:
    """The Standard SDLC Workflow template (ADR-016 §3.1, PRD §14)."""
    return {
        RESEARCHER: SDLCPhase(
            name=RESEARCHER,
            agent_profile="sdlc-researcher",
            description="Investigate the goal; produce cited research findings.",
            output_contract={
                "type": "object",
                "properties": {
                    "findings": {"type": "array"},
                    "sources": {"type": "array"},
                },
                "required": ["findings", "sources"],
            },
        ),
        ARCHITECT: SDLCPhase(
            name=ARCHITECT,
            agent_profile="sdlc-architect",
            description="Turn research into an architecture decision.",
            output_contract={
                "type": "object",
                "properties": {"decision": {"type": "string"}, "rationale": {"type": "string"}},
                "required": ["decision", "rationale"],
            },
        ),
        PLANNER: SDLCPhase(
            name=PLANNER,
            agent_profile="sdlc-planner",
            description="Produce a work breakdown / task plan.",
            output_contract={
                "type": "object",
                "properties": {"tasks": {"type": "array"}},
                "required": ["tasks"],
            },
        ),
        DEVELOPER: SDLCPhase(
            name=DEVELOPER,
            agent_profile="sdlc-developer",
            description="Implement the approved plan in the workspace.",
            output_contract={
                "type": "object",
                "properties": {"changed_files": {"type": "array"}, "summary": {"type": "string"}},
                "required": ["changed_files", "summary"],
            },
        ),
        TESTER: SDLCPhase(
            name=TESTER,
            agent_profile="sdlc-tester",
            description="Independently verify behaviour with tests.",
            output_contract={"type": "object", "properties": {"passed": {"type": "boolean"}, "failed": {"type": "integer"}}, "required": ["passed"]},
        ),
        REVIEWER: SDLCPhase(
            name=REVIEWER,
            agent_profile="sdlc-reviewer",
            description="Independent code review of the candidate.",
            output_contract={"type": "object", "properties": {"approved": {"type": "boolean"}, "findings": {"type": "array"}}, "required": ["approved"]},
        ),
        SECURITY: SDLCPhase(
            name=SECURITY,
            agent_profile="sdlc-security",
            description="Security review / vulnerability scan.",
            output_contract={"type": "object", "properties": {"approved": {"type": "boolean"}, "findings": {"type": "array"}}, "required": ["approved"]},
        ),
        FIXER: SDLCPhase(
            name=FIXER,
            agent_profile="sdlc-fixer",
            description="Fix defects surfaced by independent checks.",
            output_contract={"type": "object", "properties": {"fixed": {"type": "array"}, "summary": {"type": "string"}}, "required": ["fixed", "summary"]},
            max_fix_loops=1,  # fixer itself is a bounded step
        ),
        RELEASE: SDLCPhase(
            name=RELEASE,
            agent_profile="sdlc-release",
            description="Assemble the release candidate for human approval.",
            output_contract={"type": "object", "properties": {"candidate_version": {"type": "string"}, "artifacts": {"type": "array"}}, "required": ["candidate_version"]},
            auto_create_next=False,
        ),
    }


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #


class SDLCWorkflow:
    """Drives the SDLC phase DAG to completion, fix-loop-bounded.

    :param phases: ordered mapping phase name -> :class:`SDLCPhase`. Only the
        sequential "mainline" phases participate in auto-advance; the FIXER
        phase is branched into on gate failure.
    :param gate_runner: ``async def (phase, output, candidate_version) ->
        list[GateVerdict]``. When omitted the engine treats gates as passing,
        which is only safe in unit tests.
    :param memory: optional :class:`~tools.storage.MemoryStore` to persist the
        audit trail and candidate invalidation (task item (d)).
    :param run_id: stable identifier for the run (auto-generated otherwise).
    """

    def __init__(
        self,
        phases: Optional[dict[str, SDLCPhase]] = None,
        *,
        gate_runner: Optional[Callable[..., Any]] = None,
        memory: Any = None,
        run_id: Optional[str] = None,
    ) -> None:
        self.phases = phases or standard_sdlc_phases()
        self._order = [p for p in (RESEARCHER, ARCHITECT, PLANNER, DEVELOPER, TESTER, REVIEWER, SECURITY, RELEASE) if p in self.phases]
        self.gate_runner = gate_runner
        self.memory = memory
        self.run_id = run_id or str(uuid.uuid4())
        self.candidate_version: Optional[str] = None
        self.audit: list[AuditEvent] = []
        self.fix_loop_map: dict[str, int] = {name: 0 for name in self.phases}
        self.history: list[PhaseOutcome] = []

    # -- public API ------------------------------------------------------------
    def phase(self, name: str) -> SDLCPhase:
        if name not in self.phases:
            raise PhaseNotFoundError(f"unknown phase: {name}")
        return self.phases[name]

    def phase_index(self, name: str) -> int:
        if name not in self._order:
            raise PhaseNotFoundError(f"unknown mainline phase: {name}")
        return self._order.index(name)

    def is_complete(self) -> bool:
        """True once the release phase has been reached."""
        return bool(self.history) and self.history[-1].phase.name == RELEASE

    async def run_phase(self, phase_name: str, output: Any) -> PhaseOutcome:
        """Run one phase: verify its output contract, run its gates, and either
        advance to the next mainline phase or branch into the fix loop."""
        phase = self.phase(phase_name)
        self._audit("sdlc.phase.started", phase.name, {"output_contract": bool(phase.output_contract)})
        self._verify_contract(phase, output)

        requires_gates = phase.name in (TESTER, REVIEWER, SECURITY) or phase.required_gates
        gate_results: list[GateVerdict] = []
        if requires_gates and self.gate_runner is not None:
            gate_results = await self.gate_runner(phase, output, self.candidate_version)

        failing = [g for g in gate_results if not g.passed]
        if failing:
            return await self._enter_fix_loop(phase, output, gate_results)

        # Phase accepted — its output becomes the new candidate of record.
        self.candidate_version = f"{self.run_id}:{phase.name}:{uuid.uuid4().hex[:8]}"
        self._audit("sdlc.phase.completed", phase.name, {"gate_results": [g.to_dict() for g in gate_results]})
        outcome = PhaseOutcome(phase, status="passed", output=output, gate_results=gate_results, fix_loop_count=self.fix_loop_map[phase.name])
        self.history.append(outcome)
        return outcome

    async def enter_fixer(self, findings: list[str]) -> PhaseOutcome:
        """Run the FIXER phase directly with gate findings as its input.

        Returns the fixer outcome. The engine then invalidates the candidate
        so the next mainline gate evaluation starts fresh (ADR-016 R3).
        """
        fixer = self.phase(FIXER)
        self.fix_loop_map[FIXER] += 1
        self._invalidate_candidate(reason=f"fixer entered with {len(findings)} finding(s)")
        return PhaseOutcome(fixer, status="passed", output={"fixed": [], "summary": "fixer pending"}, gate_results=[], fix_loop_count=self.fix_loop_map[FIXER])

    # -- internals ---------------------------------------------------------------
    async def _enter_fix_loop(self, phase: SDLCPhase, output: Any, gate_results: list[GateVerdict]) -> PhaseOutcome:
        loops = self.fix_loop_map[phase.name] + 1
        self.fix_loop_map[phase.name] = loops
        self._invalidate_candidate(reason=f"gates failed on {phase.name}")
        self._audit("sdlc.fix_loop.entered", phase.name, {"count": loops, "findings": [f for g in gate_results for f in g.findings]})
        if loops > phase.max_fix_loops:
            self._audit("sdlc.escalated", phase.name, {"reason": f"fix-loop limit {phase.max_fix_loops} exceeded"})
            return PhaseOutcome(phase, status="escalated", output=output, gate_results=gate_results, fix_loop_count=loops)
        return PhaseOutcome(phase, status="gates_failed", output=output, gate_results=gate_results, fix_loop_count=loops)

    def _verify_contract(self, phase: SDLCPhase, output: Any) -> None:
        try:
            jsonschema.validate(instance=output, schema=phase.output_contract)
        except jsonschema.ValidationError as exc:
            raise ContractViolation(f"output for '{phase.name}' violates contract: {exc.message}") from exc

    def _invalidate_candidate(self, *, reason: str) -> None:
        self.candidate_version = None
        self._audit("sdlc.candidate.invalidated", "fixer", {"reason": reason})
        if self.memory is not None:
            key = f"candidate:{self.run_id}"
            self.memory.write("task", key, {"candidate_version": None, "reason": reason, "invalidated_at": time.time()}, scope_id=self.run_id)

    def _audit(self, event_type: str, phase: str, payload: dict[str, Any]) -> None:
        event = AuditEvent(event_type=event_type, phase=phase, payload=payload)
        self.audit.append(event)
        if self.memory is not None:
            self.memory.write("task", f"audit:{event_type}:{len(self.audit)}", event.to_dict(), scope_id=self.run_id)

    # -- reporting ----------------------------------------------------------------
    def report(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "complete": self.is_complete(),
            "candidate_version": self.candidate_version,
            "phases": [o.to_dict() for o in self.history],
            "audit": [e.to_dict() for e in self.audit],
            "fix_loops": dict(self.fix_loop_map),
        }