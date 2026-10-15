"""Offline integration of the *real* native agent and orchestration packages.

This suite joins two separately installed services. There are no real LLM calls,
shells or Git hooks. It verifies that Contract Gate, not the LLM, owns outcomes.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3

import httpx
from threading import Event
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from agent_management.agent_loop import run_agent_loop
from agent_management.trusted_fs_gateway import build_trusted_filesystem_gateway
from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
from agent_management.scoped_fs import ScopedFilesystemExecutor
from agent_management.tool_ledger import SqliteToolLedger
from shared.attempt_fence import AttemptFenceDenied, TrustedSqliteAttemptFence
from orchestration_server.attempt_leases import AttemptLeaseService
from orchestration_server.db import build_engine, build_session_factory, create_all
from orchestration_server.models import AttemptLease
from orchestration_server.engine import OrchestrationEngine
from orchestration_server.models import SagaEvent
from orchestration_server.native_bridge import run_native_task_attempt
from orchestration_server.native_worker import NativeWorker
from orchestration_server.queries import OrchestrationQueries
from orchestration_server.tool_ledger_inspection import TrustedToolLedgerReader


SCHEMA = {
    "type": "object",
    "required": ["summary"],
    "properties": {"summary": {"type": "string", "minLength": 1}},
    "additionalProperties": False,
}


class ScriptedStream:
    """Predictable mock of the OpenRouter-normalized stream event interface."""

    def __init__(self, *turns):
        self._turns = list(turns)
        self.history = []

    async def stream(self, messages, *, tools, max_tokens):
        self.history.append({"messages": list(messages), "tools": tools, "max_tokens": max_tokens})
        for event in self._turns[len(self.history) - 1]:
            yield event


def tool(name, call_id, **arguments):
    return {"type": "tool_call", "id": call_id, "name": name, "arguments": arguments}


def usage():
    return {
        "type": "usage", "prompt_tokens": 5,
        "completion_tokens": 3, "total_tokens": 8,
    }


def done(reason):
    return {"type": "done", "finish_reason": reason}


@pytest_asyncio.fixture
async def runtime(tmp_path):
    db = build_engine(f"sqlite+aiosqlite:///{tmp_path / 'orchestration.sqlite3'}")
    await create_all(db)
    factory = build_session_factory(db)
    orch = OrchestrationEngine(factory)
    queries = OrchestrationQueries(factory)

    project = await orch.create_project("cross-service")
    contract = await orch.create_contract("summary-contract", SCHEMA, project_id=project.id)
    agent = await orch.register_agent("native-offline-worker")
    run = await orch.launch_run(
        project.id, "native-e2e",
        [{"title": "Create scoped artifact", "contract_id": contract.id}],
        retry_policy={"max_attempts": 1, "base_delay_seconds": 0.0,
                      "max_delay_seconds": 0.0, "backoff_multiplier": 1.0},
    )
    task = (await queries.list_tasks(run.id))[0]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "out").mkdir()
    (workspace / "src" / "source.txt").write_text("original", encoding="utf-8")
    ledger = SqliteToolLedger(tmp_path / "control-ledger.sqlite3")

    try:
        yield {
            "orch": orch, "queries": queries, "factory": factory,
            "agent": agent, "run": run, "task": task,
            "workspace": workspace, "ledger": ledger,
        }
    finally:
        await db.dispose()


def native_runner(runtime, provider, *, scopes):
    """The trusted worker binds scope and policy; the model cannot change them."""
    async def run(task_id, attempt_id):
        assert task_id == runtime["task"].id
        root = runtime["workspace"]
        fs = ScopedFilesystemExecutor(
            root, {
                "fs_read": [str(root / "src" / "**")],
                "fs_write": [str(root / "out" / "**")],
            },
        )
        scope = f"run-{runtime['run'].id}/attempt-{attempt_id}"
        scopes.append(scope)
        dispatcher = NativeFilesystemDispatcher(
            fs, ledger=runtime["ledger"], execution_scope=scope,
        )
        result = await run_agent_loop(
            provider, dispatcher,
            [{"role": "user", "content": "Write the authorized report, then return JSON"}],
            max_turns=3, max_total_tokens=100, max_tool_calls=2,
        )
        return result.output
    return run


async def saga_events(runtime):
    async with runtime["factory"]() as session:
        return list((await session.scalars(
            select(SagaEvent).where(SagaEvent.run_id == runtime["run"].id)
        )).all())


@pytest.mark.asyncio
async def test_real_native_tool_cycle_reaches_engine_contract_gate(runtime):
    provider = ScriptedStream(
        [
            tool("write_file", "file-create", path="out/artifact.txt", content="artifact-data"),
            usage(), done("tool_calls"),
        ],
        [{"type": "text_delta", "text": '{"summary":"artifact created"}'},
         usage(), done("stop")],
    )
    scopes = []
    result = await run_native_task_attempt(
        runtime["orch"], task_id=runtime["task"].id,
        agent_id=runtime["agent"].id,
        runner=native_runner(runtime, provider, scopes=scopes),
    )

    assert result.status == "completed" and result.verified
    assert (runtime["workspace"] / "out" / "artifact.txt").read_text() == "artifact-data"
    assert runtime["ledger"].state(scopes[0], "file-create") == "SUCCEEDED"
    assert provider.history[1]["messages"][-1] == {
        "role": "tool", "tool_call_id": "file-create", "content": "File written",
    }
    assert (await runtime["queries"].get_task(runtime["task"].id)).status == "completed"
    assert (await runtime["queries"].get_run(runtime["run"].id)).status == "completed"
    event_types = [e.event_type for e in await saga_events(runtime)]
    assert "task.claimed" in event_types
    assert "task.completed" in event_types
    assert "run.completed" in event_types


@pytest.mark.asyncio
async def test_denied_tool_cannot_bypass_contract_gate(runtime):
    provider = ScriptedStream(
        [tool("write_file", "attempt-escape", path="src/source.txt", content="tamper"),
         usage(), done("tool_calls")],
        [{"type": "text_delta", "text": '{"summary":""}'}, usage(), done("stop")],
    )
    scopes = []
    result = await run_native_task_attempt(
        runtime["orch"], task_id=runtime["task"].id,
        agent_id=runtime["agent"].id,
        runner=native_runner(runtime, provider, scopes=scopes),
    )
    assert result.status == "verification_failed" and not result.verified
    assert (runtime["workspace"] / "src" / "source.txt").read_text() == "original"
    assert runtime["ledger"].state(scopes[0], "attempt-escape") == "DENIED"
    assert provider.history[1]["messages"][-1]["content"] == '{"error":"POLICY_DENIED"}'
    assert (await runtime["queries"].get_task(runtime["task"].id)).status == "failed"
    assert "task.completed" not in [e.event_type for e in await saga_events(runtime)]


@pytest.mark.asyncio
async def test_truncated_model_stream_does_not_run_any_tools(runtime):
    provider = ScriptedStream([
        tool("write_file", "unfinished", path="out/unsafe.txt", content="NO"),
        done("tool_calls"),
        # Missing mandatory provider usage -> cannot authorize a side effect.
    ])
    scopes = []
    result = await run_native_task_attempt(
        runtime["orch"], task_id=runtime["task"].id,
        agent_id=runtime["agent"].id,
        runner=native_runner(runtime, provider, scopes=scopes),
    )
    assert result.status == "failed" and not result.verified
    assert not (runtime["workspace"] / "out" / "unsafe.txt").exists()
    assert runtime["ledger"].state(scopes[0], "unfinished") is None
    assert (await runtime["queries"].get_run(runtime["run"].id)).status == "failed"


@pytest.mark.asyncio
async def test_invalid_final_output_fails_task_after_real_tool_call(runtime):
    provider = ScriptedStream(
        [tool("write_file", "once-id", path="out/file.txt", content="first"),
         usage(), done("tool_calls")],
        [{"type": "text_delta", "text": '{"summary":"x","summary":"y"}'},
         usage(), done("stop")],
    )
    scopes = []
    result = await run_native_task_attempt(
        runtime["orch"], task_id=runtime["task"].id,
        agent_id=runtime["agent"].id,
        runner=native_runner(runtime, provider, scopes=scopes),
    )
    assert result.status == "failed" and not result.verified
    assert runtime["ledger"].state(scopes[0], "once-id") == "SUCCEEDED"
    assert (runtime["workspace"] / "out" / "file.txt").read_text() == "first"

    # Simulate worker restart, reusing same trusted attempt scope + call ID.
    fs = ScopedFilesystemExecutor(
        runtime["workspace"],
        {"fs_write": [str(runtime["workspace"] / "out" / "**")]},
    )
    restarted = NativeFilesystemDispatcher(
        fs, ledger=SqliteToolLedger(runtime["ledger"].path), execution_scope=scopes[0],
    )
    again = restarted.dispatch(tool("write_file", "once-id", path="out/file.txt", content="repeat"))
    assert again.error_code == "DUPLICATE_CALL"
    assert (runtime["workspace"] / "out" / "file.txt").read_text() == "first"
    assert "task.completed" not in [e.event_type for e in await saga_events(runtime)]



@pytest.mark.asyncio
async def test_worker_auto_discovers_and_runs_real_native_pipeline(runtime):
    """Task ID is discovered by worker, not passed to native_bridge by caller."""
    provider = ScriptedStream(
        [
            tool("write_file", "worker-write", path="out/worker.txt", content="autonomous-offline"),
            usage(), done("tool_calls"),
        ],
        [
            {"type": "text_delta", "text": '{"summary":"worker completed artifact"}'},
            usage(), done("stop"),
        ],
    )
    scopes = []
    worker = NativeWorker(
        runtime["orch"], runtime["queries"],
        agent_id=runtime["agent"].id,
        runner_factory=lambda task: native_runner(runtime, provider, scopes=scopes),
    )
    batch = await worker.run_batch(max_attempts=2)
    assert len(batch.attempts) == 1
    assert batch.attempts[0].verified and not batch.stopped_on_failure
    assert (runtime["workspace"] / "out" / "worker.txt").read_text() == "autonomous-offline"
    assert runtime["ledger"].state(scopes[0], "worker-write") == "SUCCEEDED"
    assert (await runtime["queries"].get_run(runtime["run"].id)).status == "completed"
    # Steady-state polling cannot spend more model calls for a completed task.
    before = len(provider.history)
    assert await worker.run_once() is None
    assert len(provider.history) == before


@pytest.mark.asyncio
async def test_real_agent_ledger_can_be_inspected_without_exposing_call_ids(runtime):
    """Verify actual tool ledger schema/scope matches read-only admin inspector."""
    provider = ScriptedStream(
        [tool("write_file", "private-call-id", path="out/report.txt", content="artifact"),
         usage(), done("tool_calls")],
        [{"type": "text_delta", "text": '{"summary":"written"}'},
         usage(), done("stop")],
    )
    scopes = []
    result = await run_native_task_attempt(
        runtime["orch"], task_id=runtime["task"].id,
        agent_id=runtime["agent"].id,
        runner=native_runner(runtime, provider, scopes=scopes),
    )
    assert result.verified
    reader = TrustedToolLedgerReader(runtime["ledger"].path)
    entries = reader.inspect(runtime["run"].id, result.attempt_id)
    assert len(entries) == 1
    assert entries[0].state == "SUCCEEDED"
    assert entries[0].tool == "write_file"
    assert entries[0].call_ref != "private-call-id"
    assert len(entries[0].call_ref) == 16


@pytest.mark.asyncio
async def test_interrupted_server_attempt_denies_late_native_write(runtime, tmp_path):
    """Offline cross-service demonstration, not a durable production fence.

    A trusted callback reads the server-owned attempt status. The test
    intentionally resumes a *new* tool request after recovery, not an
    already-started filesystem operation.
    """
    attempt = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    assert (await runtime["queries"].list_attempts(runtime["task"].id))[0].status == "running"
    await runtime["orch"].recover()

    def server_attempt_is_active():
        with sqlite3.connect(tmp_path / "orchestration.sqlite3") as db:
            row = db.execute(
                "SELECT status FROM task_attempts WHERE id = ?",
                (attempt.id,),
            ).fetchone()
        return row is not None and row[0] == "running"

    root = runtime["workspace"]
    fs = ScopedFilesystemExecutor(
        root,
        {"fs_read": [str(root / "src" / "**")],
         "fs_write": [str(root / "out" / "**")]},
    )
    scope = f"run-{runtime['run'].id}/attempt-{attempt.id}"
    dispatcher = NativeFilesystemDispatcher(
        fs, ledger=runtime["ledger"], execution_scope=scope,
        attempt_active=server_attempt_is_active,
    )
    provider = ScriptedStream(
        [tool("write_file", "late-write", path="out/late.txt", content="SHOULD_NOT_EXIST"),
         usage(), done("tool_calls")],
        [{"type": "text_delta", "text": '{"summary":"attempt blocked"}'},
         usage(), done("stop")],
    )
    await run_agent_loop(
        provider, dispatcher,
        [{"role": "user", "content": "Write only in the trusted workspace"}],
        max_turns=3, max_total_tokens=100, max_tool_calls=2,
    )

    assert runtime["ledger"].state(scope, "late-write") == "DENIED"
    assert not (root / "out" / "late.txt").exists()
    assert provider.history[1]["messages"][-1]["content"] == '{"error":"ATTEMPT_FENCED"}'
    assert (await runtime["queries"].get_task(runtime["task"].id)).status == "blocked"


def trusted_sqlite_dispatcher(runtime, tmp_path):
    # A trusted co-located worker receives IDs from its successful claim.
    # No path or attempt ID comes from the model-supplied tool call.
    attempt = runtime["claimed_attempt"]
    db_path = tmp_path / "orchestration.sqlite3"
    os.chmod(db_path, 0o600)
    root = runtime["workspace"]
    fs = ScopedFilesystemExecutor(root, {
        "fs_read": [str(root / "src" / "**")],
        "fs_write": [str(root / "out" / "**")],
    })
    gate = TrustedSqliteAttemptFence(
        db_path, run_id=runtime["run"].id,
        task_id=runtime["task"].id, attempt_id=attempt.id,
        agent_id=runtime["agent"].id,
    )
    dispatcher = NativeFilesystemDispatcher(
        fs, ledger=runtime["ledger"],
        execution_scope=gate.execution_scope,
        attempt_fence=gate,
    )
    return dispatcher, fs


@pytest.mark.asyncio
async def test_server_owned_sqlite_fence_denies_write_after_recovery(runtime, tmp_path):
    runtime["claimed_attempt"] = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    dispatcher, _ = trusted_sqlite_dispatcher(runtime, tmp_path)
    # The server owns state: no separate model-controlled active callback.
    assert (await runtime["queries"].get_task(runtime["task"].id)).status == "in_progress"
    assert dispatcher.dispatch(tool(
        "write_file", "first-valid", path="out/first.txt", content="before",
    )).ok

    await runtime["orch"].recover()
    denied = dispatcher.dispatch(tool(
        "write_file", "second-late", path="out/late.txt", content="AFTER",
    ))
    assert denied.error_code == "ATTEMPT_FENCED"
    assert not (runtime["workspace"] / "out" / "late.txt").exists()
    assert runtime["ledger"].state(dispatcher._scope, "second-late") == "DENIED"
    assert (await runtime["queries"].get_task(runtime["task"].id)).status == "blocked"


@pytest.mark.asyncio
async def test_sqlite_recovery_waits_for_in_flight_file_write(runtime, tmp_path):
    runtime["claimed_attempt"] = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    dispatcher, fs = trusted_sqlite_dispatcher(runtime, tmp_path)
    started, release = Event(), Event()
    actual_write = fs.write_text

    def paused_write(path, content):
        started.set()
        if not release.wait(5):
            raise RuntimeError("Bounded test barrier timed out")
        return actual_write(path, content)

    fs.write_text = paused_write
    writer = asyncio.create_task(asyncio.to_thread(
        dispatcher.dispatch,
        tool("write_file", "in-flight", path="out/written.txt", content="safe-before-revoke"),
    ))
    recovery = None
    try:
        assert await asyncio.to_thread(started.wait, 5)
        recovery = asyncio.create_task(runtime["orch"].recover())
        await asyncio.sleep(0.15)
        assert not recovery.done(), "Recovery committed while admitted I/O was in flight"
    finally:
        release.set()

    result = await asyncio.wait_for(writer, 10)
    assert result.ok
    assert recovery is not None
    recovered = await asyncio.wait_for(recovery, 10)
    assert recovered["recovered_attempts"] == 1
    assert (runtime["workspace"] / "out" / "written.txt").read_text() == "safe-before-revoke"
    assert runtime["ledger"].state(dispatcher._scope, "in-flight") == "SUCCEEDED"

    late = dispatcher.dispatch(tool(
        "write_file", "post-revoke", path="out/late.txt", content="forbidden",
    ))
    assert late.error_code == "ATTEMPT_FENCED"
    assert not (runtime["workspace"] / "out" / "late.txt").exists()


@pytest.mark.asyncio
async def test_sqlite_fence_invalid_database_or_identity_fails_closed(runtime, tmp_path):
    attempt = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    runtime["claimed_attempt"] = attempt
    dispatcher, _ = trusted_sqlite_dispatcher(runtime, tmp_path)
    with pytest.raises(ValueError, match="matching durable scope"):
        NativeFilesystemDispatcher(
            dispatcher._filesystem, ledger=runtime["ledger"],
            execution_scope="run-wrong/attempt-wrong",
            attempt_fence=dispatcher._attempt_fence,
        )

    os.chmod(tmp_path / "orchestration.sqlite3", 0o644)
    denied = dispatcher.dispatch(tool(
        "write_file", "database-untrusted", path="out/untrusted.txt", content="bad",
    ))
    assert denied.error_code == "ATTEMPT_FENCED"
    assert not (runtime["workspace"] / "out" / "untrusted.txt").exists()
    assert runtime["ledger"].state(dispatcher._scope, "database-untrusted") == "DENIED"


@pytest.mark.asyncio
async def test_sqlite_attempt_fence_denies_tool_after_confirmed_completion(runtime, tmp_path):
    attempt = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    runtime["claimed_attempt"] = attempt
    dispatcher, _ = trusted_sqlite_dispatcher(runtime, tmp_path)

    # Even a legitimate prior lease identity cannot authorize another
    # write once the trusted orchestration server has completed the task.
    await runtime["orch"].submit(
        runtime["task"].id, attempt.id, runtime["agent"].id,
        {"summary": "accepted by contract gate"},
    )
    result = dispatcher.dispatch(tool(
        "write_file", "after-completion", path="out/forbidden.txt", content="NO",
    ))
    assert result.error_code == "ATTEMPT_FENCED"
    assert not (runtime["workspace"] / "out" / "forbidden.txt").exists()
    assert runtime["ledger"].state(dispatcher._scope, "after-completion") == "DENIED"


@pytest.mark.asyncio
async def test_server_fence_denies_hardlinked_sqlite_database(runtime, tmp_path):
    attempt = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    database = tmp_path / "orchestration.sqlite3"
    os.chmod(database, 0o600)
    linked = tmp_path / "extra-link.sqlite3"
    os.link(database, linked)
    with pytest.raises(AttemptFenceDenied, match="unavailable"):
        TrustedSqliteAttemptFence(
            database, run_id=runtime["run"].id,
            task_id=runtime["task"].id, attempt_id=attempt.id,
            agent_id=runtime["agent"].id,
        )


@pytest.mark.asyncio
async def test_sqlite_fence_rejects_revoked_and_invalid_server_lease(runtime, tmp_path):
    attempt = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    svc = AttemptLeaseService(runtime["factory"], ttl_seconds=60)
    grant = await svc.issue(attempt.id, runtime["agent"].id)
    path = tmp_path / "orchestration.sqlite3"
    os.chmod(path, 0o600)
    workspace = runtime["workspace"]
    fs = ScopedFilesystemExecutor(workspace, {
        "fs_write": [str(workspace / "out" / "**")],
    })
    def dispatcher(token):
        fence = TrustedSqliteAttemptFence(
            path, run_id=runtime["run"].id, task_id=runtime["task"].id,
            attempt_id=attempt.id, agent_id=runtime["agent"].id,
            lease_token=token, require_lease=True,
        )
        return NativeFilesystemDispatcher(
            fs, ledger=runtime["ledger"],
            execution_scope=fence.execution_scope, attempt_fence=fence,
        )
    bad = dispatcher("x" * 44).dispatch(tool(
        "write_file", "wrong-token", path="out/bad.txt", content="NEVER",
    ))
    assert bad.error_code == "ATTEMPT_FENCED"
    assert not (workspace / "out" / "bad.txt").exists()

    allowed = dispatcher(grant.token).dispatch(tool(
        "write_file", "authorized-once", path="out/ok.txt", content="allowed",
    ))
    assert allowed.ok and (workspace / "out" / "ok.txt").read_text() == "allowed"
    assert await svc.revoke(attempt.id)

    denied = dispatcher(grant.token).dispatch(tool(
        "write_file", "revoked", path="out/revoked.txt", content="NEVER",
    ))
    assert denied.error_code == "ATTEMPT_FENCED"
    assert not (workspace / "out" / "revoked.txt").exists()
    assert runtime["ledger"].state(
        f"run-{runtime['run'].id}/attempt-{attempt.id}", "revoked",
    ) == "DENIED"


@pytest.mark.asyncio
async def test_sqlite_lease_revoke_waits_for_an_admitted_write(runtime, tmp_path):
    attempt = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    svc = AttemptLeaseService(runtime["factory"], ttl_seconds=60)
    grant = await svc.issue(attempt.id, runtime["agent"].id)
    path = tmp_path / "orchestration.sqlite3"
    os.chmod(path, 0o600)
    root = runtime["workspace"]
    fs = ScopedFilesystemExecutor(root, {
        "fs_write": [str(root / "out" / "**")],
    })
    fence = TrustedSqliteAttemptFence(
        path, run_id=runtime["run"].id, task_id=runtime["task"].id,
        attempt_id=attempt.id, agent_id=runtime["agent"].id,
        lease_token=grant.token, require_lease=True,
    )
    dispatcher = NativeFilesystemDispatcher(
        fs, ledger=runtime["ledger"],
        execution_scope=fence.execution_scope, attempt_fence=fence,
    )
    started, release = Event(), Event()
    original_write = fs.write_text
    def slow_write(path, content):
        started.set()
        if not release.wait(5):
            raise OSError("Timed out waiting for guarded test write")
        return original_write(path, content)
    fs.write_text = slow_write
    writing = asyncio.create_task(asyncio.to_thread(
        dispatcher.dispatch,
        tool("write_file", "accepted", path="out/accepted.txt", content="before revoke"),
    ))
    revoking = None
    try:
        assert await asyncio.to_thread(started.wait, 5)
        revoking = asyncio.create_task(svc.revoke(attempt.id))
        await asyncio.sleep(0.15)
        assert not revoking.done(), "Revoke completed before the guarded write"
    finally:
        release.set()
    assert (await asyncio.wait_for(writing, 10)).ok
    assert revoking is not None and await asyncio.wait_for(revoking, 10)
    assert (root / "out" / "accepted.txt").read_text() == "before revoke"
    late = dispatcher.dispatch(tool(
        "write_file", "too-late", path="out/late-leased.txt", content="DENY",
    ))
    assert late.error_code == "ATTEMPT_FENCED"
    assert not (root / "out" / "late-leased.txt").exists()


@pytest.mark.asyncio
async def test_sqlite_fence_rejects_expired_lease_before_tool_io(runtime, tmp_path):
    attempt = await runtime["orch"].claim_task(runtime["task"].id, runtime["agent"].id)
    svc = AttemptLeaseService(runtime["factory"], ttl_seconds=5)
    grant = await svc.issue(attempt.id, runtime["agent"].id)
    async with runtime["factory"]() as session:
        record = await session.get(AttemptLease, attempt.id)
        record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()
    db = tmp_path / "orchestration.sqlite3"
    os.chmod(db, 0o600)
    fs = ScopedFilesystemExecutor(runtime["workspace"], {
        "fs_write": [str(runtime["workspace"] / "out" / "**")],
    })
    fence = TrustedSqliteAttemptFence(
        db, run_id=runtime["run"].id, task_id=runtime["task"].id,
        attempt_id=attempt.id, agent_id=runtime["agent"].id,
        lease_token=grant.token, require_lease=True,
    )
    dispatch = NativeFilesystemDispatcher(
        fs, ledger=runtime["ledger"],
        execution_scope=fence.execution_scope, attempt_fence=fence,
    )
    result = dispatch.dispatch(tool(
        "write_file", "expired-credential", path="out/expired.txt", content="NEVER",
    ))
    assert result.error_code == "ATTEMPT_FENCED"
    assert runtime["ledger"].state(fence.execution_scope, "expired-credential") == "DENIED"
    assert not (runtime["workspace"] / "out" / "expired.txt").exists()


@pytest.mark.asyncio
async def test_sqlite_fence_requires_issued_capability_when_enforced(runtime, tmp_path):
    attempt = await runtime["orch"].claim_task(runtime["task"].id, runtime["agent"].id)
    db = tmp_path / "orchestration.sqlite3"
    os.chmod(db, 0o600)
    with pytest.raises(ValueError, match="required"):
        TrustedSqliteAttemptFence(
            db, run_id=runtime["run"].id, task_id=runtime["task"].id,
            attempt_id=attempt.id, agent_id=runtime["agent"].id,
            require_lease=True,
        )


@pytest.mark.asyncio
async def test_privileged_https_gateway_requires_token_and_fences_remote_write(runtime, tmp_path):
    attempt = await runtime["orch"].claim_task(runtime["task"].id, runtime["agent"].id)
    grant = await AttemptLeaseService(runtime["factory"], ttl_seconds=60).issue(
        attempt.id, runtime["agent"].id,
    )
    database = tmp_path / "orchestration.sqlite3"
    os.chmod(database, 0o600)
    key = "gateway-control-plane-secret-opaque-key-123456"
    app = build_trusted_filesystem_gateway(
        workspace_root=str(runtime["workspace"]),
        orchestration_database=str(database),
        ledger_database=str(runtime["ledger"].path),
        gateway_key=key,
    )
    def req(call_id, name="write_file", **kwargs):
        return {
            "run_id": runtime["run"].id, "task_id": runtime["task"].id,
            "attempt_id": attempt.id, "agent_id": runtime["agent"].id,
            "lease_token": grant.token, "event": tool(name, call_id, **kwargs),
        }

    async with httpx.AsyncClient(
        base_url="https://trusted-gateway.example", transport=httpx.ASGITransport(app=app),
    ) as client:
        valid = req("remote-write", path="out/report.txt", content="approved")
        unauthorized = await client.post("/v1/filesystem/dispatch", json=valid)
        assert unauthorized.status_code == 401
        assert not (runtime["workspace"] / "out" / "report.txt").exists()
        client.headers["X-Gateway-Key"] = key
        created = await client.post("/v1/filesystem/dispatch", json=valid)
        assert created.status_code == 200 and created.json()["ok"]
        assert created.headers["cache-control"] == "no-store"
        assert (runtime["workspace"] / "out" / "report.txt").read_text() == "approved"

        replay = await client.post("/v1/filesystem/dispatch", json=valid)
        assert replay.status_code == 200
        assert replay.json()["error_code"] == "DUPLICATE_CALL"

        denied_path = await client.post("/v1/filesystem/dispatch", json=req(
            "path-escape", path="../outside.txt", content="NEVER",
        ))
        assert denied_path.json()["ok"] is False
        assert not (tmp_path / "outside.txt").exists()

        incorrect = req("wrong-lease", path="out/bad.txt", content="NEVER")
        incorrect["lease_token"] = "x" * 44
        rejected = await client.post("/v1/filesystem/dispatch", json=incorrect)
        assert rejected.json()["error_code"] == "ATTEMPT_FENCED"
        assert "x" * 44 not in rejected.text
        assert not (runtime["workspace"] / "out" / "bad.txt").exists()

        assert await AttemptLeaseService(runtime["factory"]).revoke(attempt.id)
        late = await client.post("/v1/filesystem/dispatch", json=req(
            "after-revoke", path="out/late.txt", content="NEVER",
        ))
        assert late.json()["error_code"] == "ATTEMPT_FENCED"
        assert not (runtime["workspace"] / "out" / "late.txt").exists()

    assert runtime["ledger"].state(
        f"run-{runtime['run'].id}/attempt-{attempt.id}", "remote-write",
    ) == "SUCCEEDED"
    assert runtime["ledger"].state(
        f"run-{runtime['run'].id}/attempt-{attempt.id}", "after-revoke",
    ) == "DENIED"


@pytest.mark.asyncio
async def test_https_gateway_revocation_waits_for_inflight_remote_tool(runtime, tmp_path, monkeypatch):
    attempt = await runtime["orch"].claim_task(runtime["task"].id, runtime["agent"].id)
    service = AttemptLeaseService(runtime["factory"], ttl_seconds=60)
    grant = await service.issue(attempt.id, runtime["agent"].id)
    db = tmp_path / "orchestration.sqlite3"
    os.chmod(db, 0o600)
    key = "gateway-control-plane-secret-opaque-key-123456"
    app = build_trusted_filesystem_gateway(
        workspace_root=str(runtime["workspace"]), orchestration_database=str(db),
        ledger_database=str(runtime["ledger"].path), gateway_key=key,
    )
    started, finish = Event(), Event()
    original_write = ScopedFilesystemExecutor.write_text

    def held_write(self, path, data):
        started.set()
        if not finish.wait(5):
            raise OSError("Test write barrier expired")
        return original_write(self, path, data)

    monkeypatch.setattr(ScopedFilesystemExecutor, "write_text", held_write)
    body = {
        "run_id": runtime["run"].id, "task_id": runtime["task"].id,
        "attempt_id": attempt.id, "agent_id": runtime["agent"].id,
        "lease_token": grant.token,
        "event": tool("write_file", "held-write", path="out/pinned.txt", content="admitted"),
    }
    async with httpx.AsyncClient(
        base_url="https://trusted-gateway.example", transport=httpx.ASGITransport(app=app),
        headers={"X-Gateway-Key": key},
    ) as client:
        started_call = asyncio.create_task(client.post("/v1/filesystem/dispatch", json=body))
        revoke = None
        try:
            assert await asyncio.to_thread(started.wait, 5)
            revoke = asyncio.create_task(service.revoke(attempt.id))
            await asyncio.sleep(0.15)
            assert not revoke.done(), "Revoke committed before in-flight gateway write"
        finally:
            finish.set()
        assert (await asyncio.wait_for(started_call, 10)).json()["ok"]
        assert revoke is not None and await asyncio.wait_for(revoke, 10)
        after = dict(body)
        after["event"] = tool(
            "write_file", "revoke-late", path="out/later.txt", content="NEVER",
        )
        denied = await client.post("/v1/filesystem/dispatch", json=after)
        assert denied.json()["error_code"] == "ATTEMPT_FENCED"
        assert not (runtime["workspace"] / "out" / "later.txt").exists()
    assert (runtime["workspace"] / "out" / "pinned.txt").read_text() == "admitted"


@pytest.mark.asyncio
async def test_filesystem_gateway_refuses_insecure_transport_and_invalid_inputs(runtime, tmp_path):
    database = tmp_path / "orchestration.sqlite3"
    os.chmod(database, 0o600)
    key = "gateway-control-plane-secret-opaque-key-123456"
    app = build_trusted_filesystem_gateway(
        workspace_root=str(runtime["workspace"]), orchestration_database=str(database),
        ledger_database=str(runtime["ledger"].path), gateway_key=key,
    )
    async with httpx.AsyncClient(
        base_url="http://trusted-gateway.example", transport=httpx.ASGITransport(app=app),
        headers={"X-Gateway-Key": key},
    ) as client:
        resp = await client.post("/v1/filesystem/dispatch", json={"debug": "SECRET"})
        assert resp.status_code == 403
    async with httpx.AsyncClient(
        base_url="https://trusted-gateway.example", transport=httpx.ASGITransport(app=app),
        headers={"X-Gateway-Key": key},
    ) as client:
        malformed = await client.post("/v1/filesystem/dispatch", json={"lease_token": "SECRET"})
        assert malformed.status_code == 400
        assert "SECRET" not in malformed.text
        oversized = await client.post(
            "/v1/filesystem/dispatch",
            content=b"x" * 1_100_001,
        )
        assert oversized.status_code == 413
