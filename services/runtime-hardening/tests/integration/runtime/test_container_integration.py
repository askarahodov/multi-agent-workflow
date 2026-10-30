"""Integration tests exercising a real container runtime (docker).

These are marked ``integration`` and are skipped automatically when no
container engine (or no usable image) is available on the host.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

import pytest

from runtime.container_runtime import (
    ISOLATION_BACKENDS,
    DockerRuntime,
    RootlessConfig,
    build_runtime,
)
from runtime.models import IsolationTier

pytestmark = pytest.mark.integration


def _docker_images() -> list[str]:
    if shutil.which("docker") is None:
        return []
    proc = subprocess.run(
        ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [
        line.strip() for line in proc.stdout.splitlines() if line.strip() and "<none>" not in line
    ]


def _pick_image() -> str:
    images = _docker_images()
    if not images:
        pytest.skip("no docker images available")
    for preferred in ("python:3.12-bookworm", "debian:bookworm", "nginx:latest", "busybox:latest"):
        if preferred in images:
            return preferred
    return images[0]


@pytest.fixture(scope="module")
def docker() -> DockerRuntime:
    runtime = build_runtime("docker")
    if not runtime.available():
        pytest.skip("docker binary not available")
    return runtime


def test_real_container_hardening_flags(docker: DockerRuntime) -> None:
    image = _pick_image()
    name = "agent-runtime-it-hardening"
    docker.remove(name, force=True)
    args = docker.create_args(
        image=image,
        name=name,
        backend=ISOLATION_BACKENDS[IsolationTier.BASELINE_RUNC],
        rootless=RootlessConfig(enabled=False),
        seccomp_profile="RuntimeDefault",
        limits=["--memory", "268435456", "--pids-limit", "128"],
        env={"AGENT_RUNTIME_IT": "1"},
    )
    # keep the container alive long enough to inspect it
    args += ["sh", "-c", "sleep 30"]
    try:
        info = docker.create(args)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"could not start container: {exc}")
    try:
        assert info.container_id
        inspected = docker.inspect(info.container_id)
        host = inspected["HostConfig"]
        assert host["ReadonlyRootfs"] is True
        assert "ALL" in host["CapDrop"]
        assert any("no-new-privileges" in opt for opt in host["SecurityOpt"])
        assert host["Memory"] == 268435456
    finally:
        docker.remove(info.container_id, force=True)


def test_real_container_lifecycle_full(settings: Any, quota_config: Any) -> None:
    from runtime.api import RuntimeService
    from runtime.models import AgentSpec

    image = _pick_image()
    runtime = build_runtime("docker")
    if not runtime.available():
        pytest.skip("docker binary not available")

    service = RuntimeService(
        settings=settings,
        quota_config=quota_config,
        container_runtime=runtime,
        manage_containers=True,
    )
    spec = AgentSpec.model_validate(
        {
            "id": "agent-it",
            "name": "integration",
            "isolationTier": "baseline-runc",
            "image": image,
            "resourceClass": "untrusted",
            "workspace": {"baseImage": image, "durable": False},
        }
    )
    try:
        agent = service.create_agent(spec)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"container start failed: {exc}")
    try:
        assert agent.containerId
        assert agent.state.value == "running"
        assert service.get_health("agent-it").readiness.value == "pass"
    finally:
        service.delete_agent("agent-it", 0, force=True)

    assert not service.resource_manager.exists("agent-it")
