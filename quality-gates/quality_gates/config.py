"""Configuration for the quality-gates subsystem.

All values read from the environment with safe defaults so the package runs in
tests without any external setup. The same settings object is used by the gate
executors, the evidence store and the pipeline orchestrator.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

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

    # Dedicated operator-only QA receipt signing credential. Never expose it
    # to an AI worker, model, or the task workspace. Disabled by default.
    qa_attestation_key: Optional[str] = field(
        default_factory=lambda: os.environ.get("QG_QA_ATTESTATION_KEY")
    )

    # TLS certificate/key/CA paths (SEC-002). When cert_file and key_file are
    # both set the service is TLS-enabled: uvicorn serves HTTPS and the shared
    # HSTS + HTTP->HTTPS middleware is active. Env names use QG_ prefix.
    cert_file: Optional[str] = field(
        default_factory=lambda: os.environ.get("QG_TLS_CERT_FILE")
    )
    key_file: Optional[str] = field(
        default_factory=lambda: os.environ.get("QG_TLS_KEY_FILE")
    )
    ca_file: Optional[str] = field(
        default_factory=lambda: os.environ.get("QG_TLS_CA_FILE")
    )

    @property
    def tls_enabled(self) -> bool:
        """True when both a cert and a key file are configured."""
        return bool(self.cert_file and self.key_file)

    @property
    def ssl_config(self) -> dict[str, str]:
        """Keyword-args for uvicorn to serve HTTPS (empty when TLS off)."""
        if not self.tls_enabled:
            return {}
        assert self.cert_file and self.key_file
        cfg: dict[str, str] = {
            "ssl_certfile": self.cert_file,
            "ssl_keyfile": self.key_file,
        }
        if self.ca_file:
            cfg["ssl_ca_certs"] = self.ca_file
        return cfg

    def ensure_dirs(self) -> None:
        """Create evidence/artifact roots (idempotent)."""
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        self.artifact_root.mkdir(parents=True, exist_ok=True)


def _default_gates() -> tuple[str, ...]:
    raw = os.environ.get("QG_REQUIRED_GATES")
    if raw:
        return tuple(g.strip() for g in raw.split(",") if g.strip())
    return BUILTIN_GATES
