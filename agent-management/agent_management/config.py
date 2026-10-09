"""Runtime configuration for the agent-management subsystem.

Configuration is read from environment variables. Defaults keep the subsystem
self-contained and fully testable against a local SQLite file; production uses
PostgreSQL via ``postgresql+asyncpg://...``. When deployed alongside the
orchestration server the two subsystems share the same database URL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


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


def get_settings() -> Settings:
    return Settings()