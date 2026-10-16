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
async def test_independent_qa_proof_tracks_real_git_subject_and_disk_evidence(harness, clean_workspace):
    import subprocess
    import hashlib
    from quality_gates.errors import GateFailedError

    ws = clean_workspace
    def git(*args):
        return subprocess.run(
            ["git", "-C", str(ws), *args], capture_output=True,
            text=True, check=True, timeout=10,
        ).stdout.strip()
    git("init", "-q")
    git("config", "user.name", "QA Runner")
    git("config", "user.email", "qa@example.invalid")
    git("add", ".")
    git("commit", "-qm", "fixture")
    sha = git("rev-parse", "HEAD")
    attempt = "11111111-2222-3333-4444-555555555555"
    subject = {"attempt_id": attempt, "commit_sha": sha}
    context = {"qa_subject": subject, "commands": {
        "unit": [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_demo.py"]
    }}
    for gate in ("tester", "reviewer", "security"):
        response = await harness.pipeline.run_gate(
            "qa-stage", str(ws), gate,
            context if gate == "tester" else {"qa_subject": subject},
        )
        assert response["status"] == "passed"
    proof = await harness.pipeline.qa_proof("qa-stage", attempt, sha)
    assert proof["passed"] is True
    assert proof["commit_sha"] == sha
    assert proof["evidence_sha256"] == proof["evidence_ref"].rsplit("/", 1)[-1]
    with pytest.raises(GateFailedError, match="Missing"):
        await harness.pipeline.qa_proof("qa-stage", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", sha)

    runs = await harness.pipeline.runs_for_task("qa-stage")
    target = next(r for r in runs if r["gate"] == "security")
    evidence = list(
        (harness.settings.evidence_root / "qa-stage" / target["id"]).glob("secret_*.json")
    )
    assert evidence
    evidence[0].write_text('{"tampered":true}', encoding="utf-8")
    with pytest.raises(GateFailedError, match="checksum"):
        await harness.pipeline.qa_proof("qa-stage", attempt, sha)

    # A different dirty checkout can never mint a bound positive QA result.
    (ws / "src" / "uncommitted.py").write_text("x=1\n")
    with pytest.raises(GateFailedError, match="clean"):
        await harness.pipeline.run_gate("qa-stage", str(ws), "reviewer", {"qa_subject": subject})
