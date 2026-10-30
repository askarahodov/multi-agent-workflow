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


@pytest.mark.asyncio
async def test_trusted_leased_runner_records_durable_attempt_events(tmp_path):
    from agent_management.agent_journal import AgentEventJournal

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    created = []

    def journal_factory(task, attempt_id):
        assert task["id"] == "task-1"
        assert attempt_id == "attempt-1"
        journal = AgentEventJournal(
            tmp_path / "agent-journal.sqlite",
            run_id="task-1_attempt-1", workspace=workspace,
        )
        created.append(journal)
        return journal

    class Provider:
        async def stream(self, messages, *, tools, max_tokens):
            yield {"type": "text_delta", "text": '{"result":"ok"}'}
            yield {"type": "usage", "prompt_tokens": 2,
                   "completion_tokens": 2, "total_tokens": 4}
            yield {"type": "done", "finish_reason": "stop"}

    class Lease:
        token = "x" * 48
        generation = 1
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)

    runner = TrustedLeasedGatewayRunner(
        gateway_url="https://gateway.example",
        gateway_key="test-gateway-key-unique-private-value-12345678",
        agent_id="agent-1", provider=Provider(),
        messages=[{"role": "system", "content": "trusted"}],
        transport=httpx.ASGITransport(app=FastAPI()),
        journal_factory=journal_factory,
    )
    output = await runner({"id": "task-1", "workflow_run_id": "run-1"}, "attempt-1", Lease())
    assert output == '{"result":"ok"}'
    assert len(created) == 1
    rows = AgentEventJournal(
        tmp_path / "agent-journal.sqlite",
        run_id="task-1_attempt-1", workspace=workspace,
    ).snapshot()
    assert [r[1] for r in rows] == ["started", "usage", "provider_turn", "final"]
    assert rows[1][3] == 4
    assert all(r[4] == "UNKNOWN" for r in rows)


@pytest.mark.asyncio
async def test_native_runner_receives_user_task_not_lease_or_gateway_identity():
    class Provider:
        def __init__(self):
            self.messages = None

        async def stream(self, messages, *, tools, max_tokens):
            self.messages = messages
            yield {"type": "text_delta", "text": '{"summary":"stage complete"}'}
            yield {"type": "usage", "prompt_tokens": 2,
                   "completion_tokens": 3, "total_tokens": 5}
            yield {"type": "done", "finish_reason": "stop"}

    class Lease:
        token = "z" * 48
        generation = 1
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)

    provider = Provider()
    runner = TrustedLeasedGatewayRunner(
        gateway_url="https://gateway.example",
        gateway_key="test-gateway-key-unique-private-value-12345678",
        agent_id="agent-1", provider=provider,
        messages=[{"role": "system", "content": "Operator policy"}],
        transport=httpx.ASGITransport(app=FastAPI()),
    )
    result = await runner({
        "id": "task-1", "workflow_run_id": "run-1",
        "title": "Architecture", "description": "Design the solution",
        "input_data": {"requirements": "document diagram"},
    }, "attempt-1", Lease())
    assert result == '{"summary":"stage complete"}'
    assert provider.messages[0] == {"role": "system", "content": "Operator policy"}
    assert provider.messages[1]["role"] == "user"
    task_text = provider.messages[1]["content"]
    assert "Architecture" in task_text
    assert "Design the solution" in task_text
    assert "document diagram" in task_text
    assert "z" * 48 not in str(provider.messages)
    assert "test-gateway-key" not in str(provider.messages)
    assert "gateway.example" not in str(provider.messages)


@pytest.mark.asyncio
async def test_malicious_oversized_task_is_rejected_without_provider_or_gateway_io():
    class UncalledProvider:
        async def stream(self, *args, **kwargs):
            raise AssertionError("Untrusted oversized task reached model")
            yield {}

    class Lease:
        token = "z" * 48
        generation = 1
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)

    runner = TrustedLeasedGatewayRunner(
        gateway_url="https://gateway.example",
        gateway_key="test-gateway-key-unique-private-value-12345678",
        agent_id="agent-1", provider=UncalledProvider(),
        messages=[{"role": "system", "content": "Operator policy"}],
        transport=httpx.ASGITransport(app=FastAPI()),
    )
    for task in (
        {"id": "task-1", "workflow_run_id": "run-1", "title": "x" * 10000},
        {"id": "task-1", "workflow_run_id": "run-1", "description": "x" * 5000},
        {"id": "task-1", "workflow_run_id": "run-1", "input_data": {"text": "x" * 5000}},
    ):
        with pytest.raises(TrustedGatewayError, match="task|Task"):
            await runner(task, "attempt-1", Lease())
