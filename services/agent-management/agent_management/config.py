"""Runtime configuration for the agent-management subsystem.

Configuration is read from environment variables. Defaults keep the subsystem
self-contained and fully testable against a local SQLite file; production uses
PostgreSQL via ``postgresql+asyncpg://...``. When deployed alongside the
orchestration server the two subsystems share the same database URL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Settings:
    # Database URL. Defaults to a local SQLite file so the subsystem runs with
    # no external infrastructure. Production: postgresql+asyncpg://...
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "AGENT_MGMT_DATABASE_URL", "sqlite+aiosqlite:///./agent_management.db"
        )
    )

    api_prefix: str = field(
        default_factory=lambda: os.environ.get("AGENT_MGMT_API_PREFIX", "/api/v1")
    )

    # TLS certificate/key/CA paths (SEC-002). When cert_file and key_file are
    # both set the service is TLS-enabled: uvicorn serves HTTPS and the shared
    # HSTS + HTTP->HTTPS middleware is active. Env names use AGENT_MGMT_ prefix.
    cert_file: Optional[str] = field(
        default_factory=lambda: os.environ.get("AGENT_MGMT_TLS_CERT_FILE")
    )
    key_file: Optional[str] = field(
        default_factory=lambda: os.environ.get("AGENT_MGMT_TLS_KEY_FILE")
    )
    ca_file: Optional[str] = field(
        default_factory=lambda: os.environ.get("AGENT_MGMT_TLS_CA_FILE")
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