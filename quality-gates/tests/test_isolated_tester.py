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
    assert "--pull=never" in cmd
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
    assert len(commands) == 3
    assert commands[1] == ["/usr/bin/docker", "rm", "--force", commands[0][commands[0].index("--name") + 1]]
    assert commands[2][1:3] == ["ps", "-a"]


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


@pytest.mark.parametrize("name", ["source,readonly=false", "source\nmalformed", "source\rmalformed"])
def test_checkout_mount_metacharacters_denied(tmp_path, monkeypatch, name):
    path = tmp_path / name
    path.mkdir()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("docker invoked"))
    with pytest.raises(SandboxError):
        isolated_test(("true",), path, IMAGE)


@pytest.mark.parametrize("key", [
    "QG_QA_ATTESTATION_KEY",
    "MAW_QG_SIGNING_KEY_FILE",
    "MAW_QG_ADMIN_KEY_FILE",
    "MAW_QA_ORCH_ADMIN_KEY_FILE",
    "MAW_QA_SERVICE_ADMIN_KEY_FILE",
    "ADMIN_API_KEYS",
    "OPENROUTER_API_KEY",
])
def test_refuse_docker_launch_from_credential_bearing_process(tmp_path, monkeypatch, key):
    monkeypatch.setenv(key, "/dummy/protected/key")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("docker invoked"))
    with pytest.raises(SandboxError, match="credential-bearing"):
        isolated_test(("true",), tmp_path, IMAGE)


def test_refuse_docker_launch_when_signer_marker_is_empty(tmp_path, monkeypatch):
    # Presence is enough: never infer a safe execution context from key contents.
    monkeypatch.setenv("MAW_QG_SIGNING_KEY_FILE", "")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("docker invoked"))
    with pytest.raises(SandboxError, match="credential-bearing"):
        isolated_test(("true",), tmp_path, IMAGE)


def test_docker_invocation_has_no_ambient_environment_or_extra_mounts(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_UNRELATED_SECRET_CANARY", "must-never-reach-docker")
    seen = {}

    def inspect(cmd, **kwargs):
        seen["command"] = cmd
        seen["env"] = kwargs["env"]
        seen["stdin"] = kwargs["stdin"]
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", inspect)
    isolated_test(("true",), tmp_path, IMAGE)
    cmd = seen["command"]
    assert seen["env"] == {"PATH": "/usr/bin:/bin"}
    assert "QA_UNRELATED_SECRET_CANARY" not in seen["env"]
    assert seen["stdin"] == subprocess.DEVNULL
    assert cmd.count("--mount") == 1
    mount = cmd[cmd.index("--mount") + 1]
    assert mount == f"type=bind,src={tmp_path},dst=/src,readonly"
    assert "--env-file" not in cmd
    assert "--volumes-from" not in cmd
    assert "--privileged" not in cmd


def test_docker_timeout_cleanup_failure_fails_closed(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "run" in cmd:
            raise subprocess.TimeoutExpired(cmd, 2)
        if "rm" in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "daemon unavailable")
        pytest.fail("Unexpected Docker operation")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SandboxError, match="cleanup not confirmed"):
        isolated_test(("true",), tmp_path, IMAGE)
    assert len(calls) == 2
    assert calls[1][-1] == calls[0][calls[0].index("--name") + 1]


def test_docker_ipc_namespace_is_disabled(tmp_path, monkeypatch):
    captured = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    isolated_test(("true",), tmp_path, IMAGE)
    assert "--ipc=none" in captured[0]
    assert "--network=none" in captured[0]
    assert "--privileged" not in captured[0]


def test_timeout_removal_must_confirm_absence(tmp_path, monkeypatch):
    commands = []
    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        if cmd[1] == "run":
            raise subprocess.TimeoutExpired(cmd, 2)
        if cmd[1] == "rm":
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "maw-qa-still-present", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SandboxError, match="absence not confirmed"):
        isolated_test(("true",), tmp_path, IMAGE)
    assert [c[1] for c in commands] == ["run", "rm", "ps"]
    assert commands[2][-1] == commands[0][commands[0].index("--name") + 1]
