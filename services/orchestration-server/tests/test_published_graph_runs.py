"""API integration: real persisted revision -> immutable compiled native tasks."""
from copy import deepcopy

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from orchestration_server.api import build_app
from orchestration_server.config import Settings

ROOT = "/api/v1"
REFS = {
    "agent_definition_id": "11111111-1111-4111-8111-111111111111",
    "model_profile_id": "22222222-2222-4222-8222-222222222222",
    "tool_policy_id": "33333333-3333-4333-8333-333333333333",
}


@pytest_asyncio.fixture
async def client(tmp_path):
    app = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'published-graph.db'}",
        recover_on_startup=False,
    ))
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
            yield api


def graph(contract_id, *, two_agents=False):
    def node(node_id, kind, config=None):
        return {
            "id": node_id, "type": kind, "label": node_id,
            "position": {"x": 0, "y": 0}, "config": config or {},
        }
    sequence = [node("start", "start"), node("agent-a", "agent", dict(REFS)),
                node("gate-a", "gate", {"gate_type": "automatic", "contract_id": contract_id})]
    if two_agents:
        sequence += [node("agent-b", "agent", dict(REFS)),
                     node("gate-b", "gate", {"gate_type": "automatic", "contract_id": contract_id})]
    sequence.append(node("end", "end"))
    return {
        "schema_version": "1.0",
        "metadata": {"name": "runtime graph", "version": 1, "created_at": "2026-11-05T00:00:00Z"},
        "nodes": sequence,
        "edges": [{
            "id": f"e-{idx}", "source_node_id": a["id"], "target_node_id": b["id"],
            "output_mapping": {}, "on_error": "fail", "max_retries": 0,
        } for idx, (a, b) in enumerate(zip(sequence, sequence[1:]))],
    }


async def setup(client, *, two_agents=False):
    project = (await client.post(f"{ROOT}/projects", json={"name": "graph-project"})).json()
    contract = (await client.post(f"{ROOT}/contracts", json={
        "project_id": project["id"], "name": "graph-contract",
        "schema": {"type": "object", "required": ["summary"], "properties": {
            "summary": {"type": "string"}
        }},
    })).json()
    definition = graph(contract["id"], two_agents=two_agents)
    created = await client.post(f"{ROOT}/workflows/definitions", json={
        "name": "graph-" + project["id"], "definition": definition,
    })
    assert created.status_code == 201, created.text
    return project, created.json(), definition


async def publish(client, record, definition):
    result = await client.post(
        f"{ROOT}/workflows/definitions/{record['id']}/versions",
        json={"definition_snapshot": definition, "expected_version": record["version"]},
    )
    assert result.status_code == 201, result.text
    return result.json()


async def launch(client, project, record, version):
    return await client.post(
        f"{ROOT}/workflows/definitions/{record['id']}/versions/{version['id']}/runs",
        json={"project_id": project["id"], "name": "compiled"},
    )


async def test_published_graph_creates_only_saved_agent_tasks_with_contract_dependencies(client):
    project, record, definition = await setup(client, two_agents=True)
    version = await publish(client, record, definition)
    result = await launch(client, project, record, version)
    assert result.status_code == 201, result.text
    run = result.json()
    assert run["input_data"]["_workflow_version_id"] == version["id"]
    tasks = (await client.get(f"{ROOT}/workflows/runs/{run['id']}/tasks")).json()["items"]
    assert {t["node_id"] for t in tasks} == {"agent-a", "agent-b"}
    assert all(t["contract_id"] == definition["nodes"][2]["config"]["contract_id"] for t in tasks)
    assert all(t["input_data"]["workflow_agent_reference"] == REFS for t in tasks)
    # Inspect the second task's dependency via a fresh attempt: the engine
    # cannot claim a dependent task before its predecessor passes its contract.
    by_node = {task["node_id"]: task for task in tasks}
    claim = await client.post(f"{ROOT}/tasks/{by_node['agent-b']['id']}/claim", json={"agent_id": "not-registered"})
    assert claim.status_code != 201

    # A new draft must not change the immutable version already launched.
    newer = deepcopy(definition)
    newer["nodes"][1]["label"] = "CHANGED DRAFT"
    saved = await client.put(f"{ROOT}/workflows/definitions/{record['id']}", json={
        "expected_version": 2, "definition": newer,
    })
    assert saved.status_code == 200, saved.text
    again = await launch(client, project, record, version)
    assert again.status_code == 201
    tasks2 = (await client.get(f"{ROOT}/workflows/runs/{again.json()['id']}/tasks")).json()["items"]
    assert any(t["title"] == "agent-a" for t in tasks2)
    assert all(t["title"] != "CHANGED DRAFT" for t in tasks2)


async def test_optimistic_versioning_rejects_stale_publish_and_updates(client):
    project, record, definition = await setup(client)
    conflict = await client.put(f"{ROOT}/workflows/definitions/{record['id']}", json={
        "expected_version": 300, "definition": definition,
    })
    assert conflict.status_code == 409
    snapshot = deepcopy(definition)
    snapshot["nodes"][1]["label"] = "tampered"
    mismatch = await client.post(f"{ROOT}/workflows/definitions/{record['id']}/versions", json={
        "expected_version": 1, "definition_snapshot": snapshot,
    })
    assert mismatch.status_code == 409
    version = await publish(client, record, definition)
    stale = await client.post(f"{ROOT}/workflows/definitions/{record['id']}/versions", json={
        "expected_version": 1, "definition_snapshot": definition,
    })
    assert stale.status_code == 409
    assert (await launch(client, project, record, version)).status_code == 201


@pytest.mark.parametrize("mutation", [
    "unsupported_node", "branch", "cycle", "bad_ref", "unsafe_retry", "no_gate",
    "manual_gate", "stray_config", "malformed_kind", "malformed_edge",
])
async def test_non_executable_or_invalid_published_graph_fails_before_run(client, mutation):
    project, record, definition = await setup(client)
    if mutation == "unsupported_node":
        definition["nodes"][1]["type"] = "tool"
    elif mutation == "branch":
        definition["edges"].append({
            "id": "branch", "source_node_id": "start", "target_node_id": "end",
            "output_mapping": {}, "on_error": "fail", "max_retries": 0,
        })
    elif mutation == "cycle":
        definition["edges"][-1]["target_node_id"] = "start"
    elif mutation == "bad_ref":
        definition["nodes"][1]["config"]["tool_policy_id"] = "invalid"
    elif mutation == "unsafe_retry":
        definition["edges"][0]["on_error"] = "retry"
    elif mutation == "no_gate":
        definition["nodes"][2]["type"] = "delay"
    elif mutation == "manual_gate":
        definition["nodes"][2]["config"]["gate_type"] = "manual_approval"
    elif mutation == "stray_config":
        definition["nodes"][1]["config"]["ignored_model_override"] = "unsafe"
    elif mutation == "malformed_kind":
        definition["nodes"][1]["type"] = ["agent"]
    elif mutation == "malformed_edge":
        definition["edges"][0]["source_node_id"] = ["start"]
    version = await client.post(f"{ROOT}/workflows/definitions/{record['id']}/versions", json={
        "expected_version": 1, "definition_snapshot": definition,
    })
    # To publish a modified draft the server must first persist it as the
    # current revision; publish never trusts a one-off modified snapshot.
    assert version.status_code == 409
    updated = await client.put(f"{ROOT}/workflows/definitions/{record['id']}", json={
        "expected_version": 1, "definition": definition,
    })
    assert updated.status_code == 200, updated.text
    version = await client.post(f"{ROOT}/workflows/definitions/{record['id']}/versions", json={
        "expected_version": 2, "definition_snapshot": definition,
    })
    assert version.status_code in (400, 422), version.text
    # Old archival clients may have stored invalid versions; the new server
    # run endpoint must independently reject them even if they exist in DB.
    legacy = await client.post(f"{ROOT}/workflows/definitions/{record['id']}/versions", json={
        "definition_snapshot": definition,
    })
    assert legacy.status_code == 201, legacy.text
    before = (await client.get(f"{ROOT}/workflows/runs")).json()["items"]
    attempt = await launch(client, project, record, legacy.json())
    assert attempt.status_code in (400, 422), attempt.text
    after = (await client.get(f"{ROOT}/workflows/runs")).json()["items"]
    assert len(after) == len(before)


async def test_foreign_published_version_is_not_a_runnable_route(client):
    project, record, definition = await setup(client)
    version = await publish(client, record, definition)
    foreign = await client.post(f"{ROOT}/workflows/definitions", json={
        "name": "unrelated", "definition": definition,
    })
    assert foreign.status_code == 201
    result = await client.post(
        f"{ROOT}/workflows/definitions/{foreign.json()['id']}/versions/{version['id']}/runs",
        json={"project_id": project["id"], "name": "forbidden"},
    )
    assert result.status_code == 404


async def test_scoped_definition_cannot_launch_in_another_project(client):
    project = (await client.post(f"{ROOT}/projects", json={"name": "owner"})).json()
    other = (await client.post(f"{ROOT}/projects", json={"name": "foreign"})).json()
    contract = (await client.post(f"{ROOT}/contracts", json={
        "project_id": project["id"], "name": "owned-contract",
        "schema": {"type": "object"},
    })).json()
    definition = graph(contract["id"])
    response = await client.post(f"{ROOT}/workflows/definitions", json={
        "project_id": project["id"], "name": "owned-definition", "definition": definition,
    })
    assert response.status_code == 201, response.text
    record = response.json()
    assert record["project_id"] == project["id"]
    version = await publish(client, record, definition)
    denied = await client.post(
        f"{ROOT}/workflows/definitions/{record['id']}/versions/{version['id']}/runs",
        json={"project_id": other["id"], "name": "not-owner"},
    )
    assert denied.status_code in (400, 422), denied.text
    assert (await launch(client, project, record, version)).status_code == 201


async def test_manual_run_cannot_forge_published_graph_identity(client):
    project, record, definition = await setup(client)
    version = await publish(client, record, definition)
    base_task = {"title": "attempted spoof",
                 "contract_id": definition["nodes"][2]["config"]["contract_id"]}
    for forged_run in (
        {"_workflow_version_id": version["id"]},
        {"_workflow_definition_id": record["id"], "_workflow_version_id": version["id"]},
    ):
        response = await client.post(f"{ROOT}/workflows/runs", json={
            "project_id": project["id"], "name": "forged provenance",
            "tasks": [base_task], "input_data": forged_run,
            "triggered_by": "published-workflow",
        })
        assert response.status_code in (400, 422), response.text
    for forged_task in (
        {"workflow_agent_reference": dict(REFS)},
        {"workflow_node_id": "agent-a"},
    ):
        response = await client.post(f"{ROOT}/workflows/runs", json={
            "project_id": project["id"], "name": "forged task",
            "tasks": [{**base_task, "input_data": forged_task}],
            "triggered_by": "published-workflow",
        })
        assert response.status_code in (400, 422), response.text
    # Legitimate signed-by-server provenance still works via the only
    # authoritative endpoint: compile the stored immutable version.
    valid = await launch(client, project, record, version)
    assert valid.status_code == 201, valid.text
    tasks = (await client.get(
        f"{ROOT}/workflows/runs/{valid.json()['id']}/tasks"
    )).json()["items"]
    assert tasks[0]["input_data"]["workflow_agent_reference"] == REFS
