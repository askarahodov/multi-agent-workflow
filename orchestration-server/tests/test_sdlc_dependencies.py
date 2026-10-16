"""#11 stage routing: untrusted workers cannot skip Contract Gate prerequisites.

Use real SQLite across Engine restarts. Independent agent and task status remain
owned by orchestration; order is per-run and persists in an additive table.
"""
from __future__ import annotations

import pytest

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
