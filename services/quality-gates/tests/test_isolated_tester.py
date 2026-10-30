"""Managed Docker lifecycle and no-secret QA security tests."""
from __future__ import annotations
import subprocess
import pytest
from quality_gates.isolated_tester import SandboxError, isolated_test

IMAGE = "sha256:" + "a" * 64


def simulate(monkeypatch, *, timeout_start=False, cleanup_rc=0, exit_code=0, create_rc=0):
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        op = cmd[1]
        if op == "create":
            return subprocess.CompletedProcess(cmd, create_rc, "fake-id", "")
        if op == "start":
            if timeout_start:
                raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])
            return subprocess.CompletedProcess(cmd, 0, "output", "")
        if op == "wait":
            return subprocess.CompletedProcess(cmd, 0, str(exit_code) + "\n", "")
        if op == "rm":
            return subprocess.CompletedProcess(cmd, cleanup_rc, "", "")
        pytest.fail(f"unexpected Docker operation: {cmd}")
    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_isolated_runner_has_no_network_privileges_or_secret_mounts(tmp_path, monkeypatch):
    calls = simulate(monkeypatch)
    result = isolated_test(("python", "-m", "pytest"), tmp_path, IMAGE)
    assert result.returncode == 0
    assert result.stdout == "output"
    assert [c[0][1] for c in calls] == ["create", "start", "wait", "rm"]
    cmd, kwargs = calls[0]
    for fragment in ("--network=none", "--ipc=none", "--read-only", "--cap-drop=ALL",
                     "--security-opt=no-new-privileges", "--user=65534:65534"):
        assert fragment in cmd
    assert "--pull=never" in cmd
    assert "--mount" in cmd
    assert cmd[cmd.index("--mount") + 1].endswith(",readonly")
    assert "--privileged" not in cmd and "/var/run/docker.sock" not in " ".join(cmd)
    assert kwargs["shell"] is False
    assert kwargs["env"] == {"PATH": "/usr/bin:/bin"}
    assert kwargs["stdin"] == subprocess.DEVNULL


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


def test_docker_timeout_forces_created_container_removal(tmp_path, monkeypatch):
    calls = simulate(monkeypatch, timeout_start=True)
    with pytest.raises(SandboxError, match="timed out and container removed"):
        isolated_test(("true",), tmp_path, IMAGE, timeout=1)
    assert [c[0][1] for c in calls] == ["create", "start", "rm"]
    assert calls[-1][0][-1] == calls[0][0][calls[0][0].index("--name") + 1]


def test_docker_cleanup_failure_overrides_timeout(tmp_path, monkeypatch):
    calls = simulate(monkeypatch, timeout_start=True, cleanup_rc=1)
    with pytest.raises(SandboxError, match="cleanup not confirmed"):
        isolated_test(("true",), tmp_path, IMAGE)
    assert calls[-1][0][1] == "rm"


def test_docker_cleanup_failure_overrides_success(tmp_path, monkeypatch):
    simulate(monkeypatch, cleanup_rc=1)
    with pytest.raises(SandboxError, match="cleanup not confirmed"):
        isolated_test(("true",), tmp_path, IMAGE)


def test_failed_test_exit_code_comes_from_daemon_wait(tmp_path, monkeypatch):
    simulate(monkeypatch, exit_code=17)
    result = isolated_test(("false",), tmp_path, IMAGE)
    assert result.returncode == 17


def test_missing_immutable_image_is_nonpassing_without_launch(tmp_path, monkeypatch):
    calls = simulate(monkeypatch, create_rc=125)
    result = isolated_test(("true",), tmp_path, IMAGE)
    assert result.returncode == 125
    assert [c[0][1] for c in calls] == ["create"]


def test_invalid_wait_status_fails_closed_but_cleans_up(tmp_path, monkeypatch):
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1] == "wait":
            return subprocess.CompletedProcess(cmd, 0, "not-a-status", "")
        return subprocess.CompletedProcess(cmd, 0, "created", "")
    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(SandboxError, match="exit status unavailable"):
        isolated_test(("true",), tmp_path, IMAGE)
    assert calls[-1][1] == "rm"


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
    "QG_QA_ATTESTATION_KEY", "MAW_QG_SIGNING_KEY_FILE",
    "MAW_QG_ADMIN_KEY_FILE", "MAW_QA_ORCH_ADMIN_KEY_FILE",
    "MAW_QA_SERVICE_ADMIN_KEY_FILE", "ADMIN_API_KEYS",
    "OPENROUTER_API_KEY",
])
def test_refuse_docker_launch_from_credential_bearing_process(tmp_path, monkeypatch, key):
    monkeypatch.setenv(key, "/dummy/protected/key")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("docker invoked"))
    with pytest.raises(SandboxError, match="credential-bearing"):
        isolated_test(("true",), tmp_path, IMAGE)


def test_refuse_docker_launch_when_signer_marker_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("MAW_QG_SIGNING_KEY_FILE", "")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("docker invoked"))
    with pytest.raises(SandboxError, match="credential-bearing"):
        isolated_test(("true",), tmp_path, IMAGE)


def test_docker_invocation_has_no_ambient_environment_or_extra_mounts(tmp_path, monkeypatch):
    monkeypatch.setenv("QA_UNRELATED_SECRET_CANARY", "must-never-reach-docker")
    calls = simulate(monkeypatch)
    isolated_test(("true",), tmp_path, IMAGE)
    cmd, opts = calls[0]
    assert opts["env"] == {"PATH": "/usr/bin:/bin"}
    assert cmd.count("--mount") == 1
    assert cmd[cmd.index("--mount") + 1] == f"type=bind,src={tmp_path},dst=/src,readonly"
    assert "--env-file" not in cmd and "--volumes-from" not in cmd
    assert "--privileged" not in cmd
