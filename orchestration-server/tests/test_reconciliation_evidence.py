"""Verified evidence is bounded, nofollow and fails closed on mismatch."""
from __future__ import annotations

import os
import sqlite3
from hashlib import sha256

import httpx
import pytest

from conftest import seed_workflow
from orchestration_server.api import build_app
from orchestration_server.config import Settings
from orchestration_server.errors import BusinessRuleError
from orchestration_server.reconciliation_evidence import ReconciliationEvidenceVerifier


@pytest.fixture
def evidence(tmp_path):
    root = tmp_path / "operator-evidence"
    (root / "qa").mkdir(parents=True)
    data = b"reviewed proof of work, no credentials"
    (root / "qa" / "incident-123").write_bytes(data)
    return root, data


def test_verified_existing_regular_file(evidence):
    root, data = evidence
    ReconciliationEvidenceVerifier(root).verify("qa/incident-123", sha256(data).hexdigest())


@pytest.mark.parametrize("reference", [
    "", "/etc/passwd", "../private", "qa/../incident-123",
    "qa/./incident-123", "qa//incident-123",
    "qa\\incident-123", ".ssh/id_rsa", ".env",
    "qa/.git/config", "qa/incident-123?key=secret",
])
def test_paths_fail_closed(evidence, reference):
    root, data = evidence
    with pytest.raises(BusinessRuleError):
        ReconciliationEvidenceVerifier(root).verify(reference, sha256(data).hexdigest())


def test_wrong_hash_is_rejected_without_leaking_proof_path(evidence):
    root, _ = evidence
    with pytest.raises(BusinessRuleError, match="SHA-256 mismatch") as err:
        ReconciliationEvidenceVerifier(root).verify("qa/incident-123", "0" * 64)
    assert str(root) not in str(err.value)


def test_missing_file_does_not_expose_raw_os_error(evidence):
    root, _ = evidence
    with pytest.raises(BusinessRuleError, match="unavailable or unsafe") as err:
        ReconciliationEvidenceVerifier(root).verify("qa/missing", "0" * 64)
    assert str(root) not in str(err.value)


def test_final_file_symlink_is_not_followed(evidence, tmp_path):
    root, data = evidence
    outside = tmp_path / "private"
    outside.write_bytes(data)
    (root / "qa" / "fake").symlink_to(outside)
    with pytest.raises(BusinessRuleError):
        ReconciliationEvidenceVerifier(root).verify("qa/fake", sha256(data).hexdigest())


def test_parent_directory_symlink_is_not_followed(evidence, tmp_path):
    root, data = evidence
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "data").write_bytes(data)
    (root / "alias").symlink_to(outside, target_is_directory=True)
    with pytest.raises(BusinessRuleError):
        ReconciliationEvidenceVerifier(root).verify("alias/data", sha256(data).hexdigest())


def test_hardlink_is_rejected(evidence, tmp_path):
    root, data = evidence
    outside = tmp_path / "other"
    outside.write_bytes(data)
    os.link(outside, root / "qa" / "linked")
    with pytest.raises(BusinessRuleError, match="regular"):
        ReconciliationEvidenceVerifier(root).verify("qa/linked", sha256(data).hexdigest())


def test_fifo_rejected_without_hanging(evidence):
    root, _ = evidence
    os.mkfifo(root / "qa" / "pipe")
    with pytest.raises(BusinessRuleError):
        ReconciliationEvidenceVerifier(root).verify("qa/pipe", "0" * 64)


def test_maximum_size_is_enforced(evidence):
    root, _ = evidence
    (root / "qa" / "large").write_bytes(b"A" * 65)
    with pytest.raises(BusinessRuleError, match="size limit"):
        ReconciliationEvidenceVerifier(root, max_bytes=64).verify(
            "qa/large", sha256(b"A" * 65).hexdigest(),
        )


def test_untrusted_or_world_writable_root_is_denied(evidence):
    root, _ = evidence
    os.chmod(root, 0o777)
    try:
        with pytest.raises(ValueError, match="not be group/world writable"):
            ReconciliationEvidenceVerifier(root)
    finally:
        os.chmod(root, 0o755)


@pytest.mark.asyncio
async def test_confirmation_requires_configured_trusted_file(harness, tmp_path):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    await harness.orch.claim_task(tasks[0].id, agent.id)
    await harness.orch.recover()
    endpoint = f"/api/v1/admin/tasks/{tasks[0].id}/reconciliation"
    root = tmp_path / "trusted"
    (root / "qa").mkdir(parents=True)
    data = b"external evidence verified on server"
    (root / "qa" / "incident-123").write_bytes(data)
    digest = sha256(data).hexdigest()

    async def send(settings, decision, expected):
        app = build_app(settings)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver",
            ) as client:
                response = await client.post(endpoint, json={
                    "decision": decision,
                    "evidence_ref": "qa/incident-123",
                    "evidence_sha256": digest,
                })
                assert response.status_code == expected, response.text
                return response

    no_root = Settings(database_url=harness.url, recover_on_startup=False)
    await send(no_root, "CONFIRMED_SIDE_EFFECT", 503)
    with_root = Settings(
        database_url=harness.url, recover_on_startup=False,
        reconciliation_evidence_root=str(root),
    )
    # A direct admin API call must not bypass the UI's ledger prerequisite.
    await send(with_root, "CONFIRMED_SIDE_EFFECT", 503)

    ledger_path = tmp_path / "trusted-tool-ledger.sqlite3"
    with sqlite3.connect(ledger_path) as conn:
        conn.execute(
            "CREATE TABLE tool_execution ("
            "scope TEXT NOT NULL, call_id TEXT NOT NULL, "
            "name TEXT NOT NULL, state TEXT NOT NULL, "
            "PRIMARY KEY (scope, call_id))"
        )
    os.chmod(ledger_path, 0o600)
    with_root_and_ledger = Settings(
        database_url=harness.url, recover_on_startup=False,
        reconciliation_evidence_root=str(root),
        reconciliation_tool_ledger_path=str(ledger_path),
    )
    await send(with_root_and_ledger, "CONFIRMED_SIDE_EFFECT", 200)
    assert (await harness.queries.get_task(tasks[0].id)).status == "blocked"


@pytest.mark.asyncio
async def test_bad_digest_does_not_persist_a_confirmed_decision(harness, tmp_path):
    _, _, agent, _, tasks = await seed_workflow(harness.orch, harness.queries)
    await harness.orch.claim_task(tasks[0].id, agent.id)
    await harness.orch.recover()
    root = tmp_path / "trusted"
    root.mkdir()
    (root / "proof").write_bytes(b"real")
    app = build_app(Settings(
        database_url=harness.url, recover_on_startup=False,
        reconciliation_evidence_root=str(root),
    ))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                f"/api/v1/admin/tasks/{tasks[0].id}/reconciliation",
                json={
                    "decision": "CONFIRMED_NO_SIDE_EFFECT",
                    "evidence_ref": "proof",
                    "evidence_sha256": "0" * 64,
                },
            )
            assert response.status_code == 422
    with pytest.raises(Exception, match="not found"):
        await harness.queries.get_reconciliation(tasks[0].id)
    assert (await harness.queries.get_task(tasks[0].id)).status == "blocked"
