"""Role-based authorization tests for orchestration-server (SEC-001).

The main suite runs with AUTH_ENABLED=false, so auth is exercised separately
here (mirroring agent-management/tests/test_security_auth.py): we enable the
module-level auth configuration directly and assert that unauthenticated /
underprivileged requests are rejected while properly-keyed requests pass.

Proves the acceptance contract: no credentials -> 401, read-only key on a
write/admin endpoint -> 403, admin key -> passes (not 401/403).
"""

from __future__ import annotations

import os

os.environ.setdefault("AUTH_ENABLED", "false")

import shared.auth_middleware as auth_mod


def _enable_auth(monkeypatch, *, admin=(), write=(), read=()):
    monkeypatch.setattr(auth_mod, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_mod, "ADMIN_API_KEYS", set(admin))
    monkeypatch.setattr(auth_mod, "WRITE_API_KEYS", set(write))
    monkeypatch.setattr(auth_mod, "READ_API_KEYS", set(read))


def _client(tmp_path):
    from fastapi.testclient import TestClient

    from orchestration_server.api import build_app
    from orchestration_server.config import Settings

    app = build_app(
        Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'auth.db'}")
    )
    # Entering the TestClient context runs the app lifespan (engine + schema).
    return TestClient(app)


def test_unauthenticated_rejected(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.get("/api/v1/workflows/runs")
        assert resp.status_code == 401
        assert resp.json().get("type") == "urn:auth:error:unauthorized"


def test_invalid_key_is_rejected(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.get("/api/v1/workflows/runs", headers={"X-API-Key": "bogus"})
        assert resp.status_code == 401


def test_read_key_reads_list_endpoint(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.get("/api/v1/workflows/runs", headers={"X-API-Key": "rea"})
        assert resp.status_code == 200


def test_read_key_denied_on_write_endpoint(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.post(
            "/api/v1/workflows/runs",
            json={"project_id": "p1", "name": "r1", "tasks": []},
            headers={"X-API-Key": "rea"},
        )
        assert resp.status_code == 403


def test_write_key_allowed_on_write_endpoint(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.post(
            "/api/v1/workflows/runs",
            json={"project_id": "p1", "name": "r1", "tasks": []},
            headers={"X-API-Key": "wri"},
        )
        # Auth passed; handler may 4xx on business validation, never 401/403.
        assert resp.status_code not in (401, 403)


def test_read_key_denied_on_admin_endpoint(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        assert (
            c.post("/api/v1/admin/recover", headers={"X-API-Key": "rea"}).status_code
            == 403
        )
        assert (
            c.post("/api/v1/admin/recover", headers={"X-API-Key": "wri"}).status_code
            == 403
        )


def test_admin_key_allowed_on_admin_endpoint(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.post("/api/v1/admin/recover", headers={"X-API-Key": "adm"})
        assert resp.status_code not in (401, 403)


def test_read_key_denied_on_submit(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        resp = c.post(
            "/api/v1/tasks/t1/attempts/a1/submit",
            json={"output": "x"},
            headers={"X-API-Key": "rea"},
        )
        assert resp.status_code == 403


def test_health_is_exempt_from_auth(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with _client(tmp_path) as c:
        assert c.get("/health").status_code == 200


def test_no_configured_keys_rejects_everything(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=[], write=[], read=[])
    with _client(tmp_path) as c:
        assert c.get("/api/v1/workflows/runs").status_code == 401
        assert (
            c.get("/api/v1/workflows/runs", headers={"X-API-Key": "any"}).status_code
            == 401
        )


def test_qa_attestation_requires_real_admin_not_worker_or_dev(monkeypatch, tmp_path):
    from orchestration_server.api import build_app
    from orchestration_server.config import Settings
    from fastapi.testclient import TestClient

    payload = {
        "commit_sha": "a" * 40,
        "evidence_sha256": "b" * 64,
        "evidence_ref": "qg://operator/report",
    }
    path = "/api/v1/tasks/task-id/qa-attestation"
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    with TestClient(build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'qa-auth.db'}",
        recover_on_startup=False,
    ))) as c:
        assert c.post(path, json=payload).status_code == 401
        assert c.post(path, json=payload, headers={"X-API-Key": "wri"}).status_code == 403
        assert c.post(path, json=payload, headers={"X-API-Key": "rea"}).status_code == 403
        # Correctly authenticated admin enters handler; missing task is
        # rejected by domain layer rather than the authentication middleware.
        assert c.post(path, json=payload, headers={"X-API-Key": "adm"}).status_code == 404
        monkeypatch.setattr(auth_mod, "AUTH_ENABLED", False)
        assert c.post(path, json=payload).status_code == 403


def test_strict_qa_configuration_rejects_missing_or_non_https_source(tmp_path):
    from orchestration_server.api import build_app
    from orchestration_server.config import Settings
    import pytest

    base = f"sqlite+aiosqlite:///{tmp_path / 'qa-strict.db'}"
    for url, key in ((None, None), ("http://localhost:8005", "key"), ("https://qa.example/?evil=1", "key")):
        with pytest.raises(ValueError, match="trusted HTTPS"):
            build_app(Settings(
                database_url=base, require_qa_attestation=True,
                qa_service_url=url, qa_service_read_key=key,
            ))


def test_strict_qa_admin_attestation_requires_server_readback(monkeypatch, tmp_path):
    import httpx
    from fastapi.testclient import TestClient
    from orchestration_server.api import build_app
    from orchestration_server.config import Settings
    from orchestration_server.models import TaskGitEvidence
    from orchestration_server.db import build_engine, build_session_factory, create_all
    from orchestration_server.engine import OrchestrationEngine
    import asyncio
    _enable_auth(monkeypatch, admin=["adm"], write=["worker"], read=["read"])
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'qa-bridge.db'}"
    sha = "a" * 40
    async def prepare():
        engine = build_engine(db_url)
        await create_all(engine)
        sf = build_session_factory(engine)
        orch = OrchestrationEngine(sf)
        project = await orch.create_project("qa-proof-project")
        contract = await orch.create_contract("c", {
            "type": "object", "required": ["summary"],
            "properties": {"summary": {"type": "string"}},
        })
        agent = await orch.register_agent("worker")
        run = await orch.launch_run(project.id, "qa-proof", [{"title": "stage", "contract_id": contract.id}])
        from orchestration_server.queries import OrchestrationQueries
        task = (await OrchestrationQueries(sf).list_tasks(run.id))[0]
        attempt = await orch.claim_task(task.id, agent.id)
        await orch.submit(task.id, attempt.id, agent.id, {"summary": "complete"})
        async with sf() as session:
            session.add(TaskGitEvidence(
                task_id=task.id, attempt_id=attempt.id, commit_sha=sha,
                changed_paths=["out/result.txt"], provenance="worker_reported",
            ))
            await session.commit()
        await engine.dispose()
        return task.id, attempt.id
    task_id, attempt_id = asyncio.run(prepare())
    calls = []
    proof_digest = "b" * 64
    proof_ref = f"qg://{task_id}/{attempt_id}/{proof_digest}"
    def qg(request):
        calls.append(str(request.url))
        assert request.headers["X-API-Key"] == "read-only-qg-key"
        return httpx.Response(200, json={
            "passed": True, "task_id": task_id, "attempt_id": attempt_id,
            "commit_sha": sha, "evidence_sha256": proof_digest,
            "evidence_ref": proof_ref,
        })
    app = build_app(Settings(
        database_url=db_url, recover_on_startup=False,
        require_qa_attestation=True, qa_service_url="https://quality-gates.example",
        qa_service_read_key="read-only-qg-key",
    ))
    app.state.qa_transport = httpx.MockTransport(qg)
    path = f"/api/v1/tasks/{task_id}/qa-attestation"
    with TestClient(app) as c:
        headers = {"X-API-Key": "adm"}
        forged = c.post(path, json={
            "commit_sha": sha, "evidence_sha256": "c" * 64, "evidence_ref": proof_ref,
        }, headers=headers)
        assert forged.status_code == 409
        accepted = c.post(path, json={
            "commit_sha": sha, "evidence_sha256": proof_digest, "evidence_ref": proof_ref,
        }, headers=headers)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["attempt_id"] == attempt_id
        assert c.post(path, json={
            "commit_sha": sha, "evidence_sha256": proof_digest, "evidence_ref": proof_ref,
        }, headers=headers).status_code == 409
        assert c.post(path, json={
            "commit_sha": sha, "evidence_sha256": proof_digest, "evidence_ref": proof_ref,
        }, headers={"X-API-Key":"worker"}).status_code == 403
        assert len(calls) >= 2
