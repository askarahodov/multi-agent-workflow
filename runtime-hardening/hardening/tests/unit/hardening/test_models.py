"""Unit tests for the shared data contracts (models)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from runtime.hardening.models import (
    AgentSpec,
    CpuLimits,
    DegradationMode,
    IsolationTier,
    MemoryLimits,
    ResourceLimits,
    ResourceLimitsDelta,
    ResourceQuotaConfig,
    WorkloadClass,
    WorkspaceSpec,
)


def test_memory_swap_must_equal_max() -> None:
    with pytest.raises(ValidationError):
        MemoryLimits(maxBytes=1024, swapMaxBytes=2048)


def test_memory_high_must_be_le_max() -> None:
    with pytest.raises(ValidationError):
        MemoryLimits(maxBytes=1024, highBytes=2048)


def test_memory_valid_invariants() -> None:
    mem = MemoryLimits(maxBytes=1024, swapMaxBytes=1024, highBytes=800, oomGroup=True)
    assert mem.oomGroup is True


def test_quota_config_rejects_unknown_class() -> None:
    with pytest.raises(ValidationError):
        ResourceQuotaConfig(
            schemaVersion="1.0.0",
            parentBudget={"memory": {"maxBytes": 4096, "swapMaxBytes": 4096}},
            resourceClasses={"trusted": {"pids": {"max": 256}}},
            agents={"a1": {"class": "missing"}},
        )


def test_quota_config_valid() -> None:
    cfg = ResourceQuotaConfig(
        schemaVersion="1.0.0",
        parentBudget={"memory": {"maxBytes": 4096, "swapMaxBytes": 4096}},
        resourceClasses={"trusted": {"pids": {"max": 256}}},
        agents={"a1": {"class": "trusted"}},
    )
    assert cfg.agents["a1"].cls == "trusted"


def test_resource_limits_delta() -> None:
    delta = ResourceLimitsDelta(cpuQuotaMicrosDelta=100_000, pidsMaxDelta=64)
    assert delta.cpuQuotaMicrosDelta == 100_000


def test_agent_spec_pattern() -> None:
    with pytest.raises(ValidationError):
        AgentSpec(id="BAD_ID!", name="x", isolationTier=IsolationTier.BASELINE_RUNC, image="img")


def test_agent_spec_valid() -> None:
    spec = AgentSpec(
        name="build-farm-01",
        isolationTier=IsolationTier.GVISOR_RUNSC,
        image="harbor/base",
        resourceClass="untrusted",
        labels={"harbor.hardening/isolation": WorkloadClass.UNTRUSTED.value},
    )
    assert spec.isolationTier == IsolationTier.GVISOR_RUNSC


def test_workspace_spec_durability() -> None:
    ws = WorkspaceSpec(
        baseImage="img", scratchBytes=1024, durable=True, durabilityClass="persistent"
    )
    assert ws.durable is True


def test_degradation_enum_values() -> None:
    assert [m.value for m in DegradationMode] == [
        "full",
        "throttled",
        "read_only",
        "paused",
        "terminated",
    ]


def test_cpu_limits_quota_ge_minus1() -> None:
    with pytest.raises(ValidationError):
        CpuLimits(quotaMicros=-5)


def test_resource_limits_roundtrip() -> None:
    limits = ResourceLimits(
        cpu=CpuLimits(quotaMicros=100_000), memory=MemoryLimits(maxBytes=2048, swapMaxBytes=2048)
    )
    dumped = limits.model_dump(exclude_none=True)
    assert dumped["cpu"]["quotaMicros"] == 100_000
