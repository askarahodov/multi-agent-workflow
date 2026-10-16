"""#11 stage routing: untrusted workers cannot skip Contract Gate prerequisites.

Use real SQLite across Engine restarts. Independent agent and task status remain
owned by orchestration; order is per-run and persists in an additive table.
"""
from __future__ import annotations

import pytest

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


@pytest.mark.asyncio
async def test_strict_qa_handoff_requires_operator_attestation_bound_to_git_sha(harness):
    from orchestration_server.models import TaskGitEvidence
    from orchestration_server.errors import BusinessRuleError

    project = await harness.orch.create_project("qa-isolated")
    contract = await harness.orch.create_contract("summary", SCHEMA, project_id=project.id)
    agent = await harness.orch.register_agent("native-writer")
    run = await harness.orch.launch_run(project.id, "strict-sdlc", [
        {"title": "implementation", "contract_id": contract.id},
        {"title": "tests", "contract_id": contract.id, "depends_on": [0]},
    ])
    tasks = {t.title: t for t in await harness.queries.list_tasks(run.id)}
    implementation = tasks["implementation"]
    tests = tasks["tests"]
    attempt = await harness.orch.claim_task(implementation.id, agent.id)
    await harness.orch.submit(
        implementation.id, attempt.id, agent.id, {"summary": "implemented"},
    )
    # A worker-reported SHA on its own has no independent QA authority.
    sha = "a" * 40
    async with harness.sf() as session:
        session.add(TaskGitEvidence(
            attempt_id=attempt.id, task_id=implementation.id,
            commit_sha=sha, changed_paths=["out/implementation.txt"],
            provenance="worker_reported",
        ))
        await session.commit()

    strict = OrchestrationEngine(harness.sf, require_qa_attestation=True)
    with pytest.raises(ConflictError, match="Independent QA attestation required"):
        await strict.claim_task(tests.id, agent.id)
    with pytest.raises(ConflictError, match="must match completed Git attempt"):
        await strict.attest_qa(
            implementation.id, commit_sha="b" * 40, evidence_sha256="c" * 64,
            evidence_ref="qg://report-1", operator_subject="key-" + "a" * 12,
        )
    with pytest.raises(BusinessRuleError, match="Valid QA evidence"):
        await strict.attest_qa(
            implementation.id, commit_sha=sha, evidence_sha256="c" * 64,
            evidence_ref="qg://report-1", operator_subject="fake-human",
        )
    attestation = await strict.attest_qa(
        implementation.id, commit_sha=sha, evidence_sha256="c" * 64,
        evidence_ref="qg://report-1", operator_subject="key-" + "a" * 12,
    )
    assert attestation.commit_sha == sha
    with pytest.raises(ConflictError, match="immutable"):
        await strict.attest_qa(
            implementation.id, commit_sha=sha, evidence_sha256="c" * 64,
            evidence_ref="qg://report-2", operator_subject="key-" + "a" * 12,
        )
    # The persisted operator attestation gates the next claim, even after
    # constructing a new engine (equivalent to a restarted control plane).
    restarted = OrchestrationEngine(harness.sf, require_qa_attestation=True)
    next_attempt = await restarted.claim_task(tests.id, agent.id)
    assert next_attempt.status == "running"

