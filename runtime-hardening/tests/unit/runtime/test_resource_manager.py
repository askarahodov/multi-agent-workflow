"""Unit tests for the cgroup v2 resource manager."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.models import (
    BudgetLimits,
    CpuLimits,
    DiskIoDeviceLimit,
    DiskIoLimits,
    MemoryLimits,
    NetworkLimits,
    PidLimits,
    ResourceLimits,
    ResourceLimitsDelta,
)
from runtime.resource_manager import (
    QuotaExceededError,
    ResourceManager,
    ResourceManagerError,
    UnknownAgentError,
    parse_cpu_stat,
    parse_io_stat,
    parse_memory_events,
    parse_pressure,
)


@pytest.fixture
def manager(cgroup_root: Path) -> ResourceManager:
    return ResourceManager(root=cgroup_root, parent_slice="agent.slice")


def test_ensure_parent_enables_controllers(manager: ResourceManager) -> None:
    manager.ensure_parent()
    assert manager.parent_path.is_dir()
    assert set(manager.enable_subtree_control()) == {"+cpu", "+memory", "+io", "+pids"}


def test_apply_and_read_limits(manager: ResourceManager) -> None:
    limits = ResourceLimits(
        cpu=CpuLimits(quotaMicros=100_000, periodMicros=100_000, weight=200),
        memory=MemoryLimits(highBytes=800, maxBytes=1000, swapMaxBytes=1000),
        pids=PidLimits(max=64),
    )
    applied = manager.apply_limits("a1", limits)
    assert applied.cpu is not None and applied.cpu.quotaMicros == 100_000
    assert applied.memory is not None and applied.memory.maxBytes == 1000
    assert applied.pids is not None and applied.pids.max == 64
    # swap.max must equal max
    assert (manager.agent_path("a1") / "memory.swap.max").read_text().strip() == "1000"
    assert (manager.agent_path("a1") / "memory.oom.group").read_text().strip() == "1"


def test_apply_limits_unlimited_cpu(manager: ResourceManager) -> None:
    manager.apply_limits("a1", ResourceLimits(cpu=CpuLimits(quotaMicros=-1)))
    assert (manager.agent_path("a1") / "cpu.max").read_text().startswith("max ")


def test_apply_limits_disk_io(manager: ResourceManager) -> None:
    limits = ResourceLimits(
        diskIo=DiskIoLimits(
            max=[DiskIoDeviceLimit(device="8:0", rbps=100, wbps=50)],
            weight=300,
        )
    )
    manager.apply_limits("a1", limits)
    io_max = (manager.agent_path("a1") / "io.max").read_text()
    assert "8:0" in io_max and "rbps=100" in io_max and "wbps=50" in io_max
    assert (manager.agent_path("a1") / "io.weight").read_text().strip() == "default 300"


def test_adjust_limits_cpu_and_memory(manager: ResourceManager) -> None:
    manager.apply_limits(
        "a1",
        ResourceLimits(
            cpu=CpuLimits(quotaMicros=100_000, periodMicros=100_000),
            memory=MemoryLimits(highBytes=800, maxBytes=1000, swapMaxBytes=1000),
            pids=PidLimits(max=64),
        ),
    )
    new = manager.adjust_limits(
        "a1",
        ResourceLimitsDelta(
            cpuQuotaMicrosDelta=100_000,
            memoryMaxBytesDelta=500,
            memoryHighBytesDelta=100,
            pidsMaxDelta=10,
        ),
    )
    assert new.cpu is not None and new.cpu.quotaMicros == 200_000
    assert new.memory is not None and new.memory.maxBytes == 1500
    assert new.memory.swapMaxBytes == 1500
    assert new.pids is not None and new.pids.max == 74


def test_adjust_limits_network_delta(manager: ResourceManager) -> None:
    manager.apply_limits("a1", ResourceLimits(network=NetworkLimits(egressBps=1000)))
    new = manager.adjust_limits("a1", ResourceLimitsDelta(networkEgressBpsDelta=500))
    assert new.network is not None and new.network.egressBps == 1500


def test_unknown_agent_raises(manager: ResourceManager) -> None:
    with pytest.raises(UnknownAgentError):
        manager.get_limits("ghost")


def test_hierarchical_parent_budget(manager: ResourceManager) -> None:
    manager.parent_budget = BudgetLimits(
        memory=MemoryLimits(maxBytes=1000, swapMaxBytes=1000),
        cpu=CpuLimits(quotaMicros=200_000),
        pids=PidLimits(max=100),
    )
    with pytest.raises(QuotaExceededError):
        manager.apply_limits("a1", ResourceLimits(memory=MemoryLimits(maxBytes=2000)))
    with pytest.raises(QuotaExceededError):
        manager.apply_limits("a2", ResourceLimits(cpu=CpuLimits(quotaMicros=400_000)))
    with pytest.raises(QuotaExceededError):
        manager.apply_limits("a3", ResourceLimits(pids=PidLimits(max=500)))


def test_enforce_hierarchical_aggregate(manager: ResourceManager) -> None:
    manager.parent_budget = BudgetLimits(
        memory=MemoryLimits(maxBytes=1000, swapMaxBytes=1000),
    )
    with pytest.raises(QuotaExceededError):
        manager.enforce_hierarchical(
            {
                "a": ResourceLimits(memory=MemoryLimits(maxBytes=600)),
                "b": ResourceLimits(memory=MemoryLimits(maxBytes=600)),
            }
        )
    manager.enforce_hierarchical({"a": ResourceLimits(memory=MemoryLimits(maxBytes=400))})


def test_read_usage_and_pressure(manager: ResourceManager) -> None:
    path = manager.create("a1")
    (path / "cpu.stat").write_text("usage_usec 1000\nnr_throttled 2\nthrottled_usec 500\n")
    (path / "memory.current").write_text("2048\n")
    (path / "memory.peak").write_text("4096\n")
    (path / "memory.events").write_text("low 0\nhigh 3\nmax 1\noom 0\noom_kill 1\n")
    (path / "io.stat").write_text("8:0 rbytes=1000 wbytes=500\n")
    (path / "pids.current").write_text("5\n")
    (path / "pids.max").write_text("64\n")
    (path / "cpu.pressure").write_text("some avg10=1.00 avg60=0.50 avg300=0.25 total=12345\n")
    (path / "memory.pressure").write_text("some avg10=2.00 avg60=2.00 avg300=2.00 total=99\n")

    usage = manager.read_usage("a1", now=100.0)
    assert usage.memory.currentBytes == 2048
    assert usage.memory.events.high == 3
    assert usage.memory.events.oomKill == 1
    assert usage.pids.current == 5
    assert usage.cpu.throttledSecs == 0.0005

    # second read computes a rate (same cumulative value → 0/s)
    usage2 = manager.read_usage("a1", now=101.0)
    assert usage2.cpu.usageMicrosPerSec == 0.0
    assert usage2.diskIo.readBytesPerSec == 0.0

    pressure = manager.read_pressure("a1")
    assert pressure.cpu.avg10 == 1.0
    assert pressure.memory.totalMicros == 99


def test_remove_is_idempotent(manager: ResourceManager) -> None:
    manager.create("a1")
    manager.remove("a1")
    assert manager.exists("a1") is False
    manager.remove("a1")  # no error


def test_invalid_agent_id(manager: ResourceManager) -> None:
    with pytest.raises(ResourceManagerError):
        manager.agent_path("bad/id")


def test_parsers() -> None:
    assert parse_pressure("some avg10=1.5 avg60=0.0 avg300=0.0 total=7\n").totalMicros == 7
    events = parse_memory_events("high 5\noom_kill 2\n")
    assert events.high == 5 and events.oomKill == 2
    usage, throttled, ttime = parse_cpu_stat("usage_usec 10\nnr_throttled 1\nthrottled_usec 3\n")
    assert (usage, throttled, ttime) == (10, 1, 3)
    assert parse_io_stat("8:0 rbytes=1 wbytes=2\n") == {"8:0": (1, 2)}
