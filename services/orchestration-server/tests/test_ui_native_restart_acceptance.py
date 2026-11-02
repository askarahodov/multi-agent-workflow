"""UI-shaped native SDLC HTTP->dispatcher->Contract Gate->SQLite restart acceptance.

Offline runner is deliberately scripted. This test does not claim live OpenRouter
or independently attested QA; it proves the actual platform HTTP boundaries.
"""
from __future__ import annotations

import httpx
import pytest

from orchestration_server.api import build_app
from orchestration_server.config import Settings
from orchestration_server.native_http_worker import NativeHttpWorker
from orchestration_server.native_worker_supervisor import NativeWorkerSupervisor


@pytest.mark.asyncio
async def test_ui_created_dependent_tasks_execute_and_survive_server_restart(harness):
    settings = Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=True, attempt_lease_ttl_seconds=30,
    )
    app = build_app(settings)
    calls = []
    async def scripted_native_runner(task, attempt_id, lease):
        calls.append((task["title"], task["id"], attempt_id, lease.generation))
        return '{"summary":"contract checked"}'

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://control.example",
        ) as ui:
            project = await ui.post("/api/v1/projects", json={
                "name": "UI native project",
            })
            assert project.status_code == 201, project.text
            pid = project.json()["id"]
            contract = await ui.post("/api/v1/contracts", json={
                "project_id": pid, "name": "native-summary",
                "schema": {
                    "type": "object", "required": ["summary"],
                    "properties": {"summary": {"type": "string", "minLength": 1}},
                    "additionalProperties": False,
                },
            })
            assert contract.status_code == 201, contract.text
            cid = contract.json()["id"]
            agent = await ui.post("/api/v1/agents/register", json={
                "name": "native-operator-worker",
            })
            assert agent.status_code == 201, agent.text
            agent_id = agent.json()["id"]
            launch = await ui.post("/api/v1/workflows/runs", json={
                "project_id": pid, "name": "UI-led native SDLC",
                "tasks": [
                    {"title": "Research", "contract_id": cid},
                    {"title": "Architecture", "contract_id": cid, "depends_on": [0]},
                ],
            })
            assert launch.status_code == 201, launch.text
            run_id = launch.json()["id"]
            tasks_response = await ui.get(f"/api/v1/workflows/runs/{run_id}/tasks")
            assert tasks_response.status_code == 200
            tasks = tasks_response.json()["items"]
            assert len(tasks) == 2
            assert all(t["contract_id"] == cid for t in tasks)
            async with NativeHttpWorker(
                server_url="https://control.example", api_key="integration-test-key",
                agent_id=agent_id, leased_runner=scripted_native_runner,
                require_lease=True, lease_renew_interval_seconds=0.05,
                transport=transport,
            ) as worker:
                report = await NativeWorkerSupervisor(
                    worker, max_polls=4, max_attempts_per_poll=1,
                    poll_interval_seconds=0.01, max_completed_attempts=2,
                ).run(__import__("asyncio").Event())
            assert report.reason == "BUDGET_REACHED"
            assert report.completed_attempts == 2
            assert [x[0] for x in calls] == ["Research", "Architecture"]
            completed = await ui.get(f"/api/v1/workflows/runs/{run_id}")
            assert completed.json()["status"] == "completed"
            for task in tasks:
                item = await ui.get(f"/api/v1/tasks/{task['id']}")
                assert item.json()["status"] == "completed"
                assert item.json()["output_data"]["summary"] == "contract checked"
    # Fresh ASGI app and independent SQLite engine, as after process restart.
    restarted = build_app(settings)
    async with restarted.router.lifespan_context(restarted):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted),
            base_url="https://control.example",
        ) as ui:
            projects = await ui.get("/api/v1/projects")
            assert pid in [p["id"] for p in projects.json()]
            contracts = await ui.get("/api/v1/contracts")
            assert cid in [c["id"] for c in contracts.json()]
            runs = await ui.get("/api/v1/workflows/runs", params={"project_id": pid})
            assert run_id in [r["id"] for r in runs.json()["items"]]
            stored = await ui.get(f"/api/v1/workflows/runs/{run_id}/tasks")
            assert len(stored.json()["items"]) == 2
            assert all(x["status"] == "completed" for x in stored.json()["items"])


@pytest.mark.asyncio
async def test_ui_launch_without_native_contract_fails_before_dispatch(harness):
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=True,
    ))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://control.example",
        ) as ui:
            project = await ui.post("/api/v1/projects", json={"name": "strict project"})
            pid = project.json()["id"]
            launch = await ui.post("/api/v1/workflows/runs", json={
                "project_id": pid, "name": "invalid native run",
                "tasks": [{"title": "No Contract Gate"}],
            })
            assert launch.status_code in (400, 409, 422), launch.text
            runs = await ui.get("/api/v1/workflows/runs", params={"project_id": pid})
            assert runs.json()["items"] == []
