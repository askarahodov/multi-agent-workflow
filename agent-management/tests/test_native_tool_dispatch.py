"""Contract and negative tests for native tool dispatch, without an LLM.

Only read_file and write_file may reach the trusted scoped filesystem executor.
Unsupported shell/Git/HTTP tool calls never launch subprocesses or use network.
"""
from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from agent_management.errors import ToolPolicyDenied
from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
from agent_management.scoped_fs import ScopedFilesystemExecutor

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW"),
    reason="Native POSIX filesystem boundary only",
)


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "task"
    root.mkdir()
    (root / "src").mkdir()
    (root / "out").mkdir()
    (root / "src" / "input.txt").write_text("allowed-content", encoding="utf-8")
    return root


@pytest.fixture
def dispatcher(workspace):
    executor = ScopedFilesystemExecutor(
        workspace,
        {
            "fs_read": [str(workspace / "src" / "**")],
            "fs_write": [str(workspace / "out" / "**")],
        },
        max_read_bytes=128,
        max_write_bytes=128,
    )
    return NativeFilesystemDispatcher(executor)


def event(name, call_id="call-1", **arguments):
    return {"type": "tool_call", "id": call_id, "name": name, "arguments": arguments}


def test_stable_static_tool_specs_do_not_offer_code_execution():
    tools = NativeFilesystemDispatcher.tools_schema()
    assert [x["function"]["name"] for x in tools] == ["read_file", "write_file"]
    assert all(x["function"]["parameters"]["additionalProperties"] is False for x in tools)
    assert all(x["type"] == "function" for x in tools)


def test_allowed_read_and_openai_tool_result(dispatcher):
    result = dispatcher.dispatch(event("read_file", path="src/input.txt"))
    assert result.ok
    assert result.content == "allowed-content"
    assert result.to_provider_message() == {
        "role": "tool", "tool_call_id": "call-1", "content": "allowed-content",
    }
    assert dispatcher.audit_snapshot()[0].outcome == "OK"


def test_allowed_write(dispatcher, workspace):
    result = dispatcher.dispatch(event("write_file", path="out/result.txt", content="output"))
    assert result.ok
    assert (workspace / "out" / "result.txt").read_text() == "output"


@pytest.mark.parametrize("tool", ["shell", "git", "http", "exec", "python", "write_command"])
def test_unsupported_tool_never_executes(dispatcher, tool):
    with patch.object(subprocess, "run") as command, patch("os.system") as shell:
        result = dispatcher.dispatch(event(tool, path="out/result.txt"))
    assert not result.ok
    assert result.error_code == "UNKNOWN_TOOL"
    assert result.name == "<unsupported>"
    assert command.call_count == 0
    assert shell.call_count == 0
    assert dispatcher.audit_snapshot()[0].name == "<unsupported>"


def test_unsupported_name_is_redacted(dispatcher):
    outcome = dispatcher.dispatch(event("key_abcd_token_123"))
    assert not outcome.ok
    assert outcome.name == "<unsupported>"
    assert "token" not in repr(dispatcher.audit_snapshot())


@pytest.mark.parametrize("arguments", [
    {},
    {"path": "src/input.txt", "extra": "payload"},
    {"path": 17},
    {"path": ["src/input.txt"]},
    {"content": "payload"},
])
def test_read_schema_rejected_before_io(dispatcher, arguments):
    with patch.object(dispatcher._filesystem, "read_text") as read:
        result = dispatcher.dispatch({
            "type": "tool_call", "id": "call-schema", "name": "read_file",
            "arguments": arguments,
        })
    assert not result.ok
    assert result.error_code == "INVALID_ARGUMENTS"
    read.assert_not_called()


@pytest.mark.parametrize("arguments", [
    {},
    {"path": "out/result.txt"},
    {"path": "out/result.txt", "content": 42},
    {"path": "out/result.txt", "content": "ok", "root": "/"},
    {"path": "out/result.txt", "content": "ok", "mode": "override"},
])
def test_write_schema_rejected_before_io(dispatcher, arguments):
    with patch.object(dispatcher._filesystem, "write_text") as write:
        result = dispatcher.dispatch({
            "type": "tool_call", "id": "call-schema", "name": "write_file",
            "arguments": arguments,
        })
    assert not result.ok
    assert result.error_code == "INVALID_ARGUMENTS"
    write.assert_not_called()


def test_filesystem_permission_denial_is_redacted(dispatcher, workspace):
    failed = dispatcher.dispatch(event("read_file", path="out/not-readable.txt"))
    assert not failed.ok
    assert failed.error_code == "POLICY_DENIED"
    assert "/task/" not in str(failed.to_provider_message())
    assert failed.to_provider_message()["content"] == '{"error":"POLICY_DENIED"}'
    assert not (workspace / "out" / "not-readable.txt").exists()


def test_symlink_escape_cannot_be_executed(dispatcher, workspace, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret")
    (workspace / "src" / "escape.txt").symlink_to(outside)
    failed = dispatcher.dispatch(event("read_file", path="src/escape.txt"))
    assert not failed.ok and failed.error_code == "POLICY_DENIED"
    assert "secret" not in str(failed)


def test_duplicate_write_id_never_runs_again(dispatcher, workspace):
    a = dispatcher.dispatch(event("write_file", path="out/file.txt", content="first"))
    b = dispatcher.dispatch(event("write_file", path="out/file.txt", content="second"))
    assert a.ok and not b.ok and b.error_code == "DUPLICATE_CALL"
    assert (workspace / "out" / "file.txt").read_text() == "first"


def test_id_is_consumed_even_on_denied_attempt(dispatcher):
    a = dispatcher.dispatch(event("read_file", path="out/nope.txt"))
    b = dispatcher.dispatch(event("read_file", path="src/input.txt"))
    assert a.error_code == "POLICY_DENIED"
    assert b.error_code == "DUPLICATE_CALL"


def test_bad_stream_event_and_identifier_rejected_without_io(dispatcher):
    with patch.object(dispatcher._filesystem, "read_text") as read:
        for payload in (
            {}, {"type": "text_delta", "id": "call-1", "name": "read_file", "arguments": {}},
            {"type": "tool_call", "id": "../../secret", "name": "read_file", "arguments": {}},
            {"type": "tool_call", "id": 55, "name": "read_file", "arguments": {}},
            {"type": "tool_call", "id": "okay", "name": "weird\nsecret", "arguments": {}},
        ):
            with pytest.raises(ToolPolicyDenied):
                dispatcher.dispatch(payload)
        read.assert_not_called()


def test_results_and_audit_never_contain_secret_paths(dispatcher, workspace):
    response = dispatcher.dispatch(event("write_file", path="out/.env", content="SENSITIVE"))
    assert not response.ok
    assert response.to_provider_message()["content"] == '{"error":"POLICY_DENIED"}'
    assert "SENSITIVE" not in repr(dispatcher.audit_snapshot())
    assert str(workspace) not in repr(dispatcher.audit_snapshot())


def test_exceptions_are_sanitized(dispatcher):
    with patch.object(dispatcher._filesystem, "read_text", side_effect=OSError("SECRET /home/user/key")):
        result = dispatcher.dispatch(event("read_file", path="src/input.txt"))
    assert result.error_code == "TOOL_IO_ERROR"
    assert "SECRET" not in repr(result)
    assert "SECRET" not in str(result.to_provider_message())


def test_concurrent_calls_with_same_id_execute_at_most_once(dispatcher):
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: dispatcher.dispatch(
            event("read_file", path="src/input.txt")
        ), range(2)))
    assert [x.ok for x in results].count(True) == 1
    assert [x.error_code for x in results].count("DUPLICATE_CALL") == 1


def test_dispatcher_requires_trusted_scoped_executor(tmp_path):
    with pytest.raises(TypeError):
        NativeFilesystemDispatcher(str(tmp_path))  # type: ignore[arg-type]
