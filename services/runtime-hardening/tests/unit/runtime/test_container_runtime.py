"""Unit tests for the container runtime abstraction and isolation backends."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.container_runtime import (
    ISOLATION_BACKENDS,
    CliContainerRuntime,
    ContainerRuntimeError,
    DockerRuntime,
    PodmanRuntime,
    RootlessConfig,
    SeccompProfileGenerator,
    UsernsMapping,
    build_runtime,
    kvm_available,
    select_isolation_backend,
)
from runtime.models import IsolationTier


def test_build_runtime_factory() -> None:
    assert isinstance(build_runtime("docker"), DockerRuntime)
    assert isinstance(build_runtime("Podman"), PodmanRuntime)
    with pytest.raises(ValueError):
        build_runtime("containerd")


def test_isolation_backend_engine_args() -> None:
    runsc = ISOLATION_BACKENDS[IsolationTier.GVISOR_RUNSC]
    assert runsc.runtime_class == "runsc"
    assert "--runtime" in runsc.engine_args()
    assert "runsc" in runsc.engine_args()
    runc = ISOLATION_BACKENDS[IsolationTier.BASELINE_RUNC]
    assert runc.engine_args() == []


def test_select_isolation_backend_kata_without_kvm_falls_back() -> None:
    backend = select_isolation_backend(IsolationTier.KATA_FC, kvm_available=False)
    assert backend.tier == IsolationTier.GVISOR_NSJAIL
    backend_kvm = select_isolation_backend(IsolationTier.KATA_FC, kvm_available=True)
    assert backend_kvm.tier == IsolationTier.KATA_FC


def test_select_isolation_backend_non_kvm_tier_unaffected() -> None:
    backend = select_isolation_backend(IsolationTier.BASELINE_RUNC, kvm_available=False)
    assert backend.tier == IsolationTier.BASELINE_RUNC


def test_seccomp_profile_generation() -> None:
    profile = SeccompProfileGenerator(allowed_syscalls=("read", "write")).generate()
    assert profile["defaultAction"] == "SCMP_ACT_ERRNO"
    assert profile["syscalls"][0]["names"] == ["read", "write"]
    assert profile["syscalls"][0]["action"] == "SCMP_ACT_ALLOW"
    assert "SCMP_ARCH_X86_64" in profile["architectures"]


def test_seccomp_profile_write(tmp_path: Path) -> None:
    target = SeccompProfileGenerator(allowed_syscalls=("read",)).write(tmp_path / "sp" / "p.json")
    assert json.loads(target.read_text(encoding="utf-8"))["defaultAction"] == "SCMP_ACT_ERRNO"


def test_rootless_config_engine_args() -> None:
    config = RootlessConfig(enabled=True)
    podman_args = config.engine_args("podman")
    assert "--userns=keep-id" in podman_args
    assert "--user=1000" in podman_args
    docker_args = config.engine_args("docker")
    assert "--userns=keep-id" not in docker_args
    assert "--user=1000" in docker_args
    assert RootlessConfig(enabled=False).engine_args("docker") == []


def test_userns_mapping_render() -> None:
    assert UsernsMapping(0, 100000, 65536).render() == "0 100000 65536"


def test_create_args_includes_hardening(tmp_path: Path) -> None:
    runtime = DockerRuntime()
    args = runtime.create_args(
        image="alpine:latest",
        name="agent-x",
        backend=ISOLATION_BACKENDS[IsolationTier.BASELINE_RUNC],
        rootless=RootlessConfig(enabled=True),
        seccomp_profile=tmp_path / "seccomp.json",
        limits=["--memory", "1000"],
        env={"FOO": "bar"},
    )
    joined = " ".join(args)
    assert "run" in args
    assert "--read-only" in args
    assert "--cap-drop=ALL" in args
    assert "--security-opt=no-new-privileges:true" in args
    assert f"seccomp={tmp_path / 'seccomp.json'}" in joined
    assert "-e FOO=bar" in joined
    assert args[-1] == "alpine:latest"


def test_create_args_runtime_default_seccomp_omitted() -> None:
    runtime = DockerRuntime()
    args = runtime.create_args(
        image="alpine",
        name="a",
        backend=ISOLATION_BACKENDS[IsolationTier.BASELINE_RUNC],
        rootless=RootlessConfig(enabled=False),
        seccomp_profile="RuntimeDefault",
        limits=[],
        env={},
    )
    assert not any("seccomp=" in a for a in args)


def test_runtime_unavailable_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = DockerRuntime()
    monkeypatch.setattr("runtime.container_runtime.shutil.which", lambda _: None)
    assert runtime.available() is False
    with pytest.raises(ContainerRuntimeError):
        runtime.inspect("nope")


def test_kvm_available_checks_path(tmp_path: Path) -> None:
    fake = tmp_path / "kvm"
    assert kvm_available(fake) is False
    fake.write_text("")
    assert kvm_available(fake) is True


def test_cli_runtime_is_abstract_base() -> None:
    assert issubclass(DockerRuntime, CliContainerRuntime)
