"""Integration fixtures for the hardened runtime.

These tests exercise a real container runtime (Docker) when available and are
skipped otherwise. They verify the baseline hardening flags on a created
sandbox (AC-2) via ``docker inspect`` and the full lifecycle.
"""

from __future__ import annotations

import shutil
import subprocess
from contextlib import suppress

import pytest

from runtime.hardening.isolation import DockerRuntime, SandboxSpec, SeccompProfile
from runtime.hardening.models import IsolationTier

pytestmark = pytest.mark.integration

DOCKER_IMAGE = "busybox:latest"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(["docker", "info"], capture_output=True, timeout=10, check=False)
        return True
    except Exception:
        return False


requires_docker = pytest.mark.skipif(not _docker_available(), reason="docker daemon not available")


@requires_docker
def test_baseline_hardening_flags_via_docker_inspect() -> None:
    """AC-2: baseline hardening flags present on the created sandbox."""
    rt = DockerRuntime()
    spec = SandboxSpec(
        agent_id="integ-hardening",
        image=DOCKER_IMAGE,
        tier=IsolationTier.BASELINE_RUNC,
        runtime_class_name="runc",
        command=["sleep", "30"],
        seccomp=SeccompProfile(),
    )
    container_id = rt.start(spec)
    try:
        flags = rt.inspect_hardening(container_id)
        assert flags["readOnlyRootFilesystem"] is True
        assert "ALL" in str(flags["capabilities_drop"])
        assert "no-new-privileges" in str(flags["securityOpt"]).lower()
        assert "65532" in str(flags["user"])
        assert rt.status(container_id) in ("running", "created")
    finally:
        with suppress(Exception):
            rt.stop(container_id, grace_seconds=1)


@requires_docker
def test_full_lifecycle() -> None:
    """Create -> status -> stop -> cleanup lifecycle against a real runtime."""
    rt = DockerRuntime()
    spec = SandboxSpec(
        agent_id="integ-lifecycle",
        image=DOCKER_IMAGE,
        tier=IsolationTier.BASELINE_RUNC,
        runtime_class_name="runc",
        command=["sleep", "30"],
    )
    container_id = rt.start(spec)
    assert rt.status(container_id) in ("running", "created")
    rt.stop(container_id, grace_seconds=1)
    assert rt.status(container_id) == "exited"
