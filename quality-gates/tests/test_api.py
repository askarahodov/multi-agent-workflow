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

    # A dev-mode request has no authenticated human principal, even if
    # the caller supplies a plausible name or the all-roles dev context.
    for claimed_name in ("release_prep", "human-qe"):
        ar = await client.post(
            f"/api/v1/releases/{body['id']}/approve",
            json={"approver": claimed_name},
        )
        assert ar.status_code == 403
    still_pending = await client.get("/api/v1/releases")
    assert still_pending.json()[0]["status"] == "awaiting_approval"


async def test_release_approval_uses_admin_principal_not_untrusted_body(
    client, clean_workspace, monkeypatch,
):
    import hashlib
    import shared.auth_middleware as auth_mod

    one = await client.post(
        "/api/v1/tasks/t1/releases",
        json={"workspace": str(clean_workspace), "version": "3.0.0"},
    )
    two = await client.post(
        "/api/v1/tasks/t1/releases",
        json={"workspace": str(clean_workspace), "version": "3.0.1"},
    )
    assert one.status_code == two.status_code == 200

    admin_key = "release-admin-credential"
    writer_key = "native-worker-write-credential"
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_mod, "ADMIN_API_KEYS", {admin_key})
    monkeypatch.setattr(auth_mod, "WRITE_API_KEYS", {writer_key})
    monkeypatch.setattr(auth_mod, "READ_API_KEYS", set())

    target = f"/api/v1/releases/{one.json()['id']}/approve"
    for key, expected in ((writer_key, 403), ("wrong-key", 401)):
        response = await client.post(
            target, json={"approver": "human-qe"}, headers={"X-API-Key": key},
        )
        assert response.status_code == expected
    approved = await client.post(
        target,
        # Even a forged assertion of another human identity cannot alter
        # the server-derived authenticated principal.
        json={"approver": "human-qe"},
        headers={"X-API-Key": admin_key},
    )
    assert approved.status_code == 200, approved.text
    principal = "key-" + hashlib.sha256(admin_key.encode()).hexdigest()[:12]
    assert approved.json()["approved_by"] == principal
    assert approved.json()["approved_by"] != "human-qe"
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_at"]

    reject = await client.post(
        f"/api/v1/releases/{two.json()['id']}/reject",
        json={"approver": "someone-else"},
        headers={"X-API-Key": writer_key},
    )
    assert reject.status_code == 403
    rejected = await client.post(
        f"/api/v1/releases/{two.json()['id']}/reject",
        json={"approver": "another-person"},
        headers={"X-API-Key": admin_key},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"
    assert rejected.json()["approved_by"] == principal


async def test_release_list(client, clean_workspace):
    await client.post(
        "/api/v1/tasks/t1/releases",
        json={"workspace": str(clean_workspace), "version": "2.0.0"},
    )
    r = await client.get("/api/v1/releases")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["version"] == "2.0.0"


async def test_run_detail_rejects_cross_task_evidence_access(client, clean_workspace):
    created = await client.post("/api/v1/runs", json={
        "task_id": "task-owner", "workspace": str(clean_workspace), "gate": "reviewer",
    })
    assert created.status_code == 200, created.text
    run_id = created.json()["id"]
    own = await client.get(f"/api/v1/tasks/task-owner/runs/{run_id}")
    assert own.status_code == 200, own.text
    assert own.json()["task_id"] == "task-owner"
    assert own.json()["evidence"]
    denied = await client.get(f"/api/v1/tasks/unrelated-task/runs/{run_id}")
    assert denied.status_code == 404
    assert "evidence" not in denied.text
    assert run_id not in denied.text


async def test_api_crashed_gate_is_500_and_auditable_as_failed(
    client, clean_workspace, monkeypatch,
):
    from quality_gates.gates.base import GATE_REGISTRY

    gate_cls = GATE_REGISTRY.get("reviewer")

    def crash(_self, _workspace, _context=None):
        raise RuntimeError("synthetic gate crash")

    monkeypatch.setattr(gate_cls, "execute", crash)
    response = await client.post("/api/v1/runs", json={
        "task_id": "api-crash", "workspace": str(clean_workspace), "gate": "reviewer",
    })
    assert response.status_code == 500
    runs = await client.get("/api/v1/tasks/api-crash/runs")
    assert runs.status_code == 200
    assert len(runs.json()) == 1
    assert runs.json()[0]["status"] == "failed"
    assert runs.json()[0]["finished_at"] is not None
    detail = await client.get(f"/api/v1/tasks/api-crash/runs/{runs.json()[0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "failed"
    assert (await client.get("/api/v1/tasks/api-crash/gates")).json()["passed"] is False


async def test_api_transition_denies_equal_timestamp_failed_retry(client, app):
    from datetime import datetime, timezone
    from quality_gates.models import GateRun

    when = datetime(2026, 10, 28, tzinfo=timezone.utc)
    sf = app.state.pipeline.sf
    async with sf() as session:
        session.add(GateRun(id="z-api-fail", task_id="api-retry", gate_name="tester",
                            status="failed", started_at=when, finished_at=when))
        session.add(GateRun(id="a-api-pass", task_id="api-retry", gate_name="tester",
                            status="passed", started_at=when, finished_at=when))
        for name in ("reviewer", "security", "release_prep"):
            session.add(GateRun(task_id="api-retry", gate_name=name, status="passed",
                                started_at=when, finished_at=when))
        await session.commit()

    readiness = await client.get("/api/v1/tasks/api-retry/gates")
    assert readiness.status_code == 200
    assert readiness.json()["passed"] is False
    assert readiness.json()["per_gate"]["tester"] == "failed"
    transition = await client.post(
        "/api/v1/tasks/api-retry/transition", json={"to": "review"}
    )
    assert transition.status_code == 403
