"""Health probes (ADR-005).

Implements liveness / readiness / startup probe evaluation for the control
plane and for individual agents. A probe is any zero-argument callable
returning a truthy value; ``None`` means "no probe configured" and reports
``unknown``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from runtime.models import HealthProbeResult, HealthStatus, utcnow

ProbeFn = Callable[[], bool]

PROBE_NAMES: tuple[str, ...] = ("liveness", "readiness", "startup")


@dataclass
class Probes:
    """The three Kubernetes-style probes for one subject."""

    liveness: ProbeFn | None = None
    readiness: ProbeFn | None = None
    startup: ProbeFn | None = None

    def as_dict(self) -> dict[str, ProbeFn | None]:
        return {"liveness": self.liveness, "readiness": self.readiness, "startup": self.startup}


def _evaluate(probe: ProbeFn | None) -> HealthProbeResult:
    if probe is None:
        return HealthProbeResult.UNKNOWN
    try:
        return HealthProbeResult.PASS if probe() else HealthProbeResult.FAIL
    except Exception:  # noqa: BLE001 - a probe error is a failed probe
        return HealthProbeResult.FAIL


@dataclass
class HealthChecker:
    """Evaluate the probes for a subject and track the last transition."""

    subject: str
    probes: Probes = field(default_factory=Probes)
    _last: HealthStatus | None = None

    def check(self) -> HealthStatus:
        results = {name: _evaluate(fn) for name, fn in self.probes.as_dict().items()}
        status = HealthStatus(
            liveness=results["liveness"],
            readiness=results["readiness"],
            startup=results["startup"],
            lastTransition=self._last.lastTransition if self._last else None,
            detail=self._detail(results),
        )
        if self._changed(results):
            status.lastTransition = utcnow()
        self._last = status
        return status

    def _changed(self, results: dict[str, HealthProbeResult]) -> bool:
        if self._last is None:
            return True
        return any(getattr(self._last, name) != value for name, value in results.items())

    @staticmethod
    def _detail(results: dict[str, HealthProbeResult]) -> str | None:
        failed = [name for name, value in results.items() if value == HealthProbeResult.FAIL]
        return f"failing probes: {', '.join(failed)}" if failed else None

    def ready(self) -> bool:
        """Readiness gate used to decide whether the subject serves traffic."""
        return self.check().readiness == HealthProbeResult.PASS


class ControlPlaneHealth:
    """Health checks for the runtime control plane itself."""

    def __init__(self) -> None:
        self.started = True
        self.dependencies: dict[str, Callable[[], bool]] = {}

    def register_dependency(self, name: str, check: Callable[[], bool]) -> None:
        self.dependencies[name] = check

    def liveness(self) -> bool:
        return self.started

    def startup(self) -> bool:
        return self.started

    def readiness(self) -> bool:
        return all(_evaluate(fn) == HealthProbeResult.PASS for fn in self.dependencies.values())

    def as_probes(self) -> Probes:
        return Probes(liveness=self.liveness, readiness=self.readiness, startup=self.startup)


def aggregate_status(states: list[HealthProbeResult]) -> HealthProbeResult:
    """Combine several probe results conservatively (fail > unknown > pass)."""
    if any(s == HealthProbeResult.FAIL for s in states):
        return HealthProbeResult.FAIL
    if any(s == HealthProbeResult.UNKNOWN for s in states):
        return HealthProbeResult.UNKNOWN
    return HealthProbeResult.PASS


def probe_result(value: bool | Literal["pass", "fail", "unknown"]) -> HealthProbeResult:
    if isinstance(value, bool):
        return HealthProbeResult.PASS if value else HealthProbeResult.FAIL
    return HealthProbeResult(value)
