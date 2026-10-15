"""Gateway restart acceptance: durable ledger prevents replay of file side effects.

Tests fresh gateway application construction against the same persisted control
SQLite and private tool ledger. Network TLS/container restart remain separate.
"""
from __future__ import annotations

import os
import httpx
import pytest

from agent_management.trusted_fs_gateway import build_trusted_filesystem_gateway
from orchestration_server.attempt_leases import AttemptLeaseService
from test_native_contract_pipeline import runtime, tool


@pytest.mark.asyncio
async def test_gateway_restart_preserves_completed_tool_receipt(runtime, tmp_path):
    attempt = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    lease = await AttemptLeaseService(runtime["factory"], ttl_seconds=60).issue(
        attempt.id, runtime["agent"].id,
    )
    db = tmp_path / "orchestration.sqlite3"
    os.chmod(db, 0o600)
    key = "gateway-restart-control-key-opaque-123456789"
    scope = f"run-{runtime['run'].id}/attempt-{attempt.id}"
    payload = {
        "run_id": runtime["run"].id, "task_id": runtime["task"].id,
        "attempt_id": attempt.id, "agent_id": runtime["agent"].id,
        "lease_token": lease.token,
        "event": tool(
            "write_file", "restart-once", path="out/restart.txt", content="FIRST",
        ),
    }

    def gateway():
        return build_trusted_filesystem_gateway(
            workspace_root=str(runtime["workspace"]),
            orchestration_database=str(db),
            ledger_database=str(runtime["ledger"].path),
            gateway_key=key,
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway()),
        base_url="https://gateway.test",
        headers={"X-Gateway-Key": key},
    ) as client:
        first = await client.post("/v1/filesystem/dispatch", json=payload)
        assert first.status_code == 200 and first.json()["ok"] is True
    artifact = runtime["workspace"] / "out" / "restart.txt"
    assert artifact.read_text() == "FIRST"
    assert runtime["ledger"].state(scope, "restart-once") == "SUCCEEDED"

    # New gateway app instance, reopening persistent ledger. Even a changed
    # model-provided argument with the same call_id MUST NOT run again.
    replay = {
        **payload,
        "event": tool(
            "write_file", "restart-once", path="out/restart.txt", content="REPLAY",
        ),
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway()),
        base_url="https://gateway.test",
        headers={"X-Gateway-Key": key},
    ) as client:
        again = await client.post("/v1/filesystem/dispatch", json=replay)
        assert again.status_code == 200
        assert again.json()["ok"] is False
        assert again.json()["error_code"] == "DUPLICATE_CALL"
    assert artifact.read_text() == "FIRST"
    assert runtime["ledger"].state(scope, "restart-once") == "SUCCEEDED"


@pytest.mark.asyncio
async def test_gateway_restart_cannot_revive_revoked_lease(runtime, tmp_path):
    attempt = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    svc = AttemptLeaseService(runtime["factory"], ttl_seconds=60)
    lease = await svc.issue(attempt.id, runtime["agent"].id)
    db = tmp_path / "orchestration.sqlite3"
    os.chmod(db, 0o600)
    key = "gateway-restart-control-key-opaque-123456789"
    def gateway():
        return build_trusted_filesystem_gateway(
            workspace_root=str(runtime["workspace"]),
            orchestration_database=str(db),
            ledger_database=str(runtime["ledger"].path),
            gateway_key=key,
        )
    # Create a real first instance to simulate a clean process lifecycle.
    gateway()
    assert await svc.revoke(attempt.id)
    payload = {
        "run_id": runtime["run"].id, "task_id": runtime["task"].id,
        "attempt_id": attempt.id, "agent_id": runtime["agent"].id,
        "lease_token": lease.token,
        "event": tool(
            "write_file", "new-after-restart", path="out/forbidden.txt",
            content="NEVER",
        ),
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway()),
        base_url="https://gateway.test",
        headers={"X-Gateway-Key": key},
    ) as client:
        denied = await client.post("/v1/filesystem/dispatch", json=payload)
        assert denied.status_code == 409
        assert denied.json()["error_code"] == "ATTEMPT_FENCED"
    assert not (runtime["workspace"] / "out" / "forbidden.txt").exists()
