"""cgroup v2 resource management (ADR-002).

A single enforcement layer over the cgroup v2 unified hierarchy with a
three-tier per-agent limit model and hierarchical budget allocation. The
manager operates directly on cgroupfs, so the same code runs against
``/sys/fs/cgroup`` on a host and against a synthetic tree in unit tests.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from runtime.models import (
    BudgetLimits,
    CpuLimits,
    CpuUsage,
    DiskIoUsage,
    MemoryEvents,
    MemoryLimits,
    MemoryUsage,
    NetworkUsage,
    PidLimits,
    PidUsage,
    PressureReport,
    PressureSample,
    ResourceLimits,
    ResourceLimitsDelta,
    ResourceUsage,
)

SUBTREE_CONTROLLERS: tuple[str, ...] = ("+cpu", "+memory", "+io", "+pids")


class ResourceManagerError(RuntimeError):
    """Raised on cgroup manipulation failures."""


class QuotaExceededError(ResourceManagerError):
    """Raised when a request would exceed the parent aggregate budget."""


class UnknownAgentError(ResourceManagerError):
    """Raised when an agent cgroup does not exist."""


def _read_int(path: Path) -> int:
    text = path.read_text(encoding="utf-8").strip()
    return 0 if text in ("", "max") else int(text)


def parse_pressure(text: str) -> PressureSample:
    """Parse a cgroup v2 PSI file.

    Format: ``some avg10=0.00 avg60=0.00 avg300=0.00 total=12345`` (optionally a
    second ``full`` line).
    """
    sample = PressureSample()
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0] == "some":
            values = dict(p.split("=", 1) for p in parts[1:] if "=" in p)
            sample = PressureSample(
                avg10=float(values.get("avg10", 0.0)),
                avg60=float(values.get("avg60", 0.0)),
                avg300=float(values.get("avg300", 0.0)),
                totalMicros=int(values.get("total", 0)),
            )
    return sample


def parse_memory_events(text: str) -> MemoryEvents:
    """Parse a ``memory.events`` file into a :class:`MemoryEvents`."""
    raw: dict[str, int] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        key, _, value = line.partition(" ")
        raw[key.strip()] = int(value.strip() or 0)
    return MemoryEvents(
        low=raw.get("low", 0),
        high=raw.get("high", 0),
        max=raw.get("max", 0),
        oom=raw.get("oom", 0),
        oomKill=raw.get("oom_kill", 0),
    )


def parse_cpu_stat(text: str) -> tuple[int, int, int]:
    """Return ``(usage_usec, nr_throttled, throttled_usec)`` from ``cpu.stat``."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, value = line.partition(" ")
        if value.strip():
            values[key.strip()] = int(value.strip())
    return (
        values.get("usage_usec", 0),
        values.get("nr_throttled", 0),
        values.get("throttled_usec", 0),
    )


def parse_io_stat(text: str) -> dict[str, tuple[int, int]]:
    """Return ``{device: (read_bytes, write_bytes)}`` from ``io.stat``."""
    result: dict[str, tuple[int, int]] = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        device = parts[0]
        values: dict[str, int] = {}
        for token in parts[1:]:
            key, _, value = token.partition("=")
            if value:
                values[key] = int(value)
        result[device] = (values.get("rbytes", 0), values.get("wbytes", 0))
    return result


@dataclass
class _RateState:
    sampled_at: float
    value: float


@dataclass
class ResourceManager:
    """Manage cgroup v2 limits, quotas and telemetry for agent scopes."""

    root: Path = Path("/sys/fs/cgroup")
    parent_slice: str = "agent.slice"
    parent_budget: BudgetLimits | None = None
    _applied: dict[str, ResourceLimits] = field(default_factory=dict)
    _cpu_rates: dict[str, _RateState] = field(default_factory=dict)
    _io_rates: dict[str, _RateState] = field(default_factory=dict)

    # -- paths ---------------------------------------------------------------- #
    @property
    def parent_path(self) -> Path:
        return self.root / self.parent_slice

    def agent_path(self, agent_id: str) -> Path:
        if not agent_id or "/" in agent_id:
            raise ResourceManagerError(f"invalid agent id {agent_id!r}")
        return self.parent_path / f"agent-{agent_id}.scope"

    # -- hierarchy ------------------------------------------------------------ #
    def ensure_parent(self) -> Path:
        """Create the parent slice and enable required controllers."""
        self.parent_path.mkdir(parents=True, exist_ok=True)
        self._write(self.parent_path / "cgroup.subtree_control", " ".join(SUBTREE_CONTROLLERS))
        return self.parent_path

    def enable_subtree_control(self) -> list[str]:
        """Read back the enabled controllers on the parent slice."""
        return self._read(self.parent_path / "cgroup.subtree_control").split()

    def create(self, agent_id: str) -> Path:
        """Create (idempotently) the per-agent child cgroup."""
        self.ensure_parent()
        path = self.agent_path(agent_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def exists(self, agent_id: str) -> bool:
        return self.agent_path(agent_id).is_dir()

    # -- limits --------------------------------------------------------------- #
    def apply_limits(self, agent_id: str, limits: ResourceLimits) -> ResourceLimits:
        """Apply (replace) limits for an agent and return the applied limits."""
        path = self.create(agent_id)
        if self.parent_budget is not None:
            self.check_within_parent(limits)
        for name, value in self._limit_files(limits).items():
            self._write(path / name, value)
        self._applied[agent_id] = limits
        applied = self.get_limits(agent_id)
        self._applied[agent_id] = applied
        return applied

    def adjust_limits(self, agent_id: str, delta: ResourceLimitsDelta) -> ResourceLimits:
        """Adjust current limits by a delta, respecting the parent budget."""
        current = self.get_limits(agent_id)
        new = self._apply_delta(current, delta)
        return self.apply_limits(agent_id, new)

    def get_limits(self, agent_id: str) -> ResourceLimits:
        """Read the applied limits back from cgroupfs."""
        path = self.agent_path(agent_id)
        if not path.is_dir():
            if agent_id in self._applied:
                return self._applied[agent_id]
            raise UnknownAgentError(f"agent {agent_id!r} has no cgroup")

        cpu: CpuLimits | None = None
        cpu_max = self._read_optional(path / "cpu.max")
        if cpu_max is not None:
            quota_str, _, period_str = cpu_max.partition(" ")
            quota = -1 if quota_str == "max" else int(quota_str)
            cpu = CpuLimits(
                quotaMicros=quota,
                periodMicros=int(period_str or 100_000),
                weight=_read_int(path / "cpu.weight") if (path / "cpu.weight").exists() else 100,
            )

        memory: MemoryLimits | None = None
        if (path / "memory.max").exists():
            memory = MemoryLimits(
                highBytes=_read_int(path / "memory.high")
                if (path / "memory.high").exists()
                else None,
                maxBytes=_read_int(path / "memory.max"),
                swapMaxBytes=_read_int(path / "memory.swap.max")
                if (path / "memory.swap.max").exists()
                else None,
                oomGroup=_read_int(path / "memory.oom.group") == 1
                if (path / "memory.oom.group").exists()
                else True,
            )

        pids: PidLimits | None = None
        if (path / "pids.max").exists():
            value = self._read_optional(path / "pids.max")
            if value is not None and value != "max":
                pids = PidLimits(max=int(value))

        # Network/disk I/O shaping is not a cgroup v2 controller, so it cannot be
        # read back from cgroupfs — fall back to the last applied value.
        cached = self._applied.get(agent_id)
        return ResourceLimits(
            cpu=cpu,
            memory=memory,
            diskIo=cached.diskIo if cached else None,
            network=cached.network if cached else None,
            pids=pids,
        )

    def _limit_files(self, limits: ResourceLimits) -> dict[str, str]:
        files: dict[str, str] = {}
        if limits.cpu is not None:
            quota = "max" if limits.cpu.quotaMicros in (None, -1) else str(limits.cpu.quotaMicros)
            files["cpu.max"] = f"{quota} {limits.cpu.periodMicros}"
            files["cpu.weight"] = str(limits.cpu.weight)
            if limits.cpu.burstMicros is not None:
                files["cpu.max.burst"] = str(limits.cpu.burstMicros)
            if limits.cpu.cpusetCpus:
                files["cpuset.cpus"] = limits.cpu.cpusetCpus
            if limits.cpu.cpusetMems:
                files["cpuset.mems"] = limits.cpu.cpusetMems
        if limits.memory is not None:
            mem = limits.memory
            if mem.highBytes is not None:
                files["memory.high"] = str(mem.highBytes)
            if mem.maxBytes is not None:
                files["memory.max"] = str(mem.maxBytes)
                # Disable swap: swap.max MUST equal max (ADR-002 invariant).
                files["memory.swap.max"] = str(mem.swapMaxBytes or mem.maxBytes)
            if mem.lowBytes is not None:
                files["memory.low"] = str(mem.lowBytes)
            if mem.minBytes is not None:
                files["memory.min"] = str(mem.minBytes)
            files["memory.oom.group"] = "1" if mem.oomGroup else "0"
        if limits.diskIo is not None:
            files["io.weight"] = f"default {limits.diskIo.weight}"
            if limits.diskIo.max:
                entries = []
                for dev in limits.diskIo.max:
                    parts = [dev.device]
                    for key in ("rbps", "wbps", "riops", "wiops"):
                        value = getattr(dev, key)
                        if value is not None:
                            parts.append(f"{key}={value}")
                    entries.append(" ".join(parts))
                files["io.max"] = "\n".join(entries)
        if limits.pids is not None and limits.pids.max is not None:
            files["pids.max"] = str(limits.pids.max)
        return files

    def _apply_delta(self, current: ResourceLimits, delta: ResourceLimitsDelta) -> ResourceLimits:
        data = current.model_dump(exclude_none=True)
        if delta.cpuQuotaMicrosDelta is not None:
            cpu = data.setdefault("cpu", {"periodMicros": 100_000, "weight": 100})
            base = cpu.get("quotaMicros")
            base = 0 if base in (None, -1) else base
            cpu["quotaMicros"] = max(-1, base + delta.cpuQuotaMicrosDelta)
        if delta.memoryMaxBytesDelta is not None or delta.memoryHighBytesDelta is not None:
            memory = data.setdefault("memory", {})
            if memory.get("maxBytes") is not None:
                memory["maxBytes"] = max(0, memory["maxBytes"] + (delta.memoryMaxBytesDelta or 0))
                memory["swapMaxBytes"] = memory["maxBytes"]
            if memory.get("highBytes") is not None and delta.memoryHighBytesDelta is not None:
                memory["highBytes"] = max(0, memory["highBytes"] + delta.memoryHighBytesDelta)
        if delta.pidsMaxDelta is not None:
            pids = data.setdefault("pids", {"max": 256})
            pids["max"] = max(1, pids.get("max", 256) + delta.pidsMaxDelta)
        if delta.networkEgressBpsDelta is not None:
            network = data.setdefault("network", {"qdisc": "htb"})
            base = network.get("egressBps") or 0
            network["egressBps"] = max(0, base + delta.networkEgressBpsDelta)
        return ResourceLimits.model_validate(data)

    # -- hierarchical quotas -------------------------------------------------- #
    def check_within_parent(self, limits: ResourceLimits) -> None:
        """Validate a single agent's limits against the parent absolute budget."""
        if self.parent_budget is None:
            return
        budget = self.parent_budget
        if limits.memory and limits.memory.maxBytes is not None:
            cap = budget.memory.maxBytes if budget.memory else None
            if cap is not None and limits.memory.maxBytes > cap:
                raise QuotaExceededError(
                    f"memory.max {limits.memory.maxBytes} exceeds parent budget {cap}"
                )
        if limits.cpu and limits.cpu.quotaMicros not in (None, -1):
            cap_cpu = budget.cpu.quotaMicros if budget.cpu else None
            if cap_cpu not in (None, -1) and limits.cpu.quotaMicros > cap_cpu:
                raise QuotaExceededError(
                    f"cpu quota {limits.cpu.quotaMicros} exceeds parent budget {cap_cpu}"
                )
        if limits.pids and limits.pids.max is not None:
            cap_pids = budget.pids.max if budget.pids else None
            if cap_pids is not None and limits.pids.max > cap_pids:
                raise QuotaExceededError(
                    f"pids.max {limits.pids.max} exceeds parent budget {cap_pids}"
                )

    def enforce_hierarchical(self, children: dict[str, ResourceLimits]) -> None:
        """Ensure the aggregate of all child limits fits the parent budget."""
        if self.parent_budget is None:
            return
        budget = self.parent_budget
        total_mem = sum(c.memory.maxBytes or 0 for c in children.values() if c.memory is not None)
        total_cpu = sum(
            c.cpu.quotaMicros or 0
            for c in children.values()
            if c.cpu is not None and c.cpu.quotaMicros not in (None, -1)
        )
        total_pids = sum(c.pids.max or 0 for c in children.values() if c.pids is not None)
        mem_cap = budget.memory.maxBytes if budget.memory else None
        if mem_cap is not None and total_mem > mem_cap:
            raise QuotaExceededError(f"aggregate memory.max {total_mem} exceeds parent {mem_cap}")
        cpu_cap = budget.cpu.quotaMicros if budget.cpu else None
        if cpu_cap not in (None, -1) and total_cpu > cpu_cap:
            raise QuotaExceededError(f"aggregate cpu quota {total_cpu} exceeds parent {cpu_cap}")
        pids_cap = budget.pids.max if budget.pids else None
        if pids_cap is not None and total_pids > pids_cap:
            raise QuotaExceededError(f"aggregate pids.max {total_pids} exceeds parent {pids_cap}")

    # -- telemetry ------------------------------------------------------------ #
    def read_usage(self, agent_id: str, *, now: float | None = None) -> ResourceUsage:
        """Read current usage for an agent's cgroup."""
        path = self.agent_path(agent_id)
        if not path.is_dir():
            raise UnknownAgentError(f"agent {agent_id!r} has no cgroup")
        stamp = time.monotonic() if now is None else now

        cpu = CpuUsage()
        if (path / "cpu.stat").exists():
            usage_usec, _, throttled_usec = parse_cpu_stat(self._read(path / "cpu.stat"))
            cpu = CpuUsage(
                usageMicrosPerSec=self._rate(self._cpu_rates, agent_id, float(usage_usec), stamp),
                throttledSecs=throttled_usec / 1_000_000,
            )

        memory = MemoryUsage()
        if (path / "memory.current").exists():
            memory = MemoryUsage(
                currentBytes=_read_int(path / "memory.current"),
                peakBytes=_read_int(path / "memory.peak") if (path / "memory.peak").exists() else 0,
                events=parse_memory_events(self._read(path / "memory.events"))
                if (path / "memory.events").exists()
                else MemoryEvents(),
            )

        disk = DiskIoUsage()
        if (path / "io.stat").exists():
            stats = parse_io_stat(self._read(path / "io.stat"))
            total_read = float(sum(v[0] for v in stats.values()))
            total_write = float(sum(v[1] for v in stats.values()))
            disk = DiskIoUsage(
                readBytesPerSec=self._rate(self._io_rates, f"{agent_id}:r", total_read, stamp),
                writeBytesPerSec=self._rate(self._io_rates, f"{agent_id}:w", total_write, stamp),
            )

        pids = PidUsage()
        if (path / "pids.current").exists():
            pids = PidUsage(
                current=_read_int(path / "pids.current"),
                max=_read_int(path / "pids.max") if (path / "pids.max").exists() else 0,
            )

        return ResourceUsage(cpu=cpu, memory=memory, diskIo=disk, pids=pids, network=NetworkUsage())

    def read_pressure(self, agent_id: str) -> PressureReport:
        """Read PSI pressure samples for the agent cgroup."""
        path = self.agent_path(agent_id)
        if not path.is_dir():
            raise UnknownAgentError(f"agent {agent_id!r} has no cgroup")
        report = PressureReport()
        for attr, filename in (
            ("cpu", "cpu.pressure"),
            ("memory", "memory.pressure"),
            ("io", "io.pressure"),
        ):
            file = path / filename
            if file.exists():
                setattr(report, attr, parse_pressure(self._read(file)))
        return report

    def _rate(self, store: dict[str, _RateState], key: str, value: float, now: float) -> float:
        previous = store.get(key)
        store[key] = _RateState(sampled_at=now, value=value)
        if previous is None or now <= previous.sampled_at:
            return 0.0
        return max(0.0, (value - previous.value) / (now - previous.sampled_at))

    # -- io helpers ----------------------------------------------------------- #
    def _read(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def _read_optional(self, path: Path) -> str | None:
        if not path.exists():
            return None
        return self._read(path).strip()

    def _write(self, path: Path, value: str) -> None:
        try:
            path.write_text(value, encoding="utf-8")
        except OSError as exc:  # pragma: no cover - depends on host cgroupfs
            raise ResourceManagerError(f"failed to write {path}: {exc}") from exc

    def remove(self, agent_id: str) -> None:
        """Remove an agent cgroup directory (best effort, idempotent)."""
        path = self.agent_path(agent_id)
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                # Synthetic trees carry real files; real cgroupfs dirs are empty
                # of regular files and rmdir above succeeds.
                shutil.rmtree(path, ignore_errors=True)
                if path.exists():  # pragma: no cover - kernel cgroupfs busy
                    raise ResourceManagerError(f"failed to remove cgroup {path}") from None
        self._applied.pop(agent_id, None)
