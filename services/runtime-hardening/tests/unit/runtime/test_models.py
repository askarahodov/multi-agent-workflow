"""Unit tests for the Pydantic contract models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from runtime.models import (
    AgentSpec,
    IsolationTier,
    MemoryLimits,
    ResourceLimits,
    ResourceQuotaConfig,
)


def test_memory_swap_must_equal_max() -> None:
    with pytest.raises(ValidationError):
        MemoryLimits(maxBytes=100, swapMaxBytes=50)


def test_memory_high_must_not_exceed_max() -> None:
    with pytest.raises(ValidationError):
        MemoryLimits(highBytes=200, maxBytes=100)


def test_memory_valid_three_tier() -> None:
    mem = MemoryLimits(highBytes=80, maxBytes=100, swapMaxBytes=100)
    assert mem.highBytes == 80
    assert mem.oomGroup is True


def test_agent_spec_id_pattern() -> None:
    with pytest.raises(ValidationError):
        AgentSpec(name="x", isolationTier=IsolationTier.BASELINE_RUNC, image="img", id="INVALID")


def test_agent_spec_defaults() -> None:
    spec = AgentSpec(name="a", isolationTier=IsolationTier.GVISOR_RUNSC, image="img")
    assert spec.seccompProfile == "RuntimeDefault"
    assert spec.resourceClass == "default"


def test_quota_config_rejects_unknown_class() -> None:
    with pytest.raises(ValidationError):
        ResourceQuotaConfig.model_validate(
            {
                "schemaVersion": "1.0.0",
                "parentBudget": {},
                "resourceClasses": {"default": {}},
                "agents": {"a": {"class": "missing"}},
            }
        )


def test_resource_limits_roundtrip() -> None:
    limits = ResourceLimits.model_validate(
        {
            "cpu": {"quotaMicros": 100_000, "periodMicros": 100_000, "weight": 100},
            "memory": {"highBytes": 10, "maxBytes": 20, "swapMaxBytes": 20},
            "pids": {"max": 10},
        }
    )
    dumped = limits.model_dump(exclude_none=True)
    assert dumped["memory"]["maxBytes"] == 20
