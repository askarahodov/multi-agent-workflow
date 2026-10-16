"""Issue #5: adversarial negative checks for native filesystem execution boundary."""
from __future__ import annotations

import os
from unittest.mock import patch
import pytest

from agent_management.errors import ToolPolicyDenied
from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
from agent_management.scoped_fs import ScopedFilesystemExecutor

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX descriptor boundary only")


@pytest.fixture
def fs(tmp_path):
    root = tmp_path / "workspace"
    (root / "out").mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "ok.txt").write_text("ok", encoding="utf-8")
    executor = ScopedFilesystemExecutor(root, {
        "fs_read": [str(root / "src" / "**")],
        "fs_write": [str(root / "out" / "**")],
        "git": ["*"], "shell": ["*"], "network": ["*"],
    })
    return root, executor


@pytest.mark.parametrize("path", [
    "src/../src/ok.txt", "src/../../control.db", "src/./ok.txt",
    "src\\..\\control.db", "src/ok.txt/../ok.txt", "../workspace/src/ok.txt",
    "/etc/passwd", "src/.ssh/id_rsa", "src/.git/config", "src/.env.local",
])
def test_escape_and_protected_resources_denied_before_file_open(fs, path):
    _, executor = fs
    with patch("agent_management.scoped_fs.os.open") as open_file:
        with pytest.raises(ToolPolicyDenied):
            executor.read_text(path)
        open_file.assert_not_called()


def test_nonexistent_path_outside_workspace_never_created(fs, tmp_path):
    root, executor = fs
    target = tmp_path / "control-plane" / "new-secret"
    with pytest.raises(ToolPolicyDenied):
        executor.write_text(str(target), "never")
    assert not target.exists()
    executor.write_text("out/result.txt", "allowed")
    assert (root / "out" / "result.txt").read_text() == "allowed"


@pytest.mark.parametrize("tool_name", ["shell", "git", "http", "network", "exec", "bash"])
def test_model_cannot_select_unsupported_side_effect_tool(fs, tool_name):
    root, executor = fs
    dispatcher = NativeFilesystemDispatcher(executor)
    event = {"type": "tool_call", "id": "call-secure", "name": tool_name,
             "arguments": {"path": "out/attacked.txt", "content": "bad"}}
    with patch.object(executor, "write_text") as write, patch.object(executor, "read_text") as read:
        outcome = dispatcher.dispatch(event)
        assert not outcome.ok and outcome.error_code == "UNKNOWN_TOOL"
        read.assert_not_called()
        write.assert_not_called()
    assert not (root / "out" / "attacked.txt").exists()


def test_parent_symlink_cannot_reach_platform_db(fs, tmp_path):
    root, executor = fs
    platform = tmp_path / "control-plane"
    platform.mkdir()
    db = platform / "engine.sqlite"
    db.write_text("do not alter")
    (root / "out" / "alias").symlink_to(platform, target_is_directory=True)
    with pytest.raises(ToolPolicyDenied):
        executor.write_text("out/alias/engine.sqlite", "changed")
    assert db.read_text() == "do not alter"
