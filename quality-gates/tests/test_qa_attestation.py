"""Independent QG signing is admin-only and depends on actual persisted gate runs."""
from __future__ import annotations

import hashlib
import sys

import httpx
import pytest

from quality_gates.api import build_app
from quality_gates.config import Settings
from shared import auth_middleware
from shared.qa_attestation import (
    QaAttestationRejected,
    sign_qa_attestation,
    verify_qa_attestation,
)


KEY = "operator-qa-receipt-key-not-available-to-worker-00000001"


@pytest.mark.asyncio
async def test_qa_receipt_requires_real_passing_gates_and_authenticated_admin(
    harness, clean_workspace, monkeypatch,
):
    settings = Settings(
        evidence_root=harness.settings.evidence_root,
        artifact_root=harness.settings.artifact_root,
        qa_attestation_key=KEY,
    )
    app = build_app(settings, sf=harness.sf)
    monkeypatch.setattr(auth_middleware, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_middleware, "ADMIN_API_KEYS", {"trusted-human-operator"})
    monkeypatch.setattr(auth_middleware, "WRITE_API_KEYS", {"native-worker"})
    monkeypatch.setattr(auth_middleware, "READ_API_KEYS", set())
    task_id = "task-qa-bound-01"
    endpoint = f"/api/v1/tasks/{task_id}/qa-attestation"
    payload = {"attempt_id": "attempt-one", "commit_sha": "a" * 40}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://qg.example",
    ) as client:
        for headers, code in (
            ({}, 401), ({"X-API-Key": "native-worker"}, 403),
        ):
            denied = await client.post(endpoint, json=payload, headers=headers)
            assert denied.status_code == code
        admin = {"X-API-Key": "trusted-human-operator"}
        missing = await client.post(endpoint, json=payload, headers=admin)
        assert missing.status_code == 409

        # The checks are independently run by QG, not submitted as a
        # worker-provided claim that they passed.
        commands = {"commands": {"unit": [sys.executable, "-c", "print('passed')"]}}
        for gate in ("tester", "reviewer", "security"):
            content = {
                "task_id": task_id, "workspace": str(clean_workspace),
                "gate": gate,
            }
            if gate == "tester":
                content["context"] = commands
            result = await client.post(
                "/api/v1/runs", json=content, headers=admin,
            )
            assert result.status_code == 200, result.text
            assert result.json()["status"] == "passed"
        issued = await client.post(endpoint, json=payload, headers=admin)
        assert issued.status_code == 200, issued.text
        receipt = issued.json()

        assert receipt["task_id"] == task_id
        assert receipt["attempt_id"] == payload["attempt_id"]
        assert receipt["commit_sha"] == payload["commit_sha"]
        expected_principal = (
            "key-" + hashlib.sha256(b"trusted-human-operator").hexdigest()[:12]
        )
        assert receipt["issued_by"] == expected_principal
        assert set(receipt["gate_run_ids"]) == {"tester", "reviewer", "security"}
        assert verify_qa_attestation(receipt, KEY)["commit_sha"] == "a" * 40
        with pytest.raises(QaAttestationRejected, match="signature"):
            verify_qa_attestation(
                dict(receipt, commit_sha="b" * 40), KEY,
            )
        with pytest.raises(QaAttestationRejected, match="Expired"):
            verify_qa_attestation(
                receipt, KEY, now=receipt["issued_at"] + 3601,
            )

        # Most recent failed test result blocks reuse of older green evidence.
        failed = await client.post(
            "/api/v1/runs",
            json={
                "task_id": task_id, "workspace": str(clean_workspace),
                "gate": "tester",
                "context": {"commands": {
                    "unit": [sys.executable, "-c", "raise SystemExit(1)"],
                }},
            },
            headers=admin,
        )
        assert failed.status_code == 200 and failed.json()["status"] == "failed"
        stale = await client.post(endpoint, json=payload, headers=admin)
        assert stale.status_code == 409


@pytest.mark.asyncio
async def test_dev_mode_cannot_sign_independent_qa(harness, monkeypatch):
    settings = Settings(
        evidence_root=harness.settings.evidence_root,
        artifact_root=harness.settings.artifact_root,
        qa_attestation_key=KEY,
    )
    app = build_app(settings, sf=harness.sf)
    monkeypatch.setattr(auth_middleware, "AUTH_ENABLED", False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://qg.example",
    ) as client:
        rejected = await client.post(
            "/api/v1/tasks/t1/qa-attestation",
            json={"attempt_id": "a1", "commit_sha": "a" * 40},
        )
        assert rejected.status_code == 403
