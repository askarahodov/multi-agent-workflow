"""Shared data contracts mirroring the control-plane OpenAPI and quota JSON Schema.

These Pydantic models are the single source of truth for the field names and
enums used across the isolation layer, Resource Manager, Workspace Manager,
resilience layer, observability and the API. Field names match
``api/agent-runtime-openapi.yaml`` and ``schemas/resource-quota.schema.json``
exactly (ADR-011 §9 cross-file consistency requirement).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utcnow() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class IsolationTier(StrEnum):
    """Isolation tier selected per workload (spec §3.1, ADR-011)."""

    BASELINE_RUNC = "baseline-runc"
    GVISOR_RUNSC = "gvisor-runsc"
    KATA_FC = "kata-fc"
    GVISOR_NSJAIL = "gvisor-nsjail"


class WorkloadClass(StrEnum):
    """Workload trust label used by the runtime selector (spec §3.3)."""

    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"
    ADVERSARIAL = "adversarial"


class AgentState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    DEGRADED = "degraded"
    FAILED = "failed"
    TERMINATED = "terminated"


class DegradationMode(StrEnum):
    FULL = "full"
    THROTTLED = "throttled"
    READ_ONLY = "read_only"
    PAUSED = "paused"
    TERMINATED = "terminated"


class CircuitBreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ResourceClass(StrEnum):
    CPU = "cpu"
    MEMORY = "memory"
    DISK_IO = "disk_io"
    NETWORK = "network"
    PIDS = "pids"


class HealthProbeResult(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# --------------------------------------------------------------------------- #
# Resource limits (spec §4 / resource-quota.schema.json)
# --------------------------------------------------------------------------- #
class CpuLimits(_Base):
    quotaMicros: int | None = Field(default=None, ge=-1)
    periodMicros: int = Field(default=100_000, ge=1_000, le=1_000_000)
    weight: int = Field(default=100, ge=1, le=10_000)
    burstMicros: int | None = Field(default=None, ge=0)
    cpusetCpus: str | None = None
    cpusetMems: str | None = None


class MemoryLimits(_Base):
    highBytes: int | None = Field(default=None, ge=0)
    maxBytes: int | None = Field(default=None, ge=0)
    swapMaxBytes: int | None = Field(default=None, ge=0)
    lowBytes: int | None = Field(default=None, ge=0)
    minBytes: int | None = Field(default=None, ge=0)
    oomGroup: bool = True

    @model_validator(mode="after")
    def _check_invariants(self) -> MemoryLimits:
        if (
            self.highBytes is not None
            and self.maxBytes is not None
            and self.highBytes > self.maxBytes
        ):
            raise ValueError("memory.highBytes must be <= memory.maxBytes")
        if (
            self.swapMaxBytes is not None
            and self.maxBytes is not None
            and self.swapMaxBytes != self.maxBytes
        ):
            raise ValueError("memory.swapMaxBytes must equal memory.maxBytes to disable swap")
        return self


class DiskIoDeviceLimit(_Base):
    device: str = Field(pattern=r"^\d+:\d+$")
    rbps: int | None = Field(default=None, ge=0)
    wbps: int | None = Field(default=None, ge=0)
    riops: int | None = Field(default=None, ge=0)
    wiops: int | None = Field(default=None, ge=0)


class DiskIoLimits(_Base):
    max: list[DiskIoDeviceLimit] | None = None
    weight: int = Field(default=100, ge=1, le=10_000)


class NetworkLimits(_Base):
    egressBps: int | None = Field(default=None, ge=0)
    ingressBps: int | None = Field(default=None, ge=0)
    qdisc: str = Field(default="htb", pattern="^(tbf|htb|none)$")


class PidLimits(_Base):
    max: int | None = Field(default=None, ge=1)


class ResourceLimits(_Base):
    """cgroup v2 limits. Soft limits throttle, hard limits enforce."""

    cpu: CpuLimits | None = None
    memory: MemoryLimits | None = None
    diskIo: DiskIoLimits | None = None
    network: NetworkLimits | None = None
    pids: PidLimits | None = None


class BudgetLimits(_Base):
    """Aggregate ceilings applied to the parent cgroup (no relative fields)."""

    cpu: CpuLimits | None = None
    memory: MemoryLimits | None = None
    diskIo: DiskIoLimits | None = None
    network: NetworkLimits | None = None
    pids: PidLimits | None = None


class ResourceLimitsDelta(_Base):
    """Relative adjustment used by PATCH /agents/{id}/limits."""

    cpuQuotaMicrosDelta: int | None = None
    memoryMaxBytesDelta: int | None = None
    memoryHighBytesDelta: int | None = None
    pidsMaxDelta: int | None = None
    diskWbpsDelta: int | None = None
    networkEgressBpsDelta: int | None = None


# --------------------------------------------------------------------------- #
# Quota configuration (resource-quota.schema.json)
# --------------------------------------------------------------------------- #
class AgentQuota(_Base):
    cls: str = Field(alias="class")
    overrides: ResourceLimits | None = None


class ResourceQuotaConfig(_Base):
    schemaVersion: str = "1.0.0"
    parentBudget: BudgetLimits
    resourceClasses: dict[str, ResourceLimits]
    agents: dict[str, AgentQuota] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _classes_nonempty(self) -> ResourceQuotaConfig:
        if not self.resourceClasses:
            raise ValueError("resourceClasses must define at least one class")
        for agent_id, quota in self.agents.items():
            if quota.cls not in self.resourceClasses:
                raise ValueError(f"agent {agent_id!r} references unknown class {quota.cls!r}")
        return self


# --------------------------------------------------------------------------- #
# Usage / pressure / health (OpenAPI)
# --------------------------------------------------------------------------- #
class CpuUsage(_Base):
    usageMicrosPerSec: float = 0.0
    throttledSecs: float = 0.0


class MemoryEvents(_Base):
    low: int = 0
    high: int = 0
    max: int = 0
    oom: int = 0
    oomKill: int = 0


class MemoryUsage(_Base):
    currentBytes: int = 0
    peakBytes: int = 0
    events: MemoryEvents = Field(default_factory=MemoryEvents)


class DiskIoUsage(_Base):
    readBytesPerSec: float = 0.0
    writeBytesPerSec: float = 0.0


class PidUsage(_Base):
    current: int = 0
    max: int = 0


class NetworkUsage(_Base):
    rxBytesPerSec: float = 0.0
    txBytesPerSec: float = 0.0


class ResourceUsage(_Base):
    cpu: CpuUsage = Field(default_factory=CpuUsage)
    memory: MemoryUsage = Field(default_factory=MemoryUsage)
    diskIo: DiskIoUsage = Field(default_factory=DiskIoUsage)
    pids: PidUsage = Field(default_factory=PidUsage)
    network: NetworkUsage = Field(default_factory=NetworkUsage)


class PressureSample(_Base):
    avg10: float = 0.0
    avg60: float = 0.0
    avg300: float = 0.0
    totalMicros: int = 0


class PressureReport(_Base):
    cpu: PressureSample = Field(default_factory=PressureSample)
    memory: PressureSample = Field(default_factory=PressureSample)
    io: PressureSample = Field(default_factory=PressureSample)


class HealthStatus(_Base):
    liveness: HealthProbeResult = HealthProbeResult.UNKNOWN
    readiness: HealthProbeResult = HealthProbeResult.UNKNOWN
    startup: HealthProbeResult = HealthProbeResult.UNKNOWN
    lastTransition: datetime | None = None
    detail: str | None = None


# --------------------------------------------------------------------------- #
# Agents
# --------------------------------------------------------------------------- #
class WorkspaceSpec(_Base):
    id: str | None = None
    baseImage: str | None = None
    scratchBytes: int | None = Field(default=None, ge=0)
    durable: bool = False
    durabilityClass: str = Field(default="ephemeral", pattern="^(ephemeral|persistent)$")


class AgentSpec(_Base):
    id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(min_length=1, max_length=128)
    isolationTier: IsolationTier
    image: str
    resourceClass: str = "default"
    resources: ResourceLimits | None = None
    workspace: WorkspaceSpec | None = None
    seccompProfile: str = "RuntimeDefault"
    networkEgressAllowlist: list[str] = Field(default_factory=list)
    labels: dict[str, str] = Field(default_factory=dict)
    env: dict[str, str] = Field(default_factory=dict)


class Agent(_Base):
    id: str
    name: str
    state: AgentState
    isolationTier: IsolationTier
    runtimeClass: str | None = None
    degradationMode: DegradationMode = DegradationMode.FULL
    createdAt: datetime = Field(default_factory=utcnow)
    updatedAt: datetime = Field(default_factory=utcnow)
    containerId: str | None = None
    cgroupPath: str | None = None


class AgentStatus(_Base):
    agent: Agent
    circuitBreaker: CircuitBreakerState = CircuitBreakerState.CLOSED
    degradationMode: DegradationMode = DegradationMode.FULL
    health: HealthStatus | None = None
    usage: ResourceUsage | None = None
    pressure: PressureReport | None = None
    workspace: Workspace | None = None


# --------------------------------------------------------------------------- #
# Workspaces
# --------------------------------------------------------------------------- #
class WorkspaceState(StrEnum):
    CREATING = "creating"
    READY = "ready"
    DEGRADED = "degraded"
    RESTORING = "restoring"
    CLEANING = "cleaning"
    GONE = "gone"


class Workspace(_Base):
    id: str
    state: WorkspaceState
    baseImage: str | None = None
    overlayLower: str | None = None
    overlayUpper: str | None = None
    durablePath: str | None = None
    createdAt: datetime = Field(default_factory=utcnow)
    lastSnapshotId: str | None = None


class Snapshot(_Base):
    id: str
    workspaceId: str
    checksum: str
    createdAt: datetime = Field(default_factory=utcnow)
    sizeBytes: int = 0


class ProblemDetails(_Base):
    """RFC 9457 Problem Details."""

    type: str = "about:blank"
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    retryable: bool = False


class PromotedArtifact(_Base):
    path: str
    checksum: str


class ValidationCheck(_Base):
    name: str
    ok: bool
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ok": self.ok, "detail": self.detail}


# Resolve forward reference used by AgentStatus.workspace.
AgentStatus.model_rebuild()
