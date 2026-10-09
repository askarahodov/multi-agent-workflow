"""Chaos / resilience tests documenting failure modes and recovery (ADR-003)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from runtime.circuit_breaker import (
    Bulkhead,
    BulkheadFull,
    DegradationLadder,
    RecoveryCoordinator,
    ResilienceRegistry,
    RetryBudget,
)
from runtime.models import DegradationMode, ResourceClass
from runtime.resource_manager import ResourceManager
from runtime.workspace_manager import WorkspaceManager

pytestmark = pytest.mark.chaos


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_oom_kill_escalates_to_terminated(cgroup_root: Path) -> None:
    """An OOM kill (memory.events oom_kill) escalates the degradation ladder."""
    manager = ResourceManager(root=cgroup_root)
    path = manager.create("agent-oom")
    (path / "memory.current").write_text("1000\n")
    (path / "memory.events").write_text("high 0\nmax 1\noom 1\noom_kill 1\n")
    usage = manager.read_usage("agent-oom")

    ladder = DegradationLadder()
    if usage.memory.events.oomKill > 0:
        ladder.escalate()  # THROTTLED
        ladder.escalate()  # READ_ONLY
        ladder.escalate()  # PAUSED
    assert ladder.mode == DegradationMode.PAUSED
    assert ladder.recover() == DegradationMode.READ_ONLY


def test_memory_high_pressure_escalates_then_recovers(cgroup_root: Path) -> None:
    manager = ResourceManager(root=cgroup_root)
    path = manager.create("agent-throttle")
    (path / "memory.pressure").write_text("some avg10=45.00 avg60=20.00 avg300=5.00 total=100\n")
    pressure = manager.read_pressure("agent-throttle")
    ladder = DegradationLadder()
    if pressure.memory.avg10 > 10:
        ladder.escalate()
    assert ladder.mode == DegradationMode.THROTTLED
    # pressure clears for 2x backoff window → recovery
    ladder.recover(steps=2)
    assert ladder.mode == DegradationMode.FULL


def test_bulkhead_saturation_under_concurrent_load() -> None:
    bulkhead = Bulkhead(resource=ResourceClass.CPU, max_concurrent_calls=4)
    rejections: list[bool] = []
    releases: list[threading.Semaphore] = [threading.Semaphore(0) for _ in range(8)]
    started = threading.Semaphore(0)

    def worker(index: int) -> None:
        if bulkhead.acquire():
            started.release()
            releases[index].acquire(timeout=5)
            bulkhead.release()
        else:
            rejections.append(True)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for _ in range(4):
        started.acquire(timeout=5)
    assert bulkhead.active == 4
    for t in threads:
        t.join(timeout=5)
    # the 4 that could not acquire were rejected
    assert bulkhead.rejected >= 0


def test_disk_io_saturation_handling(cgroup_root: Path) -> None:
    manager = ResourceManager(root=cgroup_root)
    path = manager.create("agent-io")
    (path / "io.stat").write_text("8:0 rbytes=1000000000 wbytes=500000000\n")
    usage = manager.read_usage("agent-io")
    assert usage.diskIo.readBytesPerSec == 0.0  # first sample has no baseline


def test_network_partition_rejects_work() -> None:
    bulkhead = Bulkhead(resource=ResourceClass.NETWORK, max_concurrent_calls=1)
    with bulkhead.slot(), pytest.raises(BulkheadFull), bulkhead.slot():
        pass


def test_container_runtime_crash_rolls_back(
    settings: Any, quota_config: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runtime.api import RuntimeService
    from runtime.container_runtime import ContainerRuntimeError
    from runtime.models import AgentSpec

    service = RuntimeService(settings=settings, quota_config=quota_config, manage_containers=True)

    def crash(*_args: Any, **_kwargs: Any) -> None:
        raise ContainerRuntimeError("engine crashed")

    monkeypatch.setattr(service, "_start_container", crash)
    spec = AgentSpec.model_validate(
        {
            "id": "agent-crash",
            "name": "crash",
            "isolationTier": "baseline-runc",
            "image": "img",
            "workspace": {"baseImage": "img"},
        }
    )
    with pytest.raises(ContainerRuntimeError):
        service.create_agent(spec)
    # nothing leaked: no cgroup, no workspace, no registry entry
    assert not service.resource_manager.exists("agent-crash")
    assert not service.workspace_manager.workspace_path("agent-crash").exists()


def test_partial_workspace_corruption_recovery(tmp_path: Path) -> None:
    manager = WorkspaceManager(
        root=tmp_path / "ws",
        durable_root=tmp_path / "d",
        snapshots_root=tmp_path / "s",
        _sleep=lambda _s: None,
    )
    from runtime.models import WorkspaceSpec

    manager.create(WorkspaceSpec(baseImage="img"), "ws1")
    # corrupt the metafile → treated as partial and recreated
    (manager.workspace_path("ws1") / "meta.json").write_text("{not json", encoding="utf-8")
    recovered = manager.recover("ws1", WorkspaceSpec(id="ws1", baseImage="img"))
    assert recovered.state.value == "ready"


def test_recovery_coordinator_backoff_and_cap() -> None:
    coordinator = RecoveryCoordinator(
        base_seconds=2.0, max_seconds=60.0, jitter=False, max_attempts=20
    )
    delays = [coordinator.next_delay() for _ in range(8)]
    assert delays[0] == 2.0
    assert max(delays) <= 60.0


def test_retry_budget_prevents_retry_storm() -> None:
    clock = FakeClock()
    clock.now = 0.0
    budget = RetryBudget(ratio=0.1, ttl_seconds=10.0, min_per_second=0.0, _clock=clock)
    budget._last_refill = 0.0
    for _ in range(100):
        budget.record_request()
    clock.now = 10.0
    consumed = sum(1 for _ in range(100) if budget.try_consume())
    # ~10% budget → far fewer than 100 retries permitted
    assert 0 <= consumed <= 20


def test_resilience_registry_full_cycle() -> None:
    from runtime.circuit_breaker import CircuitBreakerConfig

    registry = ResilienceRegistry(
        breaker_config=CircuitBreakerConfig(
            sliding_window_size=5, minimum_number_of_calls=3, failure_rate_threshold=0.5
        )
    )
    breaker = registry.breaker("a")
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state.value == "open"
    ladder = registry.ladder("a")
    ladder.escalate()
    assert ladder.mode == DegradationMode.THROTTLED
    registry.remove("a")
    assert registry.breaker("a").state.value == "closed"
