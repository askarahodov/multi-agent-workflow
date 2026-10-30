"""Hardened runtime components for the Harbor-Transfer-Portal agent sandbox.

Implements the interfaces specified by the P8.3 architecture package
(t_72478f3c):

* :mod:`runtime.container_runtime` — container runtime abstraction + isolation backends
* :mod:`runtime.resource_manager` — cgroup v2 resource management (ADR-002)
* :mod:`runtime.workspace_manager` — atomic workspace lifecycle (ADR-004)
* :mod:`runtime.health` / :mod:`runtime.metrics` — health probes and observability (ADR-005)
* :mod:`runtime.circuit_breaker` — resilience: circuit breaker, bulkheads, degradation (ADR-003)
* :mod:`runtime.api` — FastAPI control plane
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
