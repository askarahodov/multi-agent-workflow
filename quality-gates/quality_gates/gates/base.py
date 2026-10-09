"""Gate abstraction and shared result types.

A *gate* is a deterministic evaluation of a workspace against a set of rules. It
produces ``Findings`` (evidence) and an overall pass/fail verdict. Concrete gates
(Tester, Reviewer, Security, ReleasePrepHook) implement :class:`Gate` and are
registered in :data:`GATE_REGISTRY`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Finding:
    """A single piece of evidence produced by a gate."""

    category: str  # unit / integration / lint / style / arch / dep / secret / release
    key: str
    passed: bool
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)

    def as_evidence(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "key": self.key,
            "passed": self.passed,
            "summary": self.summary,
            "detail": self.detail,
        }


@dataclass
class GateResult:
    """Outcome of running one gate."""

    gate: str
    passed: bool
    summary: str
    findings: list[Finding] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def categories(self) -> list[str]:
        return sorted({f.category for f in self.findings})


class Gate(Protocol):
    """Protocol every gate executor implements."""

    name: str
    description: str

    def execute(self, workspace: str, context: dict[str, Any] | None = None) -> GateResult:
        """Run the gate against ``workspace`` and return a verdict + findings."""
        ...


class Registry:
    """Name -> Gate class mapping plus pipeline ordering."""

    def __init__(self) -> None:
        self._gates: dict[str, type[Gate]] = {}

    def register(self, gate: type[Gate]) -> type[Gate]:
        self._gates[gate.name] = gate
        return gate

    def get(self, name: str) -> type[Gate]:
        if name not in self._gates:
            raise KeyError(f"unknown gate: {name}")
        return self._gates[name]

    def names(self) -> list[str]:
        return list(self._gates.keys())


GATE_REGISTRY: Registry = Registry()
