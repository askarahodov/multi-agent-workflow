"""P0 #11: separate operator approval after Contract Gate and independent QA."""
from __future__ import annotations

import hashlib

import httpx
import pytest

from conftest import seed_workflow
from orchestration_server.api import build_app
from orchestration_server.config import Settings
from shared import auth_middleware


WORKER = "release-worker-test-key"
QA_ADMIN = "release-qa-admin-test-key"
APPROVER = "release-human-approval-test-key"


@pytest.fixture(autouse=True)
def authentic_roles(monkeypatch):
    monkeypatch.setattr(auth_middleware, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_middleware, "WRITE_API_KEYS", {WORKER})
    monkeypatch.setattr(auth_middleware, "ADMIN_API_KEYS", {QA_ADMIN, APPROVER})
    monkeypatch.setattr(auth_middleware, "READ_API_KEYS", set())


@pytest.mark.asyncio
async def test_release_approval_is_operator_only_durable_and_once(harness, tmp_path):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)
    previous = await harness.orch.claim_task(tasks[0].id, agent.id)
    await harness.orch.submit(
        tasks[0].id, previous.id, agent.id, {"summary": "contract passed"}
    )
    # Legacy worker completed its run, but approval policy must be verified
    # using a fresh run owned by the release-gated application.
    from orchestration_server.engine import OrchestrationEngine
    gated = OrchestrationEngine(
        harness.sf, require_lease=True, require_release_approval=True
    )
    project = await harness.queries.get_run(run.id)
    # A new run uses the same registered project/contract and a leased API.
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=True, release_approval_key=APPROVER,
    ))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="https://control.example",
        ) as client:
            launch = await client.post(
                "/api/v1/workflows/runs",
                headers={"X-API-Key": WORKER},
                json={
                    "project_id": run.project_id, "name": "approved native release",
                    "tasks": [{"title": "release-prep", "contract_id": tasks[0].contract_id}],
                    "retry_policy": {"max_attempts": 1},
                },
            )
            assert launch.status_code == 201, launch.text
            rid = launch.json()["id"]
            task_response = await client.get(
                f"/api/v1/workflows/runs/{rid}/tasks",
                headers={"X-API-Key": WORKER},
            )
            task_id = task_response.json()["items"][0]["id"]
            claim = await client.post(
                f"/api/v1/tasks/{task_id}/claim", headers={"X-API-Key": WORKER},
                json={"agent_id": agent.id},
            )
            assert claim.status_code == 201, claim.text
            attempt = claim.json()
            submit = await client.post(
                f"/api/v1/tasks/{task_id}/attempts/{attempt['id']}/submit",
                params={"agent_id": agent.id},
                headers={"X-API-Key": WORKER, "X-Attempt-Lease": attempt["lease_token"]},
                json={"output": {"summary": "release prepared"}},
            )
            assert submit.status_code == 200, submit.text
            assert (await harness.queries.get_run(rid)).status == "running"
            url = f"/api/v1/workflows/runs/{rid}/release-approval"
            for key in (WORKER, QA_ADMIN):
                denied = await client.post(url, headers={"X-API-Key": key})
                assert denied.status_code in (403,)
            approved = await client.post(url, headers={"X-API-Key": APPROVER})
            assert approved.status_code == 200, approved.text
            assert approved.json()["status"] == "approved"
            assert approved.json()["approved_by"] == "key-" + hashlib.sha256(
                APPROVER.encode()
            ).hexdigest()[:12]
            assert (await harness.queries.get_run(rid)).status == "completed"
            repeated = await client.post(url, headers={"X-API-Key": APPROVER})
            assert repeated.status_code == 409

    # New app and new SQLite connection must retain both run status and
    # the immutable operator approval.
    restarted = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        attempt_lease_enabled=True, release_approval_key=APPROVER,
    ))
    async with restarted.router.lifespan_context(restarted):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted),
            base_url="https://control.example",
            headers={"X-API-Key": APPROVER},
        ) as client:
            persisted = await client.get(f"/api/v1/workflows/runs/{rid}")
            assert persisted.status_code == 200
            assert persisted.json()["status"] == "completed"


def test_operator_release_approval_requires_leased_engine(harness):
    from orchestration_server.engine import OrchestrationEngine
    with pytest.raises(ValueError, match="leased"):
        OrchestrationEngine(harness.sf, require_release_approval=True)
