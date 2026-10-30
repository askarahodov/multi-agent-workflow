"""Tests for the pipeline orchestrator: gate enforcement, evidence, transitions,
and the release human-approval gate.

These directly verify the acceptance criteria:
* gates are enforced (transition blocked until all required gates pass);
* evidence is stored and auditable (runs + checksummed evidence persisted);
* release prep produces a verifiable artifact awaiting human approval.
"""

from __future__ import annotations

import sys

import pytest

from quality_gates.errors import (
    GateNotFoundError,
    ReleaseNotAwaitingApprovalError,
    TransitionForbiddenError,
)
from quality_gates.pipeline import GatePipeline

from conftest import FAKE_AWS_KEY

REQ = ("tester", "reviewer", "security", "release_prep")


async def _all_pass(harness, workspace, task_id="task1"):
    """Run all four required gates against a clean workspace so they pass."""
    tester_ctx = {
        "commands": {"unit": [sys.executable, "-m", "pytest", "-q", "--no-header", "--collect-only"]}
    }
    r_tester = await harness.pipeline.run_gate(task_id, str(workspace), "tester", tester_ctx)
    r_rev = await harness.pipeline.run_gate(task_id, str(workspace), "reviewer")
    r_sec = await harness.pipeline.run_gate(task_id, str(workspace), "security")
    r_rel = await harness.pipeline.run_gate(
        task_id, str(workspace), "release_prep", {"version": "0.1.0"}
    )
    return [r_tester, r_rev, r_sec, r_rel]


def test_registry_contains_builtin_gates():
    from quality_gates.gates.base import GATE_REGISTRY

    for name in REQ:
        assert name in GATE_REGISTRY.names()


@pytest.mark.asyncio
async def test_transition_blocked_without_any_gate(harness, clean_workspace):
    with pytest.raises(TransitionForbiddenError):
        await harness.pipeline.transition("task1", "review")


@pytest.mark.asyncio
async def test_transition_blocked_when_gate_fails(harness, tmp_path):
    ws = tmp_path / "app"
    ws.mkdir()
    (ws / "code.py").write_text(f"SECRET = '{FAKE_AWS_KEY}'\n")  # fails security
    (ws / "pyproject.toml").write_text("x\n")
    (ws / "README.md").write_text("x\n")

    # run only security gate -> it fails
    run = await harness.pipeline.run_gate("task1", str(ws), "security")
    assert run["status"] == "failed"

    check = await harness.pipeline.required_gates_passed("task1")
    assert check["passed"] is False
    assert "security" in check["missing"]

    with pytest.raises(TransitionForbiddenError):
        await harness.pipeline.transition("task1", "review")


@pytest.mark.asyncio
async def test_all_gates_passed_allows_transition(harness, clean_workspace):
    runs = await _all_pass(harness, clean_workspace)
    for r in runs:
        assert r["status"] == "passed", r
    out = await harness.pipeline.transition("task1", "review")
    assert out["allowed"] is True
    for g in REQ:
        assert out["gates"][g] == "passed"


@pytest.mark.asyncio
async def test_evidence_is_persisted_and_auditable(harness, clean_workspace):
    runs = await _all_pass(harness, clean_workspace)
    for run in runs:
        detail = await harness.pipeline.get_run(run["task_id"], run["id"])
        assert detail["status"] == "passed"
        assert len(detail["evidence"]) > 0
        for ev in detail["evidence"]:
            assert ev["checksum"]  # every evidence item carries a checksum
        # checksummed JSON documents exist under the evidence root for this run
        run_dir = harness.settings.evidence_root / run["task_id"] / run["id"]
        assert run_dir.exists()
        docs = list(run_dir.glob("*.json"))
        assert len(docs) == len(detail["evidence"])
        # and every stored document verifies against its own embedded checksum
        for doc in docs:
            assert harness.pipeline.evidence_store.verify(
                str(doc.relative_to(harness.settings.evidence_root))
            )


@pytest.mark.asyncio
async def test_runs_for_task_returns_trail(harness, clean_workspace):
    await _all_pass(harness, clean_workspace)
    runs = await harness.pipeline.runs_for_task("task1")
    assert len(runs) == 4
    names = {r["gate"] for r in runs}
    assert names == set(REQ)


@pytest.mark.asyncio
async def test_unknown_gate_raises(harness, clean_workspace):
    with pytest.raises(GateNotFoundError):
        await harness.pipeline.run_gate("task1", str(clean_workspace), "nope")


# --- release lifecycle / human gate --------------------------------------------


@pytest.mark.asyncio
async def test_release_candidate_created_awaiting_approval(harness, clean_workspace):
    cand = await harness.pipeline.create_release_candidate("task1", str(clean_workspace), "1.0.0")
    assert cand["status"] == "awaiting_approval"
    assert cand["id"]
    assert cand["artifact_checksum"]
    assert (harness.settings.artifact_root / f"release-1.0.0.tar.gz").exists()


@pytest.mark.asyncio
async def test_release_requires_human_approval(harness, clean_workspace):
    cand = await harness.pipeline.create_release_candidate("task1", str(clean_workspace), "1.0.0")
    # agent cannot self-approve
    with pytest.raises(Exception, match="cannot approve"):
        await harness.pipeline.approve_release_candidate(cand["id"], "release_prep")
    # still awaiting approval (no silent advance)
    listing = await harness.pipeline.list_release_candidates("task1")
    assert listing[0]["status"] == "awaiting_approval"

    # human approval works and is recorded
    approved = await harness.pipeline.approve_release_candidate(cand["id"], "human-qe")
    assert approved["status"] == "approved"
    assert approved["approved_by"] == "human-qe"
    assert approved["approved_at"]


@pytest.mark.asyncio
async def test_cannot_approve_twice_or_wrong_state(harness, clean_workspace):
    cand = await harness.pipeline.create_release_candidate("task1", str(clean_workspace), "1.0.0")
    await harness.pipeline.approve_release_candidate(cand["id"], "human-qe")
    with pytest.raises(ReleaseNotAwaitingApprovalError):
        await harness.pipeline.approve_release_candidate(cand["id"], "human-qe")


@pytest.mark.asyncio
async def test_release_rejection(harness, clean_workspace):
    cand = await harness.pipeline.create_release_candidate("task1", str(clean_workspace), "1.0.0")
    rejected = await harness.pipeline.reject_release_candidate(cand["id"], "human-manager")
    assert rejected["status"] == "rejected"
    assert rejected["approved_by"] == "human-manager"


@pytest.mark.asyncio
async def test_release_artifact_is_verifiable(harness, clean_workspace):
    from quality_gates.evidence import checksum_file

    cand = await harness.pipeline.create_release_candidate("task1", str(clean_workspace), "1.0.0")
    art = harness.settings.artifact_root / f"release-1.0.0.tar.gz"
    assert checksum_file(art) == cand["artifact_checksum"]


@pytest.mark.asyncio
async def test_run_detail_is_bound_to_own_task_and_evidence(harness, clean_workspace):
    from quality_gates.errors import GateFailedError

    result = await harness.pipeline.run_gate("owner-task", str(clean_workspace), "reviewer")
    assert result["status"] == "passed"
    own = await harness.pipeline.get_run("owner-task", result["id"])
    assert own["task_id"] == "owner-task"
    assert own["id"] == result["id"]
    assert own["evidence"]  # Ensure this check covers populated evidence, not an empty row.
    with pytest.raises(GateFailedError, match="run not found"):
        await harness.pipeline.get_run("other-task", result["id"])


@pytest.mark.asyncio
async def test_gate_exception_persists_terminal_failed_run(harness, clean_workspace, monkeypatch):
    from quality_gates.errors import GateFailedError
    from quality_gates.gates.base import GATE_REGISTRY

    gate_cls = GATE_REGISTRY.get("reviewer")

    def crash(_self, _workspace, _context=None):
        raise RuntimeError("synthetic reviewer crash")

    monkeypatch.setattr(gate_cls, "execute", crash)
    with pytest.raises(GateFailedError, match="synthetic reviewer crash"):
        await harness.pipeline.run_gate("crash-task", str(clean_workspace), "reviewer")

    runs = await harness.pipeline.runs_for_task("crash-task")
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["finished_at"] is not None
    assert "RuntimeError" in runs[0]["summary"]
    assert (await harness.pipeline.required_gates_passed("crash-task"))["passed"] is False


@pytest.mark.asyncio
async def test_git_postcheck_failure_persists_terminal_failed_run(
    harness, clean_workspace, monkeypatch,
):
    from quality_gates.errors import GateFailedError

    def check_checkout(_workspace, _sha, *, after):
        if after:
            raise GateFailedError("QA Git HEAD mismatch or dirty checkout")

    monkeypatch.setattr(harness.pipeline, "_check_git_checkout", check_checkout)
    with pytest.raises(GateFailedError, match="QA Git HEAD mismatch"):
        await harness.pipeline.run_gate(
            "postcheck-task", str(clean_workspace), "reviewer",
            qa_attempt_id="attempt-01", qa_commit_sha="a" * 40,
        )
    runs = await harness.pipeline.runs_for_task("postcheck-task")
    assert len(runs) == 1
    assert runs[0]["status"] == "failed"
    assert runs[0]["finished_at"] is not None
    detail = await harness.pipeline.get_run("postcheck-task", runs[0]["id"])
    assert detail["attempt_id"] == "attempt-01"
    assert detail["commit_sha"] == "a" * 40
    assert detail["status"] == "failed"
    with pytest.raises(GateFailedError, match="missing or failed"):
        await harness.pipeline.issue_qa_attestation(
            "postcheck-task", "attempt-01", "a" * 40,
            issued_by="operator", signing_key="operator-key",
        )


@pytest.mark.asyncio
async def test_equal_timestamp_retry_failure_blocks_transition(harness):
    from datetime import datetime, timezone
    from quality_gates.models import GateRun

    task = "same-time-retries"
    when = datetime(2026, 10, 28, tzinfo=timezone.utc)
    # Insert the newer (lexically greater ID) FAILED retry first, so a
    # naive query/insertion order would incorrectly pick the older PASS.
    async with harness.sf() as session:
        session.add(GateRun(id="z-retry", task_id=task, gate_name="tester",
                            status="failed", started_at=when, finished_at=when))
        session.add(GateRun(id="a-old-pass", task_id=task, gate_name="tester",
                            status="passed", started_at=when, finished_at=when))
        for name in ("reviewer", "security", "release_prep"):
            session.add(GateRun(task_id=task, gate_name=name,
                                status="passed", started_at=when, finished_at=when))
        await session.commit()

    state = await harness.pipeline.required_gates_passed(task)
    assert state["passed"] is False
    assert state["per_gate"]["tester"] == "failed"
    assert state["missing"] == ["tester"]
    with pytest.raises(TransitionForbiddenError):
        await harness.pipeline.transition(task, "review")
    trail = await harness.pipeline.runs_for_task(task)
    assert [run["id"] for run in trail if run["gate"] == "tester"] == [
        "z-retry", "a-old-pass"
    ]

    # A genuinely later pass can restore readiness.
    async with harness.sf() as session:
        session.add(GateRun(id="z-recovered", task_id=task, gate_name="tester",
                            status="passed", started_at=datetime(2026, 10, 29, tzinfo=timezone.utc),
                            finished_at=datetime(2026, 10, 29, tzinfo=timezone.utc)))
        await session.commit()
    assert (await harness.pipeline.required_gates_passed(task))["passed"] is True
    assert (await harness.pipeline.transition(task, "review"))["allowed"] is True
