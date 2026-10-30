"""Unit tests for the cgroups v2 Resource Manager (spec §4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.hardening.models import (
    BudgetLimits,
    CpuLimits,
    DiskIoDeviceLimit,
    DiskIoLimits,
    MemoryLimits,
    PidLimits,
    ResourceLimits,
    ResourceLimitsDelta,
)
from runtime.hardening.resource_manager import (
    QuotaExceededError,
    ResourceManager,
    ResourceManagerError,
    UnknownAgentError,
    parse_memory_events,
    parse_pressure,
)


def test_create_and_apply_limits(resource_manager: ResourceManager) -> None:
    limits = ResourceLimits(
        cpu=CpuLimits(quotaMicros=100_000, weight=200),
        memory=MemoryLimits(maxBytes=2048, swapMaxBytes=2048, highBytes=1600, oomGroup=True),
        pids=PidLimits(max=256),
    )
    applied = resource_manager.apply_limits("agent-1", limits)
    assert applied.cpu is not None
    assert applied.cpu.quotaMicros == 100_000
    assert applied.memory is not None
    assert applied.memory.maxBytes == 2048
    assert applied.memory.swapMaxBytes == 2048  # swap disabled (swap==max)
    assert applied.pids is not None
    assert applied.pids.max == 256


def test_swap_disabled_invariant(resource_manager: ResourceManager) -> None:
    limits = ResourceLimits(memory=MemoryLimits(maxBytes=4096, swapMaxBytes=4096))
    resource_manager.apply_limits("agent-swap", limits)
    path = resource_manager.agent_path("agent-swap")
    # memory.swap.max written == memory.max.
    swap = (path / "memory.swap.max").read_text(encoding="utf-8").strip()
    mx = (path / "memory.max").read_text(encoding="utf-8").strip()
    assert swap == mx


def test_oom_group_set(resource_manager: ResourceManager) -> None:
    limits = ResourceLimits(memory=MemoryLimits(maxBytes=1024, swapMaxBytes=1024, oomGroup=True))
    resource_manager.apply_limits("agent-oom", limits)
    path = resource_manager.agent_path("agent-oom")
    assert (path / "memory.oom.group").read_text(encoding="utf-8").strip() == "1"


def test_budget_exceeded_returns_409_semantics() -> None:
    manager = ResourceManager(
        root=Path("/tmp/does-not-exist-cgroup"),
        parent_budget=BudgetLimits(memory=MemoryLimits(maxBytes=1024, swapMaxBytes=1024)),
    )
    over = ResourceLimits(memory=MemoryLimits(maxBytes=2048, swapMaxBytes=2048))
    with pytest.raises(QuotaExceededError):
        manager.check_within_parent(over)


def test_aggregate_child_budget_checked() -> None:
    manager = ResourceManager(
        root=Path("/tmp/does-not-exist-cgroup"),
        parent_budget=BudgetLimits(memory=MemoryLimits(maxBytes=1000, swapMaxBytes=1000)),
    )
    children = {
        "a": ResourceLimits(memory=MemoryLimits(maxBytes=600, swapMaxBytes=600)),
        "b": ResourceLimits(memory=MemoryLimits(maxBytes=600, swapMaxBytes=600)),
    }
    with pytest.raises(QuotaExceededError):
        manager.enforce_hierarchical(children)


def test_adjust_limits_delta(resource_manager: ResourceManager) -> None:
    limits = ResourceLimits(
        cpu=CpuLimits(quotaMicros=100_000),
        memory=MemoryLimits(maxBytes=2048, swapMaxBytes=2048),
        pids=PidLimits(max=256),
    )
    resource_manager.apply_limits("agent-adj", limits)
    result = resource_manager.adjust_limits(
        "agent-adj",
        ResourceLimitsDelta(cpuQuotaMicrosDelta=50_000, pidsMaxDelta=64),
    )
    assert result.cpu is not None and result.cpu.quotaMicros == 150_000
    assert result.pids is not None and result.pids.max == 320


def test_unknown_agent_error(resource_manager: ResourceManager) -> None:
    with pytest.raises(UnknownAgentError):
        resource_manager.read_usage("missing")


def test_parse_pressure() -> None:
    sample = parse_pressure(
        "some avg10=1.50 avg60=2.00 avg300=3.00 total=12345\n"
        "full avg10=9.99 avg60=10.00 avg300=10.00 total=99999"
    )
    assert sample.avg10 == 1.50
    assert sample.totalMicros == 12345


def test_parse_memory_events() -> None:
    events = parse_memory_events("low 1\nhigh 2\nmax 0\noom 1\noom_kill 1")
    assert events.high == 2
    assert events.oomKill == 1


def test_io_limits_apply(resource_manager: ResourceManager) -> None:
    limits = ResourceLimits(
        diskIo=DiskIoLimits(
            max=[DiskIoDeviceLimit(device="8:0", rbps=1000, wbps=2000)],
            weight=200,
        )
    )
    resource_manager.apply_limits("agent-io", limits)
    path = resource_manager.agent_path("agent-io")
    io_max = (path / "io.max").read_text(encoding="utf-8").strip()
    assert "8:0" in io_max and "rbps=1000" in io_max


def test_read_usage_and_pressure(resource_manager: ResourceManager) -> None:
    resource_manager.apply_limits(
        "agent-telemetry",
        ResourceLimits(
            cpu=CpuLimits(quotaMicros=100_000),
            memory=MemoryLimits(maxBytes=2048, swapMaxBytes=2048),
            pids=PidLimits(max=128),
        ),
    )
    path = resource_manager.agent_path("agent-telemetry")
    (path / "cpu.stat").write_text(
        "usage_usec 5000\nnr_throttled 1\nthrottled_usec 1000", encoding="utf-8"
    )
    (path / "memory.current").write_text("1024", encoding="utf-8")
    (path / "memory.peak").write_text("2048", encoding="utf-8")
    (path / "memory.events").write_text("low 0\nhigh 1\nmax 0\noom 0\noom_kill 0", encoding="utf-8")
    (path / "io.stat").write_text("8:0 rbytes=1000 wbytes=2000", encoding="utf-8")
    (path / "pids.current").write_text("5", encoding="utf-8")
    (path / "cpu.pressure").write_text(
        "some avg10=0.2 avg60=0.1 avg300=0.0 total=100", encoding="utf-8"
    )
    (path / "memory.pressure").write_text(
        "some avg10=0.3 avg60=0.2 avg300=0.0 total=200", encoding="utf-8"
    )

    usage = resource_manager.read_usage("agent-telemetry", now=1.0)
    assert usage.cpu.throttledSecs == 0.001
    assert usage.memory.currentBytes == 1024
    assert usage.memory.events.high == 1
    assert usage.pids.current == 5

    pressure = resource_manager.read_pressure("agent-telemetry")
    assert pressure.cpu.avg10 == 0.2
    assert pressure.memory.totalMicros == 200


def test_remove_is_idempotent(resource_manager: ResourceManager) -> None:
    resource_manager.apply_limits(
        "agent-remove", ResourceLimits(memory=MemoryLimits(maxBytes=1024, swapMaxBytes=1024))
    )
    resource_manager.remove("agent-remove")
    resource_manager.remove("agent-remove")  # second call no-op
    assert not resource_manager.exists("agent-remove")


def test_invalid_agent_id_rejected(resource_manager: ResourceManager) -> None:
    with pytest.raises(ResourceManagerError):
        resource_manager.agent_path("../evil")


def test_cpuset_and_memory_low_min_burst(resource_manager: ResourceManager) -> None:
    limits = ResourceLimits(
        cpu=CpuLimits(quotaMicros=200_000, burstMicros=50_000, cpusetCpus="0-3", cpusetMems="0"),
        memory=MemoryLimits(maxBytes=2048, swapMaxBytes=2048, lowBytes=256, minBytes=128),
    )
    applied = resource_manager.apply_limits("agent-cpupin", limits)
    path = resource_manager.agent_path("agent-cpupin")
    assert (path / "cpu.max.burst").read_text(encoding="utf-8").strip() == "50000"
    assert (path / "cpuset.cpus").read_text(encoding="utf-8").strip() == "0-3"
    assert (path / "cpuset.mems").read_text(encoding="utf-8").strip() == "0"
    assert (path / "memory.low").read_text(encoding="utf-8").strip() == "256"
    assert applied.cpu is not None and applied.cpu.quotaMicros == 200_000


def test_unlimited_cpu_quota(resource_manager: ResourceManager) -> None:
    limits = ResourceLimits(cpu=CpuLimits(quotaMicros=-1, periodMicros=100_000))
    applied = resource_manager.apply_limits("agent-unlim", limits)
    path = resource_manager.agent_path("agent-unlim")
    assert (path / "cpu.max").read_text(encoding="utf-8").strip() == "max 100000"
    assert applied.cpu is not None and applied.cpu.quotaMicros == -1


def test_disk_io_weight_apply(resource_manager: ResourceManager) -> None:
    limits = ResourceLimits(diskIo=DiskIoLimits(weight=300))
    resource_manager.apply_limits("agent-iodisk", limits)
    path = resource_manager.agent_path("agent-iodisk")
    assert "default 300" in (path / "io.weight").read_text(encoding="utf-8")


def test_network_delta_adjust(resource_manager: ResourceManager) -> None:
    from runtime.hardening.models import NetworkLimits

    limits = ResourceLimits(network=NetworkLimits(egressBps=1000, qdisc="htb"))
    resource_manager.apply_limits("agent-net", limits)
    result = resource_manager.adjust_limits(
        "agent-net", ResourceLimitsDelta(networkEgressBpsDelta=500)
    )
    assert result.network is not None and result.network.egressBps == 1500


def test_adjust_memory_delta_syncs_swap(resource_manager: ResourceManager) -> None:
    resource_manager.apply_limits(
        "agent-memadj",
        ResourceLimits(memory=MemoryLimits(maxBytes=2048, swapMaxBytes=2048, highBytes=1600)),
    )
    result = resource_manager.adjust_limits(
        "agent-memadj", ResourceLimitsDelta(memoryMaxBytesDelta=1024, memoryHighBytesDelta=200)
    )
    assert result.memory is not None
    assert result.memory.maxBytes == 3072
    assert result.memory.swapMaxBytes == 3072  # swap follows max
    assert result.memory.highBytes == 1800


def test_get_limits_falls_back_to_cached_diskio_network(resource_manager: ResourceManager) -> None:
    """Network/disk I/O are not cgroup controllers, so they fall back to applied cache."""
    from runtime.hardening.models import NetworkLimits

    limits = ResourceLimits(
        memory=MemoryLimits(maxBytes=1024, swapMaxBytes=1024),
        network=NetworkLimits(egressBps=5000, qdisc="tbf"),
        diskIo=DiskIoLimits(weight=150),
    )
    resource_manager.apply_limits("agent-cache", limits)
    result = resource_manager.get_limits("agent-cache")
    assert result.network is not None and result.network.egressBps == 5000
    assert result.diskIo is not None and result.diskIo.weight == 150


def test_apply_limits_returns_readback(resource_manager: ResourceManager) -> None:
    """apply_limits returns the limits read back from the tree (not just input)."""
    limits = ResourceLimits(memory=MemoryLimits(maxBytes=1024, swapMaxBytes=1024, oomGroup=True))
    applied = resource_manager.apply_limits("agent-readback", limits)
    assert applied.memory is not None
    assert applied.memory.maxBytes == 1024
    assert applied.memory.oomGroup is True
