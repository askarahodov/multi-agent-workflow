"""Reconciliation REST boundary: admin RBAC and actor provenance."""
from __future__ import annotations

from hashlib import sha256
import os
import sqlite3

import httpx
import pytest

from conftest import seed_workflow
from orchestration_server.api import build_app
from orchestration_server.config import Settings
from test_security_auth import _client, _enable_auth

REF = "qa/recovery-incident-42"
DIGEST = sha256(b"reviewed-offline").hexdigest()


def test_admin_only_reconciliation_and_quarantine_read(monkeypatch, tmp_path):
    _enable_auth(monkeypatch, admin=["adm"], write=["wri"], read=["rea"])
    payload = {
        "decision": "UNKNOWN", "evidence_ref": REF, "evidence_sha256": DIGEST,
    }
    with _client(tmp_path) as c:
        for endpoint in (
            "/api/v1/admin/recovery-quarantine",
            "/api/v1/admin/tasks/no-task/reconciliation",
        ):
            assert c.get(endpoint).status_code == 401
            assert c.get(endpoint, headers={"X-API-Key": "rea"}).status_code == 403
            assert c.get(endpoint, headers={"X-API-Key": "wri"}).status_code == 403
        target = "/api/v1/admin/tasks/no-task/reconciliation"
        assert c.post(target, json=payload).status_code == 401
        assert c.post(target, json=payload, headers={"X-API-Key": "rea"}).status_code == 403
        assert c.post(target, json=payload, headers={"X-API-Key": "wri"}).status_code == 403
        assert c.get("/api/v1/admin/recovery-quarantine",
                     headers={"X-API-Key": "adm"}).json() == []
        # Admin auth passes; nonexistent task is a 404, not a permission error.
        assert c.post(target, json=payload, headers={"X-API-Key": "adm"}).status_code == 404


async def test_api_attestation_subject_not_controlled_by_request(harness, tmp_path):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)
    await harness.orch.claim_task(tasks[0].id, agent.id)
    await harness.orch.recover()
    root = tmp_path / "trusted-evidence"
    (root / "qa").mkdir(parents=True)
    (root / "qa" / "recovery-incident-42").write_bytes(b"reviewed-offline")
    # Confirmed decisions need the same trusted ledger as the recovery UI.
    ledger_path = tmp_path / "trusted-tool-ledger.sqlite3"
    with sqlite3.connect(ledger_path) as conn:
        conn.execute(
            "CREATE TABLE tool_execution ("
            "scope TEXT NOT NULL, call_id TEXT NOT NULL, "
            "name TEXT NOT NULL, state TEXT NOT NULL, "
            "PRIMARY KEY (scope, call_id))"
        )
    os.chmod(ledger_path, 0o600)
    app = build_app(Settings(
        database_url=harness.url,
        recover_on_startup=False,
        reconciliation_evidence_root=str(root),
        reconciliation_tool_ledger_path=str(ledger_path),
    ))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            endpoint = f"/api/v1/admin/tasks/{tasks[0].id}/reconciliation"
            response = await client.post(endpoint, json={
                "decision": "CONFIRMED_NO_SIDE_EFFECT",
                "evidence_ref": REF, "evidence_sha256": DIGEST,
                "operator_subject": "forged-human",
                "status": "completed",
            })
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["operator_subject"] == "development"
            assert body["decision"] == "CONFIRMED_NO_SIDE_EFFECT"
            assert (await client.get(endpoint)).status_code == 200
            queue = (await client.get("/api/v1/admin/recovery-quarantine")).json()
            assert [t["id"] for t in queue] == [tasks[0].id]
    assert (await harness.queries.get_task(tasks[0].id)).status == "blocked"

@pytest.mark.parametrize("bad_name", [b"binary", "x" * 65])
async def test_confirmed_attestation_fails_closed_on_corrupt_ledger(harness, tmp_path, bad_name):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)
    attempt = await harness.orch.claim_task(tasks[0].id, agent.id)
    await harness.orch.recover()

    root = tmp_path / "trusted-evidence"
    (root / "qa").mkdir(parents=True)
    (root / "qa" / "recovery-incident-42").write_bytes(b"reviewed-offline")
    path = tmp_path / "tool-ledger.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE tool_execution (scope TEXT NOT NULL, call_id TEXT NOT NULL, "
            "name TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (scope,call_id))"
        )
        conn.execute(
            "INSERT INTO tool_execution (scope,call_id,name,state) VALUES (?,?,?,?)",
            (f"run-{run.id}/attempt-{attempt.id}", "call-1", bad_name, "CLAIMED"),
        )
    os.chmod(path, 0o600)
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        reconciliation_evidence_root=str(root),
        reconciliation_tool_ledger_path=str(path),
    ))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver",
        ) as client:
            response = await client.post(
                f"/api/v1/admin/tasks/{tasks[0].id}/reconciliation",
                json={"decision": "CONFIRMED_NO_SIDE_EFFECT",
                      "evidence_ref": REF, "evidence_sha256": DIGEST},
            )
            assert response.status_code == 422
            assert "Invalid tool ledger record" in response.text
    assert (await harness.queries.get_task(tasks[0].id)).status == "blocked"
    from orchestration_server.errors import NotFoundError
    with pytest.raises(NotFoundError):
        await harness.queries.get_reconciliation(tasks[0].id)
