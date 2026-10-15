"""Offline negative security tests for trusted remote gateway client.

No paid provider calls, external network, subprocess or local agent runtime.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, RedirectResponse

from agent_management.trusted_fs_client import (
    TrustedGatewayError, TrustedRemoteFilesystemDispatcher,
    TrustedLeasedGatewayRunner,
)


def _remote(*, app=None, origin="https://gateway.example"):
    return TrustedRemoteFilesystemDispatcher(
        gateway_url=origin,
        gateway_key="test-gateway-key-unique-private-value-12345678",
        run_id="run-1", task_id="task-1", attempt_id="attempt-1",
        agent_id="agent-1", lease_token="x" * 48,
        transport=httpx.ASGITransport(app=app) if app is not None else None,
    )


def _call(call_id="same-id"):
    return {"type": "tool_call", "id": call_id, "name": "write_file",
            "arguments": {"path": "out/report.txt", "content": "value"}}


@pytest.mark.parametrize("origin", [
    "http://gateway.example", "https://user:pass@gateway.example",
    "https://gateway.example/sensitive", "https://gateway.example?q=1",
    "https://gateway.example#fragment",
])
def test_remote_dispatcher_requires_bare_https(origin):
    with pytest.raises(ValueError, match="HTTPS"):
        _remote(origin=origin)


@pytest.mark.asyncio
async def test_gateway_redirect_is_not_followed_even_if_target_claims_success():
    destination_calls = []
    app = FastAPI()

    @app.post("/v1/filesystem/dispatch")
    async def move():
        return RedirectResponse("https://bad.example/secret", status_code=307)

    @app.post("/secret")
    async def steal():
        destination_calls.append(True)
        return {"ok": True, "content": "ok", "error_code": None}

    async with _remote(app=app) as remote:
        with pytest.raises(TrustedGatewayError, match="reconciliation"):
            await remote.dispatch_async(_call())
    assert destination_calls == []


@pytest.mark.parametrize("status,body", [
    (503, {"detail": "MY_GATEWAY_CREDENTIAL"}),
    (200, {"ok": False, "content": "", "error_code": "ATTEMPT_FENCED"}),
    (200, {"ok": False, "content": "", "error_code": "DUPLICATE_CALL"}),
    (200, {"ok": True, "content": "ok", "error_code": "DUPLICATE_CALL"}),
    (200, {"ok": True, "content": "ok"}),
])
@pytest.mark.asyncio
async def test_gateway_failure_or_ambiguous_replay_stops_agent_loop(status, body):
    app = FastAPI()

    @app.post("/v1/filesystem/dispatch")
    async def failing():
        return JSONResponse(status_code=status, content=body)

    async with _remote(app=app) as remote:
        with pytest.raises(TrustedGatewayError) as exc:
            await remote.dispatch_async(_call())
        assert "MY_GATEWAY_CREDENTIAL" not in str(exc.value)
        assert "x" * 48 not in str(exc.value)


@pytest.mark.asyncio
async def test_only_policy_errors_are_safe_to_show_to_model():
    app = FastAPI()

    @app.post("/v1/filesystem/dispatch")
    async def deny():
        return {"ok": False, "content": "", "error_code": "POLICY_DENIED"}

    async with _remote(app=app) as remote:
        outcome = await remote.dispatch_async(_call())
    assert not outcome.ok
    assert outcome.to_provider_message()["content"] == '{"error":"POLICY_DENIED"}'


@pytest.mark.asyncio
async def test_model_cannot_supply_gateway_identity_or_unknown_tool():
    app = FastAPI()
    executed = []

    @app.post("/v1/filesystem/dispatch")
    async def record():
        executed.append(True)
        return {"ok": True, "content": "File written", "error_code": None}

    async with _remote(app=app) as remote:
        with pytest.raises(TrustedGatewayError, match="Unauthorized"):
            await remote.dispatch_async({
                "type": "tool_call", "id": "unknown",
                "name": "shell", "arguments": {"cmd": "whoami"},
            })
        with pytest.raises(TrustedGatewayError, match="Invalid"):
            await remote.dispatch_async("not-an-event")
    assert not executed


def test_trusted_runner_does_not_repr_or_accept_expired_leases():
    class MockProvider:
        async def stream(self, *args, **kwargs):
            raise AssertionError("Expired lease must not call model")
            yield {}

    runner = TrustedLeasedGatewayRunner(
        gateway_url="https://gateway.example",
        gateway_key="test-gateway-key-unique-private-value-12345678",
        agent_id="agent-1", provider=MockProvider(),
        messages=[{"role": "user", "content": "trusted"}],
    )

    class ExpiredLease:
        token = "x" * 48
        generation = 1
        expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

    async def check():
        with pytest.raises(TrustedGatewayError, match="Invalid trusted"):
            await runner({"id": "task-1", "workflow_run_id": "run-1"},
                         "attempt-1", ExpiredLease())

    import asyncio
    asyncio.run(check())
