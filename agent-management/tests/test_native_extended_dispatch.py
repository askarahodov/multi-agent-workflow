"""Optional tool dispatch is only enabled with persistent ledger and fencing."""
from __future__ import annotations

import asyncio
import os
import time
import shutil
import sqlite3
from unittest.mock import patch

import pytest

from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
from agent_management.scoped_fs import ScopedFilesystemExecutor
from agent_management.tool_ledger import SqliteToolLedger
from agent_management.trusted_process_tools import TrustedReadOnlyProcessTools, ProcessToolResult
from shared.attempt_fence import TrustedSqliteAttemptFence

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX SQLite execution fence")


@pytest.fixture
def trusted(tmp_path):
    git, ls = shutil.which("git"), shutil.which("ls")
    if not git or not ls:
        pytest.skip("Git and ls required")
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "out").mkdir()
    fs = ScopedFilesystemExecutor(root, {
        "fs_read": [str(root / "**")], "fs_write": [str(root / "out" / "**")],
    })
    ledger = SqliteToolLedger(tmp_path / "ledger.sqlite3")
    database = tmp_path / "orchestration.sqlite3"
    with sqlite3.connect(database) as db:
        db.executescript("""
        CREATE TABLE workflow_runs (id TEXT, status TEXT);
        CREATE TABLE agents (id TEXT, status TEXT);
        CREATE TABLE tasks (id TEXT, status TEXT, assigned_agent_id TEXT,
                            workflow_run_id TEXT, attempt_count INTEGER);
        CREATE TABLE task_attempts (id TEXT, task_id TEXT, agent_id TEXT,
                                    attempt_number INTEGER, status TEXT);
        INSERT INTO workflow_runs VALUES ('run1','running');
        INSERT INTO agents VALUES ('agent1','busy');
        INSERT INTO tasks VALUES ('task1','in_progress','agent1','run1',1);
        INSERT INTO task_attempts VALUES ('attempt1','task1','agent1',1,'running');
        """)
    os.chmod(database, 0o600)
    fence = TrustedSqliteAttemptFence(
        database, run_id="run1", task_id="task1",
        attempt_id="attempt1", agent_id="agent1",
    )
    proc = TrustedReadOnlyProcessTools(
        root, {"git": ["status"], "shell": ["ls"]},
        git_executable=os.path.realpath(git),
        ls_executable=os.path.realpath(ls),
    )
    return fs, ledger, fence, proc, database


def dispatcher(parts):
    fs, ledger, fence, proc, _db = parts
    return NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope=fence.execution_scope,
        attempt_fence=fence, process_tools=proc,
    )


def event(name, call, **arguments):
    return {"type": "tool_call", "name": name, "id": call, "arguments": arguments}


def test_default_dispatcher_still_offers_only_file_tools(trusted):
    fs = trusted[0]
    normal = NativeFilesystemDispatcher(fs)
    assert [x["function"]["name"] for x in normal.available_tools_schema()] == [
        "read_file", "write_file",
    ]
    assert normal.dispatch(event("git_status", "call-x")).error_code == "UNKNOWN_TOOL"


def test_extended_tools_require_durable_fence(trusted):
    fs, ledger, fence, proc, _db = trusted
    with pytest.raises(ValueError, match="ledger"):
        NativeFilesystemDispatcher(fs, process_tools=proc)
    with pytest.raises(ValueError, match="fencing"):
        NativeFilesystemDispatcher(
            fs, ledger=ledger, execution_scope=fence.execution_scope,
            process_tools=proc,
        )


def test_extended_schema_only_lists_enabled_operations(trusted):
    gate = dispatcher(trusted)
    assert [x["function"]["name"] for x in gate.available_tools_schema()] == [
        "read_file", "write_file", "git_status", "shell_list",
    ]


@pytest.mark.parametrize("name,response", [
    ("git_status", "clean"), ("shell_list", "entry.txt"),
])
def test_process_operations_record_and_reject_replay(trusted, name, response):
    gate = dispatcher(trusted)
    proc = trusted[3]
    with patch.object(proc, "execute", return_value=ProcessToolResult(True, response)) as call:
        first = gate.dispatch(event(name, "call-once"))
        repeated = dispatcher(trusted).dispatch(event(name, "call-once"))
    assert first.ok and first.content == response
    assert repeated.error_code == "DUPLICATE_CALL"
    call.assert_called_once_with(name)
    assert trusted[1].state(trusted[2].execution_scope, "call-once") == "SUCCEEDED"


@pytest.mark.parametrize("name,arguments", [
    ("git_status", {"command": "status"}),
    ("shell_list", {"path": "/etc"}),
])
def test_bad_args_never_execute_side_effect(trusted, name, arguments):
    gate = dispatcher(trusted)
    with patch.object(trusted[3], "execute") as process:
        out = gate.dispatch({"type": "tool_call", "name": name,
                             "id": "call-invalid", "arguments": arguments})
    assert not out.ok and out.error_code == "INVALID_ARGUMENTS"
    process.assert_not_called()


def test_revoked_attempt_blocks_process(trusted):
    db = trusted[-1]
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE task_attempts SET status = 'interrupted'")
    gate = dispatcher(trusted)
    with patch.object(trusted[3], "execute") as process:
        assert gate.dispatch(event("git_status", "call-revoked")).error_code == "ATTEMPT_FENCED"
    process.assert_not_called()


@pytest.mark.asyncio
async def test_agent_loop_exposes_only_trusted_schema_and_uses_fenced_tool(trusted):
    from agent_management.agent_loop import run_agent_loop

    class Provider:
        def __init__(self):
            self.calls = []
        async def stream(self, messages, *, tools, max_tokens):
            self.calls.append((messages, tools))
            if len(self.calls) == 1:
                yield event("git_status", "from-model")
                yield {"type": "usage", "prompt_tokens": 4,
                       "completion_tokens": 2, "total_tokens": 6}
                yield {"type": "done", "finish_reason": "tool_calls"}
            else:
                yield {"type": "text_delta", "text": "Checked"}
                yield {"type": "usage", "prompt_tokens": 2,
                       "completion_tokens": 2, "total_tokens": 4}
                yield {"type": "done", "finish_reason": "stop"}

    gate = dispatcher(trusted)
    provider = Provider()
    with patch.object(trusted[3], "execute", return_value=ProcessToolResult(True, "clean")):
        result = await run_agent_loop(
            provider, gate, [{"role": "user", "content": "check"}],
        )
    assert result.output == "Checked" and result.executed_calls == 1
    assert provider.calls[1][0][-1] == {
        "role": "tool", "tool_call_id": "from-model", "content": "clean",
    }
    assert any(x["function"]["name"] == "git_status" for x in provider.calls[0][1])
    assert trusted[1].state(trusted[2].execution_scope, "from-model") == "SUCCEEDED"


def test_http_remains_unavailable_without_hard_total_deadline(trusted):
    from agent_management.trusted_https_get import TrustedHttpsGet
    fs, ledger, fence, proc, _database = trusted
    adapter = TrustedHttpsGet(
        {"network": ["https://api.example.com/**"]},
        allowed_hosts=frozenset({"api.example.com"}),
    )
    with pytest.raises(ValueError, match="cancellable total deadline"):
        NativeFilesystemDispatcher(
            fs, ledger=ledger, execution_scope=fence.execution_scope,
            attempt_fence=fence, process_tools=proc, https_get=adapter,
        )
    assert dispatcher(trusted).dispatch(
        event("http_get", "call-unsupported", url="https://api.example.com/")
    ).error_code == "UNKNOWN_TOOL"


def test_execution_ledger_cannot_share_orchestration_sqlite_file(trusted):
    fs, _ledger, fence, proc, database = trusted
    shared_ledger = SqliteToolLedger(database)
    with pytest.raises(ValueError, match="must be separate"):
        NativeFilesystemDispatcher(
            fs, ledger=shared_ledger, execution_scope=fence.execution_scope,
            attempt_fence=fence, process_tools=proc,
        )


def test_process_failure_is_finalized_after_fence_releases(trusted):
    gate = dispatcher(trusted)
    with patch.object(trusted[3], "execute", return_value=ProcessToolResult(
        False, "", "PROCESS_FAILED",
    )):
        outcome = gate.dispatch(event("git_status", "call-failed"))
    assert outcome.error_code == "PROCESS_FAILED"
    assert trusted[1].state(trusted[2].execution_scope, "call-failed") == "DENIED"


@pytest.mark.asyncio
async def test_agent_deadline_interrupts_wait_for_process_tool(trusted):
    from agent_management.agent_loop import run_agent_loop

    class Provider:
        async def stream(self, messages, *, tools, max_tokens):
            yield event("git_status", "call-slow")
            yield {"type": "usage", "prompt_tokens": 1,
                   "completion_tokens": 1, "total_tokens": 2}
            yield {"type": "done", "finish_reason": "tool_calls"}

    def slow(_name):
        time.sleep(0.1)
        return ProcessToolResult(True, "late")

    with patch.object(trusted[3], "execute", side_effect=slow):
        with pytest.raises(TimeoutError):
            await run_agent_loop(
                Provider(), dispatcher(trusted),
                [{"role": "user", "content": "check"}],
                timeout_seconds=0.01,
            )
        # Offloaded bounded tool may still finish, but never produces a
        # successful agent result after deadline and retains its fence.
        await asyncio.sleep(0.15)
    assert trusted[1].state(trusted[2].execution_scope, "call-slow") == "SUCCEEDED"


def test_pinned_https_requires_fence_and_is_not_advertised_by_default(trusted):
    from agent_management.trusted_https import TrustedHTTPSExecutor
    client = TrustedHTTPSExecutor(
        {"network": ["https://example.com/status"]},
        allowed_targets={"https://example.com/status": ("93.184.215.14",)},
    )
    fs, ledger, fence, _proc, _db = trusted
    with pytest.raises(ValueError, match="ledger"):
        NativeFilesystemDispatcher(fs, pinned_https=client)
    normal = NativeFilesystemDispatcher(fs)
    assert "http_get" not in [item["function"]["name"] for item in normal.available_tools_schema()]
    gate = NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope=fence.execution_scope,
        attempt_fence=fence, pinned_https=client,
    )
    assert "http_get" in [item["function"]["name"] for item in gate.available_tools_schema()]


def test_pinned_https_dispatch_is_fenced_durable_and_replay_safe(trusted):
    from agent_management.trusted_https import TrustedHTTPSExecutor, HTTPOutcome
    fs, ledger, fence, _proc, db = trusted
    client = TrustedHTTPSExecutor(
        {"network": ["https://example.com/status"]},
        allowed_targets={"https://example.com/status": ("93.184.215.14",)},
    )
    def new_dispatcher():
        return NativeFilesystemDispatcher(
            fs, ledger=ledger, execution_scope=fence.execution_scope,
            attempt_fence=fence, pinned_https=client,
        )
    gate = new_dispatcher()
    with patch.object(client, "get_bounded", return_value=HTTPOutcome(200, b"ok")) as get:
        invalid = gate.dispatch(event("http_get", "invalid", url="https://example.com", extra="bad"))
        assert invalid.error_code == "INVALID_ARGUMENTS"
        get.assert_not_called()
        result = gate.dispatch(event("http_get", "http-once", url="https://example.com/status"))
        duplicate = new_dispatcher().dispatch(event("http_get", "http-once", url="https://example.com/status"))
        assert result.ok and result.content == "ok"
        assert duplicate.error_code == "DUPLICATE_CALL"
        get.assert_called_once_with("https://example.com/status")
        assert ledger.state(fence.execution_scope, "http-once") == "SUCCEEDED"
        with sqlite3.connect(db) as connection:
            connection.execute("UPDATE task_attempts SET status = 'interrupted'")
        revoked = new_dispatcher().dispatch(event("http_get", "http-revoked", url="https://example.com/status"))
        assert revoked.error_code == "ATTEMPT_FENCED"
        get.assert_called_once()
