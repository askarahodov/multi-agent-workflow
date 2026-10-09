"""Configuration for the quality-gates subsystem.

All values read from the environment with safe defaults so the package runs in
tests without any external setup. The same settings object is used by the gate
executors, the evidence store and the pipeline orchestrator.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Built-in, well-known gates. Names are stable identifiers used both by the
# registry and by pipeline definitions in config.
BUILTIN_GATES = ("tester", "reviewer", "security", "release_prep")


def _as_path(value: str | None, default: str) -> Path:
    return Path(value) if value else Path(default)


@dataclass(frozen=True)
class Settings:
    """Resolved settings for one quality-gates process."""

    evidence_root: Path = field(
        default_factory=lambda: _as_path(
            os.environ.get("QG_EVIDENCE_ROOT"), "./evidence_store"
        )
    )
    artifact_root: Path = field(
        default_factory=lambda: _as_path(
            os.environ.get("QG_ARTIFACT_ROOT"), "./release_artifacts"
        )
    )
    # Comma separated gate names that the pipeline treats as mandatory for any
    # transition; if unset defaults to the full BUILTIN_GATES set.
    required_gates: tuple[str, ...] = field(default_factory=lambda: _default_gates())

    def ensure_dirs(self) -> None:
        """Create evidence/artifact roots (idempotent)."""
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)


def _default_gates() -> tuple[str, ...]:
    raw = os.environ.get("QG_REQUIRED_GATES")
    if raw:
        return tuple(g.strip() for g in raw.split(",") if g.strip())
    return BUILTIN_GATES
