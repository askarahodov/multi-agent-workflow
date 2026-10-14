"""Negative security tests for POSIX scoped filesystem execution.

No network, LLM, shell or platform agent is invoked in these tests.
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from agent_management.errors import ToolPolicyDenied
from agent_management.scoped_fs import ScopedFilesystemExecutor

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW"),
    reason="POSIX directory-descriptor implementation only",
)


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "src").mkdir()
    (root / "out").mkdir()
    (root / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    return root


@pytest.fixture
def executor(workspace):
    return ScopedFilesystemExecutor(
        workspace,
        {
            "fs_read": [str(workspace / "src" / "**")],
            "fs_write": [str(workspace / "out" / "**")],
        },
        max_read_bytes=128,
        max_write_bytes=128,
    )


def test_valid_read_and_atomic_write(executor, workspace):
    assert executor.read_text("src/app.py") == "print('hello')\n"
    executor.write_text("out/report.txt", "first")
    assert (workspace / "out" / "report.txt").read_text() == "first"
    executor.write_text("out/report.txt", "second")
    assert executor._checked_parts("out/report.txt", "fs_write") == ["out", "report.txt"]
    assert (workspace / "out" / "report.txt").read_text() == "second"
    assert list((workspace / "out").glob("*.scoped-*")) == []


def test_reject_dotdot_even_if_normalized_back_inside(executor):
    with pytest.raises(ToolPolicyDenied):
        executor.read_text("src/../src/app.py")


def test_reject_absolute_path_outside_workspace(executor, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    with pytest.raises(ToolPolicyDenied):
        executor.read_text(str(outside))
    assert outside.read_text() == "private"


def test_reject_sibling_prefix(executor, workspace):
    sibling = workspace.parent / "workspace-not"
    sibling.mkdir()
    (sibling / "steal").write_text("secret")
    with pytest.raises(ToolPolicyDenied):
        executor.read_text(str(sibling / "steal"))


def test_denied_before_any_filesystem_open(executor):
    with patch("agent_management.scoped_fs.os.open") as opened:
        with pytest.raises(ToolPolicyDenied):
            executor.read_text("out/report.txt")  # no fs_read permission
        opened.assert_not_called()


def test_policy_enforced_on_write_before_side_effect(executor, workspace):
    with pytest.raises(ToolPolicyDenied):
        executor.write_text("src/app.py", "modified")
    assert (workspace / "src" / "app.py").read_text() == "print('hello')\n"


def test_parent_symlink_cannot_escape(executor, workspace, tmp_path):
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "file.txt").write_text("secret")
    (workspace / "src" / "alias").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ToolPolicyDenied):
        executor.read_text("src/alias/file.txt")


def test_final_symlink_cannot_read_or_write(executor, workspace, tmp_path):
    target = tmp_path / "secret.txt"
    target.write_text("secret")
    (workspace / "src" / "linked.txt").symlink_to(target)
    (workspace / "out" / "linked.txt").symlink_to(target)
    with pytest.raises(ToolPolicyDenied):
        executor.read_text("src/linked.txt")
    with pytest.raises(ToolPolicyDenied):
        executor.write_text("out/linked.txt", "overwrite")
    assert target.read_text() == "secret"


def test_special_file_fifo_rejected(executor, workspace):
    pipe = workspace / "src" / "pipe"
    os.mkfifo(pipe)
    with pytest.raises(ToolPolicyDenied):
        executor.read_text("src/pipe")


def test_hardlink_write_does_not_touch_external_inode(executor, workspace, tmp_path):
    outside = tmp_path / "private.txt"
    outside.write_text("preserve")
    os.link(outside, workspace / "out" / "linked.txt")
    with pytest.raises(ToolPolicyDenied):
        executor.write_text("out/linked.txt", "overwrite")
    assert outside.read_text() == "preserve"


@pytest.mark.parametrize("name", [
    ".env", ".env.local", ".git/config", ".ssh/id_rsa",
    "key.pem", "key.p12", "api.key", ".hermes/config",
])
def test_protected_paths_denied_even_with_broad_permission(workspace, name):
    broad = ScopedFilesystemExecutor(
        workspace, {"fs_read": [str(workspace / "**")], "fs_write": [str(workspace / "**")]}
    )
    with pytest.raises(ToolPolicyDenied):
        broad.read_text(name)
    with pytest.raises(ToolPolicyDenied):
        broad.write_text(name, "key")



def test_short_posix_reads_do_not_truncate_a_valid_file(executor, workspace):
    expected = "abc123" * 12
    (workspace / "src" / "short.txt").write_text(expected, encoding="utf-8")
    original_read = os.read

    def short_read(fd, count):
        return original_read(fd, min(count, 3))

    with patch("agent_management.scoped_fs.os.read", side_effect=short_read):
        assert executor.read_text("src/short.txt") == expected


def test_read_limit_rejects_oversized_file(executor, workspace):
    (workspace / "src" / "big.txt").write_text("a" * 300)
    with pytest.raises(ToolPolicyDenied, match="size limit"):
        executor.read_text("src/big.txt")


def test_write_limit_does_not_replace_existing_content(executor, workspace):
    old = workspace / "out" / "report.txt"
    old.write_text("original")
    with pytest.raises(ToolPolicyDenied, match="size limit"):
        executor.write_text("out/report.txt", "b" * 300)
    assert old.read_text() == "original"


def test_missing_parent_is_not_implicitly_created(executor, workspace):
    with pytest.raises(FileNotFoundError):
        executor.write_text("out/unknown/file.txt", "text")
    assert not (workspace / "out" / "unknown").exists()


def test_invalid_resource_and_non_text_input(executor):
    with pytest.raises(ToolPolicyDenied):
        executor.read_text("")
    with pytest.raises(ToolPolicyDenied):
        executor.read_text("src\\app.py")
    with pytest.raises(ToolPolicyDenied):
        executor.write_text("out/report.txt", b"bytes")  # type: ignore[arg-type]


def test_no_unrestricted_policy_permissions(workspace, monkeypatch):
    monkeypatch.delenv("ALLOW_DEV_PERMISSIVE_POLICY", raising=False)
    broad = ScopedFilesystemExecutor(
        workspace, {"fs_read": ["**"], "fs_write": ["**"], "git": ["*"],
                    "shell": ["*"], "network": ["*"]}
    )
    with pytest.raises(ToolPolicyDenied):
        broad.read_text("src/app.py")


def test_missing_workspace_rejected(tmp_path):
    with pytest.raises(FileNotFoundError):
        ScopedFilesystemExecutor(tmp_path / "missing", {})


def test_empty_policy_denies_even_valid_path(workspace):
    with pytest.raises(ToolPolicyDenied):
        ScopedFilesystemExecutor(workspace, {}).read_text("src/app.py")
