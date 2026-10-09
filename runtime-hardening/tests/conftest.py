"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.config import RuntimeSettings
from runtime.models import (
    BudgetLimits,
    CpuLimits,
    MemoryLimits,
    PidLimits,
    ResourceLimits,
    ResourceQuotaConfig,
)


@pytest.fixture
def cgroup_root(tmp_path: Path) -> Path:
    """A synthetic cgroup2 tree that the ResourceManager can write to."""
    root = tmp_path / "cgroup"
    root.mkdir()
    (root / "cgroup.controllers").write_text("cpu memory io pids\n", encoding="utf-8")
    return root


@pytest.fixture
def quota_config() -> ResourceQuotaConfig:
    return ResourceQuotaConfig(
        schemaVersion="1.0.0",
        parentBudget=BudgetLimits(
            cpu=CpuLimits(quotaMicros=4_000_000, periodMicros=100_000),
            memory=MemoryLimits(maxBytes=8 << 30, swapMaxBytes=8 << 30),
            pids=PidLimits(max=4096),
        ),
        resourceClasses={
            "default": ResourceLimits(
                cpu=CpuLimits(quotaMicros=200_000, periodMicros=100_000),
                memory=MemoryLimits(
                    highBytes=800 << 20, maxBytes=1000 << 20, swapMaxBytes=1000 << 20
                ),
                pids=PidLimits(max=256),
            ),
            "untrusted": ResourceLimits(
                cpu=CpuLimits(quotaMicros=100_000, periodMicros=100_000),
                memory=MemoryLimits(
                    highBytes=800 << 20, maxBytes=1000 << 20, swapMaxBytes=1000 << 20
                ),
                pids=PidLimits(max=128),
            ),
        },
    )


@pytest.fixture
def settings(tmp_path: Path, cgroup_root: Path) -> RuntimeSettings:
    return RuntimeSettings(
        cgroup_root=cgroup_root,
        workspace_root=tmp_path / "workspaces",
        durable_root=tmp_path / "durable",
        snapshots_root=tmp_path / "snapshots",
        container_runtime="docker",
        rootless=True,
        cleanup_grace_seconds=0,
    )
