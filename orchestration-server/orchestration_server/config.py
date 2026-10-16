"""Runtime configuration for the orchestration server.

Configuration is read from environment variables so the same binary can run
against SQLite (default, zero-infrastructure) or PostgreSQL (production,
``postgresql+asyncpg://...``). Defaults keep the server self-contained and
testable in any environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Settings:
    # Database URL. Defaults to a local SQLite file so the server runs with no
    # external infrastructure. Production uses PostgreSQL via asyncpg:
    #   postgresql+asyncpg://user:pass@host:5432/orchestration
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "ORCH_DATABASE_URL",
            "sqlite+aiosqlite:///./orchestration.db",
        )
    )

    api_prefix: str = field(
        default_factory=lambda: os.environ.get("ORCH_API_PREFIX", "/api/v1")
    )

    # Default retry policy applied to workflow runs that do not specify one.
    default_max_attempts: int = field(
        default_factory=lambda: int(os.environ.get("ORCH_DEFAULT_MAX_ATTEMPTS", "3"))
    )
    default_base_delay_seconds: float = field(
        default_factory=lambda: float(
            os.environ.get("ORCH_DEFAULT_BASE_DELAY_SECONDS", "1.0")
        )
    )
    default_max_delay_seconds: float = field(
        default_factory=lambda: float(
            os.environ.get("ORCH_DEFAULT_MAX_DELAY_SECONDS", "300.0")
        )
    )
    default_backoff_multiplier: float = field(
        default_factory=lambda: float(
            os.environ.get("ORCH_DEFAULT_BACKOFF_MULTIPLIER", "2.0")
        )
    )

    # When true the server runs its durable-recovery pass on startup (see
    # OrchestrationEngine.recover). Disabled in some unit tests.
    recover_on_startup: bool = field(
        default_factory=lambda: os.environ.get("ORCH_RECOVER_ON_STARTUP", "1") == "1"
    )

    # Opt-in server-issued attempt credentials. Disabled for existing workers
    # until they support secure token storage and renewal. Enabling this does
    # not by itself fence remote file/shell/network side effects.
    attempt_lease_enabled: bool = field(
        default_factory=lambda: os.environ.get("ORCH_ATTEMPT_LEASE_ENABLED", "0") == "1"
    )
    attempt_lease_ttl_seconds: int = field(
        default_factory=lambda: int(os.environ.get("ORCH_ATTEMPT_LEASE_TTL_SECONDS", "60"))
    )

    # Optional fail-closed independent QA. Keep this dedicated secret outside
    # native worker containers and task workspaces. Requires attempt leases.
    qa_attestation_key: Optional[str] = field(
        default_factory=lambda: os.environ.get("ORCH_QA_ATTESTATION_KEY")
    )

    # Trusted, operator-managed evidence directory (Issue #38). Disabled by
    # default. Confirmed reconciliation requires this setting and matching
    # local evidence bytes; no arbitrary filesystem references are accepted.
    reconciliation_evidence_root: Optional[str] = field(
        default_factory=lambda: os.environ.get("ORCH_RECONCILIATION_EVIDENCE_ROOT")
    )

    # Optional READ-ONLY local view of the worker's SQLite claim ledger.
    # This must be a private, operator-owned DB outside agent workspaces.
    # Does not work across hosts without a separately authenticated bridge.
    reconciliation_tool_ledger_path: Optional[str] = field(
        default_factory=lambda: os.environ.get("ORCH_RECONCILIATION_TOOL_LEDGER_PATH")
    )

    # TLS certificate/key/CA paths (SEC-002). When cert_file and key_file are
    # both set, the server is considered TLS-enabled: uvicorn is launched with
    # ssl_certfile/ssl_keyfile and the shared HSTS + HTTP->HTTPS middleware is
    # active. Env names use the ORCH_ prefix to match the other settings.
    cert_file: Optional[str] = field(
        default_factory=lambda: os.environ.get("ORCH_TLS_CERT_FILE")
    )
    key_file: Optional[str] = field(
        default_factory=lambda: os.environ.get("ORCH_TLS_KEY_FILE")
    )
    ca_file: Optional[str] = field(
        default_factory=lambda: os.environ.get("ORCH_TLS_CA_FILE")
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


def get_settings() -> Settings:
    return Settings()
