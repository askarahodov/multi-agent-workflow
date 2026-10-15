"""Offline security checks for trusted fixed-argv process tools."""
from __future__ import annotations

import os
import shutil
import subprocess
from unittest.mock import patch

import pytest

from agent_management.errors import ToolPolicyDenied
from agent_management.trusted_process_tools import TrustedReadOnlyProcessTools


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
    with patch("subprocess.run") as run:
        with pytest.raises(ToolPolicyDenied):
            tool.execute(command)
        run.assert_not_called()


@pytest.mark.parametrize("operation,permissions", [
    ("git_status", {"git": [], "shell": ["ls"]}),
    ("shell_list", {"git": ["status"], "shell": []}),
])
def test_policy_denied_before_process(tool, operation, permissions):
    tool.permissions = permissions
    with patch("subprocess.run") as run:
        with pytest.raises(ToolPolicyDenied):
            tool.execute(operation)
        run.assert_not_called()


def test_fixed_git_argv_and_clean_environment(tool):
    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, b" M src.py\n", b"")) as run:
        out = tool.execute("git_status")
    assert out.ok and out.output == " M src.py\n"
    args, kwargs = run.call_args
    assert args[0][0] == tool.git
    assert "-c" in args[0] and "core.fsmonitor=false" in args[0]
    assert args[0][-4:] == ["status", "--porcelain=v1", "--untracked-files=no", "--ignore-submodules=all"]
    assert kwargs["shell"] is False
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert kwargs["cwd"] == tool.workspace
    assert kwargs["env"]["HOME"] == "/nonexistent"
    assert "GIT_EXTERNAL_DIFF" not in kwargs["env"]


def test_shell_listing_fixed_argv_without_option_injection(tool):
    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, b"safe.txt\n", b"")) as run:
        out = tool.execute("shell_list")
    assert out.ok and out.output == "safe.txt\n"
    args, kwargs = run.call_args
    assert args[0] == [tool.ls, "-A", "--", "."]
    assert kwargs["shell"] is False


@pytest.mark.parametrize("rc,payload,expected", [
    (1, b"", "PROCESS_FAILED"),
    (0, b"123456789", "OUTPUT_LIMIT"),
    (0, b"\\xff", "OUTPUT_INVALID"),
])
def test_process_errors_redacted(tool, rc, payload, expected):
    tool.max_output_bytes = 8
    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], rc, payload, b"secret")):
        out = tool.execute("shell_list")
    assert not out.ok and out.error_code == expected
    assert "secret" not in repr(out)


def test_timeout_does_not_expose_subprocess_exception(tool):
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["git"], 1)):
        out = tool.execute("git_status")
    assert not out.ok and out.error_code == "PROCESS_FAILED"


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
