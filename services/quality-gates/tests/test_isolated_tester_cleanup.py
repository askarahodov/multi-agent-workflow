"""Managed Docker runner must always clean a successfully created container."""
import subprocess
import pytest
from quality_gates.isolated_tester import SandboxError, isolated_test

IMAGE = "sha256:" + "a" * 64


def test_successful_run_removes_created_container(tmp_path, monkeypatch):
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "wait":
            return subprocess.CompletedProcess(cmd, 0, "0\n", "")
        return subprocess.CompletedProcess(cmd, 0, "output", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert isolated_test(("true",), tmp_path, IMAGE).returncode == 0
    assert [c[1] for c in calls] == ["create", "start", "wait", "rm"]


def test_unconfirmed_cleanup_fails_closed(tmp_path, monkeypatch):
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "wait":
            return subprocess.CompletedProcess(cmd, 0, "0\n", "")
        if cmd[1] == "rm":
            return subprocess.CompletedProcess(cmd, 1, "", "failure")
        return subprocess.CompletedProcess(cmd, 0, "created", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SandboxError, match="operator intervention required"):
        isolated_test(("true",), tmp_path, IMAGE)
    assert calls[-1][1] == "rm"
