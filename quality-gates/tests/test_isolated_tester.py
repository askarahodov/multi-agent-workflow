"""Security contract for the opt-in Docker QA sandbox argument builder."""
from __future__ import annotations

import subprocess
import pytest
from quality_gates.isolated_tester import SandboxError, isolated_test

IMAGE = "sha256:" + "a" * 64


def test_isolated_runner_has_no_network_privileges_or_secret_mounts(tmp_path, monkeypatch):
    observed = {}
    def fake_run(cmd, **kwargs):
        observed["cmd"] = cmd
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, "ok", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    result = isolated_test(("python", "-m", "pytest"), tmp_path, IMAGE)
    assert result.returncode == 0
    cmd = observed["cmd"]
    for fragment in ("--network=none", "--read-only", "--cap-drop=ALL",
                     "--security-opt=no-new-privileges", "--user=65534:65534"):
        assert fragment in cmd
    assert "--mount" in cmd
    assert cmd[cmd.index("--mount") + 1].endswith(",readonly")
    assert "--privileged" not in cmd and "/var/run/docker.sock" not in " ".join(cmd)
    assert observed["kwargs"]["shell"] is False


@pytest.mark.parametrize("image,argv", [
    ("ubuntu:latest", ("true",)),
    ("sha256:" + "a" * 63, ("true",)),
    (IMAGE, ()),
    (IMAGE, ("python", "\x00")),
])
def test_invalid_arguments_fail_before_docker(tmp_path, image, argv, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("docker invoked"))
    with pytest.raises(SandboxError):
        isolated_test(argv, tmp_path, image)


def test_docker_error_fails_closed(tmp_path, monkeypatch):
    commands = []

    def timed_out_then_removed(cmd, **kwargs):
        commands.append(cmd)
        if cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", timed_out_then_removed)
    with pytest.raises(SandboxError, match="timed out and container removed"):
        isolated_test(("true",), tmp_path, IMAGE, timeout=1)
    assert len(commands) == 2
    assert commands[1] == ["/usr/bin/docker", "rm", "--force", commands[0][3]]


def test_checkout_mount_option_injection_denied(tmp_path, monkeypatch):
    injected = tmp_path / "source,readonly=false"
    injected.mkdir()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("docker invoked"))
    with pytest.raises(SandboxError):
        isolated_test(("true",), injected, IMAGE)


def test_symlink_parent_denied(tmp_path, monkeypatch):
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(actual, target_is_directory=True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("docker invoked"))
    with pytest.raises(SandboxError):
        isolated_test(("true",), link, IMAGE)


@pytest.mark.parametrize("name", ["source,readonly=false", "source\\nmalformed", "source\\rmalformed"])
def test_checkout_mount_metacharacters_denied(tmp_path, monkeypatch, name):
    path = tmp_path / name
    path.mkdir()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("docker invoked"))
    with pytest.raises(SandboxError):
        isolated_test(("true",), path, IMAGE)
