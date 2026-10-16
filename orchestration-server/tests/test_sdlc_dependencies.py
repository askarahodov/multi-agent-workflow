"""#11 stage routing: untrusted workers cannot skip Contract Gate prerequisites.

Use real SQLite across Engine restarts. Independent agent and task status remain
owned by orchestration; order is per-run and persists in an additive table.
"""
from __future__ import annotations

import time
import pytest
from shared.qa_attestation import sign_qa_attestation

from orchestration_server.attempt_leases import AttemptLeaseService
from orchestration_server.engine import OrchestrationEngine
from orchestration_server.errors import BusinessRuleError, ConflictError

SCHEMA = {
    "type": "object", "required": ["summary"],
    "properties": {"summary": {"type": "string", "minLength": 1}},
    "additionalProperties": False,
}


@pytest.mark.parametrize("depends_on", [
    [-1], [1], [True], [False], ["0"], [0, 0], list(range(17)),
])
async def test_reject_bad_edges_before_any_task_persists(harness, depends_on):
    project = await harness.orch.create_project("demo")
    with pytest.raises(BusinessRuleError, match="dependencies"):
        await harness.orch.launch_run(
            project.id, "bad", [{"title": "start"}, {
                "title": "next", "depends_on": depends_on,
            }],
        )
    assert await harness.queries.list_runs() == []


async def test_native_leased_runs_require_contract_at_launch_claim_and_submit(harness):
    orch = harness.orch
    native = OrchestrationEngine(harness.sf, require_lease=True)
    project = await orch.create_project("strict-native-contract")
    agent = await orch.register_agent("native-no-bypass")
    global_contract = await orch.create_contract("shared-stage", SCHEMA)

    with pytest.raises(BusinessRuleError, match="explicit contract"):
        await native.launch_run(project.id, "missing-contract", [
            {"title": "research", "contract_id": global_contract.id},
            {"title": "implementation", "depends_on": [0]},
        ])
    assert await harness.queries.list_runs() == []

    # A legacy run remains readable, but a leased worker cannot claim it.
    legacy = await orch.launch_run(project.id, "legacy", [{"title": "legacy-stage"}])
    task = (await harness.queries.list_tasks(legacy.id))[0]
    with pytest.raises(ConflictError, match="explicit contract"):
        await native.claim_task(task.id, agent.id)
    assert (await harness.queries.get_task(task.id)).attempt_count == 0

    # A task already claimed by an old worker cannot bypass verification by
    # submitting through the leased API, even when it has a valid token.
    legacy_attempt = await orch.claim_task(task.id, agent.id)
    grant = await AttemptLeaseService(harness.sf, ttl_seconds=30).issue(
        legacy_attempt.id, agent.id,
    )
    with pytest.raises(ConflictError, match="explicit contract"):
        await native.submit(task.id, legacy_attempt.id, agent.id,
                            {"summary": "forged success"}, lease_token=grant.token)
    assert (await harness.queries.get_task(task.id)).status == "in_progress"

    accepted = await native.launch_run(project.id, "contracted", [
        {"title": "research", "contract_id": global_contract.id},
    ])
    assert len(await harness.queries.list_tasks(accepted.id)) == 1


async def test_launch_rejects_cross_project_workspace_without_persisting_run(harness):
    orch = harness.orch
    owner = await orch.create_project("workspace-owner")
    other = await orch.create_project("workspace-other")
    foreign = await orch.create_workspace(other.id, "foreign", path="/private/other")
    own = await orch.create_workspace(owner.id, "own", path="/private/owner")

    with pytest.raises(BusinessRuleError, match="Workspace does not belong"):
        await orch.launch_run(owner.id, "wrong-workspace", [{"title": "build"}],
                                  workspace_id=foreign.id)
    assert await harness.queries.list_runs() == []

    valid = await orch.launch_run(owner.id, "own-workspace", [{"title": "build"}],
                                  workspace_id=own.id)
    assert valid.workspace_id == own.id
    assert len(await harness.queries.list_tasks(valid.id)) == 1


async def test_late_cross_project_contract_rolls_back_all_sdlc_stages(harness):
    orch = harness.orch
    owner = await orch.create_project("contract-owner")
    other = await orch.create_project("contract-other")
    own = await orch.create_contract("own", SCHEMA, project_id=owner.id)
    foreign = await orch.create_contract("foreign", SCHEMA, project_id=other.id)
    global_contract = await orch.create_contract("global", SCHEMA)

    with pytest.raises(BusinessRuleError, match="Contract does not belong"):
        await orch.launch_run(owner.id, "wrong-contract", [
            {"title": "research", "contract_id": own.id},
            {"title": "review", "contract_id": foreign.id, "depends_on": [0]},
        ])
    # The first stage was flushed before validation of the second one.
    assert await harness.queries.list_runs() == []

    valid = await orch.launch_run(owner.id, "shared-contract", [
        {"title": "research", "contract_id": own.id},
        {"title": "review", "contract_id": global_contract.id, "depends_on": [0]},
    ])
    assert {t.contract_id for t in await harness.queries.list_tasks(valid.id)} == {
        own.id, global_contract.id,
    }


async def test_seven_sdlc_stages_unlock_only_after_contract_verification(harness_factory):
    h = await harness_factory()
    project = await h.orch.create_project("autonomous-project")
    contract = await h.orch.create_contract("stage-contract", SCHEMA, project_id=project.id)
    agent = await h.orch.register_agent("native-worker")
    stages = ("research", "architecture", "implementation", "tests",
              "review", "security", "release-prep")
    specs = [
        {
            "title": stage, "description": "Stage owned by native worker",
            "contract_id": contract.id,
            "depends_on": [i - 1] if i else [],
        }
        for i, stage in enumerate(stages)
    ]
    run = await h.orch.launch_run(project.id, "SDLC", specs,
                                  retry_policy={"max_attempts": 1})
    # Sorting by priority may differ; map by title to preserve DAG identity.
    tasks = {task.title: task for task in await h.queries.list_tasks(run.id)}
    assert len(tasks) == len(stages)
    for i, stage in enumerate(stages):
        task = tasks[stage]
        if i + 1 < len(stages):
            with pytest.raises(ConflictError, match="prerequisites"):
                await h.orch.claim_task(tasks[stages[i+1]].id, agent.id)
        attempt = await h.orch.claim_task(task.id, agent.id)
        # Only the server's Contract Gate can accept the actual stage.
        result = await h.orch.submit(
            task.id, attempt.id, agent.id, {"summary": f"finished {stage}"},
        )
        assert result.status == "completed"
        if i + 1 < len(stages):
            successor = await h.queries.get_task(tasks[stages[i+1]].id)
            upstream = successor.input_data["_maw_upstream"]
            assert upstream[-1]["task_id"] == task.id
            assert upstream[-1]["summary"] == f"finished {stage}"
        if i + 1 == 3:
            # Reopen the database on another engine/session to prove edges
            # are not in-memory adjacency or an agent-controlled flag.
            next_instance = await harness_factory()
            h = next_instance
            with pytest.raises(ConflictError, match="prerequisites"):
                await h.orch.claim_task(tasks[stages[4]].id, agent.id)
    assert (await h.queries.get_run(run.id)).status == "completed"
    for task in tasks.values():
        assert (await h.queries.get_task(task.id)).status == "completed"


async def test_invalid_contract_output_does_not_unlock_next_stage(harness):
    h = harness
    project = await h.orch.create_project("invalid-project")
    contract = await h.orch.create_contract("contract", SCHEMA, project_id=project.id)
    agent = await h.orch.register_agent("native-worker")
    run = await h.orch.launch_run(project.id, "stages", [
        {"title": "research", "contract_id": contract.id},
        {"title": "architecture", "depends_on": [0], "contract_id": contract.id},
    ], retry_policy={"max_attempts": 1})
    tasks = {t.title: t for t in await h.queries.list_tasks(run.id)}
    attempt = await h.orch.claim_task(tasks["research"].id, agent.id)
    result = await h.orch.submit(
        tasks["research"].id, attempt.id, agent.id, {"success": True},
    )
    assert result.status == "verification_failed"
    assert (await h.queries.get_run(run.id)).status == "failed"
    assert (await h.queries.get_task(tasks["architecture"].id)).input_data is None
    with pytest.raises(ConflictError):
        await h.orch.claim_task(tasks["architecture"].id, agent.id)
    assert (await h.queries.get_task(tasks["architecture"].id)).attempt_count == 0


async def test_prevent_forged_server_owned_handoff_and_duplicate_stage_refs(harness):
    h = harness
    p = await h.orch.create_project("handshake")
    for stages in (
        [{"title": "forge", "input_data": {"_maw_upstream": [{"summary": "fake"}]}}],
        [{"title": "root"}, {"title": "next", "depends_on": [0, 0]}],
    ):
        with pytest.raises(BusinessRuleError):
            await h.orch.launch_run(p.id, "tampered", stages)
    assert await h.queries.list_runs() == []


async def test_strict_native_sdlc_requires_operator_qa_for_handoff_and_completion(
    harness_factory,
):
    h = await harness_factory()
    key = "operator-qa-receipt-key-not-available-to-worker-00000001"
    strict = OrchestrationEngine(
        h.sf, require_lease=True, qa_attestation_key=key,
    )
    project = await h.orch.create_project("qa-proof-project")
    contract = await h.orch.create_contract("qa-summary", SCHEMA, project_id=project.id)
    agent = await h.orch.register_agent("native-ai-write-worker")
    run = await strict.launch_run(project.id, "qa-protected", [
        {"title": "implementation", "contract_id": contract.id},
        {"title": "release-prep", "contract_id": contract.id, "depends_on": [0]},
    ], retry_policy={"max_attempts": 1})
    stages = {t.title: t for t in await h.queries.list_tasks(run.id)}

    async def execute(task, sha):
        attempt = await strict.claim_task(task.id, agent.id)
        lease = await AttemptLeaseService(h.sf, ttl_seconds=30).issue(
            attempt.id, agent.id,
        )
        completed = await strict.submit(
            task.id, attempt.id, agent.id, {"summary": task.title},
            lease_token=lease.token,
            git_artifact={"commit_sha": sha, "changed_paths": ["out/code.txt"]},
        )
        assert completed.status == "completed"
        return attempt

    def evidence(task, attempt, sha):
        return sign_qa_attestation({
            "v": 1,
            "task_id": task.id,
            "attempt_id": attempt.id,
            "commit_sha": sha,
            "gate_run_ids": {
                "tester": "qa-tester-001",
                "reviewer": "qa-reviewer-001",
                "security": "qa-security-001",
            },
            "issued_by": "key-trustedqa001",
            "issued_at": int(time.time()),
        }, key)

    first_sha, last_sha = "a" * 40, "b" * 40
    first = await execute(stages["implementation"], first_sha)
    # Passing JSON schema and a worker-reported SHA is NOT independent QA.
    with pytest.raises(ConflictError, match="Independent QA"):
        await strict.claim_task(stages["release-prep"].id, agent.id)
    assert (await h.queries.get_task(stages["release-prep"].id)).attempt_count == 0

    first_receipt = evidence(stages["implementation"], first, first_sha)
    forged = dict(first_receipt, signature="f" * 64)
    with pytest.raises(ConflictError, match="signature"):
        await strict.register_qa_attestation(stages["implementation"].id, forged)
    wrong_git = sign_qa_attestation({
        **{k: v for k, v in first_receipt.items() if k != "signature"},
        "commit_sha": "c" * 40,
    }, key)
    with pytest.raises(ConflictError, match="Git attempt"):
        await strict.register_qa_attestation(stages["implementation"].id, wrong_git)
    with pytest.raises(ConflictError, match="task mismatch"):
        await strict.register_qa_attestation(stages["release-prep"].id, first_receipt)

    verified = await strict.register_qa_attestation(
        stages["implementation"].id, first_receipt,
    )
    assert verified["status"] == "verified"
    with pytest.raises(ConflictError, match="already been attested"):
        await strict.register_qa_attestation(
            stages["implementation"].id, first_receipt,
        )

    # The same durable DB is re-opened with a new engine, as after a restart.
    other = await harness_factory()
    restarted = OrchestrationEngine(
        other.sf, require_lease=True, qa_attestation_key=key,
    )
    assert (await other.queries.get_run(run.id)).status == "running"
    # A new successful stage still cannot finish the run without QA.
    next_attempt = await restarted.claim_task(stages["release-prep"].id, agent.id)
    lease = await AttemptLeaseService(other.sf, ttl_seconds=30).issue(
        next_attempt.id, agent.id,
    )
    result = await restarted.submit(
        stages["release-prep"].id, next_attempt.id, agent.id,
        {"summary": "ready for human approval"},
        lease_token=lease.token,
        git_artifact={"commit_sha": last_sha, "changed_paths": ["out/release.txt"]},
    )
    assert result.status == "completed"
    assert (await other.queries.get_run(run.id)).status == "running"

    receipt = evidence(stages["release-prep"], next_attempt, last_sha)
    await restarted.register_qa_attestation(stages["release-prep"].id, receipt)
    assert (await other.queries.get_run(run.id)).status == "completed"


def test_independent_qa_cannot_run_without_lease(harness):
    with pytest.raises(ValueError, match="leased native"):
        OrchestrationEngine(
            harness.sf, qa_attestation_key="qa-key-with-sufficient-length-for-tests-123",
        )
