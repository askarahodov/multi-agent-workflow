"""Optional tool dispatch is only enabled with persistent ledger and fencing."""
from __future__ import annotations

import os
import shutil
import sqlite3
from unittest.mock import patch

import pytest

from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
from agent_management.scoped_fs import ScopedFilesystemExecutor
from agent_management.tool_ledger import SqliteToolLedger
from agent_management.trusted_process_tools import TrustedReadOnlyProcessTools, ProcessToolResult
from agent_management.trusted_https_get import TrustedHttpsGet, HttpsResult
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
    https = TrustedHttpsGet(
        {"network": ["https://api.example.com/**"]},
        allowed_hosts=frozenset({"api.example.com"}),
    )
    return fs, ledger, fence, proc, https, database


def dispatcher(parts):
    fs, ledger, fence, proc, https, _db = parts
    return NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope=fence.execution_scope,
        attempt_fence=fence, process_tools=proc, https_get=https,
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
    fs, ledger, fence, proc, https, _db = trusted
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
        "read_file", "write_file", "git_status", "shell_list", "http_get",
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


def test_https_operation_has_exact_schema_and_fenced_scope(trusted):
    gate = dispatcher(trusted)
    https = trusted[4]
    with patch.object(https, "get", return_value=HttpsResult(True, "trusted body")) as get:
        result = gate.dispatch(event("http_get", "call-http", url="https://api.example.com/docs"))
    assert result.ok and result.content == "trusted body"
    get.assert_called_once_with("https://api.example.com/docs")
    assert trusted[1].state(trusted[2].execution_scope, "call-http") == "SUCCEEDED"


@pytest.mark.parametrize("name,arguments", [
    ("git_status", {"command": "status"}),
    ("shell_list", {"path": "/etc"}),
    ("http_get", {}),
    ("http_get", {"url": 7}),
    ("http_get", {"url": "https://api.example.com", "extra": "bad"}),
])
def test_bad_args_never_execute_side_effect(trusted, name, arguments):
    gate = dispatcher(trusted)
    with patch.object(trusted[3], "execute") as process, patch.object(trusted[4], "get") as get:
        out = gate.dispatch({"type": "tool_call", "name": name,
                             "id": "call-invalid", "arguments": arguments})
    assert not out.ok and out.error_code == "INVALID_ARGUMENTS"
    process.assert_not_called()
    get.assert_not_called()


def test_revoked_attempt_blocks_process_and_https(trusted):
    db = trusted[-1]
    with sqlite3.connect(db) as connection:
        connection.execute("UPDATE task_attempts SET status = 'interrupted'")
    gate = dispatcher(trusted)
    with patch.object(trusted[3], "execute") as process, patch.object(trusted[4], "get") as get:
        assert gate.dispatch(event("git_status", "call-revoked")).error_code == "ATTEMPT_FENCED"
        assert gate.dispatch(event("http_get", "call-http-revoked",
                                   url="https://api.example.com/docs")).error_code == "ATTEMPT_FENCED"
    process.assert_not_called()
    get.assert_not_called()


def test_failed_https_response_is_audited_without_secret(trusted):
    gate = dispatcher(trusted)
    with patch.object(trusted[4], "get", return_value=HttpsResult(False, "", "HTTP_REJECTED")):
        outcome = gate.dispatch(event("http_get", "call-fail",
                                      url="https://api.example.com/docs"))
    assert outcome.error_code == "HTTP_REJECTED"
    assert outcome.to_provider_message()["content"] == '{"error":"HTTP_REJECTED"}'
    assert trusted[1].state(trusted[2].execution_scope, "call-fail") == "DENIED"
