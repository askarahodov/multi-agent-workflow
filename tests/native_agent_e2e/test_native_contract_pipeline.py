"""Offline integration of the *real* native agent and orchestration packages.

This suite joins two separately installed services. There are no real LLM calls,
shells or Git hooks. It verifies that Contract Gate, not the LLM, owns outcomes.
"""
from __future__ import annotations

import json

import pytest
import pytest_asyncio
from sqlalchemy import select

from agent_management.agent_loop import run_agent_loop
from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
from agent_management.scoped_fs import ScopedFilesystemExecutor
from agent_management.tool_ledger import SqliteToolLedger
from orchestration_server.db import build_engine, build_session_factory, create_all
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
