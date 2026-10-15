"""Crash/retry safety checks for the SQLite native tool claim ledger."""
from __future__ import annotations

import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from agent_management.errors import ToolPolicyDenied
from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
from agent_management.scoped_fs import ScopedFilesystemExecutor
from agent_management.tool_ledger import SqliteToolLedger

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW"),
    reason="POSIX native filesystem execution only",
)


@pytest.fixture
def runtime(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "out").mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "input.txt").write_text("readable")
    fs = ScopedFilesystemExecutor(
        workspace, {
            "fs_read": [str(workspace / "src" / "**")],
            "fs_write": [str(workspace / "out" / "**")],
        },
    )
    ledger = SqliteToolLedger(tmp_path / "control-plane.sqlite3")
    return fs, ledger, workspace


def write(call_id, content="first"):
    return {
        "type": "tool_call", "id": call_id, "name": "write_file",
        "arguments": {"path": "out/report.txt", "content": content},
    }


def test_persistent_replay_denied_after_new_dispatcher_instance(runtime):
    fs, ledger, workspace = runtime
    first = NativeFilesystemDispatcher(fs, ledger=ledger, execution_scope="run-1/task-1")
    assert first.dispatch(write("call-1", "first")).ok
    assert ledger.state("run-1/task-1", "call-1") == "SUCCEEDED"

    restarted = NativeFilesystemDispatcher(fs, ledger=ledger, execution_scope="run-1/task-1")
    result = restarted.dispatch(write("call-1", "replayed"))
    assert not result.ok and result.error_code == "DUPLICATE_CALL"
    assert (workspace / "out" / "report.txt").read_text() == "first"
    assert ledger.state("run-1/task-1", "call-1") == "SUCCEEDED"


def test_replay_denied_after_reopening_ledger(runtime):
    fs, ledger, workspace = runtime
    assert NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope="run-1/task-1",
    ).dispatch(write("call-1")).ok
    new_ledger = SqliteToolLedger(ledger.path)
    same_scope = NativeFilesystemDispatcher(
        fs, ledger=new_ledger, execution_scope="run-1/task-1",
    )
    result = same_scope.dispatch(write("call-1", "new"))
    assert result.error_code == "DUPLICATE_CALL"
    assert (workspace / "out" / "report.txt").read_text() == "first"


def test_different_trusted_scope_does_not_collide(runtime):
    fs, ledger, workspace = runtime
    assert NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope="run-1/task-1",
    ).dispatch(write("call-1", "one")).ok
    assert NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope="run-2/task-2",
    ).dispatch(write("call-1", "two")).ok
    assert (workspace / "out" / "report.txt").read_text() == "two"


def test_ambiguous_claim_is_never_auto_retried(runtime):
    fs, ledger, workspace = runtime
    assert ledger.claim("run-1/task-1", "call-aborted", "write_file")
    assert ledger.state("run-1/task-1", "call-aborted") == "CLAIMED"
    result = NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope="run-1/task-1",
    ).dispatch(write("call-aborted", "should-not-write"))
    assert result.error_code == "DUPLICATE_CALL"
    assert ledger.state("run-1/task-1", "call-aborted") == "CLAIMED"
    assert not (workspace / "out" / "report.txt").exists()


def test_concurrent_cross_instance_claim_only_one_write(runtime):
    fs, ledger, workspace = runtime
    a = NativeFilesystemDispatcher(fs, ledger=ledger, execution_scope="run-1/task-1")
    b = NativeFilesystemDispatcher(fs, ledger=ledger, execution_scope="run-1/task-1")
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(a.dispatch, write("same-id", "from-a"))
        two = pool.submit(b.dispatch, write("same-id", "from-b"))
        results = [one.result(), two.result()]
    assert [x.ok for x in results].count(True) == 1
    assert [x.error_code for x in results].count("DUPLICATE_CALL") == 1
    assert (workspace / "out" / "report.txt").read_text() in ("from-a", "from-b")


def test_ledger_failure_blocks_side_effect(runtime):
    fs, ledger, workspace = runtime
    dispatcher = NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope="run-1/task-1",
    )
    with patch.object(ledger, "claim", side_effect=ToolPolicyDenied("Ledger down")):
        with pytest.raises(ToolPolicyDenied, match="Ledger down"):
            dispatcher.dispatch(write("call-new", "should-not-write"))
    assert not (workspace / "out" / "report.txt").exists()


def test_finalize_failure_keeps_ambiguous_claim_and_blocks_replay(runtime):
    fs, ledger, workspace = runtime
    dispatcher = NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope="run-1/task-1",
    )
    with patch.object(ledger, "finalize", side_effect=ToolPolicyDenied("fail to finish")):
        with pytest.raises(ToolPolicyDenied, match="fail to finish"):
            dispatcher.dispatch(write("call-write", "already-written"))
    assert (workspace / "out" / "report.txt").read_text() == "already-written"
    assert ledger.state("run-1/task-1", "call-write") == "CLAIMED"
    after_restart = NativeFilesystemDispatcher(
        fs, ledger=SqliteToolLedger(ledger.path), execution_scope="run-1/task-1",
    )
    result = after_restart.dispatch(write("call-write", "bad-retry"))
    assert result.error_code == "DUPLICATE_CALL"
    assert (workspace / "out" / "report.txt").read_text() == "already-written"


def test_failed_permission_is_finalized_and_stays_denied(runtime):
    fs, ledger, _ = runtime
    dispatcher = NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope="run-1/task-1",
    )
    result = dispatcher.dispatch({
        "type": "tool_call", "id": "call-denied", "name": "read_file",
        "arguments": {"path": "out/report.txt"},
    })
    assert result.error_code == "POLICY_DENIED"
    assert ledger.state("run-1/task-1", "call-denied") == "DENIED"


def test_ledger_resides_outside_agent_workspace(runtime):
    fs, _, workspace = runtime
    inside = SqliteToolLedger(workspace / "out" / "insecure.sqlite3")
    with pytest.raises(ToolPolicyDenied, match="cannot live inside"):
        NativeFilesystemDispatcher(fs, ledger=inside, execution_scope="run-1/task-1")


def test_ledger_rejects_world_readable_database(tmp_path):
    db = tmp_path / "weak.sqlite3"
    db.touch(mode=0o666)
    os.chmod(db, 0o644)
    with pytest.raises(ToolPolicyDenied, match="private"):
        SqliteToolLedger(db)


def test_ledger_does_not_store_tool_data_or_arguments(runtime):
    fs, ledger, workspace = runtime
    assert NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope="run-1/task-1",
    ).dispatch(write("call-1", "UNIQUE_SENSITIVE_PAYLOAD")).ok
    with sqlite3.connect(ledger.path) as db:
        cols = {entry[1] for entry in db.execute("PRAGMA table_info(tool_execution)")}
        assert cols == {"scope", "call_id", "name", "state"}
        assert db.execute(
            "SELECT state FROM tool_execution WHERE scope = ? AND call_id = ?",
            ("run-1/task-1", "call-1"),
        ).fetchone() == ("SUCCEEDED",)
    assert "UNIQUE_SENSITIVE_PAYLOAD" not in ledger.path.read_bytes().decode(
        "utf-8", errors="ignore",
    )


def test_bad_scope_rejected_before_execution(runtime):
    fs, ledger, workspace = runtime
    dispatcher = NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope="../../unexpected",
    )
    with pytest.raises(ToolPolicyDenied):
        dispatcher.dispatch(write("call-1", "nope"))
    assert not (workspace / "out" / "report.txt").exists()


def test_no_ledger_integration_without_trusted_scope(runtime):
    fs, ledger, _ = runtime
    with pytest.raises(TypeError):
        NativeFilesystemDispatcher(fs, ledger=ledger)


def test_rejected_unknown_tool_name_is_redacted_in_ledger(runtime):
    fs, ledger, _ = runtime
    gate = NativeFilesystemDispatcher(fs, ledger=ledger, execution_scope="run-1/task-1")
    response = gate.dispatch({
        "type": "tool_call", "id": "call-x",
        "name": "key_sensitive_value_123", "arguments": {},
    })
    assert response.error_code == "UNKNOWN_TOOL"
    with sqlite3.connect(ledger.path) as db:
        assert db.execute("SELECT name FROM tool_execution").fetchone()[0] == "<unsupported>"


def test_revoked_trusted_attempt_denies_new_io(runtime):
    fs, ledger, workspace = runtime
    dispatcher = NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope="run-1/attempt-1",
        attempt_active=lambda: False,
    )
    with patch.object(fs, "write_text") as write_io:
        result = dispatcher.dispatch(write("revoked-call", "should-not-write"))
    write_io.assert_not_called()
    assert not result.ok and result.error_code == "ATTEMPT_FENCED"
    assert result.to_provider_message()["content"] == '{"error":"ATTEMPT_FENCED"}'
    assert ledger.state("run-1/attempt-1", "revoked-call") == "DENIED"
    assert not (workspace / "out" / "report.txt").exists()
    assert dispatcher.dispatch(write("revoked-call")).error_code == "DUPLICATE_CALL"


def test_trusted_attempt_guard_allows_valid_attempt_then_blocks_revoked_one(runtime):
    fs, ledger, workspace = runtime
    active = {"value": True}
    checked = []

    def check_attempt():
        checked.append(active["value"])
        return active["value"]

    dispatcher = NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope="run-1/attempt-1",
        attempt_active=check_attempt,
    )
    assert dispatcher.dispatch(write("first-call", "first")).ok
    active["value"] = False
    assert dispatcher.dispatch(write("second-call", "second")).error_code == "ATTEMPT_FENCED"
    assert checked == [True, False]
    assert ledger.state("run-1/attempt-1", "first-call") == "SUCCEEDED"
    assert ledger.state("run-1/attempt-1", "second-call") == "DENIED"
    assert (workspace / "out" / "report.txt").read_text() == "first"


def test_attempt_guard_unavailable_fails_closed_and_redacts_exception(runtime):
    fs, ledger, workspace = runtime

    def unavailable():
        raise RuntimeError("SECRET credentials or worker endpoint leaked")

    dispatcher = NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope="run-1/attempt-1",
        attempt_active=unavailable,
    )
    with patch.object(fs, "write_text") as write_io:
        result = dispatcher.dispatch(write("failed-guard", "private-content"))
    write_io.assert_not_called()
    assert result.error_code == "ATTEMPT_FENCED"
    assert result.to_provider_message()["content"] == '{"error":"ATTEMPT_FENCED"}'
    assert ledger.state("run-1/attempt-1", "failed-guard") == "DENIED"
    assert not (workspace / "out" / "report.txt").exists()
    assert "SECRET" not in repr(result)
    assert "SECRET" not in repr(dispatcher.audit_snapshot())


@pytest.mark.parametrize("unsafe_answer", [None, 1, "true", {}, []])
def test_attempt_guard_requires_literal_true(runtime, unsafe_answer):
    fs, ledger, workspace = runtime
    dispatcher = NativeFilesystemDispatcher(
        fs, ledger=ledger, execution_scope="run-1/attempt-1",
        attempt_active=lambda: unsafe_answer,
    )
    result = dispatcher.dispatch(write("not-true"))
    assert result.error_code == "ATTEMPT_FENCED"
    assert ledger.state("run-1/attempt-1", "not-true") == "DENIED"
    assert not (workspace / "out" / "report.txt").exists()


def test_attempt_guard_is_trusted_and_requires_durable_ledger(runtime):
    fs, ledger, _workspace = runtime
    with pytest.raises(ValueError, match="durable"):
        NativeFilesystemDispatcher(fs, attempt_active=lambda: True)
    with pytest.raises(TypeError, match="callable"):
        NativeFilesystemDispatcher(
            fs, ledger=ledger, execution_scope="run-1/attempt-1",
            attempt_active="yes",  # type: ignore[arg-type]
        )
