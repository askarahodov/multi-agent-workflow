"""#33 worker acceptance: real SQLite, authenticated HTTP claims and fenced gateway.

All network traffic uses ASGITransport. No Hermes, OpenRouter key, external
network or shell execution. This exercises the actual supervisor/runner
rather than manually invoking run_native_task_attempt.
"""
from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from agent_management.trusted_fs_client import TrustedLeasedGatewayRunner
from agent_management.trusted_fs_gateway import build_trusted_filesystem_gateway
from orchestration_server.api import build_app
from orchestration_server.config import Settings
from orchestration_server.native_http_worker import NativeHttpWorker, RemoteWorkerError
from orchestration_server.native_worker_supervisor import NativeWorkerSupervisor
from test_native_contract_pipeline import runtime, ScriptedStream, tool, usage, done

from shared import auth_middleware


@pytest.fixture(autouse=True)
def authenticated_worker_client(monkeypatch):
    """Use the real API-key middleware, not AUTH_ENABLED=false."""
    monkeypatch.setattr(auth_middleware, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_middleware, "WRITE_API_KEYS", {"test-worker-key"})
    monkeypatch.setattr(auth_middleware, "ADMIN_API_KEYS", set())
    monkeypatch.setattr(auth_middleware, "READ_API_KEYS", set())



def gateway_for(runtime, tmp_path):
    control = tmp_path / "orchestration.sqlite3"
    os.chmod(control, 0o600)
    return build_trusted_filesystem_gateway(
        workspace_root=str(runtime["workspace"]),
        orchestration_database=str(control),
        ledger_database=str(runtime["ledger"].path),
        gateway_key="private-gateway-key-for-worker-acceptance-01",
    )


def leased_runner(runtime, gateway, provider):
    return TrustedLeasedGatewayRunner(
        gateway_url="https://gateway.example",
        gateway_key="private-gateway-key-for-worker-acceptance-01",
        agent_id=runtime["agent"].id,
        provider=provider,
        messages=[{"role": "system", "content": "Trusted operator prompt"}],
        transport=httpx.ASGITransport(app=gateway),
        max_turns=3, max_total_tokens=100, max_tool_calls=2,
    )


@pytest.mark.asyncio
async def test_supervised_worker_claims_executes_and_contract_verifies(runtime, tmp_path):
    control = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'orchestration.sqlite3'}",
        recover_on_startup=False, attempt_lease_enabled=True,
        attempt_lease_ttl_seconds=30,
    ))
    gateway = gateway_for(runtime, tmp_path)
    provider = ScriptedStream(
        [tool("write_file", "worker-e2e", path="out/worker-e2e.txt", content="FIRST"),
         usage(), done("tool_calls")],
        [{"type": "text_delta", "text": '{"summary":"verified by Contract Gate"}'},
         usage(), done("stop")],
    )
    async with control.router.lifespan_context(control):
        async with NativeHttpWorker(
            server_url="https://control.example", api_key="test-worker-key",
            agent_id=runtime["agent"].id,
            leased_runner=leased_runner(runtime, gateway, provider),
            require_lease=True, lease_renew_interval_seconds=0.05,
            transport=httpx.ASGITransport(app=control),
        ) as worker:
            report = await NativeWorkerSupervisor(
                worker, max_polls=2, poll_interval_seconds=0.01,
            ).run(asyncio.Event())
            assert report.completed_attempts == 1
            assert report.failed_attempts == 0
            assert report.polls == 2
    assert len(provider.history) == 2
    assert (runtime["workspace"] / "out" / "worker-e2e.txt").read_text() == "FIRST"
    assert (await runtime["queries"].get_task(runtime["task"].id)).status == "completed"
    assert (await runtime["queries"].get_run(runtime["run"].id)).status == "completed"
    attempt = (await runtime["queries"].list_attempts(runtime["task"].id))[0]
    scope = f"run-{runtime['run'].id}/attempt-{attempt.id}"
    assert runtime["ledger"].state(scope, "worker-e2e") == "SUCCEEDED"

    # Restart worker with a brand new HTTP client & provider. A completed
    # task must never cause another claim, tool write or paid model call.
    restarted_control = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'orchestration.sqlite3'}",
        recover_on_startup=False, attempt_lease_enabled=True,
        attempt_lease_ttl_seconds=30,
    ))
    class Forbidden:
        async def stream(self, *args, **kwargs):
            raise AssertionError("Restart must not invoke LLM")
            yield {}

    async with restarted_control.router.lifespan_context(restarted_control):
        async with NativeHttpWorker(
            server_url="https://control.example", api_key="test-worker-key",
            agent_id=runtime["agent"].id,
            leased_runner=leased_runner(runtime, gateway_for(runtime, tmp_path), Forbidden()),
            require_lease=True, transport=httpx.ASGITransport(app=restarted_control),
        ) as worker:
            assert await worker.run_once() is None
    assert (runtime["workspace"] / "out" / "worker-e2e.txt").read_text() == "FIRST"
    assert (await runtime["queries"].get_task(runtime["task"].id)).attempt_count == 1


@pytest.mark.asyncio
async def test_worker_crash_after_tool_write_never_auto_replays(runtime, tmp_path):
    control = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'orchestration.sqlite3'}",
        recover_on_startup=False, attempt_lease_enabled=True,
        attempt_lease_ttl_seconds=30,
    ))
    gateway = gateway_for(runtime, tmp_path)

    class CrashAfterWrite:
        def __init__(self):
            self.turns = 0
        async def stream(self, messages, *, tools, max_tokens):
            self.turns += 1
            if self.turns == 1:
                yield tool("write_file", "crash-write", path="out/crash.txt", content="ONCE")
                yield usage()
                yield done("tool_calls")
            else:
                raise RuntimeError("429 quota-secret-canary")
                yield {"type": "done"}

    provider = CrashAfterWrite()
    async with control.router.lifespan_context(control):
        async with NativeHttpWorker(
            server_url="https://control.example", api_key="test-worker-key",
            agent_id=runtime["agent"].id,
            leased_runner=leased_runner(runtime, gateway, provider),
            require_lease=True, lease_renew_interval_seconds=0.05,
            transport=httpx.ASGITransport(app=control),
        ) as worker:
            with pytest.raises(RemoteWorkerError, match="reconciliation") as exc:
                await worker.run_once()
            assert "quota-secret-canary" not in str(exc.value)
    assert provider.turns == 2
    assert (runtime["workspace"] / "out" / "crash.txt").read_text() == "ONCE"
    attempt = (await runtime["queries"].list_attempts(runtime["task"].id))[0]
    assert attempt.status == "running"
    assert (await runtime["queries"].get_task(runtime["task"].id)).status == "in_progress"

    # A restarted worker cannot reclaim this interrupted task, and a fresh
    # gateway cannot execute the identical tool ID against a stale attempt.
    again = build_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'orchestration.sqlite3'}",
        recover_on_startup=False, attempt_lease_enabled=True,
    ))
    async with again.router.lifespan_context(again):
        async with NativeHttpWorker(
            server_url="https://control.example", api_key="test-worker-key",
            agent_id=runtime["agent"].id,
            leased_runner=lambda *_: pytest.fail("No automatic re-execution"),
            require_lease=True, transport=httpx.ASGITransport(app=again),
        ) as worker:
            assert await worker.run_once() is None
    assert (await runtime["queries"].get_task(runtime["task"].id)).attempt_count == 1
    assert (runtime["workspace"] / "out" / "crash.txt").read_text() == "ONCE"
    await runtime["orch"].recover()
    assert (await runtime["queries"].get_task(runtime["task"].id)).status == "blocked"
    assert (runtime["workspace"] / "out" / "crash.txt").read_text() == "ONCE"
