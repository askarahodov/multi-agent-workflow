"""REST API contract tests (end-to-end through the ASGI app)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from orchestration_server.api import build_app
from orchestration_server.config import Settings

RUN_TASK = {
    "title": "t1",
    "contract_id": None,
}
VALID_CONTRACT = {
    "type": "object",
    "required": ["summary"],
    "properties": {"summary": {"type": "string", "minLength": 1}},
    "additionalProperties": False,
}


def _settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}",
        recover_on_startup=True,
    )


@pytest_asyncio.fixture
async def api(tmp_path):
    app = build_app(_settings(tmp_path))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client


async def test_health_and_openapi(api):
    r = await api.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    spec = (await api.get("/openapi.json")).json()
    assert spec["openapi"].startswith("3.")
    assert "/workflows/runs" in spec["paths"]


async def test_full_task_lifecycle_over_rest(api):
    # Project
    r = await api.post("/projects", json={"name": "p1", "description": "demo"})
    assert r.status_code == 201, r.text
    project = r.json()

    # Contract
    r = await api.post(
        "/contracts",
        json={"name": "c1", "project_id": project["id"], "schema": VALID_CONTRACT},
    )
    assert r.status_code == 201, r.text
    contract = r.json()
    assert contract["schema"] == VALID_CONTRACT

    # Agent
    r = await api.post(
        "/agents/register", json={"name": "agent-1", "metadata": {"role": "worker"}}
    )
    assert r.status_code == 201, r.text
    agent = r.json()
    assert agent["metadata"] == {"role": "worker"}

    # Run with one contract-bound task
    r = await api.post(
        "/workflows/runs",
        json={
            "project_id": project["id"],
            "name": "run-1",
            "tasks": [{"title": "t1", "contract_id": contract["id"]}],
            "retry_policy": {"max_attempts": 1},
        },
    )
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "running"

    tasks = (await api.get(f"/workflows/runs/{run['id']}/tasks")).json()
    assert len(tasks) == 1
    task = tasks[0]
    assert task["status"] == "pending"

    # Claim
    r = await api.post(f"/tasks/{task['id']}/claim", json={"agent_id": agent["id"]})
    assert r.status_code == 201, r.text
    attempt = r.json()
    assert attempt["status"] == "running"

    # Submit valid output -> engine completes task and run
    r = await api.post(
        f"/tasks/{task['id']}/attempts/{attempt['id']}/submit",
        params={"agent_id": agent["id"]},
        json={"output": {"summary": "done"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"

    run_after = (await api.get(f"/workflows/runs/{run['id']}")).json()
    assert run_after["status"] == "completed"
    task_after = (await api.get(f"/tasks/{task['id']}")).json()
    assert task_after["status"] == "completed"
    assert task_after["output_data"] == {"summary": "done"}
    assert (await api.get(f"/agents")).json()[0]["status"] == "idle"


async def test_invalid_submission_is_rejected_and_task_requeued(api):
    project = (await api.post("/projects", json={"name": "p"})).json()
    contract = (
        await api.post(
            "/contracts",
            json={"name": "c", "project_id": project["id"], "schema": VALID_CONTRACT},
        )
    ).json()
    agent = (await api.post("/agents/register", json={"name": "a"})).json()
    run = (
        await api.post(
            "/workflows/runs",
            json={
                "project_id": project["id"],
                "name": "run",
                "tasks": [{"title": "t", "contract_id": contract["id"]}],
                "retry_policy": {"max_attempts": 2, "base_delay_seconds": 0},
            },
        )
    ).json()
    task = (await api.get(f"/workflows/runs/{run['id']}/tasks")).json()[0]
    attempt = (
        await api.post(f"/tasks/{task['id']}/claim", json={"agent_id": agent["id"]})
    ).json()

    r = await api.post(
        f"/tasks/{task['id']}/attempts/{attempt['id']}/submit",
        params={"agent_id": agent["id"]},
        json={"output": {"summary": ""}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "verification_failed"
    # Platform re-queued the task; run is not complete.
    assert (await api.get(f"/tasks/{task['id']}")).json()["status"] == "pending"
    assert (await api.get(f"/workflows/runs/{run['id']}")).json()["status"] == "running"


async def test_error_responses_are_problem_details(api):
    # 404
    r = await api.get("/tasks/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body["status"] == 404
    assert body["title"]
    assert body["detail"]
    assert body["type"].startswith("urn:orchestration:error:")

    # 409 duplicate project
    await api.post("/projects", json={"name": "dup"})
    r = await api.post("/projects", json={"name": "dup"})
    assert r.status_code == 409
    assert r.json()["type"] == "urn:orchestration:error:duplicate-key"

    # 422 invalid contract schema
    r = await api.post("/contracts", json={"name": "bad", "schema": {"type": "zzz"}})
    assert r.status_code == 422
    assert r.json()["type"] == "urn:orchestration:error:business-rule"

    # 400 missing agent_id on submit
    r = await api.post("/tasks/x/attempts/y/submit", json={"output": {}})
    assert r.status_code == 400


async def test_agent_cannot_claim_twice_or_submit_for_other_agent(api):
    project = (await api.post("/projects", json={"name": "p"})).json()
    agent1 = (await api.post("/agents/register", json={"name": "a1"})).json()
    agent2 = (await api.post("/agents/register", json={"name": "a2"})).json()
    run = (
        await api.post(
            "/workflows/runs",
            json={
                "project_id": project["id"],
                "name": "run",
                "tasks": [{"title": "t"}],
            },
        )
    ).json()
    task = (await api.get(f"/workflows/runs/{run['id']}/tasks")).json()[0]

    attempt = (
        await api.post(f"/tasks/{task['id']}/claim", json={"agent_id": agent1["id"]})
    ).json()

    # Second claim is a conflict.
    r = await api.post(f"/tasks/{task['id']}/claim", json={"agent_id": agent2["id"]})
    assert r.status_code == 409

    # A different agent cannot submit on someone else's attempt.
    r = await api.post(
        f"/tasks/{task['id']}/attempts/{attempt['id']}/submit",
        params={"agent_id": agent2["id"]},
        json={"output": {"summary": "x"}},
    )
    assert r.status_code == 409


async def test_api_enforces_contract_verification_not_self_declaration(api):
    """A submit that claims success but lacks the contract fields is rejected."""
    project = (await api.post("/projects", json={"name": "p"})).json()
    contract = (
        await api.post(
            "/contracts",
            json={"name": "c", "schema": VALID_CONTRACT, "project_id": project["id"]},
        )
    ).json()
    agent = (await api.post("/agents/register", json={"name": "a"})).json()
    run = (
        await api.post(
            "/workflows/runs",
            json={
                "project_id": project["id"],
                "name": "run",
                "tasks": [{"title": "t", "contract_id": contract["id"]}],
                "retry_policy": {"max_attempts": 1},
            },
        )
    ).json()
    task = (await api.get(f"/workflows/runs/{run['id']}/tasks")).json()[0]
    attempt = (
        await api.post(f"/tasks/{task['id']}/claim", json={"agent_id": agent["id"]})
    ).json()

    r = await api.post(
        f"/tasks/{task['id']}/attempts/{attempt['id']}/submit",
        params={"agent_id": agent["id"]},
        json={"output": {"success": True}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "verification_failed"
    assert (await api.get(f"/tasks/{task['id']}")).json()["status"] == "failed"
    assert (await api.get(f"/workflows/runs/{run['id']}")).json()["status"] == "failed"


async def test_restart_via_api_preserves_completed_run(tmp_path):
    settings = _settings(tmp_path)
    # First "process".
    app1 = build_app(settings)
    async with app1.router.lifespan_context(app1):
        async with AsyncClient(
            transport=ASGITransport(app=app1), base_url="http://test"
        ) as c1:
            project = (await c1.post("/projects", json={"name": "p"})).json()
            agent = (await c1.post("/agents/register", json={"name": "a"})).json()
            run = (
                await c1.post(
                    "/workflows/runs",
                    json={
                        "project_id": project["id"],
                        "name": "run",
                        "tasks": [{"title": "t"}],
                    },
                )
            ).json()
            task = (await c1.get(f"/workflows/runs/{run['id']}/tasks")).json()[0]
            attempt = (
                await c1.post(
                    f"/tasks/{task['id']}/claim", json={"agent_id": agent["id"]}
                )
            ).json()
            await c1.post(
                f"/tasks/{task['id']}/attempts/{attempt['id']}/submit",
                params={"agent_id": agent["id"]},
                json={"output": {"summary": "done"}},
            )
            assert (await c1.get(f"/workflows/runs/{run['id']}")).json()[
                "status"
            ] == "completed"

    # Second "process" over the same database file.
    app2 = build_app(settings)
    async with app2.router.lifespan_context(app2):
        async with AsyncClient(
            transport=ASGITransport(app=app2), base_url="http://test"
        ) as c2:
            assert (await c2.get(f"/workflows/runs/{run['id']}")).json()[
                "status"
            ] == "completed"
            assert (await c2.get(f"/tasks/{task['id']}")).json()["status"] == "completed"
