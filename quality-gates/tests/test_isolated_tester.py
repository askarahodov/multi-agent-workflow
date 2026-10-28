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
    (IMAGE, ("python", "\\x00")),
])
def test_invalid_arguments_fail_before_docker(tmp_path, image, argv, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("docker invoked"))
    with pytest.raises(SandboxError):
        isolated_test(argv, tmp_path, image)


def test_docker_error_fails_closed(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])
    monkeypatch.setattr(subprocess, "run", broken)
    with pytest.raises(SandboxError, match="failed closed"):
        isolated_test(("true",), tmp_path, IMAGE, timeout=1)
