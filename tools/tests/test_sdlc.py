"""Tests for the SDLC phase engine (task item (b), ADR-016)."""

from __future__ import annotations

import asyncio

import pytest

from tools.ci.sdlc import (
    BUILTIN_GATES,
    ContractViolation,
    FIXER,
    GateVerdict,
    SDLCWorkflow,
    standard_sdlc_phases,
)
from tools.storage import MemoryStore


async def _passing_gate_runner(phase, output, candidate_version):
    return [GateVerdict(gate=g, passed=True, findings=[]) for g in phase.required_gates or BUILTIN_GATES]


async def _failing_gate_runner(phase, output, candidate_version):
    return [GateVerdict(gate=g, passed=False, findings=[f"{g} failed"]) for g in phase.required_gates or BUILTIN_GATES]


def test_standard_phases_cover_sdlc():
    phases = standard_sdlc_phases()
    for name in ("researcher", "architect", "planner", "developer", "tester", "reviewer", "security", "fixer", "release"):
        assert name in phases


def test_contract_violation_rejected():
    engine = SDLCWorkflow()
    with pytest.raises(ContractViolation):
        # developer output missing required "summary"
        asyncio.run(engine.run_phase("developer", {"changed_files": []}))


async def test_full_mainline_flow_passes():
    engine = SDLCWorkflow(gate_runner=_passing_gate_runner, run_id="r1")
    await engine.run_phase("researcher", {"findings": [], "sources": ["x"]})
    await engine.run_phase("architect", {"decision": "d", "rationale": "r"})
    await engine.run_phase("planner", {"tasks": []})
    await engine.run_phase("developer", {"changed_files": ["a"], "summary": "s"})
    await engine.run_phase("tester", {"passed": True, "failed": 0})
    await engine.run_phase("reviewer", {"approved": True, "findings": []})
    await engine.run_phase("security", {"approved": True, "findings": []})
    await engine.run_phase("release", {"candidate_version": "cand", "artifacts": []})
    assert engine.is_complete() is True
    assert engine.report()["complete"] is True


async def test_gate_failure_drives_fixer_and_invalidates_candidate():
    engine = SDLCWorkflow(gate_runner=_failing_gate_runner, run_id="r2")
    await engine.run_phase("researcher", {"findings": [], "sources": []})
    await engine.run_phase("architect", {"decision": "d", "rationale": "r"})
    await engine.run_phase("planner", {"tasks": []})
    await engine.run_phase("developer", {"changed_files": ["a"], "summary": "s"})
    # Independent gates run at the TESTER phase; they fail → fix loop.
    out = await engine.run_phase("tester", {"passed": True, "failed": 0})
    assert out.status == "gates_failed"
    assert out.fix_loop_count == 1
    # Candidate invalidated on fix-loop entry (ADR-016 R3).
    assert engine.candidate_version is None
    types = {e.event_type for e in engine.audit}
    assert "sdlc.fix_loop.entered" in types
    assert "sdlc.candidate.invalidated" in types


async def test_fix_loop_limit_escalates():
    async def flaky_gates(phase, output, candidate_version):
        return [GateVerdict(gate=g, passed=False, findings=["nope"]) for g in phase.required_gates or BUILTIN_GATES]

    engine = SDLCWorkflow(gate_runner=flaky_gates, run_id="r3")
    for ph in ("researcher", "architect", "planner"):
        payload = {"findings": [], "sources": []} if ph == "researcher" else ({"decision": "d", "rationale": "r"} if ph == "architect" else {"tasks": []})
        await engine.run_phase(ph, payload)
    await engine.run_phase("developer", {"changed_files": ["a"], "summary": "s"})
    out = None
    for _ in range(6):
        out = await engine.run_phase("tester", {"passed": True, "failed": 0})
        if out.status == "escalated":
            break
        assert out.status == "gates_failed"
    assert out.status == "escalated"
    types = {e.event_type for e in engine.audit}
    assert "sdlc.escalated" in types


async def test_memory_persists_audit_and_invalidation():
    mem = MemoryStore()
    try:
        engine = SDLCWorkflow(gate_runner=_failing_gate_runner, memory=mem, run_id="r4")
        await engine.run_phase("researcher", {"findings": [], "sources": []})
        await engine.run_phase("architect", {"decision": "d", "rationale": "r"})
        await engine.run_phase("planner", {"tasks": []})
        await engine.run_phase("developer", {"changed_files": ["a"], "summary": "s"})
        await engine.run_phase("tester", {"passed": True, "failed": 0})
        # Candidate invalidation was persisted to memory.
        cand = mem.get("task", "candidate:r4", scope_id="r4")
        assert cand is not None and cand["value"]["candidate_version"] is None
        # Audit events persisted.
        found = mem.search("sdlc", level="task", scope_id="r4")
        assert len(found) >= 1
    finally:
        mem.close()


async def test_fixer_entered_directly():
    engine = SDLCWorkflow()
    out = await engine.enter_fixer(["finding: a"])
    assert out.phase.name == FIXER
    assert out.status == "passed"