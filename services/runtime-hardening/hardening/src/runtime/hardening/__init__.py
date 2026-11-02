"""runtime.hardening: P8.3 hardened agent runtime components.

Subpackages implement the five P8.3 components per ADR-011:

* :mod:`isolation` — isolation tier selector + admission + sandbox wrapper
* :mod:`resource_manager` — cgroups v2 resource controller
* :mod:`workspace_manager` — atomic workspace lifecycle + reaper
* :mod:`resilience` — circuit breaker, bulkheads, retry budget, degradation
* :mod:`observability` — health probes, JSON logs, metrics, OTel hooks
* :mod:`api` — FastAPI control-plane

The reference implementation targets the t_c39cb99e technical specification
(``runtime-hardening-spec.md``) and its machine-checkable interface contracts.
"""

from runtime.hardening.models import (  # noqa: F401
    Agent,
    AgentSpec,
    AgentState,
    AgentStatus,
    BudgetLimits,
    CircuitBreakerState,
    CpuLimits,
    DegradationMode,
    HealthProbeResult,
    HealthStatus,
    IsolationTier,
    MemoryLimits,
    PressureReport,
    ProblemDetails,
    ResourceClass,
    ResourceLimits,
    ResourceLimitsDelta,
    ResourceQuotaConfig,
    Snapshot,
    WorkloadClass,
    Workspace,
    WorkspaceSpec,
    WorkspaceState,
)
