"""Docker CLI timeout must not leave a named QA container running."""
from __future__ import annotations

import subprocess
import pytest
from quality_gates.isolated_tester import SandboxError, isolated_test

IMAGE = "sha256:" + "a" * 64


def test_timeout_forces_named_container_removal(tmp_path, monkeypatch):
    commands = []
    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        if cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SandboxError, match="container removed"):
        isolated_test(("true",), tmp_path, IMAGE, timeout=1)
    assert commands[0][1] == "run"
    assert "--name" in commands[0]
    assert commands[1] == ["/usr/bin/docker", "rm", "--force", commands[0][commands[0].index("--name") + 1]]
    assert commands[2][1:3] == ["ps", "-a"]


def test_unconfirmed_cleanup_fails_closed(tmp_path, monkeypatch):
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        return subprocess.CompletedProcess(cmd, 1, "", "failure")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SandboxError, match="operator intervention required"):
        isolated_test(("true",), tmp_path, IMAGE, timeout=1)
    assert len(calls) == 2


def test_successful_run_needs_no_force_removal(tmp_path, monkeypatch):
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "ok", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert isolated_test(("true",), tmp_path, IMAGE).returncode == 0
    assert len(calls) == 1
