"""Runtime configuration for the orchestration server.

Configuration is read from environment variables so the same binary can run
against SQLite (default, zero-infrastructure) or PostgreSQL (production,
``postgresql+asyncpg://...``). Defaults keep the server self-contained and
testable in any environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


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


def get_settings() -> Settings:
    return Settings()
