"""Deny-before-side-effect checks for the narrow exact-argv command boundary."""
from __future__ import annotations

import os
import shutil
import subprocess
from unittest.mock import patch

import pytest

from agent_management.errors import ToolPolicyDenied
from agent_management.trusted_commands import TrustedCommandExecutor

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX only")


@pytest.fixture
def command_executor(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    executable = shutil.which("echo")
    if executable is None:
        pytest.skip("echo executable unavailable")
    return TrustedCommandExecutor(
        root, {"shell": ["echo permitted"], "git": []},
        executables={"echo": executable},
        approved_argv={"echo": [("permitted",)]},
    )


def test_allowed_exact_command_has_bounded_output(command_executor):
    result = command_executor.execute("echo", ["permitted"])
    assert result.returncode == 0
    assert result.output.strip() == "permitted"


@pytest.mark.parametrize("name,argv", [
    ("echo", ["permitted;touch /tmp/hacked"]),
    ("echo", ["permitted", ";", "touch"]),
    ("echo", ["permitted", "&&", "id"]),
    ("echo", ["$(id)"]),
    ("echo", ["../outside"]),
    ("echo", ["-c", "evil"]),
    ("echo", ["permitted", "--"]),
    ("echo", ["permitted", "\\x00"]),
    ("sh", ["-c", "id"]),
    ("hermes", ["chat"]),
    ("git", ["-c", "core.hooksPath=/tmp", "status"]),
    ("echo", ["permitted", 5]),
])
def test_untrusted_command_is_denied_before_spawning(command_executor, name, argv):
    with patch.object(subprocess, "run", side_effect=AssertionError("must not spawn")) as run:
        with pytest.raises(ToolPolicyDenied):
            command_executor.execute(name, argv)
        run.assert_not_called()


def test_policy_denial_precedes_process_spawn(command_executor):
    command_executor.permissions["shell"] = []
    with patch.object(subprocess, "run") as run:
        with pytest.raises(ToolPolicyDenied):
            command_executor.execute("echo", ["permitted"])
        run.assert_not_called()


def test_workspace_symlink_is_denied_before_execution(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(ToolPolicyDenied):
        TrustedCommandExecutor(
            alias, {"shell": ["echo permitted"]},
            executables={"echo": "/usr/bin/echo"},
            approved_argv={"echo": [("permitted",)]},
        )


@pytest.mark.parametrize("args", [
    ("-c", "core.hooksPath=/tmp"), ("status", "--ignored"),
    ("diff", "--ext-diff"), ("commit", "-m", "hi"),
    ("status", "--porcelain=v1", "--untracked-files=all"),
])
def test_git_unapproved_argv_configuration_fails(tmp_path, args):
    root = tmp_path / "workspace"
    root.mkdir()
    git = shutil.which("git")
    if git is None:
        pytest.skip("git unavailable")
    with pytest.raises(ToolPolicyDenied):
        TrustedCommandExecutor(
            root, {"git": ["*"]},
            executables={"git": git}, approved_argv={"git": [args]},
        )


def test_exact_git_status_cannot_be_overridden_by_model(tmp_path):
    git = shutil.which("git")
    if git is None:
        pytest.skip("git unavailable")
    root = tmp_path / "workspace"
    root.mkdir()
    subprocess.run([git, "init", "-q", str(root)], check=True)
    executor = TrustedCommandExecutor(
        root, {"git": ["git status --porcelain=v1 --untracked-files=no"]},
        executables={"git": git},
        approved_argv={"git": [("status", "--porcelain=v1", "--untracked-files=no")]},
    )
    assert executor.execute("git", ["status", "--porcelain=v1", "--untracked-files=no"]).returncode == 0
    with patch.object(subprocess, "run") as spawned:
        with pytest.raises(ToolPolicyDenied):
            executor.execute("git", ["-c", "core.fsmonitor=/bin/sh", "status"])
        spawned.assert_not_called()
