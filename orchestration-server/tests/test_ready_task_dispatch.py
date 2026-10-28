"""Read-only native dispatcher readiness is dependency/contract aware."""
import pytest
from orchestration_server.engine import OrchestrationEngine
from orchestration_server.errors import BusinessRuleError


async def test_ready_tasks_do_not_bypass_dependencies_and_claim(harness):
    orch = harness.orch
    project = await orch.create_project("ready-project")
    contract = await orch.create_contract("ready-contract", {
        "type": "object", "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    })
    agent = await orch.register_agent("ready-agent")
    run = await orch.launch_run(project.id, "ready-run", [
        {"title": "first", "contract_id": contract.id, "priority": 10},
        {"title": "next", "contract_id": contract.id, "depends_on": [0]},
    ])
    tasks = {task.title: task for task in await harness.queries.list_tasks(run.id)}
    ready = await orch.ready_tasks()
    assert [item["task_id"] for item in ready] == [tasks["first"].id]
    assert ready[0]["contract_id"] == contract.id
    assert (await harness.queries.get_task(tasks["first"].id)).status == "pending"
    await orch.claim_task(tasks["first"].id, agent.id)
    assert await orch.ready_tasks() == []


async def test_strict_ready_tasks_skip_legacy_without_contract(harness):
    orch = harness.orch
    project = await orch.create_project("strict-ready")
    run = await orch.launch_run(project.id, "legacy", [{"title": "no-contract"}])
    strict = OrchestrationEngine(harness.sf, require_lease=True)
    assert await strict.ready_tasks() == []
    assert len(await orch.ready_tasks()) == 1


@pytest.mark.parametrize("limit", [0, -1, 101, True, "10"])
async def test_ready_task_limit_fail_closed(harness, limit):
    with pytest.raises(BusinessRuleError):
        await harness.orch.ready_tasks(limit)
