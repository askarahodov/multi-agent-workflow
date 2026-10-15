"""Offline security checks for trusted fixed-argv process tools."""
from __future__ import annotations

import os
import shutil
import subprocess
from unittest.mock import patch

import pytest

from agent_management.errors import ToolPolicyDenied
from agent_management.trusted_process_tools import TrustedReadOnlyProcessTools, ProcessToolResult


@pytest.fixture
def tool(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX trusted process tools only")
    git = shutil.which("git")
    ls = shutil.which("ls")
    if not git or not ls:
        pytest.skip("Git and ls must be installed")
    root = tmp_path / "work"
    root.mkdir()
    return TrustedReadOnlyProcessTools(
        root, {"git": ["status"], "shell": ["ls"]},
        git_executable=os.path.realpath(git),
        ls_executable=os.path.realpath(ls),
    )


@pytest.mark.parametrize("command", [
    "git", "git -c alias.status=!sh", "git_status --all",
    "shell", "shell_exec", "http", "shell_list /etc",
    "git_status; touch /tmp/unsafe", "shell_list && echo unsafe",
])
def test_unexpected_model_operation_denied_before_process(tool, command):
    with patch.object(tool, "_run_bounded") as run:
        with pytest.raises(ToolPolicyDenied):
            tool.execute(command)
        run.assert_not_called()


@pytest.mark.parametrize("operation,permissions", [
    ("git_status", {"git": [], "shell": ["ls"]}),
    ("shell_list", {"git": ["status"], "shell": []}),
])
def test_policy_denied_before_process(tool, operation, permissions):
    tool.permissions = permissions
    with patch.object(tool, "_run_bounded") as run:
        with pytest.raises(ToolPolicyDenied):
            tool.execute(operation)
        run.assert_not_called()


def test_fixed_git_argv_and_clean_environment(tool):
    with patch.object(tool, "_run_bounded", return_value=ProcessToolResult(True, "ok")) as run:
        result = tool.execute("git_status")
    assert result.ok
    command, env = run.call_args.args
    assert command[0] == tool.git
    assert command[-4:] == ["status", "--porcelain=v1", "--untracked-files=no", "--ignore-submodules=all"]
    assert "core.fsmonitor=false" in command
    assert env["HOME"] == "/nonexistent"


def test_fixed_shell_listing_arguments(tool):
    with patch.object(tool, "_run_bounded", return_value=ProcessToolResult(True, "ok")) as run:
        assert tool.execute("shell_list").ok
    command, _env = run.call_args.args
    assert command == [tool.ls, "-A", "--", "."]


def test_large_directory_listing_fails_on_output_cap(tool):
    for index in range(30):
        (tool.workspace / ("entry-" + str(index))).touch()
    tool.max_output_bytes = 16
    outcome = tool.execute("shell_list")
    assert not outcome.ok and outcome.error_code == "OUTPUT_LIMIT"


def test_process_errors_do_not_leak_output(tool):
    with patch.object(tool, "_run_bounded", return_value=ProcessToolResult(False, "", "PROCESS_FAILED")):
        outcome = tool.execute("git_status")
    assert outcome.error_code == "PROCESS_FAILED"
    assert outcome.output == ""


@pytest.mark.parametrize("bad", [True, False, "5", None, float("nan"), 1000, 10**400])
def test_invalid_process_timeout_rejected(tool, bad):
    with pytest.raises(ValueError):
        TrustedReadOnlyProcessTools(
            tool.workspace, tool.permissions, git_executable=tool.git,
            ls_executable=tool.ls, timeout_seconds=bad,
        )


def test_executes_real_git_status_without_external_provider(tool):
    subprocess.run([tool.git, "init", "-q"], cwd=tool.workspace, check=True, capture_output=True)
    status = tool.execute("git_status")
    assert status.ok
