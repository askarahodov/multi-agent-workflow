"""Runtime configuration for the GitHub <-> Kanban sync (no secrets in code).

Everything is resolved from the environment with safe defaults that match this
repository. The GitHub token is *never* stored in the ledger, logged, or written
to a commit: it is read from ``GKS_GITHUB_TOKEN`` / ``GITHUB_TOKEN`` /
``GH_TOKEN`` or, as a last resort, shelled out to ``gh auth token``.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_REPO = "askarahodov/multi-agent-workflow"
DEFAULT_BOARD = "me"


def _kanban_home() -> Path:
    override = os.environ.get("GKS_KANBAN_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".hermes" / "kanban" / "boards" / DEFAULT_BOARD


def resolve_token() -> Optional[str]:
    """Return a GitHub token without ever logging it.

    Order: explicit env vars, then the ``gh`` CLI keyring. Returns ``None`` when
    no credential is available so callers can degrade to ``gh api``.
    """
    for var in ("GKS_GITHUB_TOKEN", "GITHUB_TOKEN", "GH_TOKEN"):
        value = os.environ.get(var)
        if value:
            return value.strip()
    try:
        proc = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return None


@dataclass(frozen=True)
class Settings:
    """Immutable settings bundle."""

    repo: str = DEFAULT_REPO
    board: str = DEFAULT_BOARD
    coord_db: Path = field(default_factory=lambda: _kanban_home() / "coordination-sync.db")
    kanban_db: Path = field(default_factory=lambda: _kanban_home() / "kanban.db")
    api_base: str = "https://api.github.com"
    author: str = "github-kanban-sync"
    # Polling / retry tuning.
    max_retries: int = 3
    backoff_base: float = 1.0
    backoff_cap: float = 30.0
    request_timeout: float = 30.0
    # Publish rate limiting: minimum seconds between comments on one Issue.
    publish_min_interval: float = 5.0
    # Known coordination-log issues (SPEC §5.6): #182 file/migration, #44 governance.
    migration_issue: int = 182
    governance_issue: int = 44

    @classmethod
    def from_env(cls, repo: Optional[str] = None, board: Optional[str] = None,
                 coord_db: Optional[str] = None, kanban_db: Optional[str] = None) -> "Settings":
        return cls(
            repo=repo or os.environ.get("GKS_REPO", DEFAULT_REPO),
            board=board or os.environ.get("GKS_BOARD", DEFAULT_BOARD),
            coord_db=Path(coord_db).expanduser()
            if coord_db
            else Path(os.environ.get("GKS_COORD_DB", "")) if os.environ.get("GKS_COORD_DB")
            else _kanban_home() / "coordination-sync.db",
            kanban_db=Path(kanban_db).expanduser()
            if kanban_db
            else Path(os.environ.get("GKS_KANBAN_DB", "")) if os.environ.get("GKS_KANBAN_DB")
            else _kanban_home() / "kanban.db",
        )
