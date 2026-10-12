"""Configuration: Pydantic Settings (env + YAML).

Two configuration surfaces are supported:

* :class:`RuntimeSettings` — process/infrastructure settings loaded from
  environment variables (prefix ``AGENT_RUNTIME_``) and an optional YAML file.
* :class:`ResourceQuotaConfig` — the cgroup v2 quota document validated against
  ``resource-quota.schema.json``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Optional

import yaml
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from runtime.models import ResourceQuotaConfig


class RuntimeSettings(BaseSettings):
    """Runtime infrastructure settings.

    Environment variables use the ``AGENT_RUNTIME_`` prefix; nested keys use
    ``__`` as a delimiter (e.g. ``AGENT_RUNTIME_CONTAINER__RUNTIME=podman``).
    """

    model_config = SettingsConfigDict(
        env_prefix="AGENT_RUNTIME_",
        env_nested_delimiter="__",
        extra="ignore",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    cgroup_root: Path = Path("/sys/fs/cgroup")
    cgroup_parent_slice: str = "agent.slice"
    workspace_root: Path = Path("/var/lib/agent-runtime/workspaces")
    durable_root: Path = Path("/var/lib/agent-runtime/durable")
    snapshots_root: Path = Path("/var/lib/agent-runtime/snapshots")

    container_runtime: Literal["docker", "podman"] = "docker"
    rootless: bool = True
    default_seccomp_profile: str = "RuntimeDefault"

    cleanup_grace_seconds: int = Field(default=30, ge=0, le=300)
    snapshot_checksum_algorithm: str = "sha256"
    reaper_interval_seconds: int = Field(default=60, ge=1)

    service_name: str = "agent-runtime"
    log_level: str = "INFO"

    # TLS certificate/key/CA paths (SEC-002). When cert_file and key_file are
    # both set, the service is TLS-enabled: uvicorn serves HTTPS (via
    # ssl_certfile/ssl_keyfile) and the shared HSTS + HTTP->HTTPS middleware is
    # active. Env names use the AGENT_RUNTIME_ prefix for parity with the rest
    # of this settings class.
    cert_file: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("AGENT_RUNTIME_TLS_CERT_FILE", "cert_file"),
    )
    key_file: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("AGENT_RUNTIME_TLS_KEY_FILE", "key_file"),
    )
    ca_file: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("AGENT_RUNTIME_TLS_CA_FILE", "ca_file"),
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

    @classmethod
    def from_yaml(cls, path: str | Path, **overrides: Any) -> RuntimeSettings:
        """Load settings from a YAML file, allowing explicit overrides."""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ValueError(f"settings file {path} must contain a mapping")
        data.update(overrides)
        return cls(**data)


def load_quota_config(path: str | Path) -> ResourceQuotaConfig:
    """Load and validate a resource-quota YAML document."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"quota config {path} must contain a mapping")
    return ResourceQuotaConfig.model_validate(raw)
