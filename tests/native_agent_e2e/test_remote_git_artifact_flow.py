"""Real opt-in native worker -> HTTPS Git gateway -> fenced Git SHA -> server Contract Gate.

No paid OpenRouter and no Hermes. Git subprocess is real; model/tool events are
scripted. SQL ledger, attempt lease, HTTPS ASGI route and persistence are real.
"""
from __future__ import annotations

import os

import httpx
import pytest

from agent_management.trusted_fs_gateway import build_trusted_filesystem_gateway
from agent_management.trusted_fs_client import TrustedLeasedGatewayRunner
from orchestration_server.api import build_app
from orchestration_server.config import Settings
from orchestration_server.native_http_worker import NativeHttpWorker
from shared import auth_middleware
from test_git_worktree_commit import store, git
from test_native_contract_pipeline import runtime, ScriptedStream, tool, usage, done


@pytest.fixture(autouse=True)
def auth_for_worker(monkeypatch):
    monkeypatch.setattr(auth_middleware, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_middleware, "WRITE_API_KEYS", {"native-test-worker-key"})
    monkeypatch.setattr(auth_middleware, "ADMIN_API_KEYS", set())
    monkeypatch.setattr(auth_middleware, "READ_API_KEYS", set())


def make_gateway(runtime, tmp_path, storage):
    os.chmod(tmp_path / "orchestration.sqlite3", 0o600)
    return build_trusted_filesystem_gateway(
        workspace_root=str(runtime["workspace"]),
        orchestration_database=str(tmp_path / "orchestration.sqlite3"),
        ledger_database=str(runtime["ledger"].path),
        gateway_key="private-gateway-key-for-worker-acceptance-01",
        git_store=storage,
    )


def worker_runner(runtime, gateway, provider):
    return TrustedLeasedGatewayRunner(
        gateway_url="https://gateway.example",
        gateway_key="private-gateway-key-for-worker-acceptance-01",
        agent_id=runtime["agent"].id,
        provider=provider,
        messages=[{"role": "system", "content": "Operator prompt"}],
        transport=httpx.ASGITransport(app=gateway),
        git_enabled=True,
        max_turns=3, max_total_tokens=100, max_tool_calls=2,
    )


@pytest.mark.asyncio
async def test_leased_remote_worker_git_commit_persists_as_worker_reported_evidence(runtime, tmp_path):
    storage, repository = store(tmp_path)
    source_head = git(repository, "rev-parse", "HEAD")
    gateway = make_gateway(runtime, tmp_path, storage)
    control = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'orchestration.sqlite3'}",
        recover_on_startup=False, attempt_lease_enabled=True,
        attempt_lease_ttl_seconds=30,
    ))
    provider = ScriptedStream(
        [tool("write_file", "generated-code", path="out/feature.txt", content="Native artifact"),
         usage(), done("tool_calls")],
        [{"type": "text_delta", "text": '{"summary":"output written"}'},
         usage(), done("stop")],
    )
    async with control.router.lifespan_context(control):
        async with NativeHttpWorker(
            server_url="https://control.example", api_key="native-test-worker-key",
            agent_id=runtime["agent"].id,
            leased_runner=worker_runner(runtime, gateway, provider),
            require_lease=True, lease_renew_interval_seconds=0.05,
            transport=httpx.ASGITransport(app=control),
        ) as worker:
            completed = await worker.run_once()
            assert completed is not None and completed.verified
            assert await worker.run_once() is None
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=control),
            base_url="https://control.example",
            headers={"X-API-Key": "native-test-worker-key"},
        ) as client:
            r = await client.get(f"/api/v1/tasks/{runtime['task'].id}/git-evidence")
            assert r.status_code == 200
            saved = r.json()
    assert len(saved) == 1
    assert saved[0]["provenance"] == "worker_reported"
    assert saved[0]["attempt_id"] == completed.attempt_id
    assert saved[0]["changed_paths"] == ["out/feature.txt"]
    sha = saved[0]["commit_sha"]
    assert sha == git(repository, "rev-parse",
                      f"refs/maw/attempts/{runtime['task'].id}-{completed.attempt_id}")
    assert source_head == git(repository, "rev-parse", "HEAD")
    assert git(storage._path(runtime["task"].id, completed.attempt_id),
               "show", "HEAD:out/feature.txt") == "Native artifact"
    scope = f"run-{runtime['run'].id}/attempt-{completed.attempt_id}"
    assert runtime["ledger"].state(scope, "generated-code") == "SUCCEEDED"
    assert runtime["ledger"].state(scope, "git-commit-v1") == "SUCCEEDED"
    assert all(x["function"]["name"] != "git_commit" for x in provider.history[0]["tools"])
    assert (await runtime["queries"].get_run(runtime["run"].id)).status == "completed"


@pytest.mark.asyncio
async def test_invalid_contract_does_not_publish_git_evidence(runtime, tmp_path):
    storage, repository = store(tmp_path)
    gateway = make_gateway(runtime, tmp_path, storage)
    control = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'orchestration.sqlite3'}",
        recover_on_startup=False, attempt_lease_enabled=True,
        attempt_lease_ttl_seconds=30,
    ))
    provider = ScriptedStream(
        [tool("write_file", "invalid-contract-artifact", path="out/bad.txt", content="exists"),
         usage(), done("tool_calls")],
        [{"type": "text_delta", "text": '{"summary":""}'},
         usage(), done("stop")],
    )
    async with control.router.lifespan_context(control):
        async with NativeHttpWorker(
            server_url="https://control.example", api_key="native-test-worker-key",
            agent_id=runtime["agent"].id,
            leased_runner=worker_runner(runtime, gateway, provider),
            require_lease=True, transport=httpx.ASGITransport(app=control),
        ) as worker:
            result = await worker.run_once()
            assert result is not None and result.status == "verification_failed"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=control),
            base_url="https://control.example",
            headers={"X-API-Key": "native-test-worker-key"},
        ) as client:
            r = await client.get(f"/api/v1/tasks/{runtime['task'].id}/git-evidence")
            assert r.status_code == 200 and r.json() == []
    assert (await runtime["queries"].get_task(runtime["task"].id)).status == "failed"


@pytest.mark.asyncio
async def test_git_gateway_default_disabled_and_untrusted_requests_never_spawn_git(runtime, tmp_path):
    app = build_trusted_filesystem_gateway(
        workspace_root=str(runtime["workspace"]),
        orchestration_database=str(tmp_path / "orchestration.sqlite3"),
        ledger_database=str(runtime["ledger"].path),
        gateway_key="private-gateway-key-for-worker-acceptance-01",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://gateway.example",
    ) as client:
        payload = {
            "run_id": runtime["run"].id, "task_id": runtime["task"].id,
            "attempt_id": "synthetic-id", "agent_id": runtime["agent"].id,
            "lease_token": "x" * 48,
        }
        missing = await client.post("/v1/git/provision", json=payload)
        assert missing.status_code == 404
        unauth = await client.post("/v1/filesystem/dispatch", json=payload)
        assert unauth.status_code == 401
