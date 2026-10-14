"""Reconciliation REST boundary: admin RBAC and actor provenance."""
from __future__ import annotations

from hashlib import sha256

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


async def test_api_attestation_subject_not_controlled_by_request(harness):
    _, _, agent, run, tasks = await seed_workflow(harness.orch, harness.queries)
    await harness.orch.claim_task(tasks[0].id, agent.id)
    await harness.orch.recover()
    app = build_app(Settings(database_url=harness.url, recover_on_startup=False))
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
