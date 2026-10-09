"""API-level tests: gates list, run creation, transition enforcement, releases."""

from __future__ import annotations

import sys

import httpx
import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client(app):
    from httpx import ASGITransport

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_list_gates(client):
    r = await client.get("/api/v1/gates")
    assert r.status_code == 200
    names = {g["name"] for g in r.json()}
    assert names == {"tester", "reviewer", "security", "release_prep"}


async def test_run_reviewer_gate(client, clean_workspace):
    r = await client.post(
        "/api/v1/runs",
        json={"task_id": "t1", "workspace": str(clean_workspace), "gate": "reviewer"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "passed"
    assert body["gate"] == "reviewer"


async def test_run_unknown_gate_404(client, clean_workspace):
    r = await client.post(
        "/api/v1/runs",
        json={"task_id": "t1", "workspace": str(clean_workspace), "gate": "nope"},
    )
    assert r.status_code == 404


async def test_run_missing_fields_422(client):
    r = await client.post("/api/v1/runs", json={})
    assert r.status_code == 422


async def test_task_gates_status(client):
    r = await client.get("/api/v1/tasks/t1/gates")
    assert r.status_code == 200
    body = r.json()
    assert body["passed"] is False  # nothing has run yet


async def test_transition_forbidden_before_gates(client, clean_workspace):
    r = await client.post("/api/v1/tasks/t1/transition", json={"to": "review"})
    assert r.status_code == 403
    assert "blocked" in r.json()["detail"]


async def test_transition_allowed_after_all_gates_pass(client, clean_workspace):
    # run all four required gates via the API
    commands: dict = {"commands": {"unit": [sys.executable, "-m", "pytest", "-q", "--no-header", "--collect-only"]}}
    for gate in ("tester", "reviewer", "security", "release_prep"):
        payload: dict = {"task_id": "t1", "workspace": str(clean_workspace), "gate": gate}
        if gate == "tester":
            payload["context"] = commands
        if gate == "release_prep":
            payload["context"] = {"version": "0.1.0"}
        r = await client.post("/api/v1/runs", json=payload)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "passed", (gate, r.text)

    r = await client.post("/api/v1/tasks/t1/transition", json={"to": "review"})
    assert r.status_code == 200
    assert r.json()["allowed"] is True


async def test_release_created_awaiting_approval(client, clean_workspace):
    r = await client.post(
        "/api/v1/tasks/t1/releases",
        json={"workspace": str(clean_workspace), "version": "1.0.0"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "awaiting_approval"
    assert body["id"]

    # agent cannot self-approve
    ar = await client.post(
        f"/api/v1/releases/{body['id']}/approve", json={"approver": "release_prep"}
    )
    assert ar.status_code == 409

    # human approval succeeds
    hr = await client.post(
        f"/api/v1/releases/{body['id']}/approve", json={"approver": "human-qe"}
    )
    assert hr.status_code == 200
    assert hr.json()["status"] == "approved"


async def test_release_list(client, clean_workspace):
    await client.post(
        "/api/v1/tasks/t1/releases",
        json={"workspace": str(clean_workspace), "version": "2.0.0"},
    )
    r = await client.get("/api/v1/releases")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["version"] == "2.0.0"
