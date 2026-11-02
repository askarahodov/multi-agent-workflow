"""Runtime configuration: settings + quota config loading/validation.

Configuration is loaded from environment and YAML via pydantic-settings.
Resource quotas are validated against :class:`ResourceQuotaConfig` (which
enforces the ADR-011 cgroup invariants at parse time, matching the JSON
Schema). No secrets are stored in any shipped config file.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from runtime.hardening.models import ResourceQuotaConfig

DEFAULT_QUOTA_CONFIG = (
    Path(__file__).resolve().parents[3] / "config" / "resource-quotas.example.yaml"
)


class ResilienceSettings(BaseModel):
    """Circuit-breaker / timeout / bulkhead / retry / degradation defaults (spec §5)."""

    sliding_window_size: int = 100
    minimum_number_of_calls: int = 20
    failure_rate_threshold: float = 0.5
    wait_duration_in_open_state: float = 30.0
    permitted_number_of_calls_in_half_open_state: int = 3
    slow_call_duration: float | None = None
    slow_call_rate_threshold: float | None = None

    # Time limiter (per-endpoint SLA timeout).
    timeout_seconds: float = 30.0
    cancel_running_future: bool = True

    # Rate limiter (token bucket).
    rate_limit_per_second: float = 50.0

    # Bulkhead.
    bulkhead_max_concurrent: int = 25
    bulkhead_max_wait_seconds: float = 0.0

    # Retry.
    retry_max_attempts: int = 3
    retry_base_seconds: float = 0.1
    retry_max_seconds: float = 10.0
    retry_jitter: bool = True

    # Global retry budget (10% of request volume).
    retry_budget_ratio: float = 0.1
    retry_budget_ttl_seconds: float = 10.0
    retry_budget_min_per_second: float = 10.0

    # Recovery coordinator.
    recovery_base_seconds: float = 2.0
    recovery_max_seconds: float = 60.0
    recovery_max_attempts: int = 10

    # Degradation controller evaluation interval (seconds).
    eval_interval_seconds: float = 5.0
    pressure_threshold: float = 0.5


class IsolationSettings(BaseModel):
    """Isolation-layer defaults (spec §3)."""

    cgroup_root: str = "/sys/fs/cgroup"
    parent_slice: str = "agent.slice"
    reaper_force_cleanup_seconds: float = 30.0
    reaper_scan_interval_seconds: float = 15.0
    oom_score_adj: int = 500
    default_non_root_uid: int = 65532
    enable_tc_qdisc: bool = False  # host tc not wired in reference; see docs
    enable_real_mounts: bool = False  # overlayfs mount delegated to runtime backend
    # Fallback tier used when /dev/kvm is absent for untrusted/adversarial.
    no_kvm_untrusted_tier: str = "gvisor-runsc"
    no_kvm_adversarial_tier: str = "gvisor-nsjail"


class RuntimeSettings(BaseSettings):
    """Top-level runtime settings, overridable via env (``HARBOR_*``) or YAML."""

    model_config = SettingsConfigDict(
        env_prefix="HARBOR_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    log_level: str = "INFO"
    log_json: bool = True
    otlp_endpoint: str | None = None
    otlp_enabled: bool = False
    service_name: str = "agent-runtime-hardening"

    resilience: ResilienceSettings = Field(default_factory=ResilienceSettings)
    isolation: IsolationSettings = Field(default_factory=IsolationSettings)
    quota_config_path: Path = DEFAULT_QUOTA_CONFIG


def load_quota_config(path: str | Path | None = None) -> ResourceQuotaConfig:
    """Load and validate a resource-quota YAML config.

    Raises :class:`ValueError` on schema/invariant violations, mirroring the
    JSON Schema (which additionally enforces ``swapMax==max`` and
    ``high<=max``).
    """
    source = Path(path) if path is not None else DEFAULT_QUOTA_CONFIG
    with source.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"resource-quota config at {source} is not a mapping")
    return ResourceQuotaConfig.model_validate(data)
