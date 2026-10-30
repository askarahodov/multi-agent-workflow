"""Native agent execution engine and autonomy framework.

Public surface (import from ``agent_runtime``)::

    from agent_runtime import AgentRuntime, TaskGraph, ProfileManager, ...

Modules
-------
* :mod:`agent_runtime.errors`        — error taxonomy (ADR-104)
* :mod:`agent_runtime.permissions`   — deny-by-default permission evaluation (ADR-103/108)
* :mod:`agent_runtime.spec`          — AgentSpec resolution (ADR-108)
* :mod:`agent_runtime.workspace`     — isolated workspace provisioning (ADR-107/109)
* :mod:`agent_runtime.graph`         — task DAG, claimability, result passing (ADR-109)
* :mod:`agent_runtime.retry`         — retry/timeout/circuit breaker/checkpoints (ADR-104)
* :mod:`agent_runtime.limits`        — budgets, resource quotas, quality gates (ADR-105)
* :mod:`agent_runtime.observability` — structured logs, events, metrics (ADR-106)
* :mod:`agent_runtime.runner`        — the execution engine tying it together
"""

from __future__ import annotations

from .errors import (
    ErrorKind,
    ErrorRecord,
    PlatformError,
    budget_exhausted,
    claim_denied,
    config_error,
    gate_failed,
    gate_unavailable,
    is_retryable,
    isolation_unavailable,
    policy_denied,
    validation_error,
)
from .graph import (
    MAW_UPSTREAM_KEY,
    MAX_DEPENDENCIES,
    TaskGraph,
    TaskNode,
    TaskStatus,
)
from .limits import (
    DEFAULT_MINIMAL_LIMITS,
    TIER_LIMITS,
    Budget,
    BudgetCheck,
    BudgetState,
    GateConfig,
    GateResult,
    GateRunner,
    GateStatus,
    ResourceLimits,
    calculate_cost,
    limits_for_tier,
)
from .observability import (
    Event,
    EventBus,
    LogRecord,
    MetricsRegistry,
    StructuredLogger,
    correlation,
    sanitize_context,
)
from .permissions import (
    ACTION_CAPABILITY,
    VALID_ACTIONS,
    PermissionDecision,
    PermissionEvaluator,
    ToolPolicy,
    normalize_permissions,
    policy_subsumes,
)
from .retry import (
    AgentRunState,
    CheckpointStore,
    CircuitBreaker,
    CircuitState,
    RunStatus,
    TurnState,
    restore_budget,
    resume_point,
    resume_run,
    retry_async,
    with_timeout,
)
from .runner import (
    AgentExecutor,
    AgentRuntime,
    GraphRunResult,
    NodeInvocation,
    NodeOutcome,
    NodeResult,
    ToolExecutor,
)
from .server_bridge import (
    BridgeReport,
    RunBridge,
    ServerRunClient,
    failure_reason,
    graph_from_run_spec,
    single_task_graph,
    submission_payload,
)
from .spec import (
    AgentDefinition,
    AgentInstance,
    AgentSpec,
    ConfigStore,
    ContextPolicy,
    ModelProfile,
    ProfileManager,
    RetryPolicy,
    Role,
    build_model_context,
    compute_spec_version,
)
from .workspace import (
    Workspace,
    WorkspaceKind,
    WorkspaceManager,
    WorkspaceStatus,
)

__all__ = [
    # errors
    "ErrorKind",
    "ErrorRecord",
    "PlatformError",
    "budget_exhausted",
    "claim_denied",
    "config_error",
    "gate_failed",
    "gate_unavailable",
    "is_retryable",
    "isolation_unavailable",
    "policy_denied",
    "validation_error",
    # graph
    "MAW_UPSTREAM_KEY",
    "MAX_DEPENDENCIES",
    "TaskGraph",
    "TaskNode",
    "TaskStatus",
    # limits
    "DEFAULT_MINIMAL_LIMITS",
    "TIER_LIMITS",
    "Budget",
    "BudgetCheck",
    "BudgetState",
    "GateConfig",
    "GateResult",
    "GateRunner",
    "GateStatus",
    "ResourceLimits",
    "calculate_cost",
    "limits_for_tier",
    # observability
    "Event",
    "EventBus",
    "LogRecord",
    "MetricsRegistry",
    "StructuredLogger",
    "correlation",
    "sanitize_context",
    # permissions
    "ACTION_CAPABILITY",
    "VALID_ACTIONS",
    "PermissionDecision",
    "PermissionEvaluator",
    "ToolPolicy",
    "normalize_permissions",
    "policy_subsumes",
    # retry
    "AgentRunState",
    "CheckpointStore",
    "CircuitBreaker",
    "CircuitState",
    "RunStatus",
    "TurnState",
    "restore_budget",
    "resume_point",
    "resume_run",
    "retry_async",
    "with_timeout",
    # runner
    "AgentExecutor",
    "AgentRuntime",
    "GraphRunResult",
    "NodeInvocation",
    "NodeOutcome",
    "NodeResult",
    "ToolExecutor",
    # server bridge
    "ServerRunClient",
    "RunBridge",
    "BridgeReport",
    "graph_from_run_spec",
    "single_task_graph",
    "submission_payload",
    "failure_reason",
    # spec
    "AgentDefinition",
    "AgentInstance",
    "AgentSpec",
    "ConfigStore",
    "ContextPolicy",
    "ModelProfile",
    "ProfileManager",
    "RetryPolicy",
    "Role",
    "build_model_context",
    "compute_spec_version",
    # workspace
    "Workspace",
    "WorkspaceKind",
    "WorkspaceManager",
    "WorkspaceStatus",
]

__version__ = "0.1.0"
